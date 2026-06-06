import argparse
import atexit
import contextlib
import getpass
import ipaddress
import importlib
import inspect
import io
import json
import os
import pty
import signal
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.parse
import warnings
import yaml

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

from tabulate import tabulate

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
from framework.reporting.une_0087_alignment import (
    format_une_0087_console_summary,
    write_une_0087_alignment,
)
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
    DEFAULT_COMMON_DOMAIN_BASE,
    canonical_common_service_config_values,
    legacy_common_service_hostnames,
    resolved_common_service_hostnames,
    resolved_common_service_urls,
)
from deployers.infrastructure.lib.orchestrator import DeployerOrchestrator
from deployers.infrastructure.lib.topology import SUPPORTED_TOPOLOGIES as DEPLOYER_SUPPORTED_TOPOLOGIES
from deployers.infrastructure.lib.topology import (
    LOCAL_TOPOLOGY,
    VM_DISTRIBUTED_TOPOLOGY,
    VM_SINGLE_TOPOLOGY,
    normalize_topology,
)
from deployers.shared.lib.cluster_runtime import (
    SUPPORTED_CLUSTER_TYPES,
    build_cluster_runtime,
    normalize_cluster_type,
)
from deployers.shared.lib.config_loader import (
    COMMON_SERVICE_TOPOLOGY_KEYS,
    INFRASTRUCTURE_MANAGED_KEYS,
    KUBERNETES_WORKLOAD_TOPOLOGY_KEYS,
    TOPOLOGY_OVERLAY_KEYS,
    VM_SERVICE_TOPOLOGY_KEYS,
)
from deployers.shared.lib.connectors import (
    parse_connector_list,
    parse_connector_mapping,
    parse_connector_pairs,
)
from deployers.shared.lib.remote_k3s_images import remote_k3s_image_import_target
from deployers.shared.lib.vm_distributed_public_access import (
    VM_PUBLIC_PLACEHOLDER_DOMAINS,
    is_vm_public_placeholder_url,
    resolve_vm_distributed_public_urls,
)
from deployers.shared.lib import runtime_artifacts
from validation.core.test_data_cleanup import run_pre_validation_cleanup
from validation.orchestration.hosts import (
    ensure_public_endpoints_accessible,
    normalize_public_endpoint_tls_verify_mode,
    normalize_public_endpoint_url,
)
from validation.orchestration.components import (
    run_component_validations as run_level6_component_validations,
    should_run_component_validation as should_run_level6_component_validation,
)
from validation.orchestration.kafka import (
    KAFKA_LEVEL6_RUN_FLAG,
    KAFKA_LEVEL6_SKIP_FLAG,
    run_kafka_edc_validation,
    should_run_kafka_edc_validation,
    validate_kafka_runtime_preflight,
)
from validation.orchestration.reports import (
    build_experiment_dashboard,
    discover_report_experiments,
    format_report_experiment_summary,
    inspect_experiment,
    launch_playwright_report,
    launch_static_report_server,
    open_local_url,
    wsl_file_url_for_path,
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
from validation.components.console_output import (
    print_component_validation_summary,
    print_interoperability_suite_header,
)
from validation.datasets.manager import sync_level5_dataset_sources
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

SUPPORTED_COMMANDS = (
    "deploy",
    "level",
    "validate",
    "metrics",
    "run",
    "hosts",
    "public-access",
    "ssh-access",
    "local-repair",
    "recreate-dataspace",
)
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
LEVEL6_CONSOLE_LOG_FILENAME = "level6_console.log"
NEWMAN_CONSOLE_LOG_FILENAME = "newman_console.log"
KAFKA_CONSOLE_LOG_FILENAME = "kafka_console.log"


class _Level6ConsoleCapture:
    """Tee Level 6 stdout/stderr to an experiment artifact without hiding console output."""

    def __init__(
        self,
        experiment_dir,
        filename=LEVEL6_CONSOLE_LOG_FILENAME,
        mirror_output=True,
        label="Level 6 console log",
    ):
        self.experiment_dir = experiment_dir
        self.filename = filename
        self.mirror_output = mirror_output
        self.label = label
        self.path = os.path.join(str(experiment_dir), filename) if experiment_dir else None
        self._active = False
        self._log_file = None
        self._read_fd = None
        self._write_fd = None
        self._stdout_fd = None
        self._stderr_fd = None
        self._thread = None
        self._previous_stdout = None
        self._previous_stderr = None
        self._capture_stdout = None
        self._capture_stderr = None
        self._force_color_was_set = False
        self._previous_force_color = None

    def __enter__(self):
        if not self.path or not _env_flag("PIONERA_LEVEL6_CONSOLE_LOG", True):
            return self

        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            sys.stdout.flush()
            sys.stderr.flush()

            stdout_is_tty = os.isatty(1)
            self._stdout_fd = os.dup(1)
            self._stderr_fd = os.dup(2)
            if stdout_is_tty:
                self._read_fd, self._write_fd = pty.openpty()
            else:
                self._read_fd, self._write_fd = os.pipe()
            self._log_file = open(self.path, "wb", buffering=0)
            self._thread = threading.Thread(target=self._tee_output, daemon=True)
            self._thread.start()

            self._previous_force_color = os.environ.get("FORCE_COLOR")
            if (
                "FORCE_COLOR" not in os.environ
                and "NO_COLOR" not in os.environ
                and _env_flag("PIONERA_CONSOLE_LOG_FORCE_COLOR", True)
            ):
                os.environ["FORCE_COLOR"] = "1"
                self._force_color_was_set = True

            os.dup2(self._write_fd, 1)
            os.dup2(self._write_fd, 2)
            os.close(self._write_fd)
            self._write_fd = None
            self._previous_stdout = sys.stdout
            self._previous_stderr = sys.stderr
            stdout_encoding = getattr(self._previous_stdout, "encoding", None) or "utf-8"
            stderr_encoding = getattr(self._previous_stderr, "encoding", None) or stdout_encoding
            self._capture_stdout = io.TextIOWrapper(
                os.fdopen(os.dup(1), "wb", buffering=0),
                encoding=stdout_encoding,
                errors="replace",
                line_buffering=True,
            )
            self._capture_stderr = io.TextIOWrapper(
                os.fdopen(os.dup(2), "wb", buffering=0),
                encoding=stderr_encoding,
                errors="replace",
                line_buffering=True,
            )
            sys.stdout = self._capture_stdout
            sys.stderr = self._capture_stderr
            self._active = True
            print(f"{self.label}: {self.path}")
        except Exception:
            self._restore_after_failed_start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False

    def _tee_output(self):
        try:
            while True:
                chunk = os.read(self._read_fd, 8192)
                if not chunk:
                    break
                if self._log_file is not None:
                    self._log_file.write(chunk)
                if self.mirror_output and self._stdout_fd is not None:
                    os.write(self._stdout_fd, chunk)
        except OSError:
            pass
        finally:
            if self._read_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(self._read_fd)
                self._read_fd = None

    def _restore_after_failed_start(self):
        if self._previous_stdout is not None:
            sys.stdout = self._previous_stdout
            self._previous_stdout = None
        if self._previous_stderr is not None:
            sys.stderr = self._previous_stderr
            self._previous_stderr = None
        for stream_attribute in ("_capture_stdout", "_capture_stderr"):
            stream = getattr(self, stream_attribute)
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()
                setattr(self, stream_attribute, None)
        if self._stdout_fd is not None:
            with contextlib.suppress(OSError):
                os.dup2(self._stdout_fd, 1)
        if self._stderr_fd is not None:
            with contextlib.suppress(OSError):
                os.dup2(self._stderr_fd, 2)
        for attribute in ("_write_fd", "_stdout_fd", "_stderr_fd"):
            fd = getattr(self, attribute)
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
                setattr(self, attribute, None)
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._read_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._read_fd)
            self._read_fd = None
        if self._log_file is not None:
            with contextlib.suppress(Exception):
                self._log_file.close()
            self._log_file = None
        if self._force_color_was_set:
            if self._previous_force_color is None:
                os.environ.pop("FORCE_COLOR", None)
            else:
                os.environ["FORCE_COLOR"] = self._previous_force_color
        self._active = False

    def close(self):
        if not self._active:
            return

        with contextlib.suppress(Exception):
            sys.stdout.flush()
        with contextlib.suppress(Exception):
            sys.stderr.flush()
        if self._previous_stdout is not None:
            sys.stdout = self._previous_stdout
            self._previous_stdout = None
        if self._previous_stderr is not None:
            sys.stderr = self._previous_stderr
            self._previous_stderr = None
        for stream_attribute in ("_capture_stdout", "_capture_stderr"):
            stream = getattr(self, stream_attribute)
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()
                setattr(self, stream_attribute, None)
        if self._stdout_fd is not None:
            with contextlib.suppress(OSError):
                os.dup2(self._stdout_fd, 1)
        if self._stderr_fd is not None:
            with contextlib.suppress(OSError):
                os.dup2(self._stderr_fd, 2)
        if self._stdout_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._stdout_fd)
            self._stdout_fd = None
        if self._stderr_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._stderr_fd)
            self._stderr_fd = None

        if self._force_color_was_set:
            if self._previous_force_color is None:
                os.environ.pop("FORCE_COLOR", None)
            else:
                os.environ["FORCE_COLOR"] = self._previous_force_color

        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._log_file is not None:
            with contextlib.suppress(Exception):
                self._log_file.close()
            self._log_file = None
        self._active = False


def _env_flag(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in ("1", "true", "yes", "on")


def _level6_stop_after_playwright_failure_enabled(env=None):
    env = env if env is not None else os.environ
    for name in (
        "PIONERA_LEVEL6_STOP_ON_PLAYWRIGHT_FAILURE",
        "LEVEL6_STOP_ON_PLAYWRIGHT_FAILURE",
    ):
        raw_value = env.get(name)
        if raw_value is not None:
            return str(raw_value).strip().lower() in ("1", "true", "yes", "on")

    return False


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


def _adapter_config_values(adapter_name):
    normalized = str(adapter_name or "").strip().lower()
    if not normalized:
        return {}
    root_dir = os.path.dirname(__file__)
    config = {}
    for filename in ("deployer.config.example", "deployer.config"):
        config_path = os.path.join(root_dir, "deployers", normalized, filename)
        config.update(load_raw_deployer_config(config_path))
    return config


def _adapter_config_namespace(adapter_name):
    normalized = str(adapter_name or "").strip().lower()
    if not normalized:
        return ""
    config = _adapter_config_values(normalized)
    return (
        str(
            config.get("DS_1_NAMESPACE")
            or config.get("NAMESPACE")
            or config.get("DS_1_NAME")
            or config.get("DS_NAME")
            or _adapter_default_namespace(normalized)
        ).strip()
    )


def _local_adapter_managed_namespaces(adapter_name):
    normalized = str(adapter_name or "").strip().lower()
    if normalized not in {"inesdata", "edc"}:
        return []
    config = _adapter_config_values(normalized)
    namespaces = _unique_non_empty(
        [
            config.get("DS_1_NAMESPACE"),
            config.get("DS_1_REGISTRATION_NAMESPACE"),
            config.get("DS_1_PROVIDER_NAMESPACE"),
            config.get("DS_1_CONSUMER_NAMESPACE"),
            config.get("NAMESPACE"),
        ]
    )
    if namespaces:
        return namespaces
    return _unique_non_empty(
        [
            config.get("DS_1_NAME"),
            config.get("DS_NAME"),
            _adapter_default_namespace(normalized),
        ]
    )


def _local_adapter_component_namespaces(adapter_name):
    normalized = str(adapter_name or "").strip().lower()
    if normalized not in {"inesdata", "edc"}:
        return []
    config = _adapter_config_values(normalized)
    return _unique_non_empty([config.get("COMPONENTS_NAMESPACE")])


def _local_adapter_dataspace_name(adapter_name):
    normalized = str(adapter_name or "").strip().lower()
    config = _adapter_config_values(normalized)
    return str(
        config.get("DS_1_NAME")
        or config.get("DS_NAME")
        or _adapter_default_namespace(normalized)
    ).strip()


def _local_adapter_connector_full_names(adapter_name):
    normalized = str(adapter_name or "").strip().lower()
    config = _adapter_config_values(normalized)
    dataspace = _local_adapter_dataspace_name(normalized)
    connectors = []
    for raw_connector in str(config.get("DS_1_CONNECTORS") or "").split(","):
        connector = raw_connector.strip()
        if not connector:
            continue
        if connector.startswith("conn-"):
            connectors.append(connector)
        elif dataspace:
            connectors.append(f"conn-{connector}-{dataspace}")
    return _unique_non_empty(connectors)


def _local_adapter_component_release_names(adapter_name):
    dataspace = _local_adapter_dataspace_name(adapter_name)
    if not dataspace:
        return []
    config = _adapter_config_values(adapter_name)
    components = [
        component.strip().lower().replace("_", "-")
        for component in str(config.get("COMPONENTS") or "").split(",")
        if component.strip()
    ]
    return _unique_non_empty([f"{dataspace}-{component}" for component in components])


def _local_adapter_expected_release_names(adapter_name, *, include_components=False):
    dataspace = _local_adapter_dataspace_name(adapter_name)
    release_names = []
    if dataspace:
        release_names.append(f"{dataspace}-dataspace-rs")
        release_names.extend(
            f"{connector}-{dataspace}"
            for connector in _local_adapter_connector_full_names(adapter_name)
        )
    if include_components:
        release_names.extend(_local_adapter_component_release_names(adapter_name))
    return _unique_non_empty(release_names)


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
        "inesdata": _local_adapter_managed_namespaces("inesdata") or _adapter_config_namespace("inesdata"),
        "edc": _local_adapter_managed_namespaces("edc") or _adapter_config_namespace("edc"),
    }
    current_roles = _context_namespace_roles_dict(deployer_context)
    current_adapter = str(deployer_name or "").strip().lower()
    current_namespaces = _unique_non_empty(current_roles.values())
    if current_adapter in adapter_namespaces and current_namespaces:
        adapter_namespaces[current_adapter] = current_namespaces
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


def _namespace_list(value):
    if isinstance(value, (list, tuple, set)):
        return _unique_non_empty(value)
    return _unique_non_empty([value])


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
        namespaces = _unique_non_empty(
            _namespace_list(adapter_namespaces.get(adapter_name))
            + _local_adapter_managed_namespaces(adapter_name)
        )
        if not namespaces:
            namespaces = _namespace_list(_adapter_config_namespace(adapter_name))
        for namespace in namespaces:
            namespace_actions.append(
                {
                    "namespace": namespace,
                    "reason": f"{adapter_name}-adapter",
                    "adapter": adapter_name,
                    "allow_components_namespace": False,
                    "expected_releases": _local_adapter_expected_release_names(adapter_name),
                }
            )

    if "inesdata" in adapters_to_remove or target == "edc":
        component_namespaces = active_component_namespaces
        if not component_namespaces:
            for adapter_name in adapters_to_remove or [target]:
                component_namespaces.extend(_local_adapter_component_namespaces(adapter_name))
        component_expected_releases = []
        for adapter_name in adapters_to_remove:
            component_expected_releases.extend(
                _local_adapter_expected_release_names(adapter_name, include_components=True)
            )
        for namespace in component_namespaces:
            namespace_actions.append(
                {
                    "namespace": namespace,
                    "reason": "components",
                    "adapter": "inesdata",
                    "allow_components_namespace": True,
                    "expected_releases": _unique_non_empty(component_expected_releases),
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


def _local_switch_namespace_exists(namespace):
    result = _run_switch_command(["kubectl", "get", "namespace", namespace])
    return result.returncode == 0


def _local_switch_namespace_helm_releases(namespace):
    result = _run_switch_command(["helm", "list", "-n", namespace, "-q"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"helm exited with {result.returncode}"
        raise RuntimeError(f"Could not inspect Helm releases in namespace '{namespace}'. Root cause: {detail}")
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def _local_switch_namespace_cleanup_readiness(action):
    namespace = str(action.get("namespace") or "").strip()
    if not namespace:
        return {"status": "skipped", "reason": "missing-namespace", "namespace": namespace}
    if not _local_switch_namespace_exists(namespace):
        return {"status": "skipped", "reason": "namespace-not-found", "namespace": namespace}

    helm_releases = _local_switch_namespace_helm_releases(namespace)
    expected_releases = _unique_non_empty(action.get("expected_releases") or [])
    matching_releases = [
        release
        for release in helm_releases
        if not expected_releases or release in expected_releases
    ]
    if not matching_releases:
        return {
            "status": "skipped",
            "reason": "no-matching-helm-releases",
            "namespace": namespace,
            "helm_releases": helm_releases,
            "expected_releases": expected_releases,
        }
    return {
        "status": "ready",
        "namespace": namespace,
        "helm_releases": helm_releases,
        "matching_releases": matching_releases,
        "expected_releases": expected_releases,
    }


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
        readiness = _local_switch_namespace_cleanup_readiness(action)
        if readiness.get("status") != "ready":
            reason = readiness.get("reason", "not-ready")
            print(f"- Skipping namespace {namespace} ({reason})")
            namespace_results.append(
                {
                    "namespace": namespace,
                    "status": "skipped",
                    "reason": reason,
                    "adapter": action.get("adapter"),
                    "helm_releases": readiness.get("helm_releases", []),
                    "expected_releases": readiness.get("expected_releases", []),
                }
            )
            continue
        print(f"- Deleting namespace {namespace}")
        result = _run_switch_command(
            ["kubectl", "delete", "namespace", namespace, "--ignore-not-found=true"]
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip() or f"kubectl exited with {result.returncode}"
            raise RuntimeError(f"Could not delete namespace '{namespace}'. Root cause: {detail}")
        if not _wait_for_local_switch_namespace_deleted(namespace):
            raise RuntimeError(f"Timed out waiting for namespace '{namespace}' to be deleted")
        namespace_results.append(
            {
                "namespace": namespace,
                "status": "deleted",
                "reason": action.get("reason"),
                "adapter": action.get("adapter"),
                "matching_releases": readiness.get("matching_releases", []),
            }
        )

    runtime_results = []
    for entry in plan.get("runtime_dirs") or []:
        result = _safe_remove_local_switch_runtime_dir(entry)
        runtime_results.append(result)
        if result.get("status") == "removed":
            print(f"- Removed runtime artifacts {result['path']}")

    return {
        **plan,
        "status": "completed",
        "deleted_namespaces": [
            result["namespace"]
            for result in namespace_results
            if result.get("status") == "deleted"
        ],
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


def _vm_single_cluster_switch_confirmation_token(target_runtime):
    normalized = str(target_runtime or "").strip().upper()
    return f"SWITCH VM-SINGLE TO {normalized}" if normalized else "SWITCH VM-SINGLE RUNTIME"


def _vm_single_minikube_active(profile="minikube"):
    result = _run_switch_command(["minikube", "status", "-p", str(profile or "minikube")])
    output = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode == 0 and (
        "host: running" in output
        or "kubelet: running" in output
        or "apiserver: running" in output
    )


def _vm_single_k3s_active(service_name="k3s"):
    result = _run_switch_command(["systemctl", "is-active", str(service_name or "k3s")])
    return result.returncode == 0 and str(result.stdout or "").strip() == "active"


def _normalized_previous_cluster_runtime(previous_runtime):
    raw_value = str(previous_runtime or "").strip()
    if not raw_value or raw_value.lower().startswith("invalid"):
        return None
    try:
        return normalize_cluster_type(raw_value, topology="local")
    except ValueError:
        return None


def _build_vm_single_cluster_runtime_switch_plan(target_runtime, previous_runtime=None):
    target = normalize_cluster_type(target_runtime, topology="vm-single")
    previous = _normalized_previous_cluster_runtime(previous_runtime)
    if previous == target:
        return {"status": "skipped", "reason": "runtime-unchanged", "target_runtime": target}

    if target == "k3s" and _vm_single_minikube_active():
        return {
            "status": "planned",
            "target_runtime": target,
            "detected_runtime": "minikube",
            "cleanup_action": "delete-minikube-profile",
            "cleanup_command": ["minikube", "delete", "-p", "minikube"],
            "confirmation_token": _vm_single_cluster_switch_confirmation_token(target),
        }

    return {"status": "skipped", "reason": "no-active-other-runtime", "target_runtime": target}


def _print_vm_single_cluster_runtime_switch_plan(plan):
    print()
    print("VM-SINGLE CLUSTER RUNTIME SWITCH REQUIRED")
    print(f"Target runtime: {plan.get('target_runtime')}")
    print(f"Detected active runtime: {plan.get('detected_runtime')}")
    command = " ".join(plan.get("cleanup_command") or [])
    if command:
        print(f"Cleanup command: {command}")
    manual_cleanup = str(plan.get("manual_cleanup") or "").strip()
    if manual_cleanup:
        print(f"Manual cleanup if sudo is unavailable: {manual_cleanup}")
    print("Only one vm-single cluster runtime should be active on this VM.")
    print("This avoids resource contention and accidental kubectl/KUBECONFIG drift.")


def _vm_single_cluster_runtime_switch_approved(plan, env=None):
    env = env if env is not None else os.environ
    token = str(plan.get("confirmation_token") or "").strip()
    provided = str(env.get("PIONERA_VM_SINGLE_CLUSTER_SWITCH_CONFIRM") or "").strip()
    if token and provided == token:
        return True

    if not bool(getattr(sys.stdin, "isatty", lambda: False)()):
        return False

    _print_vm_single_cluster_runtime_switch_plan(plan)
    print()
    print("This will stop or remove the previously active vm-single cluster runtime.")
    answer = _interactive_read(f"Type {token} to continue: ")
    return bool(token and answer == token)


def _execute_vm_single_cluster_runtime_switch_plan(plan):
    command = list(plan.get("cleanup_command") or [])
    if not command:
        return {**plan, "status": "skipped", "reason": "missing-cleanup-command"}

    result = _run_switch_command(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"command exited with {result.returncode}"
        raise RuntimeError(f"Could not switch vm-single cluster runtime. Root cause: {detail}")
    return {**plan, "status": "completed"}


def _try_vm_single_cluster_runtime_switch(target_runtime, previous_runtime=None):
    plan = _build_vm_single_cluster_runtime_switch_plan(target_runtime, previous_runtime=previous_runtime)
    if plan.get("status") != "planned":
        return {**plan, "allowed": True}
    if not _vm_single_cluster_runtime_switch_approved(plan):
        _print_vm_single_cluster_runtime_switch_plan(plan)
        print("Cluster runtime switch cancelled. Cleanup the previous runtime before switching.")
        return {**plan, "status": "declined", "allowed": False}
    result = _execute_vm_single_cluster_runtime_switch_plan(plan)
    return {**result, "allowed": True}


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


def _prepare_local_install_capacity_summary(summary, current_adapter):
    prepared = dict(summary or {})
    normalized_adapter = str(current_adapter or "").strip().lower()
    active_adapters = set(prepared.get("active_adapters") or [])
    other_active_adapters = sorted(active_adapters - {normalized_adapter})
    components_active_without_adapter = bool(prepared.get("active_component_namespaces")) and not active_adapters
    will_create_or_extend_coexistence = (
        bool(other_active_adapters)
        or bool(prepared.get("coexistence_detected"))
        or components_active_without_adapter
    )
    prepared["installing_adapter"] = normalized_adapter
    prepared["other_active_adapters"] = other_active_adapters
    prepared["components_active_without_adapter"] = components_active_without_adapter
    prepared["coexistence_detected"] = bool(will_create_or_extend_coexistence)
    return prepared


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
    summary = _prepare_local_install_capacity_summary(summary, current_adapter)

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
            summary = _prepare_local_install_capacity_summary(summary, current_adapter)
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
    "_PASS",
    "PASS",
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


def _edc_dashboard_runtime_validation(deployer_context):
    runtime_dir = str(getattr(deployer_context, "runtime_dir", "") or "").strip()
    connectors = list(getattr(deployer_context, "connectors", []) or [])
    result = {
        "present": False,
        "valid": False,
        "issues": [],
        "checked_connectors": [],
    }
    if not runtime_dir or not connectors:
        result["issues"].append("dashboard runtime directory or connector list is empty")
        return result

    for connector in connectors:
        dashboard_dir = os.path.join(runtime_dir, "dashboard", connector)
        app_config_path = os.path.join(dashboard_dir, "app-config.json")
        connector_config_path = os.path.join(dashboard_dir, "edc-connector-config.json")
        if not os.path.isfile(app_config_path) or not os.path.isfile(connector_config_path):
            result["issues"].append(f"{connector}: dashboard runtime files are missing")
            continue

        result["present"] = True
        result["checked_connectors"].append(connector)
        try:
            with open(app_config_path, "r", encoding="utf-8") as handle:
                app_config = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            result["issues"].append(f"{connector}: app-config.json is not readable JSON ({exc})")
            continue

        menu_paths = {
            str(item.get("routerPath") or "").strip()
            for item in (app_config.get("menuItems") or [])
            if isinstance(item, dict)
        }
        if "model-observer" not in menu_paths:
            result["issues"].append(f"{connector}: Model Observer menu item is missing")
        if "ontologies" not in menu_paths:
            result["issues"].append(f"{connector}: Ontologies menu item is missing")

        runtime = app_config.get("runtime") or {}
        ontology_url = str(runtime.get("ontologyUrl") or "").strip()
        if ontology_url != "/edc-dashboard-api/components/ontology-hub":
            result["issues"].append(
                f"{connector}: ontologyUrl must be /edc-dashboard-api/components/ontology-hub"
            )
        model_observer_url = str(runtime.get("modelObserverUrl") or "").strip()
        expected_observer_prefix = f"/edc-dashboard-api/connectors/{connector}/api"
        if not model_observer_url.startswith(expected_observer_prefix):
            result["issues"].append(
                f"{connector}: modelObserverUrl must start with {expected_observer_prefix}"
            )

    result["valid"] = bool(result["present"] and not result["issues"])
    return result


def _edc_dashboard_runtime_present(deployer_context):
    validation = _edc_dashboard_runtime_validation(deployer_context)
    return bool(validation.get("present") and validation.get("valid"))


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


def _context_connector_namespace_overrides(deployer_context, default_namespace=""):
    config = getattr(deployer_context, "config", None) or {}
    dataspace_name = str(getattr(deployer_context, "dataspace_name", "") or "").strip()
    raw_mapping = (
        config.get("DS_1_CONNECTOR_NAMESPACES")
        or config.get("CONNECTOR_NAMESPACES")
        or ""
    )
    parsed = parse_connector_mapping(raw_mapping, dataspace_name)
    return {
        connector: _resolve_context_connector_namespace(
            deployer_context,
            target,
            default_namespace=default_namespace,
        )
        for connector, target in parsed.items()
    }


def _resolve_context_connector_namespace(deployer_context, target, default_namespace=""):
    raw_target = str(target or "").strip()
    normalized = raw_target.lower().replace("-", "_")
    aliases = {
        "provider": "provider_namespace",
        "provider_namespace": "provider_namespace",
        "consumer": "consumer_namespace",
        "consumer_namespace": "consumer_namespace",
        "registration": "registration_service_namespace",
        "registration_service": "registration_service_namespace",
        "core": "registration_service_namespace",
        "dataspace": "",
        "default": "",
    }
    role_field = aliases.get(normalized)
    if role_field is None:
        return raw_target
    if role_field == "":
        return default_namespace

    roles = getattr(deployer_context, "namespace_roles", None)
    if _context_namespace_profile(deployer_context) == "role-aligned":
        roles = getattr(deployer_context, "planned_namespace_roles", None) or roles
    return _namespace_role_value(roles, role_field, default_namespace)


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
    connector_namespaces.update(
        {
            connector: namespace
            for connector, namespace in _context_connector_namespace_overrides(
                deployer_context,
                default_namespace=default_namespace,
            ).items()
            if connector in connector_namespaces and namespace
        }
    )
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

    connector_namespaces = {connectors[0]: provider_namespace}
    if len(connectors) >= 2:
        connector_namespaces[connectors[1]] = consumer_namespace
    for connector in connectors[2:]:
        connector_namespaces[connector] = default_namespace
    connector_namespaces.update(
        {
            connector: namespace
            for connector, namespace in _context_connector_namespace_overrides(
                deployer_context,
                default_namespace=default_namespace,
            ).items()
            if connector in connector_namespaces and namespace
        }
    )
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


def _keycloak_base_without_realm(url, dataspace_name):
    normalized = normalize_public_endpoint_url(url)
    if not normalized:
        return None

    dataspace = str(dataspace_name or "").strip()
    if dataspace:
        realm_suffix = f"/realms/{urllib.parse.quote(dataspace, safe='')}"
        if normalized.rstrip("/").endswith(realm_suffix):
            return normalized.rstrip("/")[: -len(realm_suffix)].rstrip("/")

    return normalized.rstrip("/")


def _config_topology_value(config):
    return normalize_topology(
        (config or {}).get("TOPOLOGY")
        or (config or {}).get("PIONERA_TOPOLOGY")
        or (config or {}).get("INESDATA_TOPOLOGY")
        or LOCAL_TOPOLOGY
    )


def _config_uses_vm_public_url_resolution(config):
    topology = _config_topology_value(config)
    if topology in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}:
        return True
    values = config or {}
    public_url_keys = globals().get("VM_DISTRIBUTED_PUBLIC_URL_KEYS", ())
    return any(str(values.get(key) or "").strip() for key in public_url_keys)


def _vm_public_url_candidate(config, value):
    text = str(value or "").strip()
    if not text:
        return ""
    if (
        _config_topology_value(config) in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}
        and is_vm_public_placeholder_url(text)
    ):
        return ""
    return text


def _public_keycloak_base_url(deployer_context):
    config = dict(getattr(deployer_context, "config", {}) or {})
    dataspace = str(getattr(deployer_context, "dataspace_name", "") or "").strip()
    public_urls = (
        resolve_vm_distributed_public_urls(config)
        if _config_uses_vm_public_url_resolution(config)
        else {}
    )
    for raw_url in (
        config.get("KEYCLOAK_FRONTEND_URL"),
        config.get("KEYCLOAK_PUBLIC_URL"),
        public_urls.get("KEYCLOAK_FRONTEND_URL"),
        public_urls.get("KEYCLOAK_PUBLIC_URL"),
    ):
        normalized = _keycloak_base_without_realm(_vm_public_url_candidate(config, raw_url), dataspace)
        if normalized:
            return normalized

    resolved_urls = resolved_common_service_urls(config)
    for key in ("KC_URL", "KC_INTERNAL_URL"):
        normalized = _keycloak_base_without_realm(_mapping_value(resolved_urls, key), dataspace)
        if normalized:
            return normalized
    resolved_hostnames = resolved_common_service_hostnames(config)
    normalized = _keycloak_base_without_realm(
        f"http://{resolved_hostnames['keycloak_hostname']}",
        dataspace,
    )
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


def _configured_public_connector_base_url(connector_name, deployer_context):
    config = dict(getattr(deployer_context, "config", {}) or {})
    dataspace = str(getattr(deployer_context, "dataspace_name", "") or "").strip()
    connector = str(connector_name or "").strip()
    if not connector:
        return None

    if _config_topology_value(config) == VM_SINGLE_TOPOLOGY:
        try:
            from deployers.inesdata.access_urls import connector_public_base_url

            vm_single_url = connector_public_base_url(
                connector,
                dataspace,
                {**config, "TOPOLOGY": VM_SINGLE_TOPOLOGY},
            )
        except Exception:
            vm_single_url = ""
        if vm_single_url:
            return normalize_public_endpoint_url(vm_single_url)

    public_urls = resolve_vm_distributed_public_urls(config)
    provider_connectors = set(parse_connector_list(config.get("VM_PROVIDER_CONNECTORS"), dataspace))
    consumer_connectors = set(parse_connector_list(config.get("VM_CONSUMER_CONNECTORS"), dataspace))
    if connector in provider_connectors:
        return normalize_public_endpoint_url(public_urls.get("VM_PROVIDER_PUBLIC_URL"))
    if connector in consumer_connectors:
        return normalize_public_endpoint_url(public_urls.get("VM_CONSUMER_PUBLIC_URL"))
    return None


def _connector_portal_url_from_base(base_url):
    normalized = normalize_public_endpoint_url(base_url)
    if not normalized:
        return None
    return f"{normalized.rstrip('/')}/inesdata-connector-interface/"


def _inesdata_connector_public_base_url(connector_name, deployer_context):
    payload, _error = _load_inesdata_connector_credentials_payload(
        deployer_context,
        connector_name,
    )
    public_urls = payload.get("public_access_urls") if isinstance(payload, dict) else {}
    if isinstance(public_urls, dict):
        login_url = _normalize_readiness_url(
            public_urls.get("connector_interface_login"),
            preserve_trailing_slash=True,
        )
        if login_url:
            return login_url
        ingress_url = _connector_portal_url_from_base(public_urls.get("connector_ingress"))
        if ingress_url:
            return ingress_url

    configured_base = _configured_public_connector_base_url(connector_name, deployer_context)
    configured_portal = _connector_portal_url_from_base(configured_base)
    if configured_portal:
        return configured_portal

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
    scoped_path = os.path.join(runtime_dir, "connectors", connector, "credentials.json")
    legacy_path = os.path.join(runtime_dir, f"credentials-connector-{connector}.json")
    if os.path.isfile(scoped_path) or not os.path.isfile(legacy_path):
        return scoped_path
    return legacy_path


def _load_inesdata_connector_credentials_payload(deployer_context, connector_name):
    credentials_path = _inesdata_connector_credentials_path(deployer_context, connector_name)
    if not credentials_path:
        return {}, "runtime_dir is not configured"
    if not os.path.isfile(credentials_path):
        return {}, f"credentials file not found: {credentials_path}"

    try:
        with open(credentials_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return {}, f"failed to read {credentials_path}: {exc}"

    if not isinstance(payload, dict):
        return {}, f"credentials file is not a JSON object: {credentials_path}"

    return payload, None


def _load_inesdata_connector_user_credentials(deployer_context, connector_name):
    payload, error = _load_inesdata_connector_credentials_payload(
        deployer_context,
        connector_name,
    )
    if error:
        return None, error
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
    topology = normalize_topology(getattr(deployer_context, "topology", None) or LOCAL_TOPOLOGY)
    check_internal_endpoints = topology == LOCAL_TOPOLOGY
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
        if check_internal_endpoints:
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
        "topology": topology,
        "check_internal_endpoints": check_internal_endpoints,
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


def _context_config_loader(base_loader, deployer_context=None):
    if deployer_context is None:
        return base_loader

    def load_context_config():
        loaded = base_loader() if callable(base_loader) else {}
        config = dict(loaded or {}) if isinstance(loaded, dict) else {}
        context = _test_data_cleanup_context_with_public_runtime(deployer_context)
        context_config = getattr(context, "config", None)
        if isinstance(context_config, dict):
            config.update(context_config)
        return config

    return load_context_config


def _context_ds_domain_resolver(base_resolver, deployer_context=None):
    if deployer_context is None:
        return base_resolver

    def resolve_context_ds_domain():
        context_domain = str(getattr(deployer_context, "ds_domain_base", "") or "").strip()
        if context_domain:
            return context_domain
        if callable(base_resolver):
            return base_resolver()
        return ""

    return resolve_context_ds_domain


def build_validation_engine(adapter, engine_cls=ValidationEngine, deployer_context=None):
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
    base_load_deployer_config = _resolve_adapter_callable(
        adapter,
        "config_adapter.load_deployer_config",
        "load_deployer_config",
    )
    load_deployer_config = _context_config_loader(
        base_load_deployer_config,
        deployer_context=deployer_context,
    )
    validation_test_entities_absent = _resolve_adapter_callable(
        adapter,
        "connectors.validation_test_entities_absent",
        "validation_test_entities_absent",
        default=lambda connector: (True, []),
    )
    base_ds_domain_resolver = _resolve_adapter_callable(
        adapter,
        "config.ds_domain_base",
        "ds_domain_base",
    )
    ds_domain_resolver = _context_ds_domain_resolver(
        base_ds_domain_resolver,
        deployer_context=deployer_context,
    )
    protocol_address_resolver = _resolve_adapter_callable(
        adapter,
        "connectors.build_protocol_address",
        "connectors.build_public_protocol_address",
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


def _load_level6_kafka_runtime_config(adapter):
    kafka_config_loader = _resolve_adapter_callable(
        adapter,
        "get_kafka_config",
        default=lambda: {},
    )
    if not callable(kafka_config_loader):
        return {}
    loaded = kafka_config_loader()
    return dict(loaded or {}) if isinstance(loaded, dict) else {}


def _load_level6_kafka_deployer_config(adapter, deployer_context=None):
    base_load_deployer_config = _resolve_adapter_callable(
        adapter,
        "config_adapter.load_deployer_config",
        "load_deployer_config",
        default=lambda: {},
    )
    load_deployer_config = _context_config_loader(
        base_load_deployer_config,
        deployer_context=deployer_context,
    )
    if not callable(load_deployer_config):
        return {}
    loaded = load_deployer_config()
    return dict(loaded or {}) if isinstance(loaded, dict) else {}


def _save_level6_kafka_preflight_artifact(preflight, experiment_dir):
    if not experiment_dir or not isinstance(preflight, dict):
        return None

    path = os.path.join(experiment_dir, "kafka_runtime_preflight.json")
    os.makedirs(experiment_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(preflight, handle, indent=2, ensure_ascii=False)
    print(f"Kafka runtime preflight saved to {path}")
    return path


def _run_level6_kafka_preflight(
    adapter,
    *,
    experiment_dir=None,
    deployer_context=None,
    persist=True,
):
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        runtime_config = _load_level6_kafka_runtime_config(adapter)
        deployer_config = _load_level6_kafka_deployer_config(
            adapter,
            deployer_context=deployer_context,
        )
        preflight = validate_kafka_runtime_preflight(
            runtime_config,
            deployer_config,
        )
    except Exception as exc:
        preflight = {
            "status": "failed",
            "topology": str(getattr(adapter, "topology", "unknown") or "unknown"),
            "errors": [str(exc)],
            "warnings": [],
            "connector_bootstrap_servers": [],
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }

    preflight.setdefault("started_at", started_at)
    preflight["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    status = str(preflight.get("status") or "unknown").lower()
    for warning in preflight.get("warnings") or []:
        print(f"Warning: Kafka preflight: {warning}")
    if status == "failed":
        print("Kafka runtime preflight failed:")
        for error in preflight.get("errors") or []:
            print(f"- {error}")
        invalid_servers = preflight.get("invalid_connector_bootstrap_servers") or []
        for item in invalid_servers:
            address = item.get("address", "")
            reason = item.get("reason", "invalid")
            print(f"- Invalid connector bootstrap server: {address} ({reason})")
    else:
        topology = preflight.get("topology", "unknown")
        if topology == "vm-distributed":
            servers = ", ".join(preflight.get("connector_bootstrap_servers") or []) or "not configured"
            print(f"Kafka runtime preflight passed for vm-distributed: {servers}")

    if persist:
        _save_level6_kafka_preflight_artifact(preflight, experiment_dir)
    return preflight


def _start_level6_kafka_preparation(
    adapter,
    connectors,
    *,
    validation_profile=None,
    deployer_name=None,
    kafka_manager_cls=KafkaManager,
    background=True,
    kafka_enabled=None,
):
    if kafka_enabled is None:
        kafka_enabled = should_run_kafka_edc_validation(flag_enabled=_env_flag)
    if not kafka_enabled:
        return None
    if len(list(connectors or [])) < 2:
        return None
    if not _supports_level6_kafka_edc(
        adapter,
        validation_profile=validation_profile,
        deployer_name=deployer_name,
    ):
        return None

    preflight = _run_level6_kafka_preflight(adapter, persist=False)
    if str(preflight.get("status") or "").lower() == "failed":
        print(
            "Kafka runtime preparation skipped because preflight failed; "
            "the Kafka suite will report the failure in Level 6."
        )
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


def _level6_kafka_flag_decision(flag_enabled=None, env=None):
    flag_enabled = flag_enabled or _env_flag

    if flag_enabled(KAFKA_LEVEL6_SKIP_FLAG, False):
        return False
    if flag_enabled(KAFKA_LEVEL6_RUN_FLAG, False):
        return True

    return None


def _adapter_auto_mode_enabled(adapter):
    auto_mode_getter = getattr(adapter, "auto_mode_getter", None)
    if not callable(auto_mode_getter):
        return False
    try:
        return bool(auto_mode_getter())
    except TypeError:
        return False


def _resolve_level6_kafka_enabled_for_run(
    adapter,
    *,
    validation_profile=None,
    deployer_name=None,
    flag_enabled=None,
    prompt=True,
):
    if not _supports_level6_kafka_edc(
        adapter,
        validation_profile=validation_profile,
        deployer_name=deployer_name,
    ):
        return False

    flag_decision = _level6_kafka_flag_decision(flag_enabled=flag_enabled)
    if flag_decision is not None:
        if flag_decision:
            print()
            print(f"Kafka transfer validation enabled by {KAFKA_LEVEL6_RUN_FLAG}=true.")
        else:
            print()
            print(f"Kafka transfer validation skipped by {KAFKA_LEVEL6_SKIP_FLAG}=true.")
            print(f"Unset it or set {KAFKA_LEVEL6_SKIP_FLAG}=false to allow the interactive prompt.")
        return flag_decision

    if not prompt:
        return False
    if _adapter_auto_mode_enabled(adapter):
        print()
        print("Kafka transfer validation is available but this Level 6 run is in auto mode.")
        print(f"To enable it explicitly, rerun with {KAFKA_LEVEL6_RUN_FLAG}=true.")
        return False
    if not bool(getattr(sys.stdin, "isatty", lambda: False)()):
        print()
        print("Kafka transfer validation is available but this Level 6 run is non-interactive.")
        print(f"To enable it explicitly, rerun with {KAFKA_LEVEL6_RUN_FLAG}=true.")
        return False

    print()
    print("Kafka transfer validation is available for this Level 6 run.")
    print("It is disabled by default because it can take significantly longer than the rest of the suites.")
    return _interactive_confirm("Run Kafka validation suites too?", default=False)


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
    deployer_context=None,
):
    """Build the Level 6 functional EDC+Kafka validator from adapter hooks."""
    load_connector_credentials = _resolve_adapter_callable(
        adapter,
        "connectors.load_connector_credentials",
        "load_connector_credentials",
    )
    base_load_deployer_config = _resolve_adapter_callable(
        adapter,
        "config_adapter.load_deployer_config",
        "load_deployer_config",
    )
    load_deployer_config = _context_config_loader(
        base_load_deployer_config,
        deployer_context=deployer_context,
    )
    ds_domain_resolver = _resolve_adapter_callable(
        adapter,
        "config.ds_domain_base",
        "ds_domain_base",
    )
    ds_domain_resolver = _context_ds_domain_resolver(
        ds_domain_resolver,
        deployer_context=deployer_context,
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
        "connectors.build_protocol_address",
        "connectors.build_public_protocol_address",
        "connectors.build_internal_protocol_address",
    )
    keycloak_url_resolver = None
    if deployer_context is not None:
        keycloak_url_resolver = lambda: _edc_keycloak_public_base_url(deployer_context)

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
        keycloak_url_resolver=keycloak_url_resolver,
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
        "partial": "\033[33m",
        "not-recorded": "\033[33m",
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
        "partial": "-",
        "not-recorded": "-",
    }
    normalized = str(status or "unknown").lower()
    icon = status_labels.get(normalized, "?")
    return _colorize_console_icon(icon, normalized, stream=stream)


def _console_color(text, code, *, stream=None):
    if not _console_supports_color(stream=stream):
        return text
    return f"\033[{code}m{text}\033[0m"


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


def _kafka_result_log_key(result):
    if not isinstance(result, dict):
        return None
    provider = str(result.get("provider", "unknown-provider")).strip()
    consumer = str(result.get("consumer", "unknown-consumer")).strip()
    return provider, consumer


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
    kafka_enabled=None,
    deployer_context=None,
):
    """Run the functional EDC+Kafka suite after Newman when enabled in Level 6."""
    if not _supports_level6_kafka_edc(
        adapter,
        validation_profile=validation_profile,
        deployer_name=deployer_name,
    ):
        return []
    if kafka_enabled is None:
        kafka_enabled = should_run_kafka_edc_validation(flag_enabled=_env_flag)
    if not kafka_enabled:
        results = [
            {
                "status": "skipped",
                "reason": "disabled_by_level6_kafka_flags",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        ]
        _save_kafka_edc_results(results, experiment_dir, experiment_storage=experiment_storage)
        print_interoperability_suite_header("Kafka transfer interoperability", "Kafka")
        print(
            "Kafka transfer validation suite skipped. Kafka validations are disabled by default in Level 6 "
            "to keep routine validation faster. In an interactive Level 6 run, answer yes when prompted. "
            "For non-interactive runs, set PIONERA_LEVEL6_RUN_KAFKA=true. If PIONERA_LEVEL6_SKIP_KAFKA "
            "is enabled, unset it or set PIONERA_LEVEL6_SKIP_KAFKA=false."
        )
        return results

    print_interoperability_suite_header("Kafka transfer interoperability", "Kafka")
    kafka_preflight = _run_level6_kafka_preflight(
        adapter,
        experiment_dir=experiment_dir,
        deployer_context=deployer_context,
    )
    if str(kafka_preflight.get("status") or "").lower() == "failed":
        if kafka_preparation is not None:
            kafka_preparation.stop_runtime()
        message = "; ".join(kafka_preflight.get("errors") or []) or "Kafka runtime preflight failed"
        results = [
            {
                "status": "failed",
                "reason": "kafka_runtime_preflight_failed",
                "preflight": kafka_preflight,
                "error": {
                    "type": "KafkaRuntimePreflightError",
                    "message": message,
                },
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        ]
        _save_kafka_edc_results(results, experiment_dir, experiment_storage=experiment_storage)
        _print_kafka_edc_results(results)
        return results

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
    progress_state = {"heading_printed": False, "printed_result_keys": set()}

    def _print_progress_result(result):
        if not progress_state["heading_printed"]:
            print("Kafka transfer validation results:")
            progress_state["heading_printed"] = True
        verbose_messages = _env_flag(
            "PIONERA_KAFKA_TRANSFER_LOG_MESSAGES",
            _env_flag("KAFKA_TRANSFER_LOG_MESSAGES", False),
        )
        _print_kafka_edc_result(result, verbose_messages=verbose_messages)
        result_key = _kafka_result_log_key(result)
        if result_key is not None:
            progress_state["printed_result_keys"].add(result_key)

    try:
        validator = build_kafka_edc_validation_suite(
            adapter,
            suite_cls=suite_cls,
            experiment_storage=experiment_storage,
            kafka_manager_cls=kafka_manager_cls,
            kafka_manager=prepared_kafka_manager,
            deployer_context=deployer_context,
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

    missing_progress_results = []
    if progress_state["heading_printed"]:
        printed_result_keys = progress_state["printed_result_keys"]
        missing_progress_results = [
            result
            for result in list(results or [])
            if _kafka_result_log_key(result) not in printed_result_keys
        ]
        if missing_progress_results:
            _print_kafka_edc_results(
                missing_progress_results,
                include_heading=False,
                include_results=True,
                include_summary=False,
            )

    _print_kafka_edc_results(
        results,
        include_heading=not progress_state["heading_printed"],
        include_results=not progress_state["heading_printed"],
        include_summary=True,
    )
    return list(results or [])


def _status_from_kafka_results(results):
    normalized_statuses = {
        str(item.get("status", "")).strip().lower()
        for item in list(results or [])
        if isinstance(item, dict)
    }
    if not normalized_statuses:
        return "skipped"
    if "failed" in normalized_statuses or "error" in normalized_statuses:
        return "failed"
    if normalized_statuses == {"skipped"}:
        return "skipped"
    if "passed" in normalized_statuses:
        return "passed"
    return "completed"


def _level6_normalized_status(status):
    raw = str(status or "").strip().lower()
    if raw in {"passed", "success", "ok", "completed", "succeeded"}:
        return "passed"
    if raw in {"failed", "fail", "error", "terminated"}:
        return "failed"
    if raw in {"skipped", "skip", "pending", "disabled"}:
        return "skipped"
    if raw in {"partial", "partially-passed", "passed-with-warnings", "warning"}:
        return "partial"
    return raw or "unknown"


def _level6_failure_reason(*candidates):
    for candidate in candidates:
        if isinstance(candidate, dict):
            for key in ("message", "reason", "error", "details"):
                value = candidate.get(key)
                if isinstance(value, dict):
                    nested = _level6_failure_reason(value)
                    if nested:
                        return nested
                if value not in (None, ""):
                    return str(value)
        elif candidate not in (None, ""):
            return str(candidate)
    return "See the generated suite artifact for details."


def _level6_case_label(case):
    case_id = str(case.get("test_case_id") or case.get("case_id") or case.get("id") or "").strip()
    title = str(
        case.get("description")
        or case.get("expected_result")
        or case.get("name")
        or case.get("title")
        or ""
    ).strip()
    if case_id and title:
        if title.lower().startswith(case_id.lower()):
            return title
        return f"{case_id}: {title}"
    return case_id or title or "Unnamed test"


def _iter_level6_component_failed_tests(component_results):
    for component_result in component_results or []:
        if not isinstance(component_result, dict):
            continue
        component = str(component_result.get("component") or "component").replace("-", " ").title()
        phases = component_result.get("phases")
        emitted = False
        if isinstance(phases, dict):
            phase_order = list(component_result.get("phase_order") or phases.keys())
            for phase in phase_order:
                phase_result = phases.get(phase)
                if not isinstance(phase_result, dict):
                    continue
                phase_name = str(phase_result.get("display_name") or phase).replace("_", " ").replace("-", " ").title()
                case_groups = [phase_result.get("executed_cases")]
                suites = phase_result.get("suites")
                if isinstance(suites, dict):
                    for suite_result in suites.values():
                        if isinstance(suite_result, dict):
                            case_groups.append(suite_result.get("executed_cases"))
                for cases in case_groups:
                    for case in cases or []:
                        if not isinstance(case, dict):
                            continue
                        evaluation = case.get("evaluation") if isinstance(case.get("evaluation"), dict) else {}
                        response = case.get("response") if isinstance(case.get("response"), dict) else {}
                        if _level6_normalized_status(evaluation.get("status") or case.get("status")) != "failed":
                            continue
                        emitted = True
                        yield {
                            "suite": f"{component} / {phase_name}",
                            "test": _level6_case_label(case),
                            "reason": _level6_failure_reason(evaluation, response, case),
                        }
        if emitted:
            continue
        if _level6_normalized_status(component_result.get("status")) == "failed":
            yield {
                "suite": component,
                "test": "Component validation",
                "reason": _level6_failure_reason(component_result.get("error"), component_result.get("reason")),
            }


def _level6_playwright_suite_name(playwright_result=None, validation_profile=None):
    if validation_profile is not None:
        return _playwright_interoperability_suite_name(validation_profile)
    if isinstance(playwright_result, dict):
        suite = str(
            playwright_result.get("suite")
            or playwright_result.get("test")
            or playwright_result.get("adapter")
            or ""
        ).strip()
        lowered = suite.lower()
        if lowered == "edc":
            return "EDC UI"
        if lowered == "inesdata":
            return "INESData integration"
        if suite:
            return suite
    return "Playwright validation"


def _iter_level6_playwright_failed_tests(playwright_result, validation_profile=None):
    if not isinstance(playwright_result, dict):
        return
    summary = playwright_result.get("summary") if isinstance(playwright_result.get("summary"), dict) else {}
    suite_name = _level6_playwright_suite_name(playwright_result, validation_profile)
    for spec in summary.get("spec_results") or []:
        if not isinstance(spec, dict):
            continue
        if _level6_normalized_status(spec.get("status")) != "failed":
            continue
        title = str(spec.get("title") or spec.get("file") or "Playwright test").strip()
        yield {
            "suite": suite_name,
            "test": title,
            "reason": _level6_failure_reason(spec.get("error"), spec.get("reason")),
        }


def _iter_level6_kafka_failed_tests(kafka_results):
    for result in kafka_results or []:
        if not isinstance(result, dict):
            continue
        if _level6_normalized_status(result.get("status")) != "failed":
            continue
        provider = result.get("provider", "unknown-provider")
        consumer = result.get("consumer", "unknown-consumer")
        yield {
            "suite": "Kafka transfer interoperability",
            "test": f"Kafka transfer: {provider} -> {consumer}",
            "reason": _level6_failure_reason(result.get("error"), result.get("reason")),
        }


def _dedupe_level6_failures(failures):
    unique = []
    seen = set()
    for failure in failures or []:
        if not isinstance(failure, dict):
            continue
        key = (
            str(failure.get("suite") or ""),
            str(failure.get("test") or ""),
            str(failure.get("reason") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(failure)
    return unique


def _playwright_interoperability_suite_name(validation_profile):
    adapter_name = str(getattr(validation_profile, "adapter", "") or "").strip()
    adapter_key = adapter_name.lower()
    if adapter_key == "inesdata":
        return "INESData integration"
    if adapter_key == "edc":
        return "EDC UI"
    if adapter_name:
        return f"{adapter_name} Playwright"
    return "Playwright validation"


def _collect_level6_validation_failures(
    *,
    validation_error=None,
    playwright_result=None,
    playwright_failure=None,
    component_results=None,
    kafka_edc_results=None,
    validation_profile=None,
):
    failures = []
    if validation_error is not None:
        failures.append(
            {
                "suite": "Newman connector interoperability",
                "test": "Newman execution",
                "reason": str(validation_error),
            }
        )
    failures.extend(list(_iter_level6_playwright_failed_tests(playwright_result, validation_profile)))
    failures.extend(list(_iter_level6_component_failed_tests(component_results)))
    failures.extend(list(_iter_level6_kafka_failed_tests(kafka_edc_results)))
    failures = _dedupe_level6_failures(failures)
    playwright_suite = _level6_playwright_suite_name(playwright_result, validation_profile)
    if playwright_failure and not any(item["suite"] == playwright_suite for item in failures):
        failures.append(
            {
                "suite": playwright_suite,
                "test": "Playwright execution",
                "reason": f"Playwright validation failed with status '{playwright_failure}'",
            }
        )
    return failures


def _level6_empty_counts():
    return {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "other": 0}


def _level6_increment_counts(counts, status):
    counts["total"] += 1
    normalized = _level6_normalized_status(status)
    if normalized in {"passed", "failed", "skipped"}:
        counts[normalized] += 1
    elif normalized == "partial":
        counts["skipped"] += 1
    else:
        counts["other"] += 1


def _level6_counts_from_playwright(playwright_result):
    counts = _level6_empty_counts()
    if not isinstance(playwright_result, dict):
        return counts
    summary = playwright_result.get("summary") if isinstance(playwright_result.get("summary"), dict) else {}
    specs = [spec for spec in summary.get("spec_results") or [] if isinstance(spec, dict)]
    if specs:
        for spec in specs:
            _level6_increment_counts(counts, spec.get("status"))
        return counts
    status_counts = summary.get("status_counts") if isinstance(summary.get("status_counts"), dict) else {}
    if status_counts:
        counts["passed"] += int(status_counts.get("passed") or status_counts.get("expected") or 0)
        counts["failed"] += int(
            (status_counts.get("failed") or 0)
            + (status_counts.get("unexpected") or 0)
            + (status_counts.get("timedout") or 0)
            + (status_counts.get("interrupted") or 0)
        )
        counts["skipped"] += int(status_counts.get("skipped") or 0)
        total = int(summary.get("total_specs") or sum(int(value or 0) for value in status_counts.values()))
        counts["other"] += max(total - counts["passed"] - counts["failed"] - counts["skipped"], 0)
        counts["total"] += total
        return counts
    if playwright_result.get("status"):
        _level6_increment_counts(counts, playwright_result.get("status"))
    return counts


def _level6_counts_from_components(component_results):
    counts = _level6_empty_counts()
    for component_result in component_results or []:
        if not isinstance(component_result, dict):
            continue
        phases = component_result.get("phases")
        if isinstance(phases, dict) and phases:
            phase_order = list(component_result.get("phase_order") or phases.keys())
            counted_phase = False
            for phase in phase_order:
                phase_result = phases.get(phase)
                if not isinstance(phase_result, dict):
                    continue
                summary = phase_result.get("summary") if isinstance(phase_result.get("summary"), dict) else {}
                if summary:
                    counted_phase = True
                    counts["total"] += int(summary.get("total") or 0)
                    counts["passed"] += int(summary.get("passed") or 0)
                    counts["failed"] += int(summary.get("failed") or 0)
                    counts["skipped"] += int(summary.get("skipped") or 0)
                else:
                    counted_phase = True
                    _level6_increment_counts(counts, phase_result.get("status"))
            if counted_phase:
                known = counts["passed"] + counts["failed"] + counts["skipped"]
                counts["other"] = max(counts["total"] - known, counts["other"])
                continue
        summary = component_result.get("summary") if isinstance(component_result.get("summary"), dict) else {}
        if summary:
            counts["total"] += int(summary.get("total") or 0)
            counts["passed"] += int(summary.get("passed") or 0)
            counts["failed"] += int(summary.get("failed") or 0)
            counts["skipped"] += int(summary.get("skipped") or 0)
            known = counts["passed"] + counts["failed"] + counts["skipped"]
            counts["other"] = max(counts["total"] - known, counts["other"])
        else:
            _level6_increment_counts(counts, component_result.get("status"))
    return counts


def _level6_counts_from_kafka(kafka_edc_results):
    counts = _level6_empty_counts()
    for result in kafka_edc_results or []:
        if isinstance(result, dict):
            _level6_increment_counts(counts, result.get("status"))
    return counts


def _level6_counts_from_newman(validation_error):
    counts = _level6_empty_counts()
    if validation_error is None:
        _level6_increment_counts(counts, "passed")
    else:
        _level6_increment_counts(counts, "failed")
    return counts


def _level6_counts_status(counts):
    if not isinstance(counts, dict) or not int(counts.get("total") or 0):
        return "not-recorded"
    if int(counts.get("failed") or 0) or int(counts.get("other") or 0):
        return "failed"
    if int(counts.get("skipped") or 0):
        return "partial"
    return "passed"


def _level6_global_summary(
    *,
    validation_error=None,
    playwright_result=None,
    component_results=None,
    kafka_edc_results=None,
    validation_profile=None,
):
    layers = [
        {
            "name": "Newman connector interoperability",
            "status": "failed" if validation_error is not None else "passed",
            "counts": _level6_counts_from_newman(validation_error),
        }
    ]
    if isinstance(playwright_result, dict):
        playwright_counts = _level6_counts_from_playwright(playwright_result)
        layers.append(
            {
                "name": _level6_playwright_suite_name(playwright_result, validation_profile),
                "status": _level6_counts_status(playwright_counts),
                "counts": playwright_counts,
            }
        )
    if component_results:
        component_counts = _level6_counts_from_components(component_results)
        layers.append(
            {
                "name": "Component validation test cases",
                "status": _level6_counts_status(component_counts),
                "counts": component_counts,
            }
        )
    if kafka_edc_results:
        kafka_counts = _level6_counts_from_kafka(kafka_edc_results)
        layers.append(
            {
                "name": "Kafka transfer validation",
                "status": _level6_counts_status(kafka_counts),
                "counts": kafka_counts,
            }
        )

    total = _level6_empty_counts()
    for layer in layers:
        counts = layer.get("counts") or {}
        for key in total:
            total[key] += int(counts.get(key) or 0)
    return {
        "status": _level6_counts_status(total),
        "counts": total,
        "layers": layers,
    }


def _format_level6_counts(counts):
    counts = counts if isinstance(counts, dict) else {}
    return (
        f"{int(counts.get('passed') or 0)}/{int(counts.get('total') or 0)} passed, "
        f"{int(counts.get('failed') or 0)} failed, "
        f"{int(counts.get('skipped') or 0)} skipped"
    )


def _print_level6_validation_summary(
    *,
    experiment_dir,
    framework_report=None,
    validation_error=None,
    playwright_result=None,
    playwright_failure=None,
    component_results=None,
    kafka_edc_results=None,
    validation_profile=None,
):
    failures = _collect_level6_validation_failures(
        validation_error=validation_error,
        playwright_result=playwright_result,
        playwright_failure=playwright_failure,
        component_results=component_results,
        kafka_edc_results=kafka_edc_results,
        validation_profile=validation_profile,
    )
    global_summary = _level6_global_summary(
        validation_error=validation_error,
        playwright_result=playwright_result,
        component_results=component_results,
        kafka_edc_results=kafka_edc_results,
        validation_profile=validation_profile,
    )

    status = "failed" if failures else _level6_counts_status(global_summary.get("counts"))
    if status == "not-recorded":
        status = "skipped"
    print(f"\n{_console_color('Level 6 validation summary', '36;1')}\n")
    print(f"  Status: {_console_status_label(status)} {status}")
    print(f"  Global checks: {_format_level6_counts(global_summary.get('counts'))}")
    print("  Validation layers:")
    for layer in global_summary.get("layers") or []:
        layer_status = str(layer.get("status") or "unknown")
        print(
            f"    {_console_status_label(layer_status)} {layer.get('name')}: "
            f"{_format_level6_counts(layer.get('counts'))}"
        )
    if experiment_dir:
        print(f"  Experiment: {os.path.basename(str(experiment_dir))}")
    if isinstance(framework_report, dict) and framework_report.get("path"):
        print(f"  Dashboard: {framework_report['path']}")
    if failures:
        print("  Failed tests:")
        for item in failures:
            print(f"    {_console_status_label('failed')} [{item['suite']}] {item['test']} - {item['reason']}")
    else:
        print(f"  Failed tests: {_console_status_label('passed')} none")
    return {
        "status": status,
        "failures": failures,
        "global_summary": global_summary,
    }


def run_interoperability_newman_tests(
    adapter,
    *,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
):
    """Run only the Newman connector interoperability collections."""
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
    experiment_dir = experiment_storage.create_experiment_directory()

    with _Level6ConsoleCapture(
        experiment_dir,
        filename=NEWMAN_CONSOLE_LOG_FILENAME,
        label="Newman interoperability console log",
    ):
        _save_experiment_metadata(
            experiment_storage,
            experiment_dir,
            connectors,
            **_experiment_metadata_context(
                adapter_name=resolved_deployer_name,
                topology=topology,
                adapter=type(adapter).__name__,
                baseline=False,
            ),
        )
        experiment_storage.newman_reports_dir(experiment_dir)
        hosts_sync = (
            _sync_deployer_hosts_if_enabled(deployer_context)
            if deployer_context is not None
            else {"status": "skipped", "reason": "missing-deployer-context"}
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

        validation_engine = build_validation_engine(
            adapter,
            engine_cls=validation_engine_cls,
            deployer_context=deployer_context,
        )
        run_method = validation_engine.run
        try:
            parameters = inspect.signature(run_method).parameters
        except (TypeError, ValueError):
            parameters = {}
        print_interoperability_suite_header("Newman connector interoperability", "Newman")
        if "experiment_dir" in parameters:
            validation_result = run_method(connectors, experiment_dir=experiment_dir)
        else:
            validation_result = run_method(connectors)

        metrics_collector = build_metrics_collector(
            adapter,
            collector_cls=metrics_collector_cls,
            experiment_storage=experiment_storage,
        )
        collect_newman_metrics = getattr(metrics_collector, "collect_experiment_newman_metrics", None)
        if callable(collect_newman_metrics):
            newman_request_metrics = collect_newman_metrics(experiment_dir)
        else:
            newman_request_metrics = metrics_collector.collect_newman_request_metrics(
                experiment_storage.newman_reports_dir(experiment_dir),
                experiment_dir=experiment_dir,
            )

    return {
        "status": "completed",
        "experiment_dir": experiment_dir,
        "adapter": resolved_deployer_name,
        "topology": topology,
        "connectors": list(connectors or []),
        "validation": validation_result,
        "newman_request_metrics": newman_request_metrics,
        "storage_checks": list(getattr(validation_engine, "last_storage_checks", []) or []),
        "test_data_cleanup": test_data_cleanup,
        "public_endpoint_preflight": public_endpoint_preflight,
        "hosts_sync": hosts_sync,
        "validation_profile": (
            validation_profile.as_dict()
            if validation_profile is not None and hasattr(validation_profile, "as_dict")
            else validation_profile
        ),
    }


def run_interoperability_kafka_tests(
    adapter,
    *,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
    experiment_storage=ExperimentStorage,
    kafka_manager_cls=KafkaManager,
    kafka_edc_validation_suite_cls=KafkaEdcValidationSuite,
):
    """Run only the Kafka transfer interoperability suite."""
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
    if not _supports_level6_kafka_edc(
        adapter,
        validation_profile=validation_profile,
        deployer_name=resolved_deployer_name,
    ):
        raise RuntimeError(
            f"Adapter '{resolved_deployer_name}' does not support Kafka transfer interoperability tests."
        )

    experiment_dir = experiment_storage.create_experiment_directory()
    with _Level6ConsoleCapture(
        experiment_dir,
        filename=KAFKA_CONSOLE_LOG_FILENAME,
        label="Kafka interoperability console log",
    ):
        _save_experiment_metadata(
            experiment_storage,
            experiment_dir,
            connectors,
            **_experiment_metadata_context(
                adapter_name=resolved_deployer_name,
                topology=topology,
                adapter=type(adapter).__name__,
                baseline=False,
            ),
        )
        kafka_preparation = _start_level6_kafka_preparation(
            adapter,
            connectors,
            validation_profile=validation_profile,
            deployer_name=resolved_deployer_name,
            kafka_manager_cls=kafka_manager_cls,
            background=False,
            kafka_enabled=True,
        )
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
            kafka_enabled=True,
            deployer_context=deployer_context,
        )

    return {
        "status": _status_from_kafka_results(kafka_edc_results),
        "experiment_dir": experiment_dir,
        "adapter": resolved_deployer_name,
        "topology": topology,
        "connectors": list(connectors or []),
        "kafka_edc_results": kafka_edc_results,
        "validation_profile": (
            validation_profile.as_dict()
            if validation_profile is not None and hasattr(validation_profile, "as_dict")
            else validation_profile
        ),
    }


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

    if command in {"public-access", "ssh-access"}:
        include_deployer_dry_run = False
    elif include_deployer_dry_run is None:
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

    adapter_preview = _resolve_adapter_preview_for_topology(adapter, command, topology=topology)
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

    if command == "public-access":
        preview["actions"] = [
            "reconcile_ingress_service_type",
            "reconcile_vm_distributed_routing",
            "reconcile_common_public_path_ingresses",
            "reconcile_component_public_path_ingresses",
        ]
        preview["public_access"] = {
            "status": "planned",
            "topology": topology,
            "supported": str(topology or "").strip().lower() == "vm-distributed",
        }
        return preview

    if command == "ssh-access":
        preview["actions"] = [
            "build_idempotent_ssh_bootstrap_plan",
            "self_test_temporary_ssh_key_creation",
            "verify_dedicated_identity_file",
            "plan_authorized_keys_reconciliation",
            "plan_batchmode_ssh_checks",
        ]
        preview["ssh_access"] = {
            "status": "planned",
            "topology": topology,
            "supported": str(topology or "").strip().lower() in {"vm-single", "vm-distributed"},
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


def _resolve_adapter_preview_for_topology(adapter, command, topology="local"):
    environment_overrides = _topology_runtime_environment_overrides(topology)
    if environment_overrides:
        with _temporary_environment(environment_overrides):
            return _resolve_adapter_preview(adapter, command)
    return _resolve_adapter_preview(adapter, command)


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


def _is_loopback_endpoint(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return False
    if raw_value in {"localhost", "127.0.0.1", "::1"}:
        return True
    parsed = urllib.parse.urlparse(raw_value if "://" in raw_value else f"//{raw_value}")
    host = str(parsed.hostname or raw_value).strip().lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _test_data_cleanup_requires_local_infra_access(deployer_context):
    context_topology = normalize_topology(
        deployer_context.get("topology") if isinstance(deployer_context, dict) else getattr(deployer_context, "topology", None)
    )
    if context_topology == LOCAL_TOPOLOGY:
        return True

    config = (
        deployer_context.get("config", {}) if isinstance(deployer_context, dict)
        else getattr(deployer_context, "config", {})
    )
    if not isinstance(config, dict):
        return False

    endpoint_values = [
        config.get("PG_HOST"),
        config.get("MINIO_ENDPOINT"),
        config.get("VT_URL"),
        config.get("VAULT_URL"),
    ]
    return any(_is_loopback_endpoint(value) for value in endpoint_values)


def _test_data_cleanup_context_with_public_runtime(deployer_context):
    if deployer_context is None:
        return None

    if isinstance(deployer_context, dict):
        payload = dict(deployer_context)
    elif callable(getattr(deployer_context, "as_dict", None)):
        payload = dict(deployer_context.as_dict())
    else:
        payload = {
            "deployer": getattr(deployer_context, "deployer", ""),
            "topology": getattr(deployer_context, "topology", ""),
            "environment": getattr(deployer_context, "environment", ""),
            "dataspace_name": getattr(deployer_context, "dataspace_name", ""),
            "ds_domain_base": getattr(deployer_context, "ds_domain_base", ""),
            "connectors": list(getattr(deployer_context, "connectors", []) or []),
            "components": list(getattr(deployer_context, "components", []) or []),
            "config": dict(getattr(deployer_context, "config", {}) or {}),
        }

    config = dict(payload.get("config") or {})
    topology = normalize_topology(payload.get("topology") or config.get("TOPOLOGY"))
    if topology in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}:
        public_config = {**config, "TOPOLOGY": topology}
        public_urls = resolve_vm_distributed_public_urls(public_config)

        def replace_missing_or_placeholder(key, value):
            normalized_value = normalize_public_endpoint_url(value)
            if not normalized_value:
                return
            if _vm_public_url_candidate(public_config, config.get(key)):
                return
            config[key] = normalized_value

        replace_missing_or_placeholder(
            "KEYCLOAK_FRONTEND_URL",
            public_urls.get("KEYCLOAK_FRONTEND_URL") or public_urls.get("KEYCLOAK_PUBLIC_URL"),
        )
        replace_missing_or_placeholder(
            "KEYCLOAK_PUBLIC_URL",
            public_urls.get("KEYCLOAK_PUBLIC_URL") or public_urls.get("KEYCLOAK_FRONTEND_URL"),
        )
        replace_missing_or_placeholder(
            "MINIO_API_PUBLIC_URL",
            public_urls.get("MINIO_API_PUBLIC_URL") or public_urls.get("MINIO_PUBLIC_URL"),
        )
        replace_missing_or_placeholder(
            "MINIO_PUBLIC_URL",
            public_urls.get("MINIO_PUBLIC_URL") or public_urls.get("MINIO_API_PUBLIC_URL"),
        )
        replace_missing_or_placeholder(
            "MINIO_CONSOLE_PUBLIC_URL",
            public_urls.get("MINIO_CONSOLE_PUBLIC_URL"),
        )

    payload["config"] = config
    return types.SimpleNamespace(**payload)


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
    topology = str(getattr(deployer_context, "topology", "") or "").strip().lower()
    vm_public_topology = topology in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}

    if vm_public_topology:
        public_config = {**config, "TOPOLOGY": topology}
        public_urls = resolve_vm_distributed_public_urls(public_config)
        public_candidate = lambda value: _vm_public_url_candidate(public_config, value)
        _append_public_endpoint(
            endpoints,
            seen,
            "Keycloak public",
            public_candidate(config.get("KEYCLOAK_FRONTEND_URL"))
            or public_candidate(config.get("KEYCLOAK_PUBLIC_URL"))
            or public_urls.get("KEYCLOAK_FRONTEND_URL")
            or public_urls.get("KEYCLOAK_PUBLIC_URL"),
        )
        _append_public_endpoint(
            endpoints,
            seen,
            "MinIO console",
            public_candidate(config.get("MINIO_CONSOLE_PUBLIC_URL"))
            or public_candidate(config.get("MINIO_PUBLIC_URL"))
            or public_urls.get("MINIO_CONSOLE_PUBLIC_URL")
            or public_urls.get("MINIO_PUBLIC_URL"),
        )
        _append_public_endpoint(
            endpoints,
            seen,
            "MinIO API",
            public_candidate(config.get("PIONERA_LEVEL6_MINIO_ENDPOINT"))
            or public_candidate(config.get("LEVEL6_MINIO_ENDPOINT"))
            or public_candidate(config.get("EDC_LEVEL6_MINIO_ENDPOINT"))
            or public_candidate(config.get("MINIO_API_PUBLIC_URL"))
            or public_candidate(config.get("MINIO_PUBLIC_URL"))
            or public_urls.get("MINIO_API_PUBLIC_URL")
            or public_urls.get("MINIO_PUBLIC_URL"),
        )
    else:
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


@contextlib.contextmanager
def _temporary_environment(overrides):
    previous = {}
    sentinel = object()
    try:
        for key, value in (overrides or {}).items():
            if value is None:
                continue
            previous[key] = os.environ.get(key, sentinel)
            os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _normalized_component_tokens(values):
    if values is None:
        return []
    if isinstance(values, str):
        raw_values = values.split(",")
    else:
        raw_values = values
    return _unique_non_empty(
        str(value or "").strip().lower().replace("_", "-")
        for value in raw_values
        if str(value or "").strip()
    )


def _level6_component_validation_needs_vm_single_mapping_editor(config, components=None):
    configured_components = _normalized_component_tokens(components)
    if not configured_components:
        configured_components = _normalized_component_tokens((config or {}).get("COMPONENTS"))
    if "semantic-virtualization" not in configured_components:
        return False
    enabled = str(
        os.environ.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI")
        or (config or {}).get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI")
        or "1"
    ).strip().lower()
    return enabled not in {"0", "false", "no", "off", "disabled"}


def _level6_component_validation_environment(deployer_context, deployer_name, components=None):
    if deployer_context is None:
        return {}
    adapter_name = str(deployer_name or "").strip().lower()
    connectors = list(getattr(deployer_context, "connectors", []) or [])
    dataspace = str(getattr(deployer_context, "dataspace_name", "") or "").strip()
    ds_domain = str(getattr(deployer_context, "ds_domain_base", "") or "").strip()
    topology = str(getattr(deployer_context, "topology", "") or "").strip()
    keycloak_url = _public_keycloak_base_url(deployer_context)
    provider = connectors[0] if connectors else ""
    consumer = connectors[1] if len(connectors) > 1 else ""
    config = dict(getattr(deployer_context, "config", {}) or {})
    environment = str(getattr(deployer_context, "environment", "") or config.get("ENVIRONMENT") or "DEV").strip()
    runtime_dir = str(getattr(deployer_context, "runtime_dir", "") or "").strip()

    def _connector_base_url(connector, role):
        configured = _configured_public_connector_base_url(connector, deployer_context)
        if configured:
            return configured.rstrip("/")
        if connector and ds_domain:
            return f"http://{connector}.{ds_domain}"
        return ""

    def _connector_protocol_base_url(connector, role, public_base_url):
        mode = str(
            config.get("PIONERA_CONNECTOR_PROTOCOL_ADDRESS_MODE")
            or config.get("CONNECTOR_PROTOCOL_ADDRESS_MODE")
            or "public"
        ).strip().lower()
        if mode in {"internal", "private"} and connector and ds_domain:
            return f"http://{connector}.{ds_domain}"
        return public_base_url

    env = {
        "PIONERA_ADAPTER": adapter_name,
        "UI_ADAPTER": adapter_name,
        "AI_MODEL_HUB_COMPONENT_ADAPTER": adapter_name,
        "PIONERA_TOPOLOGY": topology,
        "INESDATA_TOPOLOGY": topology,
        "UI_TOPOLOGY": topology,
        "UI_DATASPACE": dataspace,
        "UI_ENVIRONMENT": environment,
        "UI_DS_DOMAIN": ds_domain,
        "AI_MODEL_HUB_KEYCLOAK_URL": keycloak_url,
    }
    if runtime_dir:
        env["UI_RUNTIME_DIR"] = runtime_dir
    component_validation_mode = str(
        config.get("PIONERA_COMPONENT_VALIDATION_MODE")
        or config.get("LEVEL6_COMPONENT_VALIDATION_MODE")
        or config.get("COMPONENT_VALIDATION_MODE")
        or ""
    ).strip()
    if component_validation_mode:
        env["PIONERA_COMPONENT_VALIDATION_MODE"] = component_validation_mode
        env["LEVEL6_COMPONENT_VALIDATION_MODE"] = component_validation_mode
    for key in (
        "AI_MODEL_HUB_MODEL_SERVER_MODE",
        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL",
        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH",
        "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
        "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL",
        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY",
        "AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH",
        "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_URL",
        "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_DISCOVERY_PATH",
        "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINTS",
        "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_PAYLOAD",
        "AI_MODEL_HUB_ENABLE_MODEL_SERVER_USE_CASES",
        "COMPONENTS_PUBLIC_BASE_URL",
        "MODEL_SERVER_PUBLIC_URL",
        "MODEL_SERVER_PUBLIC_PATH",
    ):
        value = str(config.get(key) or "").strip()
        if value:
            env[key] = value
    env.update(_topology_runtime_environment_overrides(topology=topology, level=5, role="components"))
    if normalize_topology(topology) == "vm-single" and _level6_component_validation_needs_vm_single_mapping_editor(
        config,
        components=components,
    ):
        env.update(_vm_single_component_validation_tunnel_environment(config))
    if provider:
        provider_base_url = _connector_base_url(provider, "provider")
        provider_protocol_base_url = _connector_protocol_base_url(provider, "provider", provider_base_url)
        env.update(
            {
                "AI_MODEL_HUB_PROVIDER_CONNECTOR_ID": provider,
                "AI_MODEL_HUB_CONNECTOR_GOVERNANCE_PROVIDER": provider,
                "AI_MODEL_HUB_MODEL_EXECUTION_PROVIDER": provider,
                "AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL": (
                    f"{provider_base_url}/management" if provider_base_url else ""
                ),
                "AI_MODEL_HUB_PROVIDER_PROTOCOL_URL": (
                    f"{provider_protocol_base_url}/protocol" if provider_protocol_base_url else ""
                ),
                "AI_MODEL_HUB_PROVIDER_DEFAULT_URL": (
                    f"{provider_base_url}/api" if provider_base_url else ""
                ),
            }
        )
    if consumer:
        consumer_base_url = _connector_base_url(consumer, "consumer")
        consumer_protocol_base_url = _connector_protocol_base_url(consumer, "consumer", consumer_base_url)
        env.update(
            {
                "AI_MODEL_HUB_CONSUMER_CONNECTOR_ID": consumer,
                "AI_MODEL_HUB_CONNECTOR_GOVERNANCE_CONSUMER": consumer,
                "AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL": (
                    f"{consumer_base_url}/management" if consumer_base_url else ""
                ),
                "AI_MODEL_HUB_CONSUMER_PROTOCOL_URL": (
                    f"{consumer_protocol_base_url}/protocol" if consumer_protocol_base_url else ""
                ),
                "AI_MODEL_HUB_CONSUMER_DEFAULT_URL": (
                    f"{consumer_base_url}/api" if consumer_base_url else ""
                ),
            }
        )
    return {key: value for key, value in env.items() if str(value or "").strip()}


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
    config = dict(getattr(deployer_context, "config", {}) or {})
    tls_verify = None
    if topology == "vm-distributed":
        tls_verify = _vm_distributed_http_preflight_tls_verify_mode(config)
    elif topology == "vm-single":
        tls_verify = normalize_public_endpoint_tls_verify_mode(
            config.get("VM_SINGLE_HTTP_PREFLIGHT_TLS_VERIFY")
        )

    if announce:
        print("\nVerifying public ingress hostnames...")
    result = ensure_public_endpoints_accessible(
        endpoints,
        topology=topology,
        tls_verify=tls_verify,
    )
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

    infrastructure = getattr(adapter, "infrastructure", None)
    ensure_local_access = getattr(infrastructure, "ensure_local_infra_access", None)
    if (
        callable(ensure_local_access)
        and _test_data_cleanup_requires_local_infra_access(deployer_context)
        and not ensure_local_access()
    ):
        raise RuntimeError(
            "Pre-validation test data cleanup failed. Local infrastructure access is not ready."
        )

    cleanup_result = run_pre_validation_cleanup(
        adapter=adapter,
        context=_test_data_cleanup_context_with_public_runtime(deployer_context),
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
        return build_cluster_runtime(config, topology="vm-single").get("cluster_type", "k3s")
    except Exception:
        return "k3s"


def _configured_vm_single_address():
    config = _load_effective_infrastructure_deployer_config(topology="vm-single")
    cluster_type = _effective_vm_single_cluster_type()
    candidates = _detect_vm_single_address_candidates() if cluster_type == "k3s" else {}
    vm_ip = _normalized_topology_address(candidates.get("vm_ip"))
    for key in (
        "VM_SINGLE_ADDRESS",
        "VM_SINGLE_IP",
        "VM_EXTERNAL_IP",
        "HOSTS_ADDRESS",
        "INGRESS_EXTERNAL_IP",
    ):
        value = _normalized_topology_address(config.get(key))
        if value:
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

    recommended_source = "vm" if vm_ip else ""
    recommended_address = vm_ip
    return {
        "vm_ip": vm_ip,
        "minikube_ip": "",
        "recommended_address": recommended_address,
        "recommended_source": recommended_source,
        "cluster_type": cluster_type,
    }


def _synchronize_vm_single_addresses_after_level1():
    candidates = _detect_vm_single_address_candidates()
    vm_ip = _normalized_topology_address(candidates.get("vm_ip"))
    stale_minikube_ip = _normalized_topology_address(candidates.get("minikube_ip"))
    cluster_type = str(candidates.get("cluster_type") or _effective_vm_single_cluster_type()).strip()
    target_ip = vm_ip
    source = "vm"
    if not target_ip:
        return {"status": "skipped", "reason": "vm-ip-unavailable"}

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
        if cluster_type == "k3s" and stale_minikube_ip and current_value == stale_minikube_ip:
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
        if cluster_type == "k3s" and stale_minikube_ip and current_value == stale_minikube_ip:
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

    if not recommended_address:
        print("Could not detect a vm-single address automatically.")
        print("Set VM_EXTERNAL_IP or INGRESS_EXTERNAL_IP in deployers/infrastructure/topologies/vm-single.config.")
        return not required

    source_label = "hostname -I"
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
    if normalized in {"0", "P", "H", "U", "X", "J"}:
        return True
    return normalized in {"3", "4", "5", "6"}


def _menu_action_benefits_from_vm_distributed_configuration(choice):
    normalized = str(choice or "").strip().upper()
    if normalized in {"0", "P", "H", "U", "X", "J"}:
        return True
    return normalized in {str(level_id) for level_id in LEVEL_DESCRIPTIONS}


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


def _is_supported_level_token(value):
    try:
        level_id = int(str(value).strip())
    except (TypeError, ValueError):
        return False
    return level_id in LEVEL_DESCRIPTIONS


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


def _is_windows_hosts_file(hosts_file):
    normalized = str(hosts_file or "").replace("\\", "/").strip().lower()
    return normalized.endswith("/windows/system32/drivers/etc/hosts")


def _raise_if_windows_hosts_file_is_not_local(context, hosts_file):
    topology = normalize_topology(getattr(context, "topology", "local"))
    if topology == "local" or not _is_windows_hosts_file(hosts_file):
        return
    raise RuntimeError(
        "Windows hosts sync is only supported for the local topology. "
        "For vm-distributed, use the DNS/VPN domains exposed by the network instead of Windows hosts."
    )


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
        if normalize_topology(getattr(context, "topology", "local")) != "local":
            raise RuntimeError(
                "PIONERA_SYNC_HOSTS=true requires PIONERA_HOSTS_FILE to point to the hosts file to update. "
                "For vm-distributed, prefer DNS/VPN domains exposed by the network and avoid Windows hosts."
            )
        raise RuntimeError(
            "PIONERA_SYNC_HOSTS=true requires PIONERA_HOSTS_FILE to point to the hosts file to update. "
            "For Windows from WSL this is usually /mnt/c/Windows/System32/drivers/etc/hosts."
        )

    _raise_if_windows_hosts_file_is_not_local(context, hosts_file)

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
        "reconciled_public_hostnames": result.get("reconciled_public_hostnames", []),
    }


def _resolve_shadow_deploy_preflight(adapter, topology="local"):
    preview = _resolve_adapter_preview_for_topology(adapter, "deploy", topology=topology)
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
    preflight = _resolve_shadow_deploy_preflight(adapter, topology=topology)

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


def _first_non_empty_config_value(config, *keys, default=""):
    values = dict(config or {})
    for key in keys:
        value = str(values.get(key) or "").strip()
        if value:
            return value
    return default


def _edc_vm_single_remote_image_import_target(config):
    values = dict(config or {})
    raw_enabled = str(values.get("VM_SINGLE_REMOTE_IMAGE_IMPORT") or "auto").strip().lower()
    if raw_enabled in {"0", "false", "no", "n", "off", "disabled", "disable", "never", "none"}:
        return None

    host = _first_non_empty_config_value(values, "VM_SINGLE_SSH_HOST", "VM_EXTERNAL_IP", "VM_SINGLE_IP")
    if not host:
        return None

    remote_config = dict(values)
    remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT"] = "true"
    remote_config["VM_COMMON_SSH_HOST"] = host
    remote_config["VM_COMMON_IP"] = _first_non_empty_config_value(values, "VM_EXTERNAL_IP", "VM_SINGLE_IP", default=host)
    remote_config["VM_COMMON_SSH_PORT"] = _first_non_empty_config_value(values, "VM_SINGLE_SSH_PORT", default="22")
    remote_config["VM_COMMON_SSH_USER"] = _first_non_empty_config_value(
        values,
        "VM_SINGLE_SSH_USER",
        "VM_SSH_USER",
        "SSH_BASTION_USER",
    )
    remote_config["VM_COMMON_SSH_IDENTITY_FILE"] = _first_non_empty_config_value(
        values,
        "VM_SINGLE_SSH_IDENTITY_FILE",
        "SSH_IDENTITY_FILE",
        "SSH_BASTION_IDENTITY_FILE",
    )
    access_mode = _first_non_empty_config_value(values, "VM_SINGLE_SSH_ACCESS_MODE")
    if access_mode:
        remote_config["SSH_ACCESS_MODE"] = access_mode
    remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND"] = _first_non_empty_config_value(
        values,
        "VM_SINGLE_REMOTE_IMAGE_IMPORT_COMMAND",
        "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND",
        "K3S_IMAGE_IMPORT_COMMAND",
    )
    remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR"] = _first_non_empty_config_value(
        values,
        "VM_SINGLE_REMOTE_IMAGE_IMPORT_DIR",
        "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR",
        default="/tmp",
    )
    remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE"] = _first_non_empty_config_value(
        values,
        "VM_SINGLE_REMOTE_IMAGE_IMPORT_INTERACTIVE",
        "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE",
        default="auto",
    )
    remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY"] = _first_non_empty_config_value(
        values,
        "VM_SINGLE_REMOTE_IMAGE_IMPORT_TTY",
        "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY",
    )
    remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE"] = _first_non_empty_config_value(
        values,
        "VM_SINGLE_REMOTE_IMAGE_PRUNE",
        "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE",
    )
    remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP"] = _first_non_empty_config_value(
        values,
        "VM_SINGLE_REMOTE_IMAGE_PRUNE_KEEP",
        "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP",
        default="2",
    )
    return remote_k3s_image_import_target(remote_config, role="common")


def _edc_local_image_build_env(adapter, topology, cluster_runtime):
    env = os.environ.copy()
    if normalize_topology(topology) != VM_SINGLE_TOPOLOGY or str(cluster_runtime or "").strip().lower() != "k3s":
        return env
    config_adapter = getattr(adapter, "config_adapter", None)
    config_loader = getattr(config_adapter, "load_deployer_config", None)
    config = dict(config_loader() or {}) if callable(config_loader) else {}
    target = _edc_vm_single_remote_image_import_target(config)
    if target is not None:
        env.update(target.shell_env())
    return env


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
        "connector",
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
    env = _edc_local_image_build_env(adapter, getattr(adapter, "topology", "local"), cluster_runtime)
    result = subprocess.run(command, cwd=root_dir, check=False, env=env)
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
    env = _edc_local_image_build_env(adapter, getattr(adapter, "topology", "local"), cluster_runtime)
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


def _normalize_local_images_mode(value, default="auto"):
    raw_value = str(value if value is not None else default).strip().lower()
    if raw_value in {"0", "false", "no", "off", "disabled", "disable"}:
        return "disabled"
    if raw_value in {"1", "true", "yes", "on", "auto", ""}:
        return "auto"
    if raw_value in {"required", "require", "strict"}:
        return "required"
    return str(default or "auto").strip().lower() or "auto"


def _edc_local_images_mode(config, topology):
    default_mode = "auto" if normalize_topology(topology or LOCAL_TOPOLOGY) == LOCAL_TOPOLOGY else "disabled"
    for candidate in (
        os.getenv("PIONERA_EDC_LOCAL_IMAGES_MODE"),
        os.getenv("EDC_LOCAL_IMAGES_MODE"),
        (config or {}).get("EDC_LOCAL_IMAGES_MODE"),
        (config or {}).get("LEVEL4_EDC_LOCAL_IMAGES_MODE"),
        (config or {}).get("LEVEL4_LOCAL_IMAGES_MODE"),
    ):
        if candidate is not None and str(candidate).strip():
            return _normalize_local_images_mode(candidate, default=default_mode)
    return default_mode


def _edc_topology_supports_local_image_preparation(topology, config=None):
    normalized_topology = normalize_topology(topology or LOCAL_TOPOLOGY)
    mode = _edc_local_images_mode(config or {}, normalized_topology)
    if mode == "disabled":
        return False
    return normalized_topology in {LOCAL_TOPOLOGY, "vm-single"}


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
            _edc_topology_supports_local_image_preparation(normalized_topology, config)
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

    if _edc_topology_supports_local_image_preparation(normalized_topology, config):
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


def run_public_access(adapter, deployer_name=None, topology="local"):
    """Reconcile public access artifacts for topology-aware deployments."""
    normalized_topology = normalize_topology(topology or LOCAL_TOPOLOGY)
    if normalized_topology != VM_DISTRIBUTED_TOPOLOGY:
        raise ValueError("public-access is only supported with --topology vm-distributed")

    sync_public_access = _resolve_adapter_callable(
        adapter,
        "infrastructure.sync_vm_distributed_public_access",
    )
    if not callable(sync_public_access):
        raise ValueError(
            f"Adapter '{deployer_name or _infer_deployer_name_from_adapter(adapter)}' "
            "does not expose vm-distributed public access reconciliation."
        )

    result = sync_public_access(topology=normalized_topology)
    if isinstance(result, dict):
        result.setdefault("adapter", deployer_name or _infer_deployer_name_from_adapter(adapter))
        result.setdefault("topology", normalized_topology)
        return result
    return {
        "status": "synced",
        "adapter": deployer_name or _infer_deployer_name_from_adapter(adapter),
        "topology": normalized_topology,
        "result": result,
    }


def run_ssh_access(adapter, deployer_name=None, topology="local", action="plan"):
    """Build the idempotent SSH bootstrap plan for VM-backed topologies."""
    normalized_topology = normalize_topology(topology or LOCAL_TOPOLOGY)
    if normalized_topology not in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
        raise ValueError("ssh-access is only supported with --topology vm-single or vm-distributed")

    normalized_action = str(action or "plan").strip().lower().replace("_", "-")
    if normalized_action == "key-self-test":
        normalized_action = "self-test"
    if normalized_action not in {"plan", "reconcile", "self-test"}:
        raise ValueError("ssh-access only supports plan, reconcile or self-test")

    if normalized_topology == VM_SINGLE_TOPOLOGY:
        plan = _current_vm_single_topology_plan(adapter_name=deployer_name)
    else:
        plan = _current_vm_distributed_topology_plan(adapter_name=deployer_name)
    ssh_bootstrap = dict(plan.get("ssh_bootstrap") or {})
    if normalized_action == "reconcile":
        reconcile = _reconcile_vm_distributed_ssh_access(plan)
        reconcile.setdefault("adapter", deployer_name or _infer_deployer_name_from_adapter(adapter))
        reconcile.setdefault("topology", normalized_topology)
        reconcile.setdefault("action", normalized_action)
        return reconcile
    if normalized_action == "self-test":
        self_test = _vm_distributed_ssh_key_self_test(plan)
        self_test.setdefault("adapter", deployer_name or _infer_deployer_name_from_adapter(adapter))
        self_test.setdefault("topology", normalized_topology)
        self_test.setdefault("action", normalized_action)
        return self_test

    bootstrap_status = str(ssh_bootstrap.get("status") or "").strip().lower()
    status = "planned" if bootstrap_status in {"ready", "synced"} else "needs-review"
    message = "SSH bootstrap plan generated."
    if status != "planned":
        message = "SSH bootstrap plan needs configuration before it can generate setup commands."

    return {
        "status": status,
        "adapter": deployer_name or _infer_deployer_name_from_adapter(adapter),
        "topology": normalized_topology,
        "action": normalized_action,
        "message": message,
        "execution_host": plan.get("execution_host"),
        "ssh": plan.get("ssh") or {},
        "ssh_bootstrap": ssh_bootstrap,
        "execution_location": _vm_distributed_ssh_access_execution_location(plan),
        "manual_bootstrap_commands": _vm_distributed_manual_ssh_bootstrap_commands(plan),
    }


def _vm_distributed_ssh_access_step_title(command_name):
    name = str(command_name or "").strip()
    if name.startswith("check_bastion") or (name.startswith("check_") and "bastion" in name):
        return "Step 1 - Check the bastion"
    if name.startswith("create_dedicated_key") or name.startswith("secure_") or name.startswith("optional_ssh_agent"):
        return "Step 2 - Prepare the dedicated key"
    if name.startswith("install_public_key"):
        return "Step 3 - Install the public key"
    if name.startswith("verify_"):
        return "Step 4 - Verify passwordless SSH"
    return "Other checks"


def _vm_distributed_ssh_status_label(status):
    normalized = str(status or "").strip().lower()
    if normalized in {"planned", "ready", "synced", "passed", "present", "created"}:
        return "Succeeded"
    if normalized in {"failed", "error"} or normalized.endswith("-failed"):
        return "Failed"
    if normalized in {"needs-review", "needs-configuration"}:
        return "Needs review"
    if normalized in {"skipped", "not-applicable"}:
        return "Skipped"
    return str(status or "Unknown").strip().title() or "Unknown"


def _vm_ssh_access_title(payload, suffix="SSH ACCESS"):
    topology = str((payload or {}).get("topology") or "vm-distributed").strip().upper().replace("-", "-")
    if not topology:
        topology = "VM-DISTRIBUTED"
    return f"{topology} {suffix}".strip()


def _vm_distributed_ssh_access_execution_location(plan_or_result):
    payload = dict(plan_or_result or {})
    ssh_bootstrap = dict(payload.get("ssh_bootstrap") or {})
    execution_host = str(payload.get("execution_host") or ssh_bootstrap.get("execution_host") or "external").strip()
    if execution_host == "common-services":
        remote_workdir = str(ssh_bootstrap.get("remote_workdir") or payload.get("remote_workdir") or "").strip()
        details = [
            "Run these commands from the common-services VM, after the framework workspace is available there.",
            "This mode prepares SSH from the common-services VM to the other distributed VMs.",
        ]
        if remote_workdir:
            details.append(f"Use the framework workspace at: {remote_workdir}")
        return {
            "mode": "common-services",
            "label": "common-services VM",
            "details": details,
        }
    return {
        "mode": "external",
        "label": "operator workstation",
        "details": [
            "Run these commands from the same shell where you run this framework.",
            "For the current WSL-based workflow, that means your WSL terminal, not inside the target VMs.",
        ],
    }


def _vm_distributed_public_key_material(public_key_value):
    parts = str(public_key_value or "").strip().split()
    if len(parts) >= 2:
        return " ".join(parts[:2])
    return str(public_key_value or "").strip()


def _vm_distributed_ssh_key_self_test_result(status, message, checks, plan):
    vm_plan = dict(plan or {})
    ssh_bootstrap = dict(vm_plan.get("ssh_bootstrap") or {})
    topology = str(vm_plan.get("topology") or "vm-distributed").strip()
    target_label = "VM" if topology == "vm-single" else "VMs"
    return {
        "status": status,
        "message": message,
        "scope": "local-temporary-key-only",
        "remote_validation": "not-run",
        "execution_host": vm_plan.get("execution_host"),
        "ssh_bootstrap": {
            "status": ssh_bootstrap.get("status"),
            "mode": ssh_bootstrap.get("mode"),
            "configured_identity_file": ssh_bootstrap.get("identity_file"),
            "key_comment": ssh_bootstrap.get("key_comment"),
        },
        "checks": checks,
        "next_step": (
            f"Run ssh-access assistant or ssh-access reconcile to install and verify the key on the {target_label}."
            if status == "passed"
            else "Fix the failed local SSH key check before preparing a new distributed environment."
        ),
    }


def _vm_distributed_ssh_key_self_test(plan, command_runner=None):
    """Validate local SSH keypair creation with an isolated temporary key."""
    vm_plan = dict(plan or {})
    ssh_bootstrap = dict(vm_plan.get("ssh_bootstrap") or {})
    runner = command_runner or _vm_distributed_default_command_runner
    checks = []

    if command_runner is None and not shutil.which("ssh-keygen"):
        checks.append(
            {
                "name": "ssh_keygen_available",
                "status": "failed",
                "reason": "ssh-keygen-not-found",
            }
        )
        return _vm_distributed_ssh_key_self_test_result(
            "failed",
            "ssh-keygen is required to create SSH keys.",
            checks,
            vm_plan,
        )

    temp_identity_file = None
    try:
        with tempfile.TemporaryDirectory(prefix="validation-env-ssh-self-test-") as temp_dir:
            temp_identity_file = os.path.join(temp_dir, "id_ed25519")
            temp_public_key_file = _vm_distributed_public_key_path(temp_identity_file)
            test_bootstrap = dict(ssh_bootstrap)
            test_bootstrap.update(
                {
                    "identity_file": temp_identity_file,
                    "key_comment": str(
                        ssh_bootstrap.get("key_comment") or "validation-environment-vm-distributed"
                    ).strip()
                    + "-self-test",
                }
            )

            first = _vm_distributed_ensure_ssh_keypair(test_bootstrap, command_runner=runner)
            if first.get("status") == "failed":
                checks.append(
                    {
                        "name": "temporary_keypair_created",
                        "status": "failed",
                        "reason": first.get("reason") or "keypair-creation-failed",
                        "error": first.get("error"),
                    }
                )
                return _vm_distributed_ssh_key_self_test_result(
                    "failed",
                    "The temporary SSH keypair could not be created.",
                    checks,
                    vm_plan,
                )
            checks.append(
                {
                    "name": "temporary_keypair_created",
                    "status": "passed",
                    "state": first.get("status"),
                    "changed": bool(first.get("changed")),
                }
            )

            if not os.path.isfile(temp_identity_file) or not os.path.isfile(temp_public_key_file):
                checks.append(
                    {
                        "name": "temporary_keypair_files_exist",
                        "status": "failed",
                        "private_key_exists": os.path.isfile(temp_identity_file),
                        "public_key_exists": os.path.isfile(temp_public_key_file),
                    }
                )
                return _vm_distributed_ssh_key_self_test_result(
                    "failed",
                    "The temporary SSH keypair files were not created as expected.",
                    checks,
                    vm_plan,
                )
            checks.append(
                {
                    "name": "temporary_keypair_files_exist",
                    "status": "passed",
                }
            )

            private_key_mode = oct(os.stat(temp_identity_file).st_mode & 0o777)
            if private_key_mode != "0o600":
                checks.append(
                    {
                        "name": "private_key_permissions",
                        "status": "failed",
                        "expected": "0o600",
                        "actual": private_key_mode,
                    }
                )
                return _vm_distributed_ssh_key_self_test_result(
                    "failed",
                    "The temporary private key was not restricted to owner-only access.",
                    checks,
                    vm_plan,
                )
            checks.append(
                {
                    "name": "private_key_permissions",
                    "status": "passed",
                    "actual": private_key_mode,
                }
            )

            derive_command = ["ssh-keygen", "-y", "-f", temp_identity_file]
            derived = runner(derive_command, timeout=30)
            if int(getattr(derived, "returncode", 1) or 0) != 0:
                checks.append(
                    {
                        "name": "public_key_derivable_from_private_key",
                        "status": "failed",
                        "reason": "public-key-derivation-failed",
                        "error": str(getattr(derived, "stderr", "") or "").strip()[:500],
                    }
                )
                return _vm_distributed_ssh_key_self_test_result(
                    "failed",
                    "The temporary public key could not be derived from the private key.",
                    checks,
                    vm_plan,
                )

            stored_public_key = _vm_distributed_read_public_key(temp_public_key_file)
            derived_public_key = str(getattr(derived, "stdout", "") or "").strip()
            if (
                not stored_public_key
                or not derived_public_key
                or _vm_distributed_public_key_material(stored_public_key)
                != _vm_distributed_public_key_material(derived_public_key)
            ):
                checks.append(
                    {
                        "name": "public_key_matches_private_key",
                        "status": "failed",
                    }
                )
                return _vm_distributed_ssh_key_self_test_result(
                    "failed",
                    "The temporary public key does not match the private key.",
                    checks,
                    vm_plan,
                )
            checks.append(
                {
                    "name": "public_key_matches_private_key",
                    "status": "passed",
                }
            )

            second = _vm_distributed_ensure_ssh_keypair(test_bootstrap, command_runner=runner)
            if second.get("status") != "present" or second.get("changed"):
                checks.append(
                    {
                        "name": "keypair_creation_is_idempotent",
                        "status": "failed",
                        "second_run_status": second.get("status"),
                        "second_run_changed": bool(second.get("changed")),
                    }
                )
                return _vm_distributed_ssh_key_self_test_result(
                    "failed",
                    "The temporary keypair creation is not idempotent.",
                    checks,
                    vm_plan,
                )
            checks.append(
                {
                    "name": "keypair_creation_is_idempotent",
                    "status": "passed",
                    "second_run_status": second.get("status"),
                    "second_run_changed": bool(second.get("changed")),
                }
            )

        if temp_identity_file and not os.path.exists(temp_identity_file) and not os.path.exists(
            _vm_distributed_public_key_path(temp_identity_file)
        ):
            checks.append(
                {
                    "name": "temporary_files_removed",
                    "status": "passed",
                }
            )
        else:
            checks.append(
                {
                    "name": "temporary_files_removed",
                    "status": "failed",
                }
            )
            return _vm_distributed_ssh_key_self_test_result(
                "failed",
                "The temporary SSH keypair was not cleaned up.",
                checks,
                vm_plan,
            )
    except Exception as exc:
        checks.append(
            {
                "name": "unexpected_self_test_error",
                "status": "failed",
                "reason": type(exc).__name__,
                "error": str(exc)[:500],
            }
        )
        return _vm_distributed_ssh_key_self_test_result(
            "failed",
            "The SSH key self-test failed unexpectedly.",
            checks,
            vm_plan,
        )

    return _vm_distributed_ssh_key_self_test_result(
        "passed",
        "Temporary SSH key creation, validation and idempotency checks passed.",
        checks,
        vm_plan,
    )


def _print_vm_distributed_ssh_key_self_test_result(result):
    payload = dict(result or {})
    print()
    print("=" * 50)
    print(_vm_ssh_access_title(payload, "SSH KEY SELF-TEST"))
    print("=" * 50)
    print(f"Status: {_vm_distributed_ssh_status_label(payload.get('status'))}")
    print(f"Topology: {payload.get('topology') or 'vm-distributed'}")
    print("Scope: temporary local key only")
    print()
    print("What this validates:")
    print("- The framework can create a new dedicated SSH keypair from scratch.")
    print("- The private key is restricted to owner-only access.")
    print("- The public key can be derived from the private key.")
    print("- Running the key creation again does not overwrite the existing key.")
    print("- The temporary key files are removed after the test.")
    print()
    print("What this does not do:")
    target_label = "vm-single VM" if payload.get("topology") == "vm-single" else "distributed VMs"
    print(f"- It does not connect to the {target_label}.")
    print("- It does not modify authorized_keys.")
    print("- It does not touch your existing SSH keys.")

    checks = [item for item in list(payload.get("checks") or []) if isinstance(item, dict)]
    if checks:
        print()
        print("Checks:")
        for item in checks:
            line = f"- {item.get('name')}: {_vm_distributed_ssh_status_label(item.get('status'))}"
            if item.get("reason"):
                line += f" ({item.get('reason')})"
            print(line)

    message = str(payload.get("message") or "").strip()
    if message:
        print()
        print(message)
    next_step = str(payload.get("next_step") or "").strip()
    if next_step:
        print()
        print(f"Next: {next_step}")
    print()
    print("For machine-readable output, add --json.")


def _print_vm_distributed_ssh_access_interactive_guide(result):
    payload = dict(result or {})
    adapter_name = str(payload.get("adapter") or "inesdata").strip()
    topology = str(payload.get("topology") or "vm-distributed").strip() or "vm-distributed"
    print()
    print("Recommended interactive guide:")
    print("- Why it exists: SSH setup may ask for a one-time password and must run from the right machine.")
    print("- What it does: it walks you through each step, asks before running commands, and verifies passwordless SSH.")
    print("- How to use it: read each step, answer yes only when ready, and type passwords only into SSH prompts.")
    print("Run:")
    print(f"  python3 main.py {adapter_name} ssh-access assistant --topology {topology}")


def _safe_local_hostname():
    try:
        return str(socket.gethostname() or "").strip()
    except OSError:
        return ""


def _vm_distributed_host_aliases(hostname=None, fqdn=None):
    hostname_value = str(hostname if hostname is not None else _safe_local_hostname()).strip()
    # Avoid implicit reverse DNS lookups here; slow DNS must not block menu/preflight planning.
    fqdn_value = str(fqdn if fqdn is not None else hostname_value).strip()
    aliases = {
        hostname_value.lower(),
        fqdn_value.lower(),
    }
    return {alias for alias in aliases if alias}


def _vm_distributed_detect_execution_environment(plan_or_result, environ=None, proc_version=None, hostname=None, fqdn=None):
    payload = dict(plan_or_result or {})
    ssh_plan = dict(payload.get("ssh") or {})
    bastion = dict(ssh_plan.get("bastion") or {})
    commands = [item for item in list(payload.get("manual_bootstrap_commands") or []) if isinstance(item, dict)]
    command_names = {str(item.get("name") or "").strip() for item in commands}
    bastion_enabled = bool(
        ssh_plan.get("mode") == "bastion"
        or bastion.get("host")
        or any(name.startswith("check_bastion") or "bastion" in name for name in command_names)
    )
    bastion_host = str(bastion.get("host") or "").strip()
    bastion_port = str(bastion.get("port") or "").strip()
    bastion_user = str(bastion.get("user") or "").strip()
    if bastion_enabled and not bastion_host:
        for item in commands:
            if str(item.get("name") or "").startswith("check_bastion_dns"):
                parts = str(item.get("command") or "").split()
                if parts:
                    bastion_host = parts[-1]
                break
    env = environ if environ is not None else os.environ
    if proc_version is None:
        try:
            with open("/proc/version", encoding="utf-8") as handle:
                proc_version = handle.read()
        except OSError:
            proc_version = ""

    is_wsl = bool(env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP") or "microsoft" in str(proc_version).lower())
    aliases = _vm_distributed_host_aliases(hostname=hostname, fqdn=fqdn)
    targets = [item for item in list((payload.get("ssh_bootstrap") or {}).get("targets") or []) if isinstance(item, dict)]
    matched_target = None
    for target in targets:
        target_host = str(target.get("host") or "").strip().lower()
        if target_host and target_host in aliases:
            matched_target = target
            break

    configured_execution_host = str(
        payload.get("execution_host")
        or (payload.get("ssh_bootstrap") or {}).get("execution_host")
        or "external"
    ).strip()

    if is_wsl:
        detected_mode = "operator-workstation"
        detected_label = "WSL operator workstation"
        confidence = "high"
    elif matched_target and str(matched_target.get("role_key") or "").strip() == "common":
        detected_mode = "common-services"
        detected_label = "common-services VM"
        confidence = "medium"
    elif matched_target:
        detected_mode = "target-vm"
        detected_label = f"{matched_target.get('role') or 'target'} VM"
        confidence = "medium"
    else:
        detected_mode = "operator-workstation"
        detected_label = "operator workstation"
        confidence = "low"

    if configured_execution_host == "common-services":
        expected_mode = "common-services"
        expected_label = "common-services VM"
    else:
        expected_mode = "operator-workstation"
        expected_label = "operator workstation"

    if detected_mode == expected_mode:
        alignment = "matched"
        recommendation = "Continue from this shell."
        needs_confirmation = False
    elif confidence == "low":
        alignment = "uncertain"
        recommendation = "Continue only if this is the shell that should prepare SSH for the distributed environment."
        needs_confirmation = True
    else:
        alignment = "mismatch"
        recommendation = "Review the configured execution host before running commands."
        needs_confirmation = True

    route_warning = ""
    if bastion_enabled and detected_mode in {"common-services", "target-vm"}:
        alignment = "route-review" if alignment == "matched" else alignment
        needs_confirmation = True
        route_warning = (
            "This shell appears to be inside a configured VM while SSH is configured through a bastion. "
            "Continue only if this VM can reach the bastion and the bastion can reach the target VMs."
        )
        recommendation = route_warning

    return {
        "detected_mode": detected_mode,
        "detected_label": detected_label,
        "confidence": confidence,
        "expected_mode": expected_mode,
        "expected_label": expected_label,
        "configured_execution_host": configured_execution_host,
        "alignment": alignment,
        "needs_confirmation": needs_confirmation,
        "recommendation": recommendation,
        "route_warning": route_warning,
        "ssh_route": "bastion" if bastion_enabled else "direct",
        "bastion": {
            "enabled": bastion_enabled,
            "host": bastion_host,
            "port": bastion_port,
            "user": bastion_user,
        },
        "hostname": next(iter(aliases), ""),
    }


def _print_vm_distributed_execution_detection(detection):
    payload = dict(detection or {})
    print()
    print("Execution context check:")
    print(f"- Detected: {payload.get('detected_label') or 'unknown'} ({payload.get('confidence') or 'unknown'} confidence)")
    print(f"- Configured execution host: {payload.get('expected_label') or 'operator workstation'}")
    print(f"- Recommendation: {payload.get('recommendation') or 'Continue if this shell is correct.'}")
    bastion = dict(payload.get("bastion") or {})
    if bastion.get("enabled"):
        target = str(bastion.get("host") or "configured bastion").strip()
        if bastion.get("user"):
            target = f"{bastion.get('user')}@{target}"
        if bastion.get("port"):
            target = f"{target}:{bastion.get('port')}"
        print(f"- SSH route from config: bastion via {target}")
        print("- The guide will not ask whether there is a bastion; it uses the configured route.")
        print("- It will check the bastion first, then use it to reach the VMs.")
        if payload.get("route_warning"):
            print(f"- Route warning: {payload.get('route_warning')}")
    else:
        print("- SSH route from config: direct SSH to the configured VMs")


def _vm_distributed_ssh_route_label(detection):
    payload = dict(detection or {})
    bastion = dict(payload.get("bastion") or {})
    if bastion.get("enabled"):
        target = str(bastion.get("host") or "configured bastion").strip()
        if bastion.get("user"):
            target = f"{bastion.get('user')}@{target}"
        if bastion.get("port"):
            target = f"{target}:{bastion.get('port')}"
        return f"bastion via {target}"
    return "direct SSH to configured VMs"


def _print_vm_distributed_ssh_access_assistant_intro(plan_result, detection, total_questions):
    payload = dict(plan_result or {})
    ssh_bootstrap = dict(payload.get("ssh_bootstrap") or {})
    detected_label = str(detection.get("detected_label") or "unknown").strip()
    expected_label = str(detection.get("expected_label") or "operator workstation").strip()
    print()
    print("=" * 50)
    print(_vm_ssh_access_title(payload))
    print("=" * 50)
    print(f"Topology: {payload.get('topology') or 'vm-distributed'}")
    if ssh_bootstrap.get("identity_file"):
        print(f"Dedicated key: {ssh_bootstrap.get('identity_file')}")
    print(f"Execution: {detected_label} -> configured {expected_label}")
    print(f"SSH route from config: {_vm_distributed_ssh_route_label(detection)}")
    if detection.get("route_warning"):
        print(f"Warning: {detection.get('route_warning')}")
    print(f"Questions: {total_questions}. Answer yes only when ready; Ctrl+C stops.")
    print("Passwords, if requested, are typed into SSH prompts and are never stored.")


def _interactive_confirm_with_progress(prompt, question_number, total_questions, default=False):
    total = max(int(total_questions or 1), 1)
    current = min(max(int(question_number or 1), 1), total)
    return _interactive_confirm(f"Question {current}/{total}: {prompt}", default=default)


def _print_vm_distributed_ssh_access_result(result, show_interactive_guide=True):
    payload = dict(result or {})
    ssh_bootstrap = dict(payload.get("ssh_bootstrap") or {})
    adapter_name = str(payload.get("adapter") or "inesdata").strip()
    commands = [item for item in list(payload.get("manual_bootstrap_commands") or []) if isinstance(item, dict)]
    execution_location = dict(
        payload.get("execution_location")
        or _vm_distributed_ssh_access_execution_location(payload)
    )

    print()
    print("=" * 50)
    print(_vm_ssh_access_title(payload))
    print("=" * 50)
    print(f"Status: {_vm_distributed_ssh_status_label(payload.get('status'))}")
    print(f"Topology: {payload.get('topology') or 'vm-distributed'}")
    print(f"Execution host: {payload.get('execution_host') or ssh_bootstrap.get('execution_host') or 'external'}")
    if ssh_bootstrap.get("identity_file"):
        print(f"Dedicated key: {ssh_bootstrap.get('identity_file')}")
    print()
    print("What this prepares:")
    print("- A dedicated SSH key for this validation environment.")
    print("- The public half of that key on the bastion and target VMs.")
    print("- A final BatchMode check, so later levels can run without password prompts.")
    print()
    print("Security rules:")
    print("- Passwords are never stored by the framework.")
    print("- Private keys are not written to versioned files.")
    print("- ssh-copy-id may ask for a password once during the initial setup.")
    print()
    print("Where to run this:")
    print(f"- Run location: {execution_location.get('label') or 'operator workstation'}")
    for detail in list(execution_location.get("details") or []):
        print(f"- {detail}")

    status = str(payload.get("status") or "").strip().lower()
    if status not in {"planned", "synced"}:
        print()
        print("What happened:")
        message = str(payload.get("message") or "").strip()
        if message:
            print(f"- {message}")
        failed_items = [
            item for item in list(payload.get("authorized_keys") or []) + list(payload.get("verification") or [])
            if isinstance(item, dict) and item.get("status") == "failed"
        ]
        for item in failed_items:
            role = item.get("role") or "target"
            reason = str(item.get("reason") or "failed").replace("-", " ")
            print(f"- {role}: {reason}")
            error = str(item.get("error") or "").strip().splitlines()
            if error:
                print(f"  Error: {error[0]}")
            next_step = str(item.get("next_step") or "").strip()
            if next_step:
                print(f"  Next: {next_step}")

    if commands and show_interactive_guide and status != "synced":
        _print_vm_distributed_ssh_access_interactive_guide(payload)

    if status == "planned" and show_interactive_guide:
        print()
        print("After the interactive guide succeeds, run:")
        print(f"  python3 main.py {adapter_name} ssh-access reconcile --topology {payload.get('topology') or 'vm-distributed'}")
    elif status == "synced":
        print()
        print(
            "SSH access is ready. You can continue with the "
            f"{payload.get('topology') or 'vm-distributed'} deployment levels."
        )

    print()
    print("For machine-readable output and planned commands, add --json.")


def _vm_distributed_default_interactive_command_runner(command):
    return subprocess.run(command, shell=True, check=False)


def _run_vm_distributed_ssh_access_assistant(
    adapter,
    deployer_name=None,
    topology="local",
    command_runner=None,
):
    plan_result = run_ssh_access(
        adapter,
        deployer_name=deployer_name,
        topology=topology,
        action="plan",
    )

    commands = [
        item
        for item in list(plan_result.get("manual_bootstrap_commands") or [])
        if isinstance(item, dict) and str(item.get("command") or "").strip()
    ]
    if not commands:
        return {
            "status": "needs-review",
            "adapter": deployer_name or _infer_deployer_name_from_adapter(adapter),
            "topology": topology,
            "message": "No SSH setup commands were generated.",
            "plan": plan_result,
        }

    detection = _vm_distributed_detect_execution_environment(plan_result)
    needs_location_confirmation = bool(detection.get("needs_confirmation"))
    total_questions = len(commands) + 1 + (1 if needs_location_confirmation else 0)
    question_number = 1

    _print_vm_distributed_ssh_access_assistant_intro(
        plan_result,
        detection,
        total_questions,
    )

    if needs_location_confirmation:
        if not _interactive_confirm_with_progress(
            "This shell may not match the configured execution host. Continue from here?",
            question_number,
            total_questions,
            default=False,
        ):
            print("Guided SSH setup cancelled before running commands.")
            return {
                "status": "cancelled",
                "adapter": deployer_name or _infer_deployer_name_from_adapter(adapter),
                "topology": topology,
                "plan": plan_result,
                "execution_detection": detection,
                "executed": [],
            }
        question_number += 1

    if not _interactive_confirm_with_progress(
        "Start the guided SSH setup now?",
        question_number,
        total_questions,
        default=False,
    ):
        print("Guided SSH setup cancelled before running commands.")
        return {
            "status": "cancelled",
            "adapter": deployer_name or _infer_deployer_name_from_adapter(adapter),
            "topology": topology,
            "plan": plan_result,
            "execution_detection": detection,
            "executed": [],
        }
    question_number += 1

    runner = command_runner or _vm_distributed_default_interactive_command_runner
    executed = []
    current_title = None
    for item in commands:
        title = _vm_distributed_ssh_access_step_title(item.get("name"))
        if title != current_title:
            current_title = title
            print()
            print(title)
        command = str(item.get("command") or "").strip()
        print(command)
        note = str(item.get("note") or "").strip()
        if note:
            print(f"Note: {note}")

        if not _interactive_confirm_with_progress(
            "Run this command?",
            question_number,
            total_questions,
            default=False,
        ):
            executed.append(
                {
                    "name": item.get("name"),
                    "command": command,
                    "status": "skipped",
                }
            )
            question_number += 1
            continue
        question_number += 1

        completed = runner(command)
        returncode = int(getattr(completed, "returncode", 1) or 0)
        status = "passed" if returncode == 0 else "failed"
        executed.append(
            {
                "name": item.get("name"),
                "command": command,
                "status": status,
                "returncode": returncode,
            }
        )
        if returncode != 0:
            print(f"Command failed with exit code {returncode}.")
            if not _interactive_confirm("Continue with the next command?", default=False):
                break

    failed = [item for item in executed if item.get("status") == "failed"]
    passed = [item for item in executed if item.get("status") == "passed"]
    skipped = [item for item in executed if item.get("status") == "skipped"]
    if failed:
        status = "failed"
    elif skipped:
        status = "partial"
    elif passed and len(passed) == len(commands):
        status = "completed"
    elif passed:
        status = "partial"
    else:
        status = "skipped"

    print()
    print("Guided SSH setup summary")
    if status == "completed":
        print("Result: SSH setup commands completed. The final check is reconciliation.")
    elif status == "partial":
        print("Result: Some SSH setup commands were skipped. Run reconciliation to see what is still missing.")
    elif status == "failed":
        print("Result: Some SSH setup commands failed. Review the failed step before deploying.")
    else:
        print("Result: No SSH setup commands were completed.")
    print(f"- Passed: {len(passed)}")
    print(f"- Skipped: {len(skipped)}")
    print(f"- Failed: {len(failed)}")
    if status in {"completed", "partial"}:
        print()
        print("Next recommended check:")
        print(
            "  python3 main.py "
            f"{deployer_name or _infer_deployer_name_from_adapter(adapter)} "
            f"ssh-access reconcile --topology {topology}"
        )

    return {
        "status": status,
        "adapter": deployer_name or _infer_deployer_name_from_adapter(adapter),
        "topology": topology,
        "plan": plan_result,
        "execution_detection": detection,
        "executed": executed,
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
            path = parsed.path.rstrip("/")
            marker = "/realms/"
            if marker in path:
                path = path[: path.rfind(marker)].rstrip("/")
            level_urls["keycloak"] = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    keycloak_admin_console = str(urls.get("keycloak_admin_console") or "").strip()
    if keycloak_admin_console:
        parsed = urllib.parse.urlparse(keycloak_admin_console)
        if parsed.scheme and parsed.netloc:
            path = parsed.path or "/admin/"
            marker = "/admin/"
            if marker in path:
                path = path[: path.find(marker) + len(marker)]
            else:
                path = "/admin/"
            level_urls["keycloak_admin_console"] = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

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
    resolved_topology = normalize_topology(
        getattr(context, "topology", None) or topology or LOCAL_TOPOLOGY
    )
    config.setdefault("TOPOLOGY", resolved_topology)
    config.setdefault("PIONERA_TOPOLOGY", resolved_topology)
    dataspace_name = str(getattr(context, "dataspace_name", "") or "").strip()
    environment = str(getattr(context, "environment", "DEV") or "DEV").strip()
    connectors = list(getattr(context, "connectors", []) or [])
    components = list(getattr(context, "components", []) or [])
    urls = {}

    if resolved_deployer_name == "inesdata":
        from deployers.inesdata.access_urls import (
            build_connector_access_urls as build_inesdata_connector_access_urls,
            build_connector_public_access_urls as build_inesdata_connector_public_access_urls,
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
            if resolved_topology in {"vm-distributed", "vm-single"}:
                access_urls = build_inesdata_connector_public_access_urls(
                    connector,
                    dataspace_name,
                    environment,
                    config,
                )
            else:
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
            component_urls = infer_component_urls(
                components,
                ds_name=dataspace_name,
                deployer_config=config,
            )
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

        infer_component_urls = _resolve_adapter_callable(adapter, "components.infer_component_urls")
        if callable(infer_component_urls) and components:
            component_urls = infer_component_urls(
                components,
                ds_name=dataspace_name,
                deployer_config=config,
            )
            if component_urls:
                urls["components"] = component_urls

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


def _runtime_artifact_entry(label, path):
    normalized = str(path or "").strip()
    if not normalized:
        return None
    absolute_path = os.path.abspath(os.path.expanduser(normalized))
    return {
        "label": label,
        "path": _framework_relative_path(absolute_path),
        "exists": os.path.exists(absolute_path),
    }


def _append_runtime_artifact(entries, label, path):
    entry = _runtime_artifact_entry(label, path)
    if entry:
        entries.append(entry)


def _call_runtime_path_resolver(resolver, *args, **kwargs):
    if not callable(resolver):
        return ""
    attempts = [
        (args, kwargs),
        (args, {key: value for key, value in kwargs.items() if key != "for_write"}),
        (args, {}),
    ]
    for call_args, call_kwargs in attempts:
        try:
            return resolver(*call_args, **call_kwargs)
        except TypeError:
            continue
    return ""


def build_runtime_artifact_path_summary(adapter_name, context, adapter=None):
    """Build a read-only summary of generated runtime artifact locations."""
    resolved_adapter = str(adapter_name or getattr(context, "deployer", "") or "").strip()
    topology = normalize_topology(getattr(context, "topology", None) or LOCAL_TOPOLOGY)
    environment = str(getattr(context, "environment", "DEV") or "DEV").strip().upper() or "DEV"
    dataspace = str(getattr(context, "dataspace_name", "") or "").strip()
    connectors = list(getattr(context, "connectors", []) or [])
    config = dict(getattr(context, "config", {}) or {})
    root = _framework_root_dir()

    vault_keys = runtime_artifacts.vault_keys_path(
        environment,
        topology=topology,
        config=config,
        root=root,
    )
    shared_entries = []
    _append_runtime_artifact(shared_entries, "Shared common runtime root", os.path.dirname(str(vault_keys)))
    _append_runtime_artifact(shared_entries, "Vault init keys", vault_keys)
    _append_runtime_artifact(
        shared_entries,
        "Common services values",
        os.path.join(root, "deployers", "shared", "deployments", environment, "common", "values.yaml"),
    )

    adapter_root = runtime_artifacts.dataspace_runtime_dir(
        resolved_adapter,
        environment,
        dataspace,
        topology=topology,
        config=config,
        root=root,
    )
    adapter_entries = []
    _append_runtime_artifact(adapter_entries, f"{resolved_adapter} runtime root", adapter_root)
    if dataspace:
        _append_runtime_artifact(
            adapter_entries,
            "Dataspace credentials",
            os.path.join(str(adapter_root), f"credentials-dataspace-{dataspace}.json"),
        )
        _append_runtime_artifact(
            adapter_entries,
            "Registration service values",
            os.path.join(str(adapter_root), "dataspace", "registration-service", f"values-{dataspace}.yaml"),
        )
        _append_runtime_artifact(
            adapter_entries,
            "Public portal values",
            os.path.join(str(adapter_root), "dataspace", "public-portal", f"values-{dataspace}.yaml"),
        )

    config_adapter = getattr(adapter, "config_adapter", None)
    connector_entries = []
    for connector in connectors:
        connector_item = {"name": connector, "artifacts": []}
        credentials_path = _call_runtime_path_resolver(
            getattr(config_adapter, "connector_credentials_path", None),
            connector,
            ds_name=dataspace,
            for_write=False,
        ) or runtime_artifacts.connector_credentials_path(
            resolved_adapter,
            environment,
            dataspace,
            connector,
            topology=topology,
            config=config,
            root=root,
        )
        certs_dir = _call_runtime_path_resolver(
            getattr(config_adapter, "connector_certificates_dir", None),
            connector_name=connector,
            ds_name=dataspace,
        ) or runtime_artifacts.connector_certificates_dir(
            resolved_adapter,
            environment,
            dataspace,
            connector,
            topology=topology,
            config=config,
            root=root,
        )
        _append_runtime_artifact(connector_item["artifacts"], "Credentials", credentials_path)
        _append_runtime_artifact(connector_item["artifacts"], "Certificates", certs_dir)

        minio_policy_path = _call_runtime_path_resolver(
            getattr(config_adapter, "connector_minio_policy_path", None),
            connector,
            ds_name=dataspace,
            for_write=False,
        )
        if not minio_policy_path and resolved_adapter == "inesdata":
            minio_policy_path = runtime_artifacts.connector_minio_policy_path(
                resolved_adapter,
                environment,
                dataspace,
                connector,
                topology=topology,
                config=config,
                root=root,
            )
        _append_runtime_artifact(connector_item["artifacts"], "MinIO policy", minio_policy_path)

        edc_policy_path = _call_runtime_path_resolver(
            getattr(config_adapter, "edc_connector_policy_file", None),
            connector,
            ds_name=dataspace,
        )
        _append_runtime_artifact(connector_item["artifacts"], "Connector policy", edc_policy_path)

        connector_entries.append(connector_item)

    return {
        "status": "available",
        "adapter": resolved_adapter,
        "topology": topology,
        "environment": environment,
        "dataspace": dataspace or None,
        "shared": shared_entries,
        "adapter_artifacts": adapter_entries,
        "connectors": connector_entries,
        "guidance": "Shared artifacts belong to deployers/shared; adapter artifacts belong to deployers/<adapter>.",
    }


def run_runtime_artifact_paths(adapter, deployer_name=None, deployer_registry=None, topology="local"):
    resolved_deployer_name, context = _resolve_deployer_context(
        adapter,
        deployer_name=deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    return build_runtime_artifact_path_summary(
        resolved_deployer_name,
        context,
        adapter=adapter,
    )


def _print_runtime_artifact_paths(summary):
    payload = dict(summary or {})
    print()
    print("Runtime artifact paths")
    print(f"Adapter: {payload.get('adapter') or '-'}")
    print(f"Topology: {payload.get('topology') or '-'}")
    print(f"Environment: {payload.get('environment') or '-'}")
    if payload.get("dataspace"):
        print(f"Dataspace: {payload.get('dataspace')}")

    def _print_entries(title, entries):
        print()
        print(title)
        for item in list(entries or []):
            status = "exists" if item.get("exists") else "missing"
            print(f"- {item.get('label')}: {item.get('path')} [{status}]")

    _print_entries("Shared foundation artifacts", payload.get("shared"))
    _print_entries("Adapter artifacts", payload.get("adapter_artifacts"))

    connectors = list(payload.get("connectors") or [])
    if connectors:
        print()
        print("Connector artifacts")
        for connector in connectors:
            print(f"- {connector.get('name')}")
            for item in list(connector.get("artifacts") or []):
                status = "exists" if item.get("exists") else "missing"
                print(f"  - {item.get('label')}: {item.get('path')} [{status}]")

    if payload.get("guidance"):
        print()
        print(payload.get("guidance"))


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
    experiment_dir = experiment_dir or experiment_storage.create_experiment_directory()
    with _Level6ConsoleCapture(experiment_dir):
        kafka_level6_enabled = _resolve_level6_kafka_enabled_for_run(
            adapter,
            validation_profile=validation_profile,
            deployer_name=resolved_deployer_name,
        )
        hosts_sync = (
            _sync_deployer_hosts_if_enabled(deployer_context)
            if deployer_context is not None
            else {"status": "skipped", "reason": "missing-deployer-context"}
        )
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
            kafka_enabled=kafka_level6_enabled,
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

        validation_engine = build_validation_engine(
            adapter,
            engine_cls=validation_engine_cls,
            deployer_context=deployer_context,
        )
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
        kafka_edc_results = []
        playwright_result = None
        playwright_failure = None
        component_results = []
        component_validation_summary = None
        une_0087_alignment = None

        print_interoperability_suite_header("Newman connector interoperability", "Newman")
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
            une_0087_alignment = _generate_level6_une_0087_alignment(experiment_dir)
            framework_report = _generate_framework_dashboard(experiment_dir)
            level6_validation_summary = _print_level6_validation_summary(
                experiment_dir=experiment_dir,
                framework_report=framework_report,
                validation_error=validation_error,
                playwright_result=playwright_result,
                playwright_failure=playwright_failure,
                component_results=component_results,
                kafka_edc_results=kafka_edc_results,
                validation_profile=validation_profile,
            )
            _offer_open_level6_dashboard(framework_report)
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
            kafka_enabled=kafka_level6_enabled,
            deployer_context=deployer_context,
        )

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
                dashboard_runtime_validation = (
                    _edc_dashboard_runtime_validation(deployer_context)
                    if is_edc_playwright
                    else {}
                )
                dashboard_runtime_present = bool(
                    dashboard_runtime_validation.get("present")
                    and dashboard_runtime_validation.get("valid")
                )
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
                if is_edc_playwright and not dashboard_runtime_present:
                    issues = dashboard_runtime_validation.get("issues") or []
                    detail = "; ".join(str(issue) for issue in issues[:6]) or "dashboard runtime is missing"
                    raise RuntimeError(
                        "Playwright validation for 'edc' requires an EDC dashboard runtime "
                        "that satisfies the current UI contract. Run Level 4 for the EDC "
                        "adapter before Level 6 to regenerate the dashboard runtime. Root cause: "
                        + detail
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
                print_interoperability_suite_header(
                    _playwright_interoperability_suite_name(validation_profile),
                    "Playwright",
                )
                playwright_result = run_playwright_validation(
                    profile=validation_profile,
                    context=deployer_context,
                    experiment_dir=experiment_dir,
                )
                if playwright_result.get("status") != "passed":
                    playwright_failure = playwright_result.get("status")
                    if _level6_stop_after_playwright_failure_enabled():
                        local_stability_postflight = _run_level6_local_stability_postflight(
                            validation_mode_info,
                            resolved_deployer_name,
                            deployer_context,
                            experiment_dir,
                            local_stability_preflight,
                            validation_profile=validation_profile,
                        )
                        une_0087_alignment = _generate_level6_une_0087_alignment(experiment_dir)
                        framework_report = _generate_framework_dashboard(experiment_dir)
                        level6_validation_summary = _print_level6_validation_summary(
                            experiment_dir=experiment_dir,
                            framework_report=framework_report,
                            validation_error=validation_error,
                            playwright_result=playwright_result,
                            playwright_failure=playwright_failure,
                            component_results=component_results,
                            kafka_edc_results=kafka_edc_results,
                            validation_profile=validation_profile,
                        )
                        _offer_open_level6_dashboard(framework_report)
                        raise RuntimeError(
                            f"Playwright validation failed with status '{playwright_failure}'"
                        )

            component_groups = list(getattr(validation_profile, "component_groups", []) or [])
            infer_component_urls = _resolve_adapter_callable(adapter, "components.infer_component_urls")
            sync_component_public_routes = _resolve_adapter_callable(
                adapter,
                "components.sync_validation_public_routes",
            )
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
                        component_env = _level6_component_validation_environment(
                            deployer_context,
                            resolved_deployer_name,
                            components=component_groups,
                        )
                        with _temporary_environment(component_env):
                            if callable(sync_component_public_routes):
                                try:
                                    route_sync = sync_component_public_routes(
                                        component_groups,
                                        ds_name=getattr(deployer_context, "dataspace_name", ""),
                                        deployer_config=getattr(deployer_context, "config", {}),
                                    )
                                    if route_sync:
                                        print("Component public validation routes synchronized.")
                                except Exception as exc:
                                    print(f"Warning: component public route synchronization failed: {exc}")
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

                    print_component_validation_summary(component_results)
                if component_results:
                    component_validation_summary = summarize_component_results(component_results)
                    component_failed = any(
                        _level6_normalized_status(item.get("status")) == "failed"
                        for item in component_results
                        if isinstance(item, dict)
                    )
                    if component_failed and _level6_stop_after_playwright_failure_enabled():
                        local_stability_postflight = _run_level6_local_stability_postflight(
                            validation_mode_info,
                            resolved_deployer_name,
                            deployer_context,
                            experiment_dir,
                            local_stability_preflight,
                            validation_profile=validation_profile,
                        )
                        une_0087_alignment = _generate_level6_une_0087_alignment(experiment_dir)
                        framework_report = _generate_framework_dashboard(experiment_dir)
                        level6_validation_summary = _print_level6_validation_summary(
                            experiment_dir=experiment_dir,
                            framework_report=framework_report,
                            validation_error=validation_error,
                            playwright_result=playwright_result,
                            playwright_failure=playwright_failure,
                            component_results=component_results,
                            kafka_edc_results=kafka_edc_results,
                            validation_profile=validation_profile,
                        )
                        _offer_open_level6_dashboard(framework_report)
                        raise RuntimeError("Component validation failed")
                if playwright_failure is not None:
                    local_stability_postflight = _run_level6_local_stability_postflight(
                        validation_mode_info,
                        resolved_deployer_name,
                        deployer_context,
                        experiment_dir,
                        local_stability_preflight,
                        validation_profile=validation_profile,
                    )
                    une_0087_alignment = _generate_level6_une_0087_alignment(experiment_dir)
                    framework_report = _generate_framework_dashboard(experiment_dir)
                    level6_validation_summary = _print_level6_validation_summary(
                        experiment_dir=experiment_dir,
                        framework_report=framework_report,
                        validation_error=validation_error,
                        playwright_result=playwright_result,
                        playwright_failure=playwright_failure,
                        component_results=component_results,
                        kafka_edc_results=kafka_edc_results,
                        validation_profile=validation_profile,
                    )
                    _offer_open_level6_dashboard(framework_report)
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
        une_0087_alignment = _generate_level6_une_0087_alignment(experiment_dir)
        framework_report = _generate_framework_dashboard(experiment_dir)
        level6_validation_summary = _print_level6_validation_summary(
            experiment_dir=experiment_dir,
            framework_report=framework_report,
            validation_error=validation_error,
            playwright_result=playwright_result,
            playwright_failure=playwright_failure,
            component_results=component_results,
            kafka_edc_results=kafka_edc_results,
            validation_profile=validation_profile,
        )
        _offer_open_level6_dashboard(framework_report)

        return {
            "experiment_dir": experiment_dir,
            "validation_status": level6_validation_summary.get("status"),
            "level6_validation_summary": level6_validation_summary,
            "validation": validation_result,
            "newman_request_metrics": newman_request_metrics,
            "kafka_edc_results": kafka_edc_results,
            "storage_checks": list(getattr(validation_engine, "last_storage_checks", []) or []),
            "playwright": playwright_result,
            "component_results": component_results,
            "component_validation_summary": component_validation_summary,
            "une_0087_alignment": une_0087_alignment,
            "test_data_cleanup": test_data_cleanup,
            "public_endpoint_preflight": public_endpoint_preflight,
            "hosts_sync": hosts_sync,
            "framework_report": framework_report,
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


def _vm_distributed_level_runtime_role(level=None):
    try:
        level_id = int(level)
    except (TypeError, ValueError):
        level_id = 0
    if level_id == 5:
        return "components"
    return "common"


def _vm_distributed_runtime_kubeconfig(runtime, role="common"):
    normalized_role = str(role or "common").strip().lower() or "common"
    role_key = {
        "common": "k3s_kubeconfig_common",
        "registration_service": "k3s_kubeconfig_common",
        "dataspace": "k3s_kubeconfig_common",
        "provider": "k3s_kubeconfig_provider",
        "consumer": "k3s_kubeconfig_consumer",
        "connectors": "k3s_kubeconfig_common",
        "components": "k3s_kubeconfig_components",
    }.get(normalized_role, "k3s_kubeconfig_common")
    return str(
        (runtime or {}).get(role_key)
        or (runtime or {}).get("k3s_kubeconfig_common")
        or (runtime or {}).get("k3s_kubeconfig")
        or ""
    ).strip()


def _topology_runtime_environment_overrides(topology="local", level=None, role=None):
    normalized_topology = normalize_topology(topology)
    if normalized_topology not in {"vm-single", "vm-distributed"}:
        return {}
    try:
        config = _load_effective_infrastructure_deployer_config(topology=normalized_topology)
        runtime = build_cluster_runtime(config, topology=normalized_topology)
    except Exception:
        return {}
    if runtime.get("cluster_type") != "k3s":
        return {}
    if normalized_topology == "vm-distributed":
        runtime_role = role or _vm_distributed_level_runtime_role(level)
        kubeconfig = _vm_distributed_runtime_kubeconfig(
            runtime,
            role=runtime_role,
        )
        kubeconfig = _vm_distributed_effective_kubeconfig_path(
            config,
            runtime_role,
            kubeconfig,
        )
    else:
        kubeconfig = _vm_single_effective_kubeconfig_path(config)
    if not kubeconfig:
        return {}
    overrides = {"KUBECONFIG": kubeconfig}
    overrides.update(_k3s_kubectl_environment_overrides())
    if normalized_topology == "vm-distributed":
        overrides["PIONERA_KUBECONFIG_ROLE"] = str(
            role or _vm_distributed_level_runtime_role(level)
        ).strip().lower() or "common"
    return overrides


def _configured_vm_distributed_role_kubeconfigs():
    config = _load_effective_infrastructure_deployer_config(topology="vm-distributed")
    return _configured_vm_distributed_role_kubeconfigs_from_config(config)


def _configured_vm_distributed_role_kubeconfigs_from_config(config):
    runtime = build_cluster_runtime(config, topology="vm-distributed")
    raw_kubeconfigs = {
        "common": _vm_distributed_runtime_kubeconfig(runtime, "common"),
        "provider": _vm_distributed_runtime_kubeconfig(runtime, "provider"),
        "consumer": _vm_distributed_runtime_kubeconfig(runtime, "consumer"),
        "components": _vm_distributed_runtime_kubeconfig(runtime, "components"),
    }
    return {
        role: _vm_distributed_effective_kubeconfig_path(config, role, path)
        for role, path in raw_kubeconfigs.items()
    }


def _kubeconfig_server(kubeconfig_path):
    try:
        with open(kubeconfig_path, encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("server:"):
                    return stripped.split(":", 1)[1].strip()
    except OSError:
        return ""
    return ""


def _local_tcp_port_open(port, host="127.0.0.1", timeout_seconds=0.5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _kubeconfig_loopback_port(server):
    parsed = urllib.parse.urlparse(str(server or "").strip())
    hostname = str(parsed.hostname or "").strip().lower()
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    return parsed.port


def _vm_distributed_role_ssh_config(config, role):
    normalized = str(role or "common").strip().upper()
    role_key = normalized.lower()
    address = _vm_distributed_config_value(
        config,
        f"VM_{normalized}_IP",
        "VM_EXTERNAL_IP",
    )
    spec = {
        "ssh_host_key": f"VM_{normalized}_SSH_HOST",
    }
    identity_file = _vm_distributed_identity_file(config, role_key)
    access_mode = _vm_distributed_role_ssh_access_mode(config, role_key)
    return {
        "host": _vm_distributed_effective_ssh_host(config, spec, address)
        or _vm_distributed_config_value(config, f"VM_{normalized}_K8S_NODE"),
        "port": _vm_distributed_config_value(config, f"VM_{normalized}_SSH_PORT", default="22") or "22",
        "user": _vm_distributed_config_value(config, f"VM_{normalized}_SSH_USER", "VM_SSH_USER"),
        "identity_file": identity_file,
        "access_mode": access_mode,
        "bastion": _vm_distributed_role_bastion_config(config, role_key, identity_file=identity_file),
    }


def _vm_distributed_k3s_tunnel_command(config, role, local_port):
    ssh_config = _vm_distributed_role_ssh_config(config, role)
    if not ssh_config.get("host") or not ssh_config.get("user"):
        return []

    timeout = _vm_distributed_connect_timeout_seconds(config)
    known_hosts_strategy = _vm_distributed_config_value(
        config,
        "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY",
        default="accept-new",
    ) or "accept-new"
    remote_port = _vm_distributed_k3s_api_remote_port(config)
    command = [
        "ssh",
        "-N",
        "-L",
        f"127.0.0.1:{int(local_port)}:127.0.0.1:{remote_port}",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        f"StrictHostKeyChecking={known_hosts_strategy}",
        "-p",
        str(ssh_config.get("port") or "22"),
    ]
    if ssh_config.get("identity_file"):
        command.extend(["-i", ssh_config["identity_file"]])

    access_mode = ssh_config.get("access_mode") or _vm_distributed_role_ssh_access_mode(config, role)
    bastion = dict(ssh_config.get("bastion") or _vm_distributed_role_bastion_config(config, role))
    bastion_host = str(bastion.get("host") or "").strip()
    if access_mode == "bastion" or (not access_mode and bastion_host):
        bastion_target = _vm_distributed_ssh_target(
            bastion.get("user"),
            bastion_host,
        )
        bastion_port = str(bastion.get("port") or "2222").strip() or "2222"
        bastion_identity_file = str(bastion.get("identity_file") or "").strip() or ssh_config.get("identity_file")
        if bastion_target:
            proxy_command = [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                f"ConnectTimeout={timeout}",
                "-o",
                f"StrictHostKeyChecking={known_hosts_strategy}",
                "-p",
                bastion_port,
                "-W",
                "%h:%p",
                bastion_target,
            ]
            if bastion_identity_file:
                proxy_command[9:9] = ["-i", bastion_identity_file]
            command.extend(["-o", f"ProxyCommand={_vm_distributed_format_command(proxy_command)}"])

    command.append(_vm_distributed_ssh_target(ssh_config.get("user"), ssh_config.get("host")))
    return command


def _run_vm_distributed_background_ssh_command(command, timeout_seconds=20):
    del timeout_seconds
    stdout_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        stdout_file.close()
        stderr_file.close()
        return types.SimpleNamespace(returncode=255, stdout="", stderr=str(exc), process=None)

    return types.SimpleNamespace(
        returncode=None,
        stdout="",
        stderr="",
        process=process,
        stdout_file=stdout_file,
        stderr_file=stderr_file,
    )


def _close_vm_distributed_background_ssh_process_files(proc):
    for name in ("stdout_file", "stderr_file"):
        handle = getattr(proc, name, None)
        if not handle:
            continue
        try:
            handle.close()
        except OSError:
            pass
        setattr(proc, name, None)


def _vm_distributed_background_ssh_process_output(proc, timeout_seconds=1):
    process = getattr(proc, "process", None)
    if not process:
        return proc
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return proc
    proc.returncode = process.returncode
    stdout_file = getattr(proc, "stdout_file", None)
    stderr_file = getattr(proc, "stderr_file", None)
    if stdout_file:
        stdout_file.seek(0)
        proc.stdout = stdout_file.read() or ""
    if stderr_file:
        stderr_file.seek(0)
        proc.stderr = stderr_file.read() or ""
    _close_vm_distributed_background_ssh_process_files(proc)
    return proc


def _terminate_vm_distributed_background_ssh_process(proc):
    process = getattr(proc, "process", None)
    if not process:
        _close_vm_distributed_background_ssh_process_files(proc)
        return
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
    _close_vm_distributed_background_ssh_process_files(proc)


def _vm_distributed_k3s_api_remote_port(config):
    return _vm_distributed_config_value(
        config,
        "VM_DISTRIBUTED_K3S_API_REMOTE_PORT",
        default="6443",
    ) or "6443"


def _vm_distributed_k3s_tunnel_recreate_enabled(config):
    mode = _vm_distributed_config_value(
        config,
        "VM_DISTRIBUTED_K3S_TUNNEL_RECREATE",
        default="auto",
    ).lower()
    return mode not in {"off", "disabled", "manual", "false", "0", "no"}


def _vm_distributed_local_k3s_tunnel_processes(local_port, remote_port):
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []

    local = str(int(local_port))
    remote = str(remote_port or "6443").strip() or "6443"
    expected_specs = {
        f"127.0.0.1:{local}:127.0.0.1:{remote}",
        f"127.0.0.1:{local}:localhost:{remote}",
        f"localhost:{local}:127.0.0.1:{remote}",
        f"localhost:{local}:localhost:{remote}",
        f"{local}:127.0.0.1:{remote}",
        f"{local}:localhost:{remote}",
    }
    matches = []
    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            pid_text, args = stripped.split(None, 1)
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        if "ssh" not in args or "-L" not in args:
            continue
        if any(spec in args for spec in expected_specs):
            matches.append({"pid": pid, "command": args})
    return matches


def _stop_vm_distributed_local_k3s_tunnel(local_port, remote_port):
    processes = _vm_distributed_local_k3s_tunnel_processes(local_port, remote_port)
    if not processes:
        return {
            "status": "skipped",
            "reason": "no-managed-k3s-ssh-tunnel-process",
            "local_port": local_port,
        }

    stopped = []
    errors = []
    for process in processes:
        pid = process.get("pid")
        try:
            os.kill(int(pid), signal.SIGTERM)
            stopped.append(pid)
        except (OSError, ValueError) as exc:
            errors.append(f"{pid}: {exc}")

    deadline = time.time() + 5
    while time.time() < deadline:
        if not _local_tcp_port_open(local_port):
            return {
                "status": "stopped",
                "local_port": local_port,
                "pids": stopped,
                "errors": errors,
            }
        time.sleep(0.25)

    return {
        "status": "failed",
        "reason": "managed-k3s-ssh-tunnel-still-listening",
        "local_port": local_port,
        "pids": stopped,
        "errors": errors,
    }


def _recreate_vm_distributed_k3s_tunnel(role, kubeconfig_path, config):
    server = _kubeconfig_server(kubeconfig_path)
    local_port = _kubeconfig_loopback_port(server)
    if not local_port:
        return {"role": role, "status": "skipped", "reason": "non-loopback-kubeconfig", "server": server}
    if not _vm_distributed_k3s_tunnel_recreate_enabled(config):
        return {"role": role, "status": "skipped", "reason": "tunnel-recreate-disabled", "server": server}

    remote_port = _vm_distributed_k3s_api_remote_port(config)
    stop_result = _stop_vm_distributed_local_k3s_tunnel(local_port, remote_port)
    if stop_result.get("status") == "failed":
        return {
            "role": role,
            "status": "failed",
            "server": server,
            "local_port": local_port,
            "reason": stop_result.get("reason") or "tunnel-stop-failed",
        }
    if stop_result.get("status") == "skipped" and _local_tcp_port_open(local_port):
        return {
            "role": role,
            "status": "failed",
            "server": server,
            "local_port": local_port,
            "reason": stop_result.get("reason") or "port-owned-by-unmanaged-process",
        }

    result = _ensure_vm_distributed_k3s_tunnel(role, kubeconfig_path, config)
    if stop_result.get("pids"):
        result = {**result, "recreated_from_pids": list(stop_result.get("pids") or [])}
    return result


def _ensure_vm_distributed_k3s_tunnel(role, kubeconfig_path, config):
    server = _kubeconfig_server(kubeconfig_path)
    local_port = _kubeconfig_loopback_port(server)
    if not local_port:
        return {"role": role, "status": "skipped", "reason": "non-loopback-kubeconfig", "server": server}
    if _local_tcp_port_open(local_port):
        return {"role": role, "status": "ready", "server": server, "local_port": local_port}

    mode = _vm_distributed_config_value(config, "VM_DISTRIBUTED_K3S_TUNNEL_MODE", default="auto").lower()
    if mode in {"off", "disabled", "manual", "false", "0", "no"}:
        return {
            "role": role,
            "status": "missing",
            "server": server,
            "local_port": local_port,
            "reason": "tunnel-mode-disabled",
        }

    command = _vm_distributed_k3s_tunnel_command(config, role, local_port)
    if not command:
        return {
            "role": role,
            "status": "failed",
            "server": server,
            "local_port": local_port,
            "reason": "missing-ssh-config",
        }

    proc = _run_vm_distributed_background_ssh_command(command, timeout_seconds=20)
    if proc.returncode not in {None, 0}:
        return {
            "role": role,
            "status": "failed",
            "server": server,
            "local_port": local_port,
            "reason": "ssh-tunnel-failed",
            "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
            "error": (proc.stderr or proc.stdout or "").strip()[:500],
        }

    deadline = time.time() + 20
    while time.time() < deadline:
        if _local_tcp_port_open(local_port):
            _close_vm_distributed_background_ssh_process_files(proc)
            return {
                "role": role,
                "status": "started",
                "server": server,
                "local_port": local_port,
                "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
                "pid": getattr(getattr(proc, "process", None), "pid", None),
            }
        process = getattr(proc, "process", None)
        if process and process.poll() is not None:
            proc = _vm_distributed_background_ssh_process_output(proc)
            return {
                "role": role,
                "status": "failed",
                "server": server,
                "local_port": local_port,
                "reason": "ssh-tunnel-failed",
                "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
                "error": (proc.stderr or proc.stdout or f"ssh exited with {proc.returncode}").strip()[:500],
            }
        time.sleep(0.25)

    _terminate_vm_distributed_background_ssh_process(proc)
    return {
        "role": role,
        "status": "failed",
        "server": server,
        "local_port": local_port,
        "reason": "ssh-tunnel-timeout",
        "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
    }


def _ensure_vm_distributed_k3s_tunnels(kubeconfigs, config):
    results = []
    seen = set()
    for role, path in (kubeconfigs or {}).items():
        key = (str(path or ""), _kubeconfig_server(path))
        if key in seen:
            continue
        seen.add(key)
        results.append(_ensure_vm_distributed_k3s_tunnel(role, path, config))
    return results


def _vm_distributed_kubeconfig_check(role, kubeconfig_path, timeout_seconds=8):
    path = str(kubeconfig_path or "").strip()
    server = _kubeconfig_server(path) if path else ""
    result = {
        "role": role,
        "path": path,
        "server": server,
    }
    if not path:
        return {**result, "status": "failed", "detail": "missing kubeconfig path"}
    if not os.path.exists(path):
        return {**result, "status": "failed", "detail": "kubeconfig file does not exist"}

    try:
        proc = subprocess.run(
            ["kubectl", "--kubeconfig", path, "get", "--raw=/version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {**result, "status": "failed", "detail": f"timed out after {timeout_seconds}s"}
    except OSError as exc:
        return {**result, "status": "failed", "detail": str(exc)}

    if proc.returncode == 0:
        return {**result, "status": "ready", "detail": "reachable"}

    detail = (proc.stderr or proc.stdout or f"kubectl exited with {proc.returncode}").strip()
    return {**result, "status": "failed", "detail": detail}


def _vm_distributed_check_role_kubeconfigs(connector_values):
    checks = []
    checked_paths = {}
    for role, path in (connector_values or {}).items():
        if path in checked_paths:
            check = {**checked_paths[path], "role": role}
        else:
            check = _vm_distributed_kubeconfig_check(role, path)
            checked_paths[path] = check
        checks.append(check)
    return checks


def _ensure_vm_distributed_level4_kubeconfig_supported():
    config = _load_effective_infrastructure_deployer_config(topology="vm-distributed")
    kubeconfig_sync = _ensure_vm_distributed_local_kubeconfigs(
        config,
        roles=_vm_distributed_level_kubeconfig_roles(4),
    )
    _raise_vm_distributed_kubeconfig_sync_failure(kubeconfig_sync)
    kubeconfigs = _configured_vm_distributed_role_kubeconfigs()
    connector_values = {
        role: path
        for role, path in kubeconfigs.items()
        if role in {"common", "provider", "consumer"} and path
    }
    unique_values = sorted(set(connector_values.values()))
    tunnel_results = _ensure_vm_distributed_k3s_tunnels(connector_values, config)
    tunnel_failures = [
        item
        for item in tunnel_results
        if item.get("status") in {"failed", "missing"}
    ]
    if tunnel_failures:
        details = []
        for item in tunnel_failures:
            role = item.get("role") or "unknown"
            server = item.get("server") or "(server not found)"
            reason = item.get("reason") or item.get("error") or "tunnel unavailable"
            command = item.get("command")
            suffix = f" Command: {command}" if command else ""
            details.append(f"{role}: {server}: {reason}.{suffix}")
        raise RuntimeError(
            "Level 4 cannot continue because required vm-distributed Kubernetes API tunnels are not available. "
            "The framework tried to prepare them before touching connector state. "
            + " ".join(details)
        )

    checks = _vm_distributed_check_role_kubeconfigs(connector_values)

    failed = [check for check in checks if check.get("status") != "ready"]
    if failed and _vm_distributed_k3s_tunnel_recreate_enabled(config):
        recreated = []
        seen_recreate = set()
        path_by_role = {role: path for role, path in connector_values.items()}
        for check in failed:
            role = check.get("role")
            path = path_by_role.get(role)
            server = check.get("server") or _kubeconfig_server(path)
            if not path or not _kubeconfig_loopback_port(server):
                continue
            recreate_key = (path, server)
            if recreate_key in seen_recreate:
                continue
            seen_recreate.add(recreate_key)
            recreated.append(_recreate_vm_distributed_k3s_tunnel(role, path, config))
        if recreated:
            tunnel_results.extend(recreated)
            checks = _vm_distributed_check_role_kubeconfigs(connector_values)
            failed = [check for check in checks if check.get("status") != "ready"]

    if failed:
        tunnel_recreate_failures = [
            item
            for item in tunnel_results
            if item.get("status") == "failed" and item.get("reason")
        ]
        details = []
        for check in failed:
            role = check.get("role") or "unknown"
            path = check.get("path") or "(empty)"
            server = check.get("server") or "(server not found)"
            detail = check.get("detail") or "unreachable"
            hint = ""
            if "127.0.0.1" in server or "localhost" in server:
                hint = " The kubeconfig points to a local tunnel; the framework tried to create or recreate it when safe."
            details.append(f"{role}: {path} -> {server}: {detail}.{hint}")
        for item in tunnel_recreate_failures:
            details.append(
                f"{item.get('role') or 'unknown'} tunnel recreate: "
                f"{item.get('server') or '(server not found)'}: {item.get('reason')}"
            )
        raise RuntimeError(
            "Level 4 cannot continue because one or more vm-distributed Kubernetes contexts are not reachable. "
            "This check runs before changing connector credentials or deploying Helm releases. "
            + " ".join(details)
        )

    return {
        "mode": "multi-kubeconfig" if len(unique_values) > 1 else "single-kubeconfig",
        "kubeconfigs": connector_values,
        "checks": checks,
        "tunnels": tunnel_results,
    }


def _context_components(context):
    if isinstance(context, dict):
        return list(context.get("components") or [])
    return list(getattr(context, "components", []) or [])


def _print_level5_dataset_sync(dataset_sync):
    status = str((dataset_sync or {}).get("status") or "not-applicable")
    datasets = list((dataset_sync or {}).get("datasets") or [])
    if status == "not-applicable":
        return

    print("\nSynchronizing Level 5 validation dataset sources...")
    for dataset in datasets:
        marker = "OK" if dataset.get("status") == "passed" else "WARN"
        location = dataset.get("relative_path") or dataset.get("path") or ""
        mode = dataset.get("source_mode") or "source"
        cloned = " cloned" if dataset.get("cloned") else ""
        print(f"  {marker} {dataset.get('name') or dataset.get('key')} ({mode}{cloned}): {location}")
        for note in list(dataset.get("notes") or [])[:2]:
            print(f"    - {note}")
        if dataset.get("error"):
            print(f"    - {dataset['error']}")

    if status == "warning":
        print("  Warning: dataset source synchronization completed with warnings.")
    elif status == "failed":
        print("  Error: dataset source synchronization failed.")


def _run_level5_dataset_sync(context):
    components = _context_components(context)
    dataset_sync = sync_level5_dataset_sources(
        components,
        strict=_env_flag("PIONERA_LEVEL5_DATASET_SYNC_STRICT", default=False),
    )
    _print_level5_dataset_sync(dataset_sync)
    if dataset_sync.get("status") == "failed":
        failed = [
            dataset.get("key") or dataset.get("name")
            for dataset in dataset_sync.get("datasets", [])
            if dataset.get("status") == "failed"
        ]
        raise RuntimeError(
            "Level 5 validation dataset synchronization failed"
            + (f": {', '.join(failed)}" if failed else "")
        )
    return dataset_sync


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
    if normalized_topology in {"vm-single", "vm-distributed"} and level_id == 2:
        _ensure_pionera_environment_profile_file(
            topology=normalized_topology,
            adapter_name=resolved_deployer_name,
        )
    if normalized_topology == VM_SINGLE_TOPOLOGY:
        vm_single_bundle = _load_vm_single_configuration_bundle(adapter_name=resolved_deployer_name)
        _ensure_vm_single_k3s_runtime_config(vm_single_bundle.get("topology") or {})
        vm_single_plan = _build_vm_single_topology_plan(
            vm_single_bundle["infrastructure"],
            vm_single_bundle["topology"],
            vm_single_bundle["adapter"],
        )
        vm_single_plan["config_files"] = vm_single_bundle["paths"]
        if _vm_single_should_run_level_remotely(level_id, vm_single_plan):
            return _run_vm_single_level_remotely(
                resolved_deployer_name,
                level_id,
            )
        if _vm_single_should_prepare_k3s_tunnel(
            level_id,
            vm_single_plan,
            vm_single_bundle.get("topology") or {},
        ):
            if level_id == 1:
                result = _run_vm_single_level1_via_ssh_tunnel(adapter, resolved_deployer_name)
                return {
                    "level": level_id,
                    "name": level_name,
                    "status": "completed",
                    "result": result,
                }
            access = _ensure_vm_single_k3s_api_access(adapter_name=resolved_deployer_name)
            with _temporary_environment(
                {
                    "KUBECONFIG": access["kubeconfig"],
                    "PIONERA_LEVEL_RUNTIME_ENV_ACTIVE": "true",
                }
            ):
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
    if os.environ.get("PIONERA_LEVEL_RUNTIME_ENV_ACTIVE") != "true":
        if normalized_topology == "vm-distributed" and level_id >= 1:
            kubeconfig_sync = _ensure_vm_distributed_local_kubeconfigs(
                roles=_vm_distributed_level_kubeconfig_roles(level_id),
            )
            _raise_vm_distributed_kubeconfig_sync_failure(kubeconfig_sync)
            if kubeconfig_sync.get("status") == "updated":
                _print_vm_distributed_kubeconfig_sync_result(kubeconfig_sync)
        environment_overrides = _topology_runtime_environment_overrides(topology, level=level_id)
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
        normalized_topology in {"vm-single", "vm-distributed"} and level_id in {1, 2, 3, 4, 5}
    ) and level_id in {1, 2, 3, 4, 5}:
        raise RuntimeError(
            f"Real Level {level_id} execution is not enabled for topology '{normalized_topology}' yet. "
            "Use the deployer dry-run/hosts plan first, then enable VM execution once the topology-specific "
            "deployment path is implemented."
        )

    if level_id == 1:
        if normalized_topology in {"vm-single", "vm-distributed"}:
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
        if normalized_topology in {"vm-single", "vm-distributed"}:
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
        if normalized_topology in {"vm-single", "vm-distributed"}:
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
        if normalized_topology == "vm-distributed":
            _ensure_vm_distributed_level4_kubeconfig_supported()
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
        if normalized_topology == "vm-distributed":
            sync_routing = _resolve_adapter_callable(adapter, "infrastructure.sync_vm_distributed_routing")
            if callable(sync_routing):
                sync_routing()
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
        dataset_sync = _run_level5_dataset_sync(context)
        result = deploy_components(context)
        if isinstance(result, dict):
            result.setdefault("datasets", dataset_sync)
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
        "status": (
            "completed_with_validation_failures"
            if (
                level_id == 6
                and isinstance(result, dict)
                and str(result.get("validation_status") or "").strip().lower() == "failed"
            )
            else "completed"
        ),
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

    status = (
        "completed_with_validation_failures"
        if any(
            isinstance(item, dict)
            and str(item.get("status") or "").strip().lower() == "completed_with_validation_failures"
            for item in completed
        )
        else "completed"
    )

    return {
        "status": status,
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


VM_DISTRIBUTED_TOPOLOGY_KEYS = (
    *tuple(sorted(COMMON_SERVICE_TOPOLOGY_KEYS)),
    *tuple(sorted(KUBERNETES_WORKLOAD_TOPOLOGY_KEYS)),
    *tuple(sorted(VM_SERVICE_TOPOLOGY_KEYS)),
    "VM_EXTERNAL_IP",
    "VM_COMMON_IP",
    "VM_DATASPACE_IP",
    "VM_PROVIDER_IP",
    "VM_CONSUMER_IP",
    "VM_PROVIDER_K8S_NODE",
    "VM_CONSUMER_K8S_NODE",
    "FRAMEWORK_EXECUTION_MODE",
    "VM_CONNECTORS_IP",
    "VM_COMPONENTS_IP",
    "VM_OBSERVABILITY_IP",
    "VM_SSH_USER",
    "INGRESS_EXTERNAL_IP",
    "CLUSTER_TYPE",
    "K3S_KUBECONFIG",
    "K3S_KUBECONFIG_COMMON",
    "K3S_KUBECONFIG_PROVIDER",
    "K3S_KUBECONFIG_CONSUMER",
    "K3S_KUBECONFIG_COMPONENTS",
    "K3S_INSTALL_EXEC",
    "K3S_SERVICE_NAME",
    "K3S_INGRESS_CONTROLLER",
    "K3S_INGRESS_SERVICE_TYPE",
    "K3S_INGRESS_HTTP_NODEPORT",
    "K3S_REPAIR_ON_LEVEL1",
    "K3S_WRITE_KUBECONFIG_MODE",
    "KEYCLOAK_BOOTSTRAP_PORT_FORWARD",
    "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES_ENABLED",
    "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES",
    "COMPONENTS_PUBLIC_BASE_URL",
    "COMPONENTS_PUBLIC_PATH_REWRITE",
    "VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER",
    "ONTOLOGY_HUB_PUBLIC_URL",
    "AI_MODEL_HUB_PUBLIC_URL",
    "SEMANTIC_VIRTUALIZATION_PUBLIC_URL",
    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL",
    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_MODE",
    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_LOCAL_PORT",
    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_REMOTE_HOST",
    "TOPOLOGY_ROUTING_MODE",
    "VM_PROVIDER_CONNECTORS",
    "VM_CONSUMER_CONNECTORS",
    "VM_PROVIDER_INGRESS_HTTP_PORT",
    "VM_CONSUMER_INGRESS_HTTP_PORT",
    "VM_PROVIDER_INGRESS_NODEPORT",
    "VM_CONSUMER_INGRESS_NODEPORT",
    "VM_PUBLIC_PROXY_IP",
    "CONNECTOR_PROTOCOL_ADDRESS_MODE",
    "SSH_BASTION_HOST",
    "SSH_BASTION_PORT",
    "SSH_BASTION_USER",
    "SSH_BASTION_IDENTITY_FILE",
    "SSH_IDENTITY_FILE",
    "SSH_ACCESS_MODE",
    "SSH_CONNECT_TIMEOUT_SECONDS",
    "VM_DISTRIBUTED_SSH_IDENTITY_FILE",
    "VM_DISTRIBUTED_EXECUTION_HOST",
    "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH",
    "VM_DISTRIBUTED_INFER_LOCAL_WORKDIR",
    "VM_DISTRIBUTED_KUBECONFIG_AUTO_LOCALIZE",
    "VM_DISTRIBUTED_KUBECONFIG_DIR",
    "VM_DISTRIBUTED_KUBECONFIG_SYNC",
    "VM_DISTRIBUTED_REMOTE_KUBECONFIG",
    "VM_COMMON_REMOTE_KUBECONFIG",
    "VM_PROVIDER_REMOTE_KUBECONFIG",
    "VM_CONSUMER_REMOTE_KUBECONFIG",
    "VM_COMPONENTS_REMOTE_KUBECONFIG",
    "VM_DISTRIBUTED_HTTP_PREFLIGHT_TLS_VERIFY",
    "VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE",
    "VM_DISTRIBUTED_SSH_KEY_COMMENT",
    "VM_DISTRIBUTED_SSH_MANAGED_MARKER",
    "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY",
    "VM_DISTRIBUTED_DEPLOYMENT_MODE",
    "VM_DISTRIBUTED_PREFLIGHT_DRY_RUN",
    "VM_DISTRIBUTED_K3S_TUNNEL_MODE",
    "VM_DISTRIBUTED_K3S_API_REMOTE_PORT",
    "VM_DISTRIBUTED_K3S_TUNNEL_RECREATE",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY",
    "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE",
    "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP",
    "VM_DISTRIBUTED_REMOTE_NGINX_INTERACTIVE",
    "VM_COMMON_K3S_API_LOCAL_PORT",
    "VM_PROVIDER_K3S_API_LOCAL_PORT",
    "VM_CONSUMER_K3S_API_LOCAL_PORT",
    "VM_COMPONENTS_K3S_API_LOCAL_PORT",
    "VM_REMOTE_WORKDIR",
    "VM_COMMON_REMOTE_WORKDIR",
    "VM_PROVIDER_REMOTE_WORKDIR",
    "VM_CONSUMER_REMOTE_WORKDIR",
    "VM_COMMON_PUBLIC_URL",
    "VM_PROVIDER_PUBLIC_URL",
    "VM_CONSUMER_PUBLIC_URL",
    "VM_COMMON_HTTP_URL",
    "VM_PROVIDER_HTTP_URL",
    "VM_CONSUMER_HTTP_URL",
    "VM_COMMON_SSH_HOST",
    "VM_COMMON_SSH_PORT",
    "VM_COMMON_SSH_USER",
    "VM_COMMON_SSH_IDENTITY_FILE",
    "VM_COMMON_SSH_ACCESS_MODE",
    "VM_COMMON_SSH_BASTION_HOST",
    "VM_COMMON_SSH_BASTION_PORT",
    "VM_COMMON_SSH_BASTION_USER",
    "VM_COMMON_SSH_BASTION_IDENTITY_FILE",
    "VM_COMPONENTS_SSH_HOST",
    "VM_COMPONENTS_SSH_PORT",
    "VM_COMPONENTS_SSH_USER",
    "VM_COMPONENTS_SSH_IDENTITY_FILE",
    "VM_COMPONENTS_SSH_ACCESS_MODE",
    "VM_COMPONENTS_SSH_BASTION_HOST",
    "VM_COMPONENTS_SSH_BASTION_PORT",
    "VM_COMPONENTS_SSH_BASTION_USER",
    "VM_COMPONENTS_SSH_BASTION_IDENTITY_FILE",
    "VM_PROVIDER_SSH_HOST",
    "VM_PROVIDER_SSH_PORT",
    "VM_PROVIDER_SSH_USER",
    "VM_PROVIDER_SSH_IDENTITY_FILE",
    "VM_PROVIDER_SSH_ACCESS_MODE",
    "VM_PROVIDER_SSH_BASTION_HOST",
    "VM_PROVIDER_SSH_BASTION_PORT",
    "VM_PROVIDER_SSH_BASTION_USER",
    "VM_PROVIDER_SSH_BASTION_IDENTITY_FILE",
    "VM_CONSUMER_SSH_HOST",
    "VM_CONSUMER_SSH_PORT",
    "VM_CONSUMER_SSH_USER",
    "VM_CONSUMER_SSH_IDENTITY_FILE",
    "VM_CONSUMER_SSH_ACCESS_MODE",
    "VM_CONSUMER_SSH_BASTION_HOST",
    "VM_CONSUMER_SSH_BASTION_PORT",
    "VM_CONSUMER_SSH_BASTION_USER",
    "VM_CONSUMER_SSH_BASTION_IDENTITY_FILE",
)

VM_DISTRIBUTED_INFRA_KEYS = ()

VM_DISTRIBUTED_ADAPTER_KEYS = (
    "DS_1_NAME",
    "DS_1_NAMESPACE",
    "DS_1_REGISTRATION_NAMESPACE",
    "DS_1_PROVIDER_NAMESPACE",
    "DS_1_CONSUMER_NAMESPACE",
    "DS_1_CONNECTORS",
    "DS_1_CONNECTOR_NAMESPACES",
    "DS_1_VALIDATION_PAIRS",
    "LEVEL4_CONNECTOR_RECONCILIATION_MODE",
)

VM_DISTRIBUTED_PROFILE_INFRA_KEYS = frozenset(
    {
        "PG_HOST",
        "PG_PORT",
    }
)

VM_DISTRIBUTED_PROFILE_TOPOLOGY_KEYS = frozenset(
    set(VM_DISTRIBUTED_TOPOLOGY_KEYS)
    | set(TOPOLOGY_OVERLAY_KEYS.get("vm-distributed", frozenset()))
)

ENVIRONMENT_PROFILE_METADATA_KEYS = frozenset(
    {
        "PROFILE_NAME",
        "PROFILE_TOPOLOGY",
        "PROFILE_ADAPTER",
        "ENVIRONMENT_NAME",
        "ENVIRONMENT_LABEL",
    }
)

ENVIRONMENT_PROFILE_INFRA_KEYS = frozenset(
    {
        *VM_DISTRIBUTED_PROFILE_INFRA_KEYS,
        *INFRASTRUCTURE_MANAGED_KEYS,
        "DOMAIN_BASE",
        "DS_DOMAIN_BASE",
        "PUBLIC_HOSTNAME",
        "PUBLIC_HOSTNAME_PROVIDER",
        "PUBLIC_HOSTNAME_CONSUMER",
        "TOPOLOGY",
    }
)

VM_DISTRIBUTED_PROFILE_SENSITIVE_KEY_TOKENS = (
    "PASSWORD",
    "PASSWD",
    "_PASS",
    "TOKEN",
    "SECRET",
    "PRIVATE_KEY",
    "UNSEAL",
    "ROOT_KEY",
)

TOPOLOGY_SCOPED_INFRASTRUCTURE_KEYS = frozenset(
    set(COMMON_SERVICE_TOPOLOGY_KEYS)
    | set(KUBERNETES_WORKLOAD_TOPOLOGY_KEYS)
    | set(VM_SERVICE_TOPOLOGY_KEYS)
    | {
        "PIONERA_LEVEL6_MINIO_ENDPOINT",
    }
)


def _effective_topology_scoped_infrastructure_config(
    infrastructure_config,
    topology_config,
    topology="vm-distributed",
):
    selected_topology = normalize_topology(topology)
    effective = dict(infrastructure_config or {})
    allowed_topology_keys = set(TOPOLOGY_OVERLAY_KEYS.get(selected_topology, frozenset()))
    for key in sorted(TOPOLOGY_SCOPED_INFRASTRUCTURE_KEYS & allowed_topology_keys):
        value = str(dict(topology_config or {}).get(key) or "").strip()
        if value:
            effective[key] = value
    return effective


def _is_vm_public_placeholder_domain(value):
    normalized = str(value or "").strip().strip(".").lower()
    if not normalized:
        return False
    return normalized in VM_PUBLIC_PLACEHOLDER_DOMAINS


def _usable_vm_public_url_config_value(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if is_vm_public_placeholder_url(text):
        return ""
    return text


VM_DISTRIBUTED_PUBLIC_URL_KEYS = (
    "VM_SINGLE_PUBLIC_URL",
    "VM_SINGLE_HTTP_URL",
    "VM_COMMON_PUBLIC_URL",
    "VM_PROVIDER_PUBLIC_URL",
    "VM_CONSUMER_PUBLIC_URL",
    "KEYCLOAK_FRONTEND_URL",
    "KEYCLOAK_PUBLIC_URL",
    "MINIO_API_PUBLIC_URL",
    "MINIO_PUBLIC_URL",
    "MINIO_CONSOLE_PUBLIC_URL",
    "COMPONENTS_PUBLIC_BASE_URL",
    "PUBLIC_PORTAL_PUBLIC_URL",
    "PUBLIC_PORTAL_BACKEND_PUBLIC_URL",
    "DATASPACE_PUBLIC_PORTAL_BACKEND_URL",
    "REGISTRATION_SERVICE_PUBLIC_URL",
    "DATASPACE_REGISTRATION_SERVICE_PUBLIC_URL",
)


def _adapter_deployer_config_path(adapter_name):
    normalized = str(adapter_name or "").strip().lower()
    if not normalized:
        return ""
    return os.path.join(os.path.dirname(__file__), "deployers", normalized, "deployer.config")


def _adapter_deployer_config_example_path(adapter_name):
    normalized = str(adapter_name or "").strip().lower()
    if not normalized:
        return ""
    return os.path.join(os.path.dirname(__file__), "deployers", normalized, "deployer.config.example")


def _seed_adapter_deployer_config_if_missing(adapter_name):
    config_path = _adapter_deployer_config_path(adapter_name)
    if not config_path:
        return ""
    if os.path.isfile(config_path):
        return config_path

    example_path = _adapter_deployer_config_example_path(adapter_name)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    if os.path.isfile(example_path):
        shutil.copy2(example_path, config_path)
    else:
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("")
    return config_path


def _vm_distributed_discovery_commands(topic):
    normalized = _vm_distributed_help_topic_base(topic)
    commands = {
        "address": [
            "hostname -I",
            "ip -4 addr show",
            "ip route get 1.1.1.1",
            "getent hosts <dns-name>",
        ],
        "domain": [
            "getent hosts <hostname>",
            "dig +short <hostname>",
            "curl -kI https://<hostname>",
        ],
        "kubeconfig": [
            "sudo ls -l /etc/rancher/k3s/k3s.yaml",
            "sudo cat /etc/rancher/k3s/k3s.yaml",
            "kubectl --kubeconfig /path/to/k3s.yaml get nodes -o wide",
        ],
        "ingress": [
            "kubectl --kubeconfig /path/to/k3s.yaml -n ingress-nginx get svc -o wide",
            "kubectl --kubeconfig /path/to/k3s.yaml get ingress -A",
            "sudo ss -lntp",
            "sudo ufw status",
        ],
        "ssh": [
            "whoami",
            "id -un",
            "ssh <user>@<vm-ip-or-dns> hostname",
            "ssh <user>@<vm-ip-or-dns> sudo -n true",
        ],
        "connectors": [
            "Use short connector names, for example: org2,org3,partnera",
            "Map locations with connector:group, for example: org2:provider,partnera:provider",
            "Map validation pairs with source>target, for example: org2>org3,partnera>org2",
        ],
        "ssh": [
            "ssh -J <bastion-user>@<bastion-host>:<port> <vm-user>@<vm-host>",
            "ssh <vm-user>@<vm-host> -p <port>",
            "ssh -G <vm-host>",
        ],
    }
    return commands.get(normalized, [])


def _vm_distributed_help_topic_base(topic):
    normalized = str(topic or "").strip().lower().replace("_", "-")
    aliases = {
        "common-domain": "domain",
        "dataspace-domain": "domain",
        "framework-execution": "framework-execution",
        "routing": "ingress",
        "common-address": "address",
        "provider-address": "address",
        "consumer-address": "address",
        "components-address": "address",
        "ingress-address": "ingress",
        "ssh-user": "ssh",
        "common-kubeconfig": "kubeconfig",
        "provider-kubeconfig": "kubeconfig",
        "consumer-kubeconfig": "kubeconfig",
        "components-kubeconfig": "kubeconfig",
        "dataspace": "connectors",
        "connector-inventory": "connectors",
        "connector-locations": "connectors",
        "validation-pairs": "connectors",
        "reconciliation": "connectors",
        "ssh": "ssh",
        "ssh-access": "ssh",
        "ssh-mode": "ssh",
        "bastion": "ssh",
        "jump-host": "ssh",
        "common-ssh": "ssh",
        "provider-ssh": "ssh",
        "consumer-ssh": "ssh",
    }
    return aliases.get(normalized, normalized)


def _vm_distributed_discovery_details(topic):
    normalized = str(topic or "").strip().lower().replace("_", "-")
    details = {
        "common-domain": {
            "purpose": [
                "Base DNS suffix used by common services such as Keycloak, MinIO, PostgreSQL and Vault.",
                "The framework uses it to build public URLs and hosts entries for shared services.",
            ],
            "choice": [
                "Keep the value in brackets if it already matches the target deployment.",
                "Otherwise enter the DNS suffix that users and VMs will use to reach common services.",
            ],
        },
        "dataspace-domain": {
            "purpose": [
                "Base DNS suffix used by the dataspace, connectors and validation components.",
                "The framework uses it to build registration-service, connector and component URLs.",
            ],
            "choice": [
                "Use a domain delegated to the distributed environment, often a subdomain of the common domain.",
                "All machines that run validation should be able to resolve or map this domain through hosts entries.",
            ],
        },
        "framework-execution": {
            "purpose": [
                "Defines where the framework process is expected to run for VM topologies.",
                "orchestrator is the recommended workstation/WSL flow; target-vm means running directly inside the target or common-services VM.",
            ],
            "choice": [
                "Use auto unless you need to force one behavior.",
                "Use orchestrator from WSL or an operator workstation.",
                "Use target-vm when launching the framework directly inside the VM that owns the deployment.",
            ],
        },
        "routing": {
            "purpose": [
                "Defines how the framework expects to reach public endpoints.",
                "The current supported mode is host-based routing through DNS or /etc/hosts entries.",
            ],
            "choice": [
                "Use host unless a new routing strategy has been explicitly implemented.",
            ],
        },
        "common-address": {
            "purpose": [
                "IP or DNS of the VM that exposes common services: Keycloak, MinIO, PostgreSQL and Vault.",
                "Levels 1 and 2 use this role as the shared foundation for the dataspace.",
            ],
            "choice": [
                "Use an address reachable from the other VMs and from the machine running the framework.",
                "On Ubuntu, hostname -I usually shows the candidate private address for the VM.",
            ],
        },
        "provider-address": {
            "purpose": [
                "IP or DNS of the VM or node group where provider-side connectors are expected to be exposed.",
                "This is a validation location label; a connector can still act as provider or consumer per flow.",
            ],
            "choice": [
                "Use the address that should receive hostnames for connectors mapped to the provider group.",
                "If all roles share one VM or one ingress, reuse the common services address.",
            ],
        },
        "consumer-address": {
            "purpose": [
                "IP or DNS of the VM or node group where consumer-side connectors are expected to be exposed.",
                "This is separate from business role: the same connector may consume or provide in different tests.",
            ],
            "choice": [
                "Use the address that should receive hostnames for connectors mapped to the consumer group.",
                "If all connectors share one ingress, reuse the provider or common services address.",
            ],
        },
        "components-address": {
            "purpose": [
                "IP or DNS of the VM or node group that exposes Ontology Hub, AI Model Hub and Semantic Virtualization.",
                "Level 5 and Level 6 use this value to plan component access URLs.",
            ],
            "choice": [
                "Use the components VM address when components are separated from connectors.",
                "If components run on the same ingress as common services, keep the default.",
            ],
        },
        "ingress-address": {
            "purpose": [
                "Public IP or DNS where ingress hostnames should resolve.",
                "The hosts planner uses it as the default address for generated entries.",
            ],
            "choice": [
                "Use the LoadBalancer, reverse proxy or VM address that actually receives HTTP/HTTPS traffic.",
                "If there is no separate ingress endpoint, keep the common services address.",
            ],
        },
        "ssh-user": {
            "purpose": [
                "Ubuntu user used only when the framework must synchronize NGINX on remote connector VMs.",
                "If it is empty, remote NGINX files are not modified automatically.",
            ],
            "choice": [
                "Use a user that can connect by SSH and run sudo for NGINX reloads on the target VMs.",
                "Leave it empty when all routing is handled on the common VM or you prefer manual NGINX updates.",
            ],
        },
        "common-kubeconfig": {
            "purpose": [
                "Kubeconfig used by the framework to operate common services and the dataspace control plane.",
                "Level 4 keeps common bootstrap work on this context even when connector roles use separate kubeconfigs.",
            ],
            "choice": [
                "Use a kubeconfig that can run kubectl and Helm against the common-services k3s cluster.",
                "For a single logical k3s cluster, /etc/rancher/k3s/k3s.yaml is usually the source file.",
            ],
        },
        "provider-kubeconfig": {
            "purpose": [
                "Kubeconfig used by Level 4 for provider-side connector Helm and kubectl operations.",
                "It may equal the common kubeconfig in a single logical cluster, or point to the provider cluster in a multi-cluster setup.",
            ],
            "choice": [
                "Use the provider cluster kubeconfig when the provider connector runs on its own k3s server.",
            ],
        },
        "consumer-kubeconfig": {
            "purpose": [
                "Kubeconfig used by Level 4 for consumer-side connector Helm and kubectl operations.",
                "It may equal the common/provider kubeconfig in a single logical cluster, or point to the consumer cluster in a multi-cluster setup.",
            ],
            "choice": [
                "Use the consumer cluster kubeconfig when the consumer connector runs on its own k3s server.",
            ],
        },
        "components-kubeconfig": {
            "purpose": [
                "Kubeconfig used by Level 5 when deploying validation components.",
                "It can point to the same logical cluster or to a components context when supported by the deployment.",
            ],
            "choice": [
                "Reuse the common services kubeconfig unless components are intentionally managed through another context.",
            ],
        },
        "dataspace": {
            "purpose": [
                "Logical dataspace name used to build release names, connector names and validation URLs.",
            ],
            "choice": [
                "Keep pionera unless the deployment intentionally uses a different dataspace identifier.",
            ],
        },
        "connector-inventory": {
            "purpose": [
                "Comma-separated list of connector short names that Level 4 should reconcile.",
                "The framework expands short names into conn-<name>-<dataspace>.",
            ],
            "choice": [
                "Use only connector names you want this run to manage.",
                "For adding a connector without recreating healthy ones, combine this with additive reconciliation.",
            ],
        },
        "connector-locations": {
            "purpose": [
                "Maps each connector to a deployment location group: provider, consumer, dataspace or a custom namespace.",
                "This controls placement/namespace, not the business role of the connector in every test.",
            ],
            "choice": [
                "Use connector:provider or connector:consumer for role-aligned namespaces.",
                "Leave a connector unmapped only if it should fall back to the dataspace namespace.",
            ],
        },
        "validation-pairs": {
            "purpose": [
                "Defines which connector pairs are used by automated interoperability validations.",
                "The left side is the source of the test flow and the right side is the target.",
            ],
            "choice": [
                "Use source>target, separated by commas for multiple flows.",
                "Example: org2>org3,partnera>org2.",
            ],
        },
        "reconciliation": {
            "purpose": [
                "Controls how Level 4 treats existing connectors.",
                "full recreates the configured set; additive preserves healthy existing connectors and adds missing ones.",
            ],
            "choice": [
                "Use full for clean validation evidence.",
                "Use additive when adding connectors to an already running dataspace.",
            ],
        },
        "ssh": {
            "purpose": [
                "Optional metadata for future remote preparation and non-destructive preflight commands.",
                "It describes bastion or direct SSH access without storing passwords, keys or tokens.",
            ],
            "choice": [
                "Leave empty when kubectl and helm are already configured on the host running the framework.",
                "Use bastion when VMs are reached through a jump host; use direct when each VM is reachable directly.",
                "Store only hostnames, ports and generic users in local .config files ignored by Git.",
            ],
        },
    }
    if normalized in details:
        return details[normalized]
    return details.get(_vm_distributed_help_topic_base(normalized), {})


def _print_vm_distributed_discovery_help(topic):
    commands = _vm_distributed_discovery_commands(topic)
    details = _vm_distributed_discovery_details(topic)
    if not commands and not details:
        print("No command hints registered for this field.")
        return
    print()
    if details:
        print("What this value controls:")
        for item in details.get("purpose") or []:
            print(f"  {item}")
        print()
        print("How to choose it:")
        for item in details.get("choice") or []:
            print(f"  {item}")
        print()
    if commands:
        print("Helpful Ubuntu commands / examples:")
        for command in commands:
            print(f"  {command}")
    print()


def _prompt_vm_distributed_value(
    label,
    current="",
    default="",
    required=False,
    help_topic="",
    profile_value=None,
):
    current_text = str(current or "").strip()
    default_text = str(default or "").strip()
    profile_text = str(profile_value or "").strip() if profile_value is not None else ""
    while True:
        suffix = ""
        if profile_text:
            suffix = f" [{profile_text}]"
        elif current_text:
            suffix = f" [{current_text}]"
        elif default_text:
            suffix = f" [{default_text}]"
        prompt = f"{label}{suffix}: "
        value = _interactive_read(prompt).strip()
        if value == "?":
            _print_vm_distributed_discovery_help(help_topic)
            continue
        if value:
            return value
        if profile_text:
            return profile_text
        if current_text:
            return current_text
        if default_text:
            return default_text
        if not required:
            return ""
        print("This value is required for the distributed deployment configuration.")


def _vm_distributed_legacy_common_service_config_values(domain_base):
    hostnames = legacy_common_service_hostnames(domain_base)
    return {
        "KC_INTERNAL_URL": f"http://{hostnames['keycloak_hostname']}",
        "KC_URL": f"http://{hostnames['keycloak_admin_hostname']}",
        "KEYCLOAK_HOSTNAME": hostnames["keycloak_hostname"],
        "KEYCLOAK_ADMIN_HOSTNAME": hostnames["keycloak_admin_hostname"],
        "MINIO_HOSTNAME": hostnames["minio_hostname"],
        "MINIO_CONSOLE_HOSTNAME": hostnames["minio_console_hostname"],
    }


def _vm_distributed_equivalent_config_value(key, left, right):
    left_value = str(left or "").strip()
    right_value = str(right or "").strip()
    if key in {"KC_INTERNAL_URL", "KC_URL"}:
        left_value = left_value.rstrip("/")
        right_value = right_value.rstrip("/")
    return left_value.lower() == right_value.lower()


def _vm_distributed_common_service_public_updates(domain_base, existing_config):
    target_domain = str(domain_base or "").strip()
    if not target_domain:
        return {}

    existing = dict(existing_config or {})
    desired = canonical_common_service_config_values(target_domain, protocol="http")
    known_domains = []
    for candidate in (
        existing.get("DOMAIN_BASE"),
        DEFAULT_COMMON_DOMAIN_BASE,
        target_domain,
    ):
        normalized = str(candidate or "").strip()
        if normalized and normalized not in known_domains:
            known_domains.append(normalized)

    generated_by_key = {key: set() for key in desired}
    for candidate_domain in known_domains:
        for generated in (
            canonical_common_service_config_values(candidate_domain, protocol="http"),
            _vm_distributed_legacy_common_service_config_values(candidate_domain),
        ):
            for key, value in generated.items():
                generated_by_key.setdefault(key, set()).add(value)

    updates = {}
    for key, target_value in desired.items():
        current_value = str(existing.get(key) or "").strip()
        if not current_value:
            updates[key] = target_value
            continue
        if any(
            _vm_distributed_equivalent_config_value(key, current_value, generated_value)
            for generated_value in generated_by_key.get(key, set())
        ):
            updates[key] = target_value
    return updates


def _vm_distributed_connector_tokens(raw_value):
    tokens = []
    for token in str(raw_value or "").split(","):
        item = token.strip()
        if item and item not in tokens:
            tokens.append(item)
    return tokens


def _default_vm_distributed_connector_locations(connectors_value):
    connectors = _vm_distributed_connector_tokens(connectors_value)
    roles = ("provider", "consumer")
    return ",".join(
        f"{connector}:{roles[index % len(roles)]}"
        for index, connector in enumerate(connectors)
    )


def _default_vm_distributed_validation_pairs(connectors_value):
    connectors = _vm_distributed_connector_tokens(connectors_value)
    if len(connectors) < 2:
        return ""
    return f"{connectors[0]}>{connectors[1]}"


def _connector_mapping_invalid_tokens(raw_value):
    invalid = []
    for token in str(raw_value or "").split(","):
        item = token.strip()
        if item and ":" not in item and "=" not in item:
            invalid.append(item)
    return invalid


def _connector_pairs_invalid_tokens(raw_value):
    invalid = []
    for token in str(raw_value or "").split(","):
        item = token.strip()
        if item and "->" not in item and ">" not in item and "=" not in item:
            invalid.append(item)
    return invalid


def _normalized_reconciliation_mode(raw_value):
    mode = str(raw_value or "full").strip().lower().replace("_", "-")
    if mode in {"additive", "add-only", "append", "preserve-existing"}:
        return "additive"
    if mode in {"full", "recreate", "reset"}:
        return "full"
    return ""


def _vm_distributed_ssh_access_preflight(topology_config):
    topology = dict(topology_config or {})
    ssh_identity_keys = (
        "SSH_ACCESS_MODE",
        "SSH_BASTION_HOST",
        "SSH_BASTION_USER",
        "VM_COMMON_SSH_ACCESS_MODE",
        "VM_COMMON_SSH_BASTION_HOST",
        "VM_COMMON_SSH_BASTION_USER",
        "VM_COMMON_SSH_HOST",
        "VM_COMMON_SSH_USER",
        "VM_PROVIDER_SSH_ACCESS_MODE",
        "VM_PROVIDER_SSH_BASTION_HOST",
        "VM_PROVIDER_SSH_BASTION_USER",
        "VM_PROVIDER_SSH_HOST",
        "VM_PROVIDER_SSH_USER",
        "VM_CONSUMER_SSH_ACCESS_MODE",
        "VM_CONSUMER_SSH_BASTION_HOST",
        "VM_CONSUMER_SSH_BASTION_USER",
        "VM_CONSUMER_SSH_HOST",
        "VM_CONSUMER_SSH_USER",
    )
    has_metadata = any(str(topology.get(key) or "").strip() for key in ssh_identity_keys)
    global_mode = _vm_distributed_effective_ssh_access_mode(topology)
    warnings = []

    if not has_metadata:
        return {
            "status": "ready",
            "detail": "optional SSH metadata not configured",
            "warnings": [],
        }

    raw_global_mode = str(topology.get("SSH_ACCESS_MODE") or "").strip()
    if raw_global_mode and not _normalize_vm_distributed_ssh_access_mode(raw_global_mode):
        warnings.append("SSH_ACCESS_MODE should be direct or bastion when SSH metadata is configured.")

    if global_mode == "bastion" and not str(topology.get("SSH_BASTION_HOST") or "").strip():
        warnings.append("SSH_BASTION_HOST is required when SSH_ACCESS_MODE=bastion.")

    role_specs = (
        ("common", "VM_COMMON_SSH_HOST", "VM_COMMON_IP", "VM_COMMON_SSH_PORT"),
        ("provider", "VM_PROVIDER_SSH_HOST", "VM_PROVIDER_IP", "VM_PROVIDER_SSH_PORT"),
        ("consumer", "VM_CONSUMER_SSH_HOST", "VM_CONSUMER_IP", "VM_CONSUMER_SSH_PORT"),
    )
    missing_hosts = []
    role_modes = {}
    for role, host_key, fallback_ip_key, port_key in role_specs:
        if not str(topology.get(host_key) or topology.get(fallback_ip_key) or "").strip():
            missing_hosts.append(role)
        role_prefix = _vm_distributed_role_prefix(role)
        raw_role_mode = str(topology.get(f"VM_{role_prefix}_SSH_ACCESS_MODE") or "").strip()
        if raw_role_mode and not _normalize_vm_distributed_ssh_access_mode(raw_role_mode):
            warnings.append(f"VM_{role_prefix}_SSH_ACCESS_MODE should be direct or bastion.")
        role_mode = _vm_distributed_role_ssh_access_mode(topology, role)
        role_modes[role] = role_mode or "not-configured"
        role_bastion = _vm_distributed_role_bastion_config(topology, role)
        if role_mode == "bastion" and not role_bastion.get("host"):
            warnings.append(f"VM_{role_prefix}_SSH_BASTION_HOST or SSH_BASTION_HOST is required for {role} bastion SSH.")
        port_value = str(topology.get(port_key) or "").strip()
        if port_value and not _vm_distributed_valid_port(port_value):
            warnings.append(f"{port_key} should be a TCP port number between 1 and 65535.")
        bastion_port_value = str(topology.get(f"VM_{role_prefix}_SSH_BASTION_PORT") or "").strip()
        if bastion_port_value and not _vm_distributed_valid_port(bastion_port_value):
            warnings.append(f"VM_{role_prefix}_SSH_BASTION_PORT should be a TCP port number between 1 and 65535.")

    if not global_mode and not any(mode in {"direct", "bastion"} for mode in role_modes.values()):
        warnings.append(
            "SSH_ACCESS_MODE or VM_<ROLE>_SSH_ACCESS_MODE should be direct or bastion when SSH metadata is configured."
        )

    if missing_hosts:
        warnings.append(
            "SSH metadata is missing a host/IP for roles: " + ", ".join(missing_hosts)
        )

    bastion_port = str(topology.get("SSH_BASTION_PORT") or "").strip()
    if bastion_port and not _vm_distributed_valid_port(bastion_port):
        warnings.append("SSH_BASTION_PORT should be a TCP port number between 1 and 65535.")

    if warnings:
        return {
            "status": "needs-review",
            "detail": "SSH metadata configured but incomplete",
            "warnings": warnings,
        }

    return {
        "status": "ready",
        "detail": (
            f"{global_mode} SSH metadata configured"
            if global_mode
            else "role-specific SSH metadata configured"
        ),
        "role_modes": role_modes,
        "warnings": [],
    }


def _vm_single_ssh_access_preflight(topology_config):
    topology = dict(topology_config or {})
    ssh_identity_keys = (
        "SSH_ACCESS_MODE",
        "SSH_BASTION_HOST",
        "SSH_BASTION_USER",
        "VM_SINGLE_SSH_HOST",
        "VM_SINGLE_SSH_USER",
        "VM_SSH_USER",
    )
    has_metadata = any(str(topology.get(key) or "").strip() for key in ssh_identity_keys)
    mode = str(topology.get("SSH_ACCESS_MODE") or "").strip().lower().replace("_", "-")
    warnings = []

    if not has_metadata:
        return {
            "status": "ready",
            "detail": "optional SSH metadata not configured",
            "warnings": [],
        }

    if mode not in {"direct", "bastion"}:
        warnings.append("SSH_ACCESS_MODE should be direct or bastion when SSH metadata is configured.")

    if mode == "bastion" and not str(topology.get("SSH_BASTION_HOST") or "").strip():
        warnings.append("SSH_BASTION_HOST is required when SSH_ACCESS_MODE=bastion.")

    target_host = _vm_distributed_config_value(
        topology,
        "VM_SINGLE_SSH_HOST",
        "VM_SINGLE_ADDRESS",
        "VM_SINGLE_IP",
        "VM_EXTERNAL_IP",
        "HOSTS_ADDRESS",
        "INGRESS_EXTERNAL_IP",
    )
    if not target_host:
        warnings.append("VM_SINGLE_SSH_HOST or VM_EXTERNAL_IP is required for vm-single SSH access.")

    target_port = str(topology.get("VM_SINGLE_SSH_PORT") or "").strip()
    if target_port and not _vm_distributed_valid_port(target_port):
        warnings.append("VM_SINGLE_SSH_PORT should be a TCP port number between 1 and 65535.")

    bastion_port = str(topology.get("SSH_BASTION_PORT") or "").strip()
    if bastion_port and not _vm_distributed_valid_port(bastion_port):
        warnings.append("SSH_BASTION_PORT should be a TCP port number between 1 and 65535.")

    if warnings:
        return {
            "status": "needs-review",
            "detail": "SSH metadata configured but incomplete",
            "warnings": warnings,
        }

    return {
        "status": "ready",
        "detail": f"{mode or 'direct'} SSH metadata configured",
        "warnings": [],
    }


def _vm_distributed_valid_port(value):
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return False
    return 1 <= port <= 65535


def _vm_distributed_config_value(config, *keys, default=""):
    for key in keys:
        value = str((config or {}).get(key) or "").strip()
        if value:
            return value
    return str(default or "").strip()


def _vm_distributed_config_flag(config, key, default=False):
    raw_value = (config or {}).get(key)
    if raw_value is None or str(raw_value).strip() == "":
        return bool(default)
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on", "y", "s", "si", "sí"}


def _framework_root_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _framework_runtime_bin_dir():
    return os.path.join(_framework_root_dir(), "runtime", "bin")


def _ensure_k3s_kubectl_wrapper():
    existing_kubectl = shutil.which("kubectl")
    if existing_kubectl:
        return {
            "status": "ready",
            "reason": "kubectl-present",
            "path": existing_kubectl,
        }

    k3s_path = shutil.which("k3s")
    if not k3s_path:
        return {
            "status": "skipped",
            "reason": "k3s-missing",
            "path": "",
        }

    bin_dir = _framework_runtime_bin_dir()
    wrapper_path = os.path.join(bin_dir, "kubectl")
    content = "\n".join(
        [
            "#!/bin/sh",
            f"exec {shlex.quote(k3s_path)} kubectl \"$@\"",
            "",
        ]
    )
    os.makedirs(bin_dir, exist_ok=True)
    previous = ""
    try:
        with open(wrapper_path, encoding="utf-8") as handle:
            previous = handle.read()
    except OSError:
        previous = ""

    if previous != content:
        with open(wrapper_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        status = "written"
    else:
        status = "ready"
    os.chmod(wrapper_path, 0o755)
    return {
        "status": status,
        "reason": "k3s-kubectl-wrapper",
        "path": wrapper_path,
        "k3s": k3s_path,
    }


def _k3s_kubectl_environment_overrides():
    wrapper = _ensure_k3s_kubectl_wrapper()
    if wrapper.get("reason") != "k3s-kubectl-wrapper":
        return {}
    wrapper_path = str(wrapper.get("path") or "").strip()
    if not wrapper_path:
        return {}
    bin_dir = os.path.dirname(wrapper_path)
    current_path = os.environ.get("PATH", "")
    return {
        "PATH": f"{bin_dir}{os.pathsep}{current_path}" if current_path else bin_dir,
        "PIONERA_KUBECTL_WRAPPER": wrapper_path,
    }


def _vm_distributed_connect_timeout_seconds(topology_config):
    raw_value = (
        os.getenv("PIONERA_VM_DISTRIBUTED_SSH_CONNECT_TIMEOUT_SECONDS")
        or _vm_distributed_config_value(topology_config, "SSH_CONNECT_TIMEOUT_SECONDS", default="5")
    )
    try:
        timeout = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return 5
    return min(max(timeout, 1), 60)


def _vm_distributed_identity_file(topology_config, role_key=None):
    role = str(role_key or "").strip().upper().replace("-", "_")
    role_identity_key = f"VM_{role}_SSH_IDENTITY_FILE" if role else ""
    return _vm_distributed_config_value(
        topology_config,
        role_identity_key,
        "VM_DISTRIBUTED_SSH_IDENTITY_FILE",
        "SSH_IDENTITY_FILE",
    )


def _vm_single_identity_file(topology_config):
    return _vm_distributed_config_value(
        topology_config,
        "VM_SINGLE_SSH_IDENTITY_FILE",
        "SSH_IDENTITY_FILE",
    )


def _vm_single_connect_timeout_seconds(topology_config):
    raw_value = (
        os.getenv("PIONERA_VM_SINGLE_SSH_CONNECT_TIMEOUT_SECONDS")
        or _vm_distributed_config_value(topology_config, "SSH_CONNECT_TIMEOUT_SECONDS", default="5")
    )
    try:
        timeout = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return 5
    return min(max(timeout, 1), 60)


def _normalized_framework_execution_mode(topology_config):
    raw_value = (
        os.getenv("PIONERA_FRAMEWORK_EXECUTION_MODE")
        or _vm_distributed_config_value(topology_config, "FRAMEWORK_EXECUTION_MODE", default="auto")
    )
    normalized = str(raw_value or "auto").strip().lower().replace("_", "-")
    aliases = {
        "": "auto",
        "detect": "auto",
        "detected": "auto",
        "operator": "orchestrator",
        "workstation": "orchestrator",
        "wsl": "orchestrator",
        "external": "orchestrator",
        "remote": "orchestrator",
        "common": "target-vm",
        "common-vm": "target-vm",
        "common-services": "target-vm",
        "common-services-vm": "target-vm",
        "inside-vm": "target-vm",
        "current-vm": "target-vm",
        "direct-vm": "target-vm",
        "local-vm": "target-vm",
        "vm": "target-vm",
    }
    return aliases.get(normalized, normalized)


def _framework_execution_mode_is_explicit(mode):
    return str(mode or "").strip().lower() not in {"", "auto"}


def _normalized_vm_single_level_execution_mode(topology_config):
    specific_env = os.getenv("PIONERA_VM_SINGLE_LEVEL_EXECUTION_MODE")
    specific_config = _vm_distributed_config_value(
        topology_config,
        "VM_SINGLE_LEVEL_EXECUTION_MODE",
        "VM_SINGLE_REMOTE_EXECUTION_MODE",
    )
    framework_mode = _normalized_framework_execution_mode(topology_config)
    if specific_env:
        raw_value = specific_env
    elif (
        _framework_execution_mode_is_explicit(framework_mode)
        and str(specific_config or "").strip().lower().replace("_", "-") in {"", "auto"}
    ):
        raw_value = {
            "orchestrator": "tunnel",
            "target-vm": "local",
        }.get(framework_mode, framework_mode)
    else:
        raw_value = specific_config or "local"

    raw_value = str(raw_value or "local").lower().replace("_", "-")
    aliases = {
        "direct": "local",
        "current": "local",
        "inside-vm": "local",
        "operator": "tunnel",
        "external": "tunnel",
        "orchestrator": "tunnel",
        "workstation": "tunnel",
        "target-vm": "local",
        "common-services": "local",
        "common-services-vm": "local",
        "ssh": "remote",
        "wsl": "auto",
    }
    return aliases.get(raw_value, raw_value)


def _normalized_vm_distributed_execution_host(topology_config):
    specific = _vm_distributed_config_value(
        topology_config,
        "VM_DISTRIBUTED_EXECUTION_HOST",
    ).lower().replace("_", "-")
    framework_mode = _normalized_framework_execution_mode(topology_config)
    if specific in {"", "auto"} and _framework_execution_mode_is_explicit(framework_mode):
        raw_value = {
            "orchestrator": "external",
            "target-vm": "common-services",
        }.get(framework_mode, framework_mode)
    else:
        raw_value = specific or "external"
    aliases = {
        "local": "external",
        "operator": "external",
        "orchestrator": "external",
        "workstation": "external",
        "common": "common-services",
        "common-vm": "common-services",
        "common-services-vm": "common-services",
        "target-vm": "common-services",
        "inside-vm": "common-services",
        "detect": "auto",
        "detected": "auto",
    }
    normalized = aliases.get(raw_value, raw_value)
    if normalized == "auto":
        return "common-services" if _vm_distributed_running_on_common_services(topology_config) else "external"
    return normalized


def _vm_single_remote_python(topology_config):
    return _vm_distributed_config_value(topology_config, "VM_SINGLE_REMOTE_PYTHON", default="python3")


def _normalized_vm_single_ssh_bootstrap_mode(topology_config):
    raw_value = _vm_distributed_config_value(
        topology_config,
        "VM_SINGLE_SSH_BOOTSTRAP_MODE",
        default="manual",
    ).lower().replace("_", "-")
    aliases = {
        "disabled": "manual",
        "off": "manual",
        "dry-run": "plan",
        "preview": "plan",
        "setup": "auto",
        "reconcile": "auto",
    }
    return aliases.get(raw_value, raw_value)


def _vm_distributed_running_on_common_services(topology_config):
    topology = dict(topology_config or {})
    target_values = {
        _vm_distributed_config_value(topology, "VM_COMMON_IP"),
        _vm_distributed_config_value(topology, "VM_COMMON_SSH_HOST"),
        _vm_distributed_config_value(topology, "VM_EXTERNAL_IP"),
    }
    target_values = {str(value or "").strip() for value in target_values if str(value or "").strip()}
    aliases = _vm_distributed_host_aliases()
    if any(value.lower() in aliases for value in target_values):
        return True

    local_addresses = _local_host_addresses()
    explicit_target_addresses = {value for value in target_values if _looks_like_ip_address(value)}
    if explicit_target_addresses:
        return bool(local_addresses.intersection(explicit_target_addresses))

    target_addresses = set()
    for value in target_values:
        target_addresses.update(_resolve_host_addresses(value))
    return bool(local_addresses.intersection(target_addresses))


def _vm_distributed_common_vm_direct_ssh_enabled(topology_config):
    return _vm_distributed_config_flag(
        topology_config,
        "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH",
        default=True,
    )


def _normalize_vm_distributed_ssh_access_mode(raw_value):
    mode = str(raw_value or "").strip().lower().replace("_", "-")
    aliases = {
        "jump": "bastion",
        "proxy": "bastion",
        "proxy-jump": "bastion",
        "proxyjump": "bastion",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in {"direct", "bastion"} else ""


def _vm_distributed_effective_ssh_access_mode(topology_config):
    topology = dict(topology_config or {})
    mode = _normalize_vm_distributed_ssh_access_mode(topology.get("SSH_ACCESS_MODE"))
    if (
        _normalized_vm_distributed_execution_host(topology) == "common-services"
        and _vm_distributed_common_vm_direct_ssh_enabled(topology)
        and mode in {"", "bastion"}
    ):
        return "direct"
    return mode


def _vm_distributed_role_key(role_key):
    normalized = str(role_key or "common").strip().lower().replace("-", "_")
    if normalized in {"component", "components"}:
        return "components"
    if normalized in {"provider", "consumer", "common"}:
        return normalized
    return normalized or "common"


def _vm_distributed_role_prefix(role_key):
    role = _vm_distributed_role_key(role_key).upper().replace("-", "_")
    return "COMPONENTS" if role == "COMPONENTS" else role


def _vm_distributed_role_bastion_config(topology_config, role_key=None, identity_file=""):
    topology = dict(topology_config or {})
    role = _vm_distributed_role_prefix(role_key)
    fallback_role = "COMMON" if role == "COMPONENTS" else ""
    keys = [f"VM_{role}_SSH_BASTION_HOST"]
    if fallback_role:
        keys.append(f"VM_{fallback_role}_SSH_BASTION_HOST")
    keys.append("SSH_BASTION_HOST")
    host = _vm_distributed_config_value(topology, *keys)

    port_keys = [f"VM_{role}_SSH_BASTION_PORT"]
    if fallback_role:
        port_keys.append(f"VM_{fallback_role}_SSH_BASTION_PORT")
    port_keys.append("SSH_BASTION_PORT")
    port = _vm_distributed_config_value(topology, *port_keys, default="2222") or "2222"

    user_keys = [f"VM_{role}_SSH_BASTION_USER"]
    if fallback_role:
        user_keys.append(f"VM_{fallback_role}_SSH_BASTION_USER")
    user_keys.append("SSH_BASTION_USER")
    user = _vm_distributed_config_value(topology, *user_keys)

    identity_keys = [f"VM_{role}_SSH_BASTION_IDENTITY_FILE"]
    if fallback_role:
        identity_keys.append(f"VM_{fallback_role}_SSH_BASTION_IDENTITY_FILE")
    identity_keys.append("SSH_BASTION_IDENTITY_FILE")
    identity = _vm_distributed_config_value(topology, *identity_keys) or str(identity_file or "").strip()

    return {
        "host": host,
        "port": port,
        "user": user,
        "identity_file": identity,
    }


def _vm_distributed_role_ssh_access_mode(topology_config, role_key=None):
    topology = dict(topology_config or {})
    role = _vm_distributed_role_prefix(role_key)
    fallback_role = "COMMON" if role == "COMPONENTS" else ""
    role_mode = _normalize_vm_distributed_ssh_access_mode(topology.get(f"VM_{role}_SSH_ACCESS_MODE"))
    if not role_mode and fallback_role:
        role_mode = _normalize_vm_distributed_ssh_access_mode(
            topology.get(f"VM_{fallback_role}_SSH_ACCESS_MODE")
        )
    if role_mode:
        return role_mode

    global_mode = _vm_distributed_effective_ssh_access_mode(topology)
    if global_mode:
        return global_mode

    if _vm_distributed_role_bastion_config(topology, role_key).get("host"):
        return "bastion"
    return ""


def _vm_distributed_effective_ssh_host(topology_config, spec, address):
    topology = dict(topology_config or {})
    configured = _vm_distributed_config_value(topology, spec["ssh_host_key"])
    role_access_mode_key = str(spec.get("ssh_host_key") or "").replace("_SSH_HOST", "_SSH_ACCESS_MODE")
    role_access_mode_configured = bool(str(topology.get(role_access_mode_key) or "").strip())
    if (
        _normalized_vm_distributed_execution_host(topology) == "common-services"
        and _vm_distributed_common_vm_direct_ssh_enabled(topology)
        and not role_access_mode_configured
    ):
        return address or configured
    return configured or address


def _vm_distributed_infer_local_workdir_enabled(topology_config):
    return _vm_distributed_config_flag(
        topology_config,
        "VM_DISTRIBUTED_INFER_LOCAL_WORKDIR",
        default=True,
    )


def _vm_distributed_effective_remote_workdir(topology_config, role_key, *keys, default=""):
    configured = _vm_distributed_config_value(topology_config, *keys, default=default)
    if configured:
        return configured
    if (
        str(role_key or "").strip().lower() == "common"
        and _normalized_vm_distributed_execution_host(topology_config) == "common-services"
        and _vm_distributed_infer_local_workdir_enabled(topology_config)
    ):
        return _framework_root_dir()
    return ""


def _vm_distributed_kubeconfig_auto_localize_enabled(topology_config):
    return _vm_distributed_config_flag(
        topology_config,
        "VM_DISTRIBUTED_KUBECONFIG_AUTO_LOCALIZE",
        default=True,
    )


def _vm_distributed_kubeconfig_dir(topology_config):
    configured = _vm_distributed_config_value(
        topology_config,
        "VM_DISTRIBUTED_KUBECONFIG_DIR",
        default="~/.kube",
    )
    return os.path.abspath(os.path.expanduser(configured))


def _vm_distributed_role_node_name(topology_config, role):
    normalized = str(role or "").strip().upper().replace("-", "_")
    if normalized == "COMPONENTS":
        normalized = "COMMON"
    value = _vm_distributed_config_value(topology_config, f"VM_{normalized}_K8S_NODE")
    if value:
        return value
    if normalized == "COMMON":
        return str(socket.gethostname() or "").strip()
    return ""


def _vm_distributed_unique_paths(paths):
    unique = []
    seen = set()
    for path in paths:
        value = os.path.abspath(os.path.expanduser(str(path or "").strip()))
        if value and value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _vm_distributed_readable_file(path):
    value = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    return bool(value and os.path.isfile(value) and os.access(value, os.R_OK))


def _vm_distributed_kubeconfig_candidates(topology_config, role, configured_path=""):
    topology = dict(topology_config or {})
    normalized_role = str(role or "").strip().lower()
    kubeconfig_dir = _vm_distributed_kubeconfig_dir(topology)
    candidates = []
    if normalized_role in {"common", "components"}:
        candidates.append("/etc/rancher/k3s/k3s.yaml")

    node_name = _vm_distributed_role_node_name(topology, normalized_role)
    if node_name:
        candidates.append(os.path.join(kubeconfig_dir, f"{node_name}.yaml"))

    basename = os.path.basename(os.path.expanduser(str(configured_path or "").strip()))
    if basename and basename not in {"k3s.yaml", "config"}:
        candidates.append(os.path.join(kubeconfig_dir, basename))
    return _vm_distributed_unique_paths(candidates)


def _vm_distributed_effective_kubeconfig_path(topology_config, role, configured_path=""):
    topology = dict(topology_config or {})
    configured = str(configured_path or "").strip()
    expanded = os.path.abspath(os.path.expanduser(configured)) if configured else ""
    if expanded and _vm_distributed_readable_file(expanded):
        return expanded
    if (
        _normalized_vm_distributed_execution_host(topology) != "common-services"
        or not _vm_distributed_kubeconfig_auto_localize_enabled(topology)
    ):
        return expanded or configured

    candidates = _vm_distributed_kubeconfig_candidates(topology, role, configured)
    for candidate in candidates:
        if _vm_distributed_readable_file(candidate):
            return candidate
    if not expanded and candidates:
        return candidates[0]
    if expanded:
        basename = os.path.basename(expanded)
        for candidate in candidates:
            if basename and os.path.basename(candidate) == basename:
                return candidate
    return expanded or (candidates[0] if candidates else "")


def _vm_distributed_kubeconfig_sync_mode(topology_config):
    raw_value = _vm_distributed_config_value(
        topology_config,
        "VM_DISTRIBUTED_KUBECONFIG_SYNC",
        default="auto",
    ).lower().replace("_", "-")
    aliases = {
        "detect": "auto",
        "detected": "auto",
        "1": "enabled",
        "true": "enabled",
        "yes": "enabled",
        "on": "enabled",
        "y": "enabled",
        "s": "enabled",
        "si": "enabled",
        "sí": "enabled",
        "0": "disabled",
        "false": "disabled",
        "no": "disabled",
        "off": "disabled",
        "manual": "disabled",
        "never": "disabled",
    }
    return aliases.get(raw_value, raw_value)


def _vm_distributed_kubeconfig_sync_enabled(topology_config):
    mode = _vm_distributed_kubeconfig_sync_mode(topology_config)
    if mode in {"disabled", "skip"}:
        return False
    if mode == "auto":
        return _normalized_vm_distributed_execution_host(topology_config) == "common-services"
    return True


def _vm_distributed_role_k3s_api_local_port(topology_config, role, configured_path=""):
    normalized = str(role or "common").strip().lower() or "common"
    role_key = "COMMON" if normalized == "components" else normalized.upper().replace("-", "_")
    configured = _vm_distributed_config_value(topology_config, f"VM_{role_key}_K3S_API_LOCAL_PORT")
    if configured and _vm_distributed_valid_port(configured):
        return int(configured)

    effective_path = _vm_distributed_effective_kubeconfig_path(
        topology_config,
        normalized,
        configured_path,
    )
    if _vm_distributed_readable_file(effective_path):
        existing_port = _kubeconfig_loopback_port(_kubeconfig_server(effective_path))
        if existing_port:
            return int(existing_port)

    defaults = {
        "common": 6443,
        "components": 6443,
        "provider": 26443,
        "consumer": 36443,
    }
    return int(defaults.get(normalized, 6443))


def _vm_distributed_remote_k3s_kubeconfig_path(topology_config, role):
    normalized = str(role or "common").strip().upper().replace("-", "_")
    if normalized == "COMPONENTS":
        normalized = "COMMON"
    return _vm_distributed_config_value(
        topology_config,
        f"VM_{normalized}_REMOTE_KUBECONFIG",
        "VM_DISTRIBUTED_REMOTE_KUBECONFIG",
        default="/etc/rancher/k3s/k3s.yaml",
    ) or "/etc/rancher/k3s/k3s.yaml"


def _vm_distributed_materialized_kubeconfig_target(topology_config, role, configured_path=""):
    effective = _vm_distributed_effective_kubeconfig_path(topology_config, role, configured_path)
    if _vm_distributed_readable_file(effective):
        return effective

    configured = str(configured_path or "").strip()
    expanded = os.path.abspath(os.path.expanduser(configured)) if configured else ""
    if effective and effective != expanded and not effective.startswith("/etc/rancher/"):
        return effective
    if expanded and not expanded.startswith("/etc/rancher/"):
        return expanded

    candidates = _vm_distributed_kubeconfig_candidates(topology_config, role, configured)
    non_system_candidates = [
        candidate for candidate in candidates if not str(candidate or "").startswith("/etc/rancher/")
    ]
    if non_system_candidates:
        return non_system_candidates[0]
    if expanded:
        return expanded

    normalized = str(role or "common").strip().lower() or "common"
    node_name = _vm_distributed_role_node_name(topology_config, normalized) or normalized
    return os.path.join(_vm_distributed_kubeconfig_dir(topology_config), f"{node_name}.yaml")


def _render_k3s_kubeconfig_with_server(remote_kubeconfig, server):
    data = yaml.safe_load(remote_kubeconfig) or {}
    clusters = data.get("clusters") or []
    if not clusters:
        raise RuntimeError("The k3s kubeconfig does not contain a cluster entry.")
    server_url = str(server or "").strip()
    if not server_url:
        raise RuntimeError("The target k3s API server URL is empty.")
    for cluster_entry in clusters:
        cluster = cluster_entry.get("cluster") if isinstance(cluster_entry, dict) else None
        if isinstance(cluster, dict):
            cluster["server"] = server_url
    return yaml.safe_dump(data, sort_keys=False)


def _vm_distributed_kubeconfig_read_shell(remote_path):
    remote_path_q = shlex.quote(str(remote_path or "").strip() or "/etc/rancher/k3s/k3s.yaml")
    return "\n".join(
        [
            "set -eu",
            f"if test -r {remote_path_q}; then",
            f"  cat {remote_path_q}",
            f"elif sudo -n test -r {remote_path_q}; then",
            f"  sudo -n cat {remote_path_q}",
            "else",
            f"  echo 'k3s kubeconfig is not readable: {remote_path_q}' >&2",
            "  echo 'Run Level 1 with K3S_WRITE_KUBECONFIG_MODE=0644 or allow non-interactive sudo for this file.' >&2",
            "  exit 65",
            "fi",
        ]
    )


def _vm_distributed_ssh_access_payload(topology_config):
    topology = dict(topology_config or {})
    bastion_host = _vm_distributed_config_value(topology, "SSH_BASTION_HOST")
    mode = _vm_distributed_effective_ssh_access_mode(topology)
    if not mode:
        mode = "bastion" if bastion_host else "direct"
    return {
        "mode": mode,
        "connect_timeout_seconds": _vm_distributed_connect_timeout_seconds(topology),
        "known_hosts_strategy": _vm_distributed_config_value(
            topology,
            "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY",
            default="accept-new",
        ) or "accept-new",
        "bastion": {
            "host": bastion_host,
            "port": _vm_distributed_config_value(topology, "SSH_BASTION_PORT", default="2222") or "2222",
            "user": _vm_distributed_config_value(topology, "SSH_BASTION_USER"),
            "identity_file": _vm_distributed_config_value(topology, "SSH_BASTION_IDENTITY_FILE")
            or _vm_distributed_identity_file(topology),
        },
    }


def _vm_distributed_role_ssh_payload(topology_config, role):
    ssh = _vm_distributed_role_ssh_config(topology_config, role)
    return {
        "role": role,
        "role_key": str(role or "").strip().lower() or "common",
        "ssh": {
            "host": ssh.get("host") or "",
            "port": ssh.get("port") or "22",
            "user": ssh.get("user") or "",
            "identity_file": ssh.get("identity_file") or "",
            "access_mode": ssh.get("access_mode") or "",
            "bastion": dict(ssh.get("bastion") or {}),
        },
    }


def _vm_distributed_fetch_remote_k3s_kubeconfig(topology_config, role, command_runner=None):
    remote_path = _vm_distributed_remote_k3s_kubeconfig_path(topology_config, role)
    remote_shell = _vm_distributed_kubeconfig_read_shell(remote_path)
    access = _vm_distributed_ssh_access_payload(topology_config)
    vm = _vm_distributed_role_ssh_payload(topology_config, role)
    command = _vm_distributed_build_ssh_command({"ssh": access}, vm, remote_command=remote_shell)
    if not command:
        raise RuntimeError(f"Cannot fetch the {role} k3s kubeconfig because SSH is not configured.")

    runner = command_runner or subprocess.run
    try:
        completed = runner(command, capture_output=True, text=True, check=False)
    except TypeError:
        completed = runner(command)
    returncode = int(getattr(completed, "returncode", 1) or 0)
    if returncode != 0:
        detail = (getattr(completed, "stderr", "") or "").strip()
        public_command = _vm_distributed_format_command(_vm_distributed_public_ssh_command(command))
        raise RuntimeError(
            f"Could not fetch the {role} k3s kubeconfig from {remote_path}. "
            f"{detail or 'Remote command failed.'} Command: {public_command}"
        )
    return getattr(completed, "stdout", "") or ""


def _vm_distributed_role_is_local_to_common_services(topology_config, role):
    normalized = str(role or "common").strip().lower() or "common"
    if normalized == "common":
        return True
    if normalized != "components":
        return False
    common_address = _vm_distributed_config_value(topology_config, "VM_COMMON_IP", "VM_EXTERNAL_IP")
    components_address = _vm_distributed_config_value(topology_config, "VM_COMPONENTS_IP", default=common_address)
    return bool(common_address and components_address and common_address == components_address)


def _vm_distributed_read_k3s_kubeconfig_source(topology_config, role, command_runner=None):
    execution_host = _normalized_vm_distributed_execution_host(topology_config)
    normalized = str(role or "common").strip().lower() or "common"
    if (
        execution_host == "common-services"
        and _vm_distributed_role_is_local_to_common_services(topology_config, normalized)
    ):
        remote_path = _vm_distributed_remote_k3s_kubeconfig_path(topology_config, normalized)
        command = ["sh", "-lc", _vm_distributed_kubeconfig_read_shell(remote_path)]
        runner = command_runner or subprocess.run
        try:
            completed = runner(command, capture_output=True, text=True, check=False)
        except TypeError:
            completed = runner(command)
        returncode = int(getattr(completed, "returncode", 1) or 0)
        if returncode != 0:
            detail = (getattr(completed, "stderr", "") or "").strip()
            raise RuntimeError(
                f"Could not read the local {normalized} k3s kubeconfig from {remote_path}. "
                f"{detail or 'Local command failed.'}"
            )
        return getattr(completed, "stdout", "") or ""
    return _vm_distributed_fetch_remote_k3s_kubeconfig(
        topology_config,
        normalized,
        command_runner=command_runner,
    )


def _write_vm_distributed_local_kubeconfig(path, content):
    target = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not target:
        raise RuntimeError("The target kubeconfig path is empty.")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(target, 0o600)
    return target


def _vm_distributed_level_kubeconfig_roles(level=None):
    try:
        level_id = int(level)
    except (TypeError, ValueError):
        level_id = 0
    if level_id in {1, 2, 3}:
        return ("common",)
    if level_id == 4:
        return ("common", "provider", "consumer")
    if level_id == 5:
        return ("common", "components")
    if level_id == 6:
        return ("common", "provider", "consumer", "components")
    return ("common", "provider", "consumer", "components")


def _ensure_vm_distributed_local_kubeconfigs(topology_config=None, roles=None, command_runner=None):
    config = dict(topology_config or _load_effective_infrastructure_deployer_config(topology="vm-distributed"))
    runtime = build_cluster_runtime(config, topology="vm-distributed")
    if runtime.get("cluster_type") != "k3s":
        return {"status": "skipped", "reason": "non-k3s-runtime", "items": []}
    if not _vm_distributed_kubeconfig_sync_enabled(config):
        return {
            "status": "skipped",
            "reason": "kubeconfig-sync-disabled",
            "mode": _vm_distributed_kubeconfig_sync_mode(config),
            "items": [],
        }

    configured_paths = _configured_vm_distributed_role_kubeconfigs_from_config(config)
    requested_roles = tuple(roles or ("common", "provider", "consumer", "components"))
    items = []
    seen_targets = set()
    for role in requested_roles:
        normalized = str(role or "").strip().lower() or "common"
        configured_path = configured_paths.get(normalized) or ""
        target_path = _vm_distributed_materialized_kubeconfig_target(
            config,
            normalized,
            configured_path,
        )
        if not target_path:
            items.append({"role": normalized, "status": "skipped", "reason": "empty-target"})
            continue
        if _vm_distributed_readable_file(target_path):
            items.append({"role": normalized, "status": "ready", "path": target_path})
            seen_targets.add(target_path)
            continue
        if target_path in seen_targets and _vm_distributed_readable_file(target_path):
            items.append({"role": normalized, "status": "ready", "path": target_path})
            continue

        try:
            local_port = _vm_distributed_role_k3s_api_local_port(config, normalized, configured_path)
            source = _vm_distributed_read_k3s_kubeconfig_source(
                config,
                normalized,
                command_runner=command_runner,
            )
            rendered = _render_k3s_kubeconfig_with_server(
                source,
                f"https://127.0.0.1:{int(local_port)}",
            )
            written_path = _write_vm_distributed_local_kubeconfig(target_path, rendered)
            items.append(
                {
                    "role": normalized,
                    "status": "written",
                    "path": written_path,
                    "server": f"https://127.0.0.1:{int(local_port)}",
                }
            )
            seen_targets.add(written_path)
        except Exception as exc:
            items.append(
                {
                    "role": normalized,
                    "status": "failed",
                    "path": target_path,
                    "error": str(exc),
                }
            )

    failed = [item for item in items if item.get("status") == "failed"]
    written = [item for item in items if item.get("status") == "written"]
    if failed:
        status = "failed"
    elif written:
        status = "updated"
    else:
        status = "ready"
    return {
        "status": status,
        "mode": _vm_distributed_kubeconfig_sync_mode(config),
        "execution_host": _normalized_vm_distributed_execution_host(config),
        "items": items,
    }


def _raise_vm_distributed_kubeconfig_sync_failure(result):
    failed = [item for item in list((result or {}).get("items") or []) if item.get("status") == "failed"]
    if not failed:
        return
    details = []
    for item in failed:
        details.append(
            f"{item.get('role') or 'unknown'}: {item.get('path') or '(empty)'}: "
            f"{item.get('error') or 'unknown error'}"
        )
    raise RuntimeError(
        "vm-distributed could not prepare the required local k3s kubeconfig files automatically. "
        + " ".join(details)
    )


def _print_vm_distributed_kubeconfig_sync_result(result):
    status = str((result or {}).get("status") or "unknown")
    if status == "skipped":
        print(
            "vm-distributed kubeconfig sync skipped: "
            f"{(result or {}).get('reason') or 'not required'}."
        )
        return
    print(f"vm-distributed kubeconfig sync: {status}")
    for item in list((result or {}).get("items") or []):
        item_status = item.get("status") or "unknown"
        role = item.get("role") or "unknown"
        path = item.get("path") or ""
        suffix = f" -> {path}" if path else ""
        if item_status == "failed":
            print(f"  - {role}: failed{suffix}: {item.get('error') or 'unknown error'}")
        elif item_status == "written":
            print(f"  - {role}: written{suffix}")
        elif item_status == "ready":
            print(f"  - {role}: ready{suffix}")
        else:
            print(f"  - {role}: {item_status}{suffix}")


def _vm_distributed_http_preflight_tls_verify_mode(config_or_plan):
    http_preflight = dict((config_or_plan or {}).get("http_preflight") or {})
    raw_value = str(
        http_preflight.get("tls_verify")
        or (config_or_plan or {}).get("VM_DISTRIBUTED_HTTP_PREFLIGHT_TLS_VERIFY")
        or "auto"
    ).strip().lower()
    aliases = {
        "1": "true",
        "yes": "true",
        "on": "true",
        "0": "false",
        "no": "false",
        "off": "false",
        "detect": "auto",
    }
    mode = aliases.get(raw_value, raw_value)
    return mode if mode in {"auto", "true", "false"} else "auto"


def _normalized_vm_distributed_ssh_bootstrap_mode(topology_config):
    raw_value = _vm_distributed_config_value(
        topology_config,
        "VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE",
        default="manual",
    ).lower().replace("_", "-")
    aliases = {
        "disabled": "manual",
        "off": "manual",
        "dry-run": "plan",
        "preview": "plan",
        "setup": "auto",
        "reconcile": "auto",
    }
    return aliases.get(raw_value, raw_value)


def _vm_distributed_ssh_target(user, host):
    normalized_host = str(host or "").strip()
    normalized_user = str(user or "").strip()
    if normalized_user and normalized_host:
        return f"{normalized_user}@{normalized_host}"
    return normalized_host


def _vm_distributed_format_command(command):
    return " ".join(shlex.quote(str(part)) for part in list(command or []))


def _vm_distributed_local_path_for_shell(path):
    value = str(path or "").strip()
    if not value:
        return ""
    return os.path.abspath(os.path.expanduser(value))


def _vm_distributed_build_ssh_command(plan, vm, remote_command=None):
    ssh = dict((vm or {}).get("ssh") or {})
    host = str(ssh.get("host") or "").strip()
    if not host:
        return []

    access = dict((plan or {}).get("ssh") or {})
    timeout = int(access.get("connect_timeout_seconds") or 5)
    known_hosts_strategy = str(access.get("known_hosts_strategy") or "accept-new").strip() or "accept-new"
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        f"StrictHostKeyChecking={known_hosts_strategy}",
        "-p",
        str(ssh.get("port") or "22").strip() or "22",
    ]

    identity_file = _vm_distributed_local_path_for_shell(ssh.get("identity_file"))
    if identity_file:
        command.extend(["-i", identity_file])

    access_mode = str(ssh.get("access_mode") or access.get("mode") or "").strip().lower().replace("_", "-")
    bastion = dict(ssh.get("bastion") or access.get("bastion") or {})
    if access_mode == "bastion" and bastion.get("host"):
        bastion_target = _vm_distributed_ssh_target(bastion.get("user"), bastion.get("host"))
        bastion_port = str(bastion.get("port") or "").strip()
        bastion_identity_file = _vm_distributed_local_path_for_shell(bastion.get("identity_file"))
        if bastion_identity_file:
            proxy_command = [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={timeout}",
                "-o",
                f"StrictHostKeyChecking={known_hosts_strategy}",
            ]
            if bastion_port:
                proxy_command.extend(["-p", bastion_port])
            proxy_command.extend(["-i", bastion_identity_file, "-W", "%h:%p", bastion_target])
            command.extend(["-o", f"ProxyCommand={_vm_distributed_format_command(proxy_command)}"])
        else:
            if bastion_port:
                bastion_target = f"{bastion_target}:{bastion_port}"
            command.extend(["-J", bastion_target])

    command.append(_vm_distributed_ssh_target(ssh.get("user"), host))
    if remote_command:
        command.append(_vm_distributed_format_command(["sh", "-lc", remote_command]))
    return command


def _vm_distributed_public_ssh_command(command):
    items = list(command or [])
    if items and str(items[-1]).startswith("sh -lc "):
        return items[:-1]
    if "sh" in items:
        return items[: items.index("sh")]
    return items


def _vm_distributed_role_plan_specs(topology_config):
    topology = dict(topology_config or {})
    shared_workdir = _vm_distributed_config_value(topology, "VM_REMOTE_WORKDIR")
    return [
        {
            "role": "common-services",
            "role_key": "common",
            "address_key": "VM_COMMON_IP",
            "fallback_address_key": "VM_EXTERNAL_IP",
            "ssh_host_key": "VM_COMMON_SSH_HOST",
            "ssh_port_key": "VM_COMMON_SSH_PORT",
            "ssh_user_key": "VM_COMMON_SSH_USER",
            "workdir_key": "VM_COMMON_REMOTE_WORKDIR",
            "public_url_key": "VM_COMMON_PUBLIC_URL",
            "http_url_key": "VM_COMMON_HTTP_URL",
            "default_workdir": shared_workdir,
            "levels": [1, 2, 3],
        },
        {
            "role": "provider-connectors",
            "role_key": "provider",
            "address_key": "VM_PROVIDER_IP",
            "fallback_address_key": "VM_CONNECTORS_IP",
            "ssh_host_key": "VM_PROVIDER_SSH_HOST",
            "ssh_port_key": "VM_PROVIDER_SSH_PORT",
            "ssh_user_key": "VM_PROVIDER_SSH_USER",
            "workdir_key": "VM_PROVIDER_REMOTE_WORKDIR",
            "public_url_key": "VM_PROVIDER_PUBLIC_URL",
            "http_url_key": "VM_PROVIDER_HTTP_URL",
            "default_workdir": shared_workdir,
            "levels": [4],
        },
        {
            "role": "consumer-connectors",
            "role_key": "consumer",
            "address_key": "VM_CONSUMER_IP",
            "fallback_address_key": "VM_CONNECTORS_IP",
            "ssh_host_key": "VM_CONSUMER_SSH_HOST",
            "ssh_port_key": "VM_CONSUMER_SSH_PORT",
            "ssh_user_key": "VM_CONSUMER_SSH_USER",
            "workdir_key": "VM_CONSUMER_REMOTE_WORKDIR",
            "public_url_key": "VM_CONSUMER_PUBLIC_URL",
            "http_url_key": "VM_CONSUMER_HTTP_URL",
            "default_workdir": shared_workdir,
            "levels": [4],
        },
    ]


def _vm_distributed_connector_plan(adapter_config):
    adapter = dict(adapter_config or {})
    dataspace_name = str(adapter.get("DS_1_NAME") or "").strip()
    connectors = parse_connector_list(adapter.get("DS_1_CONNECTORS"), dataspace_name)
    mapping = parse_connector_mapping(adapter.get("DS_1_CONNECTOR_NAMESPACES"), dataspace_name)
    return [
        {
            "connector": connector,
            "location": str(mapping.get(connector) or "dataspace").strip() or "dataspace",
        }
        for connector in connectors
    ]


def _build_vm_distributed_ssh_bootstrap_plan(infrastructure_config, topology_config, adapter_config):
    topology = dict(topology_config or {})
    adapter = dict(adapter_config or {})
    execution_host = _normalized_vm_distributed_execution_host(topology)
    bootstrap_mode = _normalized_vm_distributed_ssh_bootstrap_mode(topology)
    identity_file = _vm_distributed_identity_file(topology)
    key_comment = _vm_distributed_config_value(
        topology,
        "VM_DISTRIBUTED_SSH_KEY_COMMENT",
        default="validation-environment-vm-distributed",
    )
    marker = _vm_distributed_config_value(
        topology,
        "VM_DISTRIBUTED_SSH_MANAGED_MARKER",
        default="validation-environment-vm-distributed",
    )
    remote_workdir = _vm_distributed_effective_remote_workdir(
        topology,
        "common",
        "VM_COMMON_REMOTE_WORKDIR",
        "VM_REMOTE_WORKDIR",
    )

    target_roles = []
    for spec in _vm_distributed_role_plan_specs(topology):
        role_key = spec["role_key"]
        address = _vm_distributed_config_value(
            topology,
            spec["address_key"],
            spec["fallback_address_key"],
            "VM_EXTERNAL_IP",
        )
        ssh_host = _vm_distributed_effective_ssh_host(topology, spec, address)
        ssh_user = _vm_distributed_config_value(topology, spec["ssh_user_key"], "VM_SSH_USER")
        target_identity = _vm_distributed_identity_file(topology, role_key) or identity_file
        target_access_mode = _vm_distributed_role_ssh_access_mode(topology, role_key)
        target_roles.append(
            {
                "role": spec["role"],
                "role_key": role_key,
                "host": ssh_host,
                "user": ssh_user,
                "port": _vm_distributed_config_value(topology, spec["ssh_port_key"], default="22") or "22",
                "identity_file": target_identity,
                "access_mode": target_access_mode,
                "bastion": _vm_distributed_role_bastion_config(
                    topology,
                    role_key,
                    identity_file=target_identity,
                ),
                "needs_public_key": bool(ssh_host and ssh_user),
            }
        )

    actions = [
        {
            "name": "ensure_dedicated_keypair",
            "status": "planned" if identity_file else "needs-configuration",
            "idempotent_check": "create the key only when the private or public key is missing",
        },
        {
            "name": "install_public_key_on_target_vms",
            "status": "planned" if identity_file and any(item["needs_public_key"] for item in target_roles) else "needs-configuration",
            "idempotent_check": "append the public key only when the managed marker is absent",
        },
        {
            "name": "verify_batchmode_ssh",
            "status": "planned",
            "idempotent_check": "run ssh -o BatchMode=yes against each configured VM",
        },
    ]
    if execution_host == "common-services":
        actions.append(
            {
                "name": "prepare_common_services_execution_host",
                "status": "planned" if remote_workdir else "needs-configuration",
                "idempotent_check": "reuse or synchronize the framework workspace before running levels",
            }
        )

    warnings = []
    if bootstrap_mode not in {"manual", "plan", "auto"}:
        warnings.append("VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE should be manual, plan or auto.")
    if execution_host not in {"external", "common-services"}:
        warnings.append("VM_DISTRIBUTED_EXECUTION_HOST should be external or common-services.")
    if bootstrap_mode in {"plan", "auto"} and not identity_file:
        warnings.append("A dedicated SSH identity file is required for automated SSH bootstrap.")
    if execution_host == "common-services" and not remote_workdir:
        warnings.append("VM_COMMON_REMOTE_WORKDIR or VM_REMOTE_WORKDIR is required when executing from common-services.")

    return {
        "status": "ready" if not warnings else "needs-review",
        "mode": bootstrap_mode,
        "execution_host": execution_host,
        "identity_file": identity_file,
        "key_comment": key_comment,
        "managed_marker": marker,
        "remote_workdir": remote_workdir,
        "dataspace": str(adapter.get("DS_1_NAME") or "").strip(),
        "targets": target_roles,
        "actions": actions,
        "warnings": warnings,
        "security": [
            "private keys are never written to versioned files",
            "only public keys are installed on target VMs",
            "BatchMode=yes is used for verification",
            "managed authorized_keys entries must carry a marker for idempotent updates",
        ],
    }


def _vm_distributed_public_key_path(identity_file):
    value = str(identity_file or "").strip()
    return f"{value}.pub" if value else ""


def _vm_distributed_manual_command(name, command, note=""):
    item = {
        "name": name,
        "command": command,
    }
    if note:
        item["note"] = note
    return item


def _vm_distributed_manual_ssh_bootstrap_commands(plan):
    vm_plan = dict(plan or {})
    ssh_bootstrap = dict(vm_plan.get("ssh_bootstrap") or {})
    identity_file = str(ssh_bootstrap.get("identity_file") or "").strip()
    if not identity_file:
        return []

    local_identity_file = _vm_distributed_local_path_for_shell(identity_file)
    public_key_file = _vm_distributed_public_key_path(local_identity_file)
    key_comment = str(ssh_bootstrap.get("key_comment") or "validation-environment-vm-distributed").strip()
    access = dict(vm_plan.get("ssh") or {})
    bastion = dict(access.get("bastion") or {})

    commands = []
    bastion_entries = []

    def add_bastion_entry(name, value):
        item = dict(value or {})
        host = str(item.get("host") or "").strip()
        user = str(item.get("user") or "").strip()
        port = str(item.get("port") or "").strip()
        target = _vm_distributed_ssh_target(user, host)
        if not host or not target:
            return
        key = (target, port)
        if any(existing["key"] == key for existing in bastion_entries):
            return
        bastion_entries.append(
            {
                "key": key,
                "name": name,
                "host": host,
                "port": port,
                "target": target,
                "target_with_port": f"{target}:{port}" if port else target,
            }
        )

    if access.get("mode") == "bastion":
        add_bastion_entry("global", bastion)
    for target in list(ssh_bootstrap.get("targets") or []):
        if (target.get("access_mode") or access.get("mode")) == "bastion":
            add_bastion_entry(target.get("role_key") or target.get("role") or "target", target.get("bastion") or bastion)

    for bastion_entry in bastion_entries:
        bastion_host = bastion_entry["host"]
        bastion_port = bastion_entry["port"]
        bastion_label = "" if bastion_entry["name"] == "global" else f"{bastion_entry['name']}_"
        commands.append(
            _vm_distributed_manual_command(
                f"check_{bastion_label}bastion_dns",
                _vm_distributed_format_command(["getent", "hosts", bastion_host]),
            )
        )
        if bastion_port:
            commands.append(
                _vm_distributed_manual_command(
                    f"check_{bastion_label}bastion_port",
                    _vm_distributed_format_command(["nc", "-vz", bastion_host, bastion_port]),
                )
            )

    keygen = _vm_distributed_format_command(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            local_identity_file,
            "-C",
            key_comment,
            "-N",
            "",
        ]
    )
    commands.append(
        _vm_distributed_manual_command(
            "create_dedicated_key_if_missing",
            f"test -f {shlex.quote(local_identity_file)} || {keygen}",
            "Does not overwrite an existing key.",
        )
    )
    commands.extend(
        [
            _vm_distributed_manual_command("secure_ssh_directory", "chmod 700 ~/.ssh"),
            _vm_distributed_manual_command(
                "secure_private_key",
                _vm_distributed_format_command(["chmod", "600", local_identity_file]),
            ),
            _vm_distributed_manual_command(
                "secure_public_key",
                _vm_distributed_format_command(["chmod", "644", public_key_file]),
            ),
        ]
    )

    for bastion_entry in bastion_entries:
        bastion_label = "" if bastion_entry["name"] == "global" else f"{bastion_entry['name']}_"
        copy_id = ["ssh-copy-id", "-i", public_key_file]
        if bastion_entry["port"]:
            copy_id.extend(["-p", bastion_entry["port"]])
        copy_id.append(bastion_entry["target"])
        commands.append(
            _vm_distributed_manual_command(
                f"install_public_key_on_{bastion_label}bastion",
                _vm_distributed_format_command(copy_id),
                "May ask for the approved SSH user password; the framework does not store it.",
            )
        )

    for target in list(ssh_bootstrap.get("targets") or []):
        target_host = str(target.get("host") or "").strip()
        target_user = str(target.get("user") or "").strip()
        if not target_host or not target_user:
            continue
        copy_id = ["ssh-copy-id", "-i", public_key_file]
        target_port = str(target.get("port") or "").strip()
        if target_port and target_port != "22":
            copy_id.extend(["-p", target_port])
        target_mode = target.get("access_mode") or access.get("mode")
        target_bastion = dict(target.get("bastion") or bastion)
        target_bastion_target = _vm_distributed_ssh_target(
            target_bastion.get("user"),
            target_bastion.get("host"),
        )
        target_bastion_port = str(target_bastion.get("port") or "").strip()
        if target_bastion_target and target_bastion_port:
            target_bastion_target = f"{target_bastion_target}:{target_bastion_port}"
        if target_mode == "bastion" and target_bastion_target:
            copy_id.extend(["-o", f"ProxyJump={target_bastion_target}"])
        copy_id.append(_vm_distributed_ssh_target(target_user, target_host))
        commands.append(
            _vm_distributed_manual_command(
                f"install_public_key_on_{target.get('role_key') or target.get('role')}",
                _vm_distributed_format_command(copy_id),
                "May ask for the target VM password; the operation is idempotent.",
            )
        )

    for bastion_entry in bastion_entries:
        bastion_label = "" if bastion_entry["name"] == "global" else f"{bastion_entry['name']}_"
        verify_bastion = ["ssh", "-o", "BatchMode=yes", "-i", local_identity_file]
        if bastion_entry["port"]:
            verify_bastion.extend(["-p", bastion_entry["port"]])
        verify_bastion.extend([bastion_entry["target"], "hostname"])
        commands.append(
            _vm_distributed_manual_command(
                f"verify_{bastion_label}bastion_batchmode",
                _vm_distributed_format_command(verify_bastion),
            )
        )

    for target in list(ssh_bootstrap.get("targets") or []):
        target_vm = _vm_distributed_target_vm_from_bootstrap_target(vm_plan, target)
        command = _vm_distributed_build_ssh_command(vm_plan, target_vm, remote_command="hostname")
        if command:
            commands.append(
                _vm_distributed_manual_command(
                    f"verify_{target.get('role_key') or target.get('role')}_batchmode",
                    _vm_distributed_format_command(command),
                )
            )
    return commands


def _vm_distributed_ensure_ssh_keypair(ssh_bootstrap, command_runner=None):
    bootstrap = dict(ssh_bootstrap or {})
    identity_file = str(bootstrap.get("identity_file") or "").strip()
    if not identity_file:
        return {
            "status": "failed",
            "reason": "missing-identity-file",
            "message": "SSH_IDENTITY_FILE or VM_DISTRIBUTED_SSH_IDENTITY_FILE is required.",
        }

    private_key = os.path.abspath(os.path.expanduser(identity_file))
    public_key = _vm_distributed_public_key_path(private_key)
    key_comment = str(bootstrap.get("key_comment") or "validation-environment-vm-distributed").strip()
    runner = command_runner or _vm_distributed_default_command_runner

    if os.path.isfile(private_key) and os.path.isfile(public_key):
        try:
            os.chmod(private_key, 0o600)
        except OSError:
            pass
        return {
            "status": "present",
            "identity_file": private_key,
            "public_key_file": public_key,
            "changed": False,
        }

    if os.path.isfile(public_key) and not os.path.isfile(private_key):
        return {
            "status": "failed",
            "reason": "public-key-without-private-key",
            "identity_file": private_key,
            "public_key_file": public_key,
        }

    os.makedirs(os.path.dirname(private_key) or ".", mode=0o700, exist_ok=True)
    if not os.path.isfile(private_key):
        command = [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            private_key,
            "-C",
            key_comment,
            "-N",
            "",
        ]
        completed = runner(command, timeout=30)
        if int(getattr(completed, "returncode", 1) or 0) != 0:
            return {
                "status": "failed",
                "reason": "ssh-keygen-failed",
                "identity_file": private_key,
                "command": _vm_distributed_format_command(command[:-2] + ["-N", "***"]),
                "error": str(getattr(completed, "stderr", "") or "").strip()[:500],
            }
        try:
            os.chmod(private_key, 0o600)
        except OSError:
            pass
        return {
            "status": "created",
            "identity_file": private_key,
            "public_key_file": public_key,
            "changed": True,
        }

    command = ["ssh-keygen", "-y", "-f", private_key]
    completed = runner(command, timeout=30)
    if int(getattr(completed, "returncode", 1) or 0) != 0:
        return {
            "status": "failed",
            "reason": "public-key-derivation-failed",
            "identity_file": private_key,
            "error": str(getattr(completed, "stderr", "") or "").strip()[:500],
        }
    public_value = str(getattr(completed, "stdout", "") or "").strip()
    if not public_value:
        return {
            "status": "failed",
            "reason": "empty-derived-public-key",
            "identity_file": private_key,
        }
    with open(public_key, "w", encoding="utf-8") as handle:
        handle.write(f"{public_value}\n")
    try:
        os.chmod(private_key, 0o600)
        os.chmod(public_key, 0o644)
    except OSError:
        pass
    return {
        "status": "derived-public-key",
        "identity_file": private_key,
        "public_key_file": public_key,
        "changed": True,
    }


def _vm_distributed_read_public_key(public_key_file):
    path = str(public_key_file or "").strip()
    if not path or not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def _vm_distributed_authorized_keys_script(public_key, marker):
    safe_public_key = shlex.quote(str(public_key or "").strip())
    safe_marker = shlex.quote(str(marker or "validation-environment-vm-distributed").strip())
    return "\n".join(
        [
            "set -eu",
            "mkdir -p \"$HOME/.ssh\"",
            "chmod 700 \"$HOME/.ssh\"",
            "touch \"$HOME/.ssh/authorized_keys\"",
            "chmod 600 \"$HOME/.ssh/authorized_keys\"",
            f"public_key={safe_public_key}",
            f"marker={safe_marker}",
            "if grep -F -- \"$public_key\" \"$HOME/.ssh/authorized_keys\" >/dev/null 2>&1; then",
            "  status=present",
            "else",
            "  printf '%s # %s\\n' \"$public_key\" \"$marker\" >> \"$HOME/.ssh/authorized_keys\"",
            "  status=installed",
            "fi",
            "printf 'authorized_keys=%s\\n' \"$status\"",
        ]
    )


def _vm_distributed_target_vm_from_bootstrap_target(plan, target):
    item = dict(target or {})
    return {
        "role": item.get("role"),
        "ssh": {
            "configured": bool(item.get("host")),
            "host": item.get("host"),
            "port": item.get("port") or "22",
            "user": item.get("user"),
            "identity_file": item.get("identity_file"),
            "access_mode": item.get("access_mode"),
            "bastion": dict(item.get("bastion") or {}),
        },
    }


def _vm_distributed_sync_authorized_key(plan, target, public_key, marker, command_runner=None):
    runner = command_runner or _vm_distributed_default_command_runner
    target_vm = _vm_distributed_target_vm_from_bootstrap_target(plan, target)
    command = _vm_distributed_build_ssh_command(
        plan,
        target_vm,
        remote_command=_vm_distributed_authorized_keys_script(public_key, marker),
    )
    if not command:
        return {
            "role": target.get("role"),
            "status": "skipped",
            "reason": "missing-ssh-target",
        }

    completed = runner(command, timeout=int((plan.get("ssh") or {}).get("connect_timeout_seconds") or 5) + 20)
    returncode = int(getattr(completed, "returncode", 1) or 0)
    facts = _vm_distributed_parse_key_value_output(getattr(completed, "stdout", "") or "")
    status_value = facts.get("authorized_keys")
    if returncode == 0 and status_value in {"present", "installed"}:
        return {
            "role": target.get("role"),
            "host": target.get("host"),
            "status": "synced",
            "state": status_value,
            "changed": status_value == "installed",
            "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
        }
    return {
        "role": target.get("role"),
        "host": target.get("host"),
        "status": "failed",
        "reason": "authorized-keys-sync-failed",
        "returncode": returncode,
        "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
        "error": str(getattr(completed, "stderr", "") or "").strip()[:500],
        "next_step": "Install the dedicated public key once with an approved access path, then rerun ssh-access reconcile.",
    }


def _vm_distributed_verify_ssh_target(plan, target, command_runner=None):
    runner = command_runner or _vm_distributed_default_command_runner
    target_vm = _vm_distributed_target_vm_from_bootstrap_target(plan, target)
    command = _vm_distributed_build_ssh_command(
        plan,
        target_vm,
        remote_command="printf 'ssh_ready=1\\n'",
    )
    if not command:
        return {
            "role": target.get("role"),
            "status": "skipped",
            "reason": "missing-ssh-target",
        }

    completed = runner(command, timeout=int((plan.get("ssh") or {}).get("connect_timeout_seconds") or 5) + 20)
    returncode = int(getattr(completed, "returncode", 1) or 0)
    facts = _vm_distributed_parse_key_value_output(getattr(completed, "stdout", "") or "")
    if returncode == 0 and facts.get("ssh_ready") == "1":
        return {
            "role": target.get("role"),
            "host": target.get("host"),
            "status": "passed",
            "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
        }
    return {
        "role": target.get("role"),
        "host": target.get("host"),
        "status": "failed",
        "reason": "batchmode-ssh-failed",
        "returncode": returncode,
        "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
        "error": str(getattr(completed, "stderr", "") or "").strip()[:500],
    }


def _reconcile_vm_distributed_ssh_access(plan, command_runner=None):
    vm_plan = dict(plan or {})
    ssh_bootstrap = dict(vm_plan.get("ssh_bootstrap") or {})
    manual_bootstrap_commands = _vm_distributed_manual_ssh_bootstrap_commands(vm_plan)
    execution_location = _vm_distributed_ssh_access_execution_location(vm_plan)
    if ssh_bootstrap.get("status") == "needs-review":
        return {
            "status": "needs-review",
            "message": "SSH bootstrap plan needs review before reconciliation.",
            "execution_host": vm_plan.get("execution_host"),
            "ssh_bootstrap": ssh_bootstrap,
            "execution_location": execution_location,
            "manual_bootstrap_commands": manual_bootstrap_commands,
        }

    keypair = _vm_distributed_ensure_ssh_keypair(ssh_bootstrap, command_runner=command_runner)
    if keypair.get("status") == "failed":
        return {
            "status": "failed",
            "message": "Dedicated SSH keypair could not be prepared.",
            "execution_host": vm_plan.get("execution_host"),
            "keypair": keypair,
            "ssh_bootstrap": ssh_bootstrap,
            "execution_location": execution_location,
            "manual_bootstrap_commands": manual_bootstrap_commands,
        }

    public_key = _vm_distributed_read_public_key(keypair.get("public_key_file"))
    if not public_key:
        return {
            "status": "failed",
            "message": "Dedicated SSH public key could not be read.",
            "execution_host": vm_plan.get("execution_host"),
            "keypair": keypair,
            "ssh_bootstrap": ssh_bootstrap,
            "execution_location": execution_location,
            "manual_bootstrap_commands": manual_bootstrap_commands,
        }

    marker = str(ssh_bootstrap.get("managed_marker") or "validation-environment-vm-distributed").strip()
    targets = [item for item in list(ssh_bootstrap.get("targets") or []) if item.get("needs_public_key")]
    install_results = [
        _vm_distributed_sync_authorized_key(vm_plan, target, public_key, marker, command_runner=command_runner)
        for target in targets
    ]
    if any(item.get("status") == "failed" for item in install_results):
        return {
            "status": "failed",
            "message": "Dedicated SSH public key could not be installed on every target VM.",
            "execution_host": vm_plan.get("execution_host"),
            "keypair": keypair,
            "authorized_keys": install_results,
            "ssh_bootstrap": ssh_bootstrap,
            "execution_location": execution_location,
            "manual_bootstrap_commands": manual_bootstrap_commands,
        }

    verify_results = [
        _vm_distributed_verify_ssh_target(vm_plan, target, command_runner=command_runner)
        for target in targets
    ]
    failed_verifications = [item for item in verify_results if item.get("status") == "failed"]
    if failed_verifications:
        status = "failed"
        message = "BatchMode SSH verification failed for one or more target VMs."
    elif targets:
        status = "synced"
        message = "Dedicated SSH access is reconciled and verified."
    else:
        status = "needs-review"
        message = "No SSH targets were configured for reconciliation."

    return {
        "status": status,
        "message": message,
        "execution_host": vm_plan.get("execution_host"),
        "keypair": keypair,
        "authorized_keys": install_results,
        "verification": verify_results,
        "ssh_bootstrap": ssh_bootstrap,
        "execution_location": execution_location,
        "manual_bootstrap_commands": manual_bootstrap_commands,
    }


def _build_vm_distributed_topology_plan(infrastructure_config, topology_config, adapter_config):
    topology = dict(topology_config or {})
    infra = _effective_topology_scoped_infrastructure_config(
        infrastructure_config,
        topology,
        topology="vm-distributed",
    )
    adapter = dict(adapter_config or {})
    preflight = _vm_distributed_configuration_preflight(infra, topology, adapter)
    ssh_bootstrap = _build_vm_distributed_ssh_bootstrap_plan(infra, topology, adapter)
    mode = _vm_distributed_effective_ssh_access_mode(topology)
    timeout = _vm_distributed_connect_timeout_seconds(topology)
    access = {
        "mode": mode or "not-configured",
        "connect_timeout_seconds": timeout,
        "identity_file": _vm_distributed_identity_file(topology),
        "known_hosts_strategy": _vm_distributed_config_value(
            topology,
            "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY",
            default="accept-new",
        ),
        "bastion": {
            "host": str(topology.get("SSH_BASTION_HOST") or "").strip(),
            "port": str(topology.get("SSH_BASTION_PORT") or "2222").strip() or "2222",
            "user": str(topology.get("SSH_BASTION_USER") or "").strip(),
            "identity_file": str(topology.get("SSH_BASTION_IDENTITY_FILE") or "").strip(),
        },
    }

    vms = []
    for spec in _vm_distributed_role_plan_specs(topology):
        address = _vm_distributed_config_value(
            topology,
            spec["address_key"],
            spec["fallback_address_key"],
            "VM_EXTERNAL_IP",
        )
        ssh_host = _vm_distributed_effective_ssh_host(topology, spec, address)
        ssh_port = _vm_distributed_config_value(topology, spec["ssh_port_key"], default="22") or "22"
        ssh_user = _vm_distributed_config_value(topology, spec["ssh_user_key"], "VM_SSH_USER")
        ssh_identity_file = _vm_distributed_identity_file(topology, spec["role_key"])
        ssh_access_mode = _vm_distributed_role_ssh_access_mode(topology, spec["role_key"])
        ssh_bastion = _vm_distributed_role_bastion_config(
            topology,
            spec["role_key"],
            identity_file=ssh_identity_file,
        )
        public_url = _vm_distributed_config_value(topology, spec["public_url_key"])
        http_url = _vm_distributed_config_value(topology, spec["http_url_key"], default=f"http://{address}" if address else "")
        remote_workdir = _vm_distributed_effective_remote_workdir(
            topology,
            spec["role_key"],
            spec["workdir_key"],
            default=spec.get("default_workdir") or "",
        )
        vm = {
            "role": spec["role"],
            "role_key": spec["role_key"],
            "address": address,
            "public_url": public_url,
            "http_url": http_url,
            "remote_workdir": remote_workdir,
            "levels": spec["levels"],
            "ssh": {
                "mode": ssh_access_mode or "not-configured",
                "access_mode": ssh_access_mode,
                "host": ssh_host,
                "port": ssh_port,
                "user": ssh_user,
                "identity_file": ssh_identity_file,
                "bastion": ssh_bastion,
                "configured": bool(ssh_access_mode and ssh_host),
            },
        }
        vm["ssh"]["command"] = (
            _vm_distributed_format_command(_vm_distributed_build_ssh_command({"ssh": access}, vm))
            if vm["ssh"].get("configured")
            else ""
        )
        vms.append(vm)

    validation_pairs = [
        {"source": source, "target": target}
        for source, target in parse_connector_pairs(adapter.get("DS_1_VALIDATION_PAIRS"), adapter.get("DS_1_NAME"))
    ]
    return {
        "status": preflight.get("status") or "unknown",
        "topology": "vm-distributed",
        "execution_host": ssh_bootstrap["execution_host"],
        "deployment_mode": _vm_distributed_config_value(topology, "VM_DISTRIBUTED_DEPLOYMENT_MODE", default="orchestrator"),
        "dry_run_default": _vm_distributed_config_value(topology, "VM_DISTRIBUTED_PREFLIGHT_DRY_RUN", default="true"),
        "domain_base": str(infra.get("DOMAIN_BASE") or "").strip(),
        "dataspace_domain_base": str(infra.get("DS_DOMAIN_BASE") or "").strip(),
        "dataspace": str(adapter.get("DS_1_NAME") or "").strip(),
        "ssh": access,
        "ssh_role_modes": {
            item["role_key"]: (item.get("ssh") or {}).get("access_mode") or "not-configured"
            for item in vms
        },
        "vms": vms,
        "ssh_bootstrap": ssh_bootstrap,
        "http_preflight": {
            "tls_verify": _vm_distributed_http_preflight_tls_verify_mode(topology),
        },
        "connectors": _vm_distributed_connector_plan(adapter),
        "validation_pairs": validation_pairs,
        "configuration_preflight": preflight,
    }


def _build_vm_single_ssh_bootstrap_plan(infrastructure_config, topology_config, adapter_config):
    topology = dict(topology_config or {})
    adapter = dict(adapter_config or {})
    bootstrap_mode = _normalized_vm_single_ssh_bootstrap_mode(topology)
    identity_file = _vm_single_identity_file(topology)
    key_comment = _vm_distributed_config_value(
        topology,
        "VM_SINGLE_SSH_KEY_COMMENT",
        default="validation-environment-vm-single",
    )
    marker = _vm_distributed_config_value(
        topology,
        "VM_SINGLE_SSH_MANAGED_MARKER",
        default="validation-environment-vm-single",
    )
    remote_workdir = _vm_distributed_config_value(
        topology,
        "VM_SINGLE_REMOTE_WORKDIR",
        "VM_REMOTE_WORKDIR",
    )
    address = _vm_distributed_config_value(
        topology,
        "VM_SINGLE_ADDRESS",
        "VM_SINGLE_IP",
        "VM_EXTERNAL_IP",
        "HOSTS_ADDRESS",
        "INGRESS_EXTERNAL_IP",
    )
    ssh_host = _vm_distributed_config_value(topology, "VM_SINGLE_SSH_HOST", default=address)
    ssh_user = _vm_distributed_config_value(topology, "VM_SINGLE_SSH_USER", "VM_SSH_USER")
    ssh_port = _vm_distributed_config_value(topology, "VM_SINGLE_SSH_PORT", default="22") or "22"
    target_roles = [
        {
            "role": "vm-single",
            "role_key": "single",
            "host": ssh_host,
            "user": ssh_user,
            "port": ssh_port,
            "identity_file": identity_file,
            "needs_public_key": bool(ssh_host and ssh_user),
        }
    ]

    actions = [
        {
            "name": "ensure_dedicated_keypair",
            "status": "planned" if identity_file else "needs-configuration",
            "idempotent_check": "create the key only when the private or public key is missing",
        },
        {
            "name": "install_public_key_on_target_vm",
            "status": "planned" if identity_file and target_roles[0]["needs_public_key"] else "needs-configuration",
            "idempotent_check": "append the public key only when the managed marker is absent",
        },
        {
            "name": "verify_batchmode_ssh",
            "status": "planned",
            "idempotent_check": "run ssh -o BatchMode=yes against the vm-single target",
        },
    ]
    warnings = []
    if bootstrap_mode not in {"manual", "plan", "auto"}:
        warnings.append("VM_SINGLE_SSH_BOOTSTRAP_MODE should be manual, plan or auto.")
    if not identity_file:
        warnings.append("SSH_IDENTITY_FILE or VM_SINGLE_SSH_IDENTITY_FILE is required for SSH bootstrap.")
    if not ssh_host:
        warnings.append("VM_SINGLE_SSH_HOST or VM_EXTERNAL_IP is required for vm-single SSH bootstrap.")
    if not ssh_user:
        warnings.append("VM_SINGLE_SSH_USER or VM_SSH_USER is required for vm-single SSH bootstrap.")

    return {
        "status": "ready" if not warnings else "needs-review",
        "mode": bootstrap_mode,
        "execution_host": "external",
        "identity_file": identity_file,
        "key_comment": key_comment,
        "managed_marker": marker,
        "remote_workdir": remote_workdir,
        "dataspace": str(adapter.get("DS_1_NAME") or "").strip(),
        "targets": target_roles,
        "actions": actions,
        "warnings": warnings,
        "security": [
            "private keys are never written to versioned files",
            "only public keys are installed on the target VM",
            "BatchMode=yes is used for verification",
            "managed authorized_keys entries must carry a marker for idempotent updates",
        ],
    }


def _vm_single_configuration_preflight(infrastructure_config, topology_config, adapter_config):
    topology = dict(topology_config or {})
    adapter = dict(adapter_config or {})
    warnings = []
    checks = []

    address = _vm_distributed_config_value(
        topology,
        "VM_SINGLE_ADDRESS",
        "VM_SINGLE_IP",
        "VM_EXTERNAL_IP",
        "HOSTS_ADDRESS",
        "INGRESS_EXTERNAL_IP",
    )
    if not address:
        warnings.append(
            "vm-single needs VM_EXTERNAL_IP, VM_SINGLE_IP, VM_SINGLE_ADDRESS, HOSTS_ADDRESS or INGRESS_EXTERNAL_IP."
        )

    ssh_preflight = _vm_single_ssh_access_preflight(topology)
    warnings.extend(ssh_preflight.get("warnings") or [])
    ssh_bootstrap = _build_vm_single_ssh_bootstrap_plan(infrastructure_config, topology, adapter)
    warnings.extend(ssh_bootstrap.get("warnings") or [])

    checks.append(
        {
            "name": "VM address",
            "status": "ready" if address else "missing",
            "detail": "single VM ingress/address value",
        }
    )
    checks.append(
        {
            "name": "SSH access",
            "status": ssh_preflight.get("status") or "unknown",
            "detail": ssh_preflight.get("detail") or "",
        }
    )
    checks.append(
        {
            "name": "SSH bootstrap",
            "status": ssh_bootstrap.get("status") or "unknown",
            "detail": ssh_bootstrap.get("mode") or "manual",
        }
    )
    checks.append(
        {
            "name": "Dataspace",
            "status": "ready" if str(adapter.get("DS_1_NAME") or "").strip() else "missing",
            "detail": "DS_1_NAME",
        }
    )

    return {
        "status": "ready" if not warnings else "needs-review",
        "checks": checks,
        "warnings": warnings,
    }


def _build_vm_single_topology_plan(infrastructure_config, topology_config, adapter_config):
    topology = dict(topology_config or {})
    infra = _effective_topology_scoped_infrastructure_config(
        infrastructure_config,
        topology,
        topology="vm-single",
    )
    adapter = dict(adapter_config or {})
    preflight = _vm_single_configuration_preflight(infra, topology, adapter)
    ssh_bootstrap = _build_vm_single_ssh_bootstrap_plan(infra, topology, adapter)
    mode = str(topology.get("SSH_ACCESS_MODE") or "").strip().lower().replace("_", "-")
    if mode not in {"direct", "bastion"}:
        mode = ""
    timeout = _vm_single_connect_timeout_seconds(topology)
    identity_file = _vm_single_identity_file(topology)
    access = {
        "mode": mode or "not-configured",
        "connect_timeout_seconds": timeout,
        "identity_file": identity_file,
        "known_hosts_strategy": _vm_distributed_config_value(
            topology,
            "VM_SINGLE_SSH_KNOWN_HOSTS_STRATEGY",
            default="accept-new",
        ),
        "bastion": {
            "host": str(topology.get("SSH_BASTION_HOST") or "").strip(),
            "port": str(topology.get("SSH_BASTION_PORT") or "2222").strip() or "2222",
            "user": str(topology.get("SSH_BASTION_USER") or "").strip(),
            "identity_file": str(topology.get("SSH_BASTION_IDENTITY_FILE") or "").strip(),
        },
    }
    address = _vm_distributed_config_value(
        topology,
        "VM_SINGLE_ADDRESS",
        "VM_SINGLE_IP",
        "VM_EXTERNAL_IP",
        "HOSTS_ADDRESS",
        "INGRESS_EXTERNAL_IP",
    )
    ssh_host = _vm_distributed_config_value(topology, "VM_SINGLE_SSH_HOST", default=address)
    ssh_port = _vm_distributed_config_value(topology, "VM_SINGLE_SSH_PORT", default="22") or "22"
    ssh_user = _vm_distributed_config_value(topology, "VM_SINGLE_SSH_USER", "VM_SSH_USER")
    remote_workdir = _vm_distributed_config_value(
        topology,
        "VM_SINGLE_REMOTE_WORKDIR",
        "VM_REMOTE_WORKDIR",
    )
    http_url = _vm_distributed_config_value(
        topology,
        "VM_SINGLE_HTTP_URL",
        default=f"http://{address}" if address else "",
    )
    vm = {
        "role": "vm-single",
        "role_key": "single",
        "address": address,
        "public_url": str(topology.get("PUBLIC_GATEWAY_URL") or "").strip(),
        "http_url": http_url,
        "remote_workdir": remote_workdir,
        "levels": [1, 2, 3, 4, 5, 6],
        "ssh": {
            "mode": mode or "not-configured",
            "host": ssh_host,
            "port": ssh_port,
            "user": ssh_user,
            "identity_file": identity_file,
            "configured": bool(mode and ssh_host),
        },
    }
    vm["ssh"]["command"] = (
        _vm_distributed_format_command(_vm_distributed_build_ssh_command({"ssh": access}, vm))
        if vm["ssh"].get("configured")
        else ""
    )

    return {
        "status": preflight.get("status") or "unknown",
        "topology": "vm-single",
        "execution_host": "external",
        "deployment_mode": "single-vm",
        "domain_base": str(infra.get("DOMAIN_BASE") or "").strip(),
        "dataspace_domain_base": str(infra.get("DS_DOMAIN_BASE") or "").strip(),
        "dataspace": str(adapter.get("DS_1_NAME") or "").strip(),
        "ssh": access,
        "vms": [vm],
        "ssh_bootstrap": ssh_bootstrap,
        "configuration_preflight": preflight,
    }


def _vm_distributed_remote_preflight_shell(workdir="", http_url="http://127.0.0.1/"):
    safe_workdir = shlex.quote(str(workdir or ""))
    safe_http_url = shlex.quote(str(http_url or "http://127.0.0.1/"))
    return "\n".join(
        [
            "set +e",
            f"workdir={safe_workdir}",
            f"http_url={safe_http_url}",
            "hostname_value=$(hostname 2>/dev/null || printf unknown)",
            "user_value=$(id -un 2>/dev/null || whoami 2>/dev/null || printf unknown)",
            "os_value=$(if [ -r /etc/os-release ]; then . /etc/os-release && printf '%s %s' \"$NAME\" \"$VERSION_ID\"; else uname -srm 2>/dev/null; fi)",
            "ip_value=$(hostname -I 2>/dev/null | tr -s ' ' | sed 's/[[:space:]]*$//')",
            "docker_value=$(command -v docker >/dev/null 2>&1 && docker --version 2>/dev/null || printf missing)",
            "containerd_value=$(command -v containerd >/dev/null 2>&1 && containerd --version 2>/dev/null || printf missing)",
            "kubectl_value=$(command -v kubectl >/dev/null 2>&1 && kubectl version --client=true --short 2>/dev/null || (command -v k3s >/dev/null 2>&1 && printf 'missing; k3s kubectl available') || printf missing)",
            "k3s_value=$(command -v k3s >/dev/null 2>&1 && k3s --version 2>/dev/null | head -n 1 || printf missing)",
            "ports_value=$(ss -lntH 2>/dev/null | awk '{print $4}' | tr '\n' ',' | sed 's/,$//' || printf unavailable)",
            "if [ -n \"$workdir\" ]; then if [ -d \"$workdir\" ]; then workdir_value=present; else workdir_value=missing; fi; else workdir_value=not-configured; fi",
            "if command -v curl >/dev/null 2>&1; then http_output=$(curl -sS -m 3 -o /dev/null -w '%{http_code}' \"$http_url\" 2>/dev/null); http_status=$?; if [ \"$http_status\" = \"0\" ]; then http_value=\"$http_output\"; else http_value=unavailable; fi; else http_value=not-checked; fi",
            "printf 'hostname=%s\\n' \"$hostname_value\"",
            "printf 'user=%s\\n' \"$user_value\"",
            "printf 'os=%s\\n' \"$os_value\"",
            "printf 'ips=%s\\n' \"$ip_value\"",
            "printf 'docker=%s\\n' \"$docker_value\"",
            "printf 'containerd=%s\\n' \"$containerd_value\"",
            "printf 'kubectl=%s\\n' \"$kubectl_value\"",
            "printf 'k3s=%s\\n' \"$k3s_value\"",
            "printf 'listening_ports=%s\\n' \"$ports_value\"",
            "printf 'remote_workdir=%s\\n' \"$workdir_value\"",
            "printf 'http_local=%s\\n' \"$http_value\"",
        ]
    )


def _vm_distributed_parse_key_value_output(output):
    parsed = {}
    for raw_line in str(output or "").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        if key:
            parsed[key] = value.strip()
    return parsed


def _vm_distributed_default_command_runner(command, timeout):
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _vm_distributed_plan_vm_is_local_to_common_services(plan, vm):
    if str((plan or {}).get("execution_host") or "").strip().lower() != "common-services":
        return False
    role_key = str((vm or {}).get("role_key") or (vm or {}).get("role") or "").strip().lower()
    role_key = role_key.replace("_", "-")
    if role_key in {"common", "common-services"}:
        return True
    if role_key not in {"components", "component-services"}:
        return False

    ssh = dict((vm or {}).get("ssh") or {})
    common_vm = next(
        (
            item
            for item in list((plan or {}).get("vms") or [])
            if str(item.get("role_key") or item.get("role") or "").strip().lower().replace("_", "-")
            in {"common", "common-services"}
        ),
        {},
    )
    common_ssh = dict(common_vm.get("ssh") or {})
    local_aliases = {
        "127.0.0.1",
        "localhost",
        str(common_vm.get("address") or "").strip(),
        str(common_ssh.get("host") or "").strip(),
    }
    local_aliases.discard("")
    return str((vm or {}).get("address") or "").strip() in local_aliases or str(ssh.get("host") or "").strip() in local_aliases


def run_vm_distributed_remote_preflight(plan, command_runner=None):
    vm_plan = dict(plan or {})
    ssh_plan = dict(vm_plan.get("ssh") or {})
    has_configured_ssh = ssh_plan.get("mode") in {"direct", "bastion"} or any(
        (dict(item.get("ssh") or {}).get("access_mode") in {"direct", "bastion"})
        for item in list(vm_plan.get("vms") or [])
    ) or any(_vm_distributed_plan_vm_is_local_to_common_services(vm_plan, item) for item in list(vm_plan.get("vms") or []))
    if not has_configured_ssh:
        return {
            "status": "skipped",
            "reason": "ssh-not-configured",
            "topology": "vm-distributed",
            "vms": [],
        }
    if command_runner is None and not shutil.which("ssh"):
        return {
            "status": "failed",
            "reason": "ssh-client-missing",
            "topology": "vm-distributed",
            "vms": [],
        }

    runner = command_runner or _vm_distributed_default_command_runner
    timeout = int(ssh_plan.get("connect_timeout_seconds") or 5) + 20
    results = []
    for vm in list(vm_plan.get("vms") or []):
        ssh = dict(vm.get("ssh") or {})
        local_common_vm = _vm_distributed_plan_vm_is_local_to_common_services(vm_plan, vm)
        if not ssh.get("configured") and not local_common_vm:
            results.append(
                {
                    "role": vm.get("role"),
                    "status": "skipped",
                    "reason": "missing-ssh-host-or-mode",
                }
            )
            continue
        remote_command = _vm_distributed_remote_preflight_shell(
            workdir=vm.get("remote_workdir"),
            http_url="http://127.0.0.1/",
        )
        command = (
            ["sh", "-lc", remote_command]
            if local_common_vm
            else _vm_distributed_build_ssh_command(vm_plan, vm, remote_command=remote_command)
        )
        try:
            completed = runner(command, timeout=timeout)
            returncode = int(getattr(completed, "returncode", 1) or 0)
            stdout = getattr(completed, "stdout", "") or ""
            stderr = getattr(completed, "stderr", "") or ""
            results.append(
                {
                    "role": vm.get("role"),
                    "host": ssh.get("host"),
                    "status": "passed" if returncode == 0 else "failed",
                    "local": local_common_vm,
                    "returncode": returncode,
                    "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
                    "facts": _vm_distributed_parse_key_value_output(stdout),
                    "error": stderr.strip()[:500],
                }
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "role": vm.get("role"),
                    "host": ssh.get("host"),
                    "status": "failed",
                    "reason": "timeout",
                    "timeout_seconds": timeout,
                }
            )

    statuses = {str(item.get("status") or "").strip().lower() for item in results}
    overall = "passed" if statuses == {"passed"} else "failed" if "failed" in statuses else "skipped"
    return {
        "status": overall,
        "topology": "vm-distributed",
        "vms": results,
    }


def _vm_distributed_http_get(getter, url, *, timeout=3, allow_redirects=False, verify=None):
    kwargs = {"timeout": timeout, "allow_redirects": allow_redirects}
    if verify is not None:
        kwargs["verify"] = verify
    try:
        return getter(url, **kwargs)
    except TypeError as exc:
        if verify is not None and "verify" in str(exc):
            kwargs.pop("verify", None)
            return getter(url, **kwargs)
        raise


def run_vm_distributed_http_preflight(plan, request_get=None):
    getter = request_get or requests.get
    tls_verify_mode = _vm_distributed_http_preflight_tls_verify_mode(plan)
    results = []
    for vm in list((plan or {}).get("vms") or []):
        url = str(vm.get("http_url") or "").strip()
        if not url:
            results.append({"role": vm.get("role"), "status": "skipped", "reason": "missing-http-url"})
            continue
        parsed_url = urllib.parse.urlparse(url)
        is_https = str(parsed_url.scheme or "").lower() == "https"
        verify = None
        if is_https and tls_verify_mode in {"true", "auto"}:
            verify = True
        elif is_https and tls_verify_mode == "false":
            verify = False
        try:
            response = _vm_distributed_http_get(
                getter,
                url,
                timeout=3,
                allow_redirects=False,
                verify=verify,
            )
            status_code = int(getattr(response, "status_code", 0) or 0)
            results.append(
                {
                    "role": vm.get("role"),
                    "url": url,
                    "status": "passed" if 100 <= status_code < 500 else "failed",
                    "status_code": status_code,
                }
            )
        except requests.exceptions.SSLError as exc:
            if not is_https or tls_verify_mode != "auto":
                results.append(
                    {
                        "role": vm.get("role"),
                        "url": url,
                        "status": "failed",
                        "error": str(exc)[:500],
                    }
                )
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    response = _vm_distributed_http_get(
                        getter,
                        url,
                        timeout=3,
                        allow_redirects=False,
                        verify=False,
                    )
                status_code = int(getattr(response, "status_code", 0) or 0)
                results.append(
                    {
                        "role": vm.get("role"),
                        "url": url,
                        "status": "warning" if 100 <= status_code < 500 else "failed",
                        "status_code": status_code,
                        "reason": "tls-verification-failed",
                        "detail": str(exc)[:500],
                    }
                )
            except requests.RequestException as retry_exc:
                results.append(
                    {
                        "role": vm.get("role"),
                        "url": url,
                        "status": "failed",
                        "reason": "tls-verification-failed",
                        "error": f"{str(exc)[:240]} | retry without TLS verification: {str(retry_exc)[:240]}",
                    }
                )
        except requests.RequestException as exc:
            results.append(
                {
                    "role": vm.get("role"),
                    "url": url,
                    "status": "failed",
                    "error": str(exc)[:500],
                }
            )
    statuses = {str(item.get("status") or "").strip().lower() for item in results}
    if "failed" in statuses:
        overall = "failed"
    elif "warning" in statuses:
        overall = "passed-with-warnings"
    else:
        overall = "passed" if statuses == {"passed"} else "skipped"
    return {
        "status": overall,
        "topology": "vm-distributed",
        "vms": results,
    }


def _vm_distributed_configuration_preflight(infrastructure_config, topology_config, adapter_config):
    topology = dict(topology_config or {})
    infra = _effective_topology_scoped_infrastructure_config(
        infrastructure_config,
        topology,
        topology="vm-distributed",
    )
    adapter = dict(adapter_config or {})
    missing = []
    warnings = []
    checks = []

    domain_keys = ("DOMAIN_BASE", "DS_DOMAIN_BASE")
    missing_domain_keys = []
    for key in domain_keys:
        value = str(infra.get(key) or "").strip()
        if not value:
            missing.append(key)
            missing_domain_keys.append(key)
            continue
        if _is_vm_public_placeholder_domain(value):
            missing.append(key)
            missing_domain_keys.append(key)
            warnings.append(
                f"{key} uses the example domain '{value}'. Set a real public domain or explicit public URLs before running vm-distributed."
            )

    public_url_values = {**infra, **topology, **adapter}
    missing_public_url_keys = []
    for key in VM_DISTRIBUTED_PUBLIC_URL_KEYS:
        value = str(public_url_values.get(key) or "").strip()
        if not value or not is_vm_public_placeholder_url(value):
            continue
        if key not in missing:
            missing.append(key)
        missing_public_url_keys.append(key)
        warnings.append(
            f"{key} points to the example public URL '{value}'. Replace it with a real public URL or leave it blank to infer from real domains."
        )

    address_keys = ("VM_COMMON_IP", "VM_PROVIDER_IP", "VM_CONSUMER_IP")
    missing_address_keys = []
    for key in address_keys:
        if not str(topology.get(key) or topology.get("VM_EXTERNAL_IP") or "").strip():
            missing.append(key)
            missing_address_keys.append(key)

    adapter_required_keys = ("DS_1_NAME", "DS_1_CONNECTORS")
    missing_adapter_keys = []
    for key in adapter_required_keys:
        if not str(adapter.get(key) or "").strip():
            missing.append(key)
            missing_adapter_keys.append(key)

    kubeconfig_roles = {
        "K3S_KUBECONFIG_COMMON": "common",
        "K3S_KUBECONFIG_PROVIDER": "provider",
        "K3S_KUBECONFIG_CONSUMER": "consumer",
    }
    kubeconfig_keys = tuple(kubeconfig_roles)
    missing_kubeconfig_keys = []
    missing_kubeconfig_files = []
    effective_kubeconfigs = {}
    for key in kubeconfig_keys:
        role = kubeconfig_roles[key]
        configured_kubeconfig = str(topology.get(key) or "").strip()
        kubeconfig = _vm_distributed_effective_kubeconfig_path(topology, role, configured_kubeconfig)
        effective_kubeconfigs[role] = kubeconfig
        if not kubeconfig:
            missing_kubeconfig_keys.append(key)
            warnings.append(f"{key} is empty; vm-distributed will need a kubeconfig for that role.")
            continue
        expanded = os.path.abspath(os.path.expanduser(kubeconfig))
        if not _vm_distributed_readable_file(expanded):
            missing_kubeconfig_files.append(key)
            if configured_kubeconfig and configured_kubeconfig != kubeconfig:
                warnings.append(f"{key} is not readable locally after common-services localization: {kubeconfig}")
            else:
                warnings.append(f"{key} is not readable locally: {kubeconfig}")

    dataspace_name = str(adapter.get("DS_1_NAME") or "").strip()
    connectors = parse_connector_list(adapter.get("DS_1_CONNECTORS"), dataspace_name)
    connector_namespaces = str(adapter.get("DS_1_CONNECTOR_NAMESPACES") or "").strip()
    connector_set = set(connectors)
    mapping = parse_connector_mapping(connector_namespaces, dataspace_name)
    invalid_mapping_tokens = _connector_mapping_invalid_tokens(connector_namespaces)
    if invalid_mapping_tokens:
        warnings.append(
            "DS_1_CONNECTOR_NAMESPACES contains invalid items: "
            + ", ".join(invalid_mapping_tokens)
        )
    unknown_mapping = sorted(connector for connector in mapping if connector not in connector_set)
    if unknown_mapping:
        warnings.append(
            "DS_1_CONNECTOR_NAMESPACES references unknown connectors: "
            + ", ".join(unknown_mapping)
        )
    if connector_namespaces:
        unmapped = sorted(connector for connector in connectors if connector not in mapping)
        if unmapped:
            warnings.append(
                "Connectors without explicit namespace mapping will use the dataspace namespace: "
                + ", ".join(unmapped)
            )
    elif len(connectors) > 2:
        warnings.append("DS_1_CONNECTOR_NAMESPACES is recommended when more than two connectors are configured.")

    validation_pairs_raw = str(adapter.get("DS_1_VALIDATION_PAIRS") or "").strip()
    validation_pairs = parse_connector_pairs(validation_pairs_raw, dataspace_name)
    invalid_pair_tokens = _connector_pairs_invalid_tokens(validation_pairs_raw)
    if invalid_pair_tokens:
        warnings.append(
            "DS_1_VALIDATION_PAIRS contains invalid items: "
            + ", ".join(invalid_pair_tokens)
        )
    unknown_pairs = sorted(
        connector
        for pair in validation_pairs
        for connector in pair
        if connector not in connector_set
    )
    if unknown_pairs:
        warnings.append(
            "DS_1_VALIDATION_PAIRS references unknown connectors: "
            + ", ".join(dict.fromkeys(unknown_pairs))
        )

    reconciliation_mode = _normalized_reconciliation_mode(
        adapter.get("LEVEL4_CONNECTOR_RECONCILIATION_MODE")
    )
    if not reconciliation_mode:
        warnings.append("LEVEL4_CONNECTOR_RECONCILIATION_MODE should be full or additive.")

    role_kubeconfigs = [
        str(effective_kubeconfigs.get(kubeconfig_roles[key]) or "").strip()
        for key in kubeconfig_keys
        if str(effective_kubeconfigs.get(kubeconfig_roles[key]) or "").strip()
    ]
    multi_kubeconfig = len(set(role_kubeconfigs)) > 1
    common_address = str(topology.get("VM_COMMON_IP") or "").strip()
    provider_address = str(topology.get("VM_PROVIDER_IP") or "").strip()
    consumer_address = str(topology.get("VM_CONSUMER_IP") or "").strip()
    ssh_user = str(topology.get("VM_SSH_USER") or "").strip()
    if not ssh_user and (
        provider_address and provider_address != common_address
        or consumer_address and consumer_address != common_address
    ):
        warnings.append(
            "VM_SSH_USER is empty; remote connector VM NGINX synchronization will be skipped."
        )

    ssh_preflight = _vm_distributed_ssh_access_preflight(topology)
    warnings.extend(ssh_preflight.get("warnings") or [])
    ssh_bootstrap = _build_vm_distributed_ssh_bootstrap_plan(infra, topology, adapter)
    warnings.extend(ssh_bootstrap.get("warnings") or [])

    deployment_mode = _vm_distributed_config_value(
        topology,
        "VM_DISTRIBUTED_DEPLOYMENT_MODE",
        default="orchestrator",
    ).lower()
    if deployment_mode not in {"orchestrator", "manual", "preflight-only"}:
        warnings.append("VM_DISTRIBUTED_DEPLOYMENT_MODE should be orchestrator, manual or preflight-only.")

    checks.append(
        {
            "name": "Domains",
            "status": "missing" if missing_domain_keys else "ready",
            "detail": "DOMAIN_BASE and DS_DOMAIN_BASE",
        }
    )
    checks.append(
        {
            "name": "Public URLs",
            "status": "missing" if missing_public_url_keys else "ready",
            "detail": "browser-facing URLs must not use example domains",
        }
    )
    checks.append(
        {
            "name": "VM addresses",
            "status": "missing" if missing_address_keys else "ready",
            "detail": "common, provider and consumer IP/DNS values",
        }
    )
    kubeconfig_status = "ready"
    if missing_kubeconfig_keys:
        kubeconfig_status = "missing"
    elif missing_kubeconfig_files:
        kubeconfig_status = "needs-review"
    checks.append(
        {
            "name": "Kubeconfigs",
            "status": kubeconfig_status,
            "detail": "common, provider and consumer kubeconfig paths",
        }
    )
    checks.append(
        {
            "name": "Connector inventory",
            "status": "missing" if missing_adapter_keys else "ready",
            "detail": "DS_1_NAME and DS_1_CONNECTORS",
        }
    )
    mapping_status = "ready"
    if invalid_mapping_tokens or unknown_mapping:
        mapping_status = "needs-review"
    elif not connector_namespaces and len(connectors) > 2:
        mapping_status = "needs-review"
    checks.append(
        {
            "name": "Connector placement",
            "status": mapping_status,
            "detail": "DS_1_CONNECTOR_NAMESPACES or default provider/consumer placement",
        }
    )
    pairs_status = "ready"
    if invalid_pair_tokens or unknown_pairs:
        pairs_status = "needs-review"
    elif not validation_pairs_raw and len(connectors) > 2:
        pairs_status = "needs-review"
    checks.append(
        {
            "name": "Validation pairs",
            "status": pairs_status,
            "detail": "DS_1_VALIDATION_PAIRS or default first-pair validation",
        }
    )
    checks.append(
        {
            "name": "Level 4 reconciliation",
            "status": "ready" if reconciliation_mode else "needs-review",
            "detail": reconciliation_mode or "full/additive expected",
        }
    )
    checks.append(
        {
            "name": "Level 4 cluster scope",
            "status": "ready",
            "detail": (
                "multi-kubeconfig connector deployment enabled"
                if multi_kubeconfig
                else "single logical kubeconfig"
            ),
        }
    )
    checks.append(
        {
            "name": "SSH access",
            "status": ssh_preflight.get("status") or "ready",
            "detail": ssh_preflight.get("detail") or "optional SSH metadata",
        }
    )
    checks.append(
        {
            "name": "SSH bootstrap",
            "status": ssh_bootstrap.get("status") or "ready",
            "detail": (
                f"{ssh_bootstrap.get('mode') or 'manual'} bootstrap, "
                f"execution host: {ssh_bootstrap.get('execution_host') or 'external'}"
            ),
        }
    )
    checks.append(
        {
            "name": "Deployment mode",
            "status": "ready" if deployment_mode in {"orchestrator", "manual", "preflight-only"} else "needs-review",
            "detail": deployment_mode or "orchestrator",
        }
    )
    checks.append(
        {
            "name": "Hosts plan",
            "status": "ready" if not missing_domain_keys and not missing_address_keys else "missing",
            "detail": "run hosts --topology vm-distributed --dry-run before deployment",
        }
    )

    status = "ready" if not missing and not warnings else ("incomplete" if missing else "needs-review")
    return {
        "status": status,
        "missing": missing,
        "warnings": warnings,
        "checks": checks,
    }


def _print_vm_distributed_preflight(preflight):
    status = str((preflight or {}).get("status") or "unknown")
    print()
    print("vm-distributed configuration preflight:")
    print(f"  Status: {status}")
    checks = list((preflight or {}).get("checks") or [])
    if checks:
        print("  Checklist:")
        for check in checks:
            check_status = str(check.get("status") or "unknown")
            marker = {
                "ready": "[ok]",
                "missing": "[missing]",
                "needs-review": "[review]",
                "warning": "[warn]",
                "blocked": "[blocked]",
            }.get(check_status, "[?]")
            detail = str(check.get("detail") or "").strip()
            suffix = f": {detail}" if detail else ""
            print(f"  - {marker} {check.get('name')}{suffix}")
    missing = list((preflight or {}).get("missing") or [])
    warnings = list((preflight or {}).get("warnings") or [])
    if missing:
        print("  Missing required values:")
        for item in missing:
            print(f"  - {item}")
    if warnings:
        print("  Warnings:")
        for item in warnings:
            print(f"  - {item}")
    if not missing and not warnings:
        print("  Required values are present.")


def _vm_distributed_profile_parse_value(raw_value):
    value = str(raw_value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _vm_distributed_profile_key_has_valid_characters(key):
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
    return bool(key) and all(character in allowed for character in key)


def _load_vm_distributed_profile(profile_path):
    raw_path = str(profile_path or "").strip()
    if not raw_path:
        return {}, [{"line": 0, "message": "Profile path is empty."}]
    resolved_path = os.path.abspath(os.path.expanduser(raw_path))
    if not os.path.isfile(resolved_path):
        return {}, [{"line": 0, "message": f"Profile file does not exist: {resolved_path}"}]

    values = {}
    errors = []
    with open(resolved_path, encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                errors.append({"line": line_number, "message": "Expected KEY=VALUE."})
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not _vm_distributed_profile_key_has_valid_characters(key):
                errors.append({"line": line_number, "message": f"Invalid key: {key or '(empty)'}"})
                continue
            if key != key.upper():
                errors.append({"line": line_number, "message": f"Key must be uppercase: {key}"})
                continue
            parsed_value = _vm_distributed_profile_parse_value(value)
            if parsed_value == "":
                continue
            values[key] = parsed_value
    return values, errors


def _vm_distributed_profile_sensitive_key(key):
    normalized = str(key or "").strip().upper()
    return any(token in normalized for token in VM_DISTRIBUTED_PROFILE_SENSITIVE_KEY_TOKENS)


DEFAULT_ENVIRONMENT_PROFILE_NAME = "pionera"


def _environment_profile_name(raw_name=None):
    requested = str(
        raw_name
        if raw_name is not None
        else os.getenv("PIONERA_ENVIRONMENT_PROFILE", DEFAULT_ENVIRONMENT_PROFILE_NAME)
    ).strip()
    if not requested:
        return DEFAULT_ENVIRONMENT_PROFILE_NAME
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
    cleaned = "".join(character if character in allowed else "-" for character in requested)
    cleaned = cleaned.strip(".-") or DEFAULT_ENVIRONMENT_PROFILE_NAME
    if cleaned in {".", ".."}:
        return DEFAULT_ENVIRONMENT_PROFILE_NAME
    return cleaned


def _environment_profiles_dir():
    return os.path.abspath(os.path.join(_framework_root_dir(), ".profiles"))


def _environment_profile_path(profile_name=None):
    return os.path.join(_environment_profiles_dir(), f"{_environment_profile_name(profile_name)}.env")


def _available_environment_profiles():
    profiles_dir = _environment_profiles_dir()
    if not os.path.isdir(profiles_dir):
        return []
    profiles = []
    for filename in sorted(os.listdir(profiles_dir)):
        if not filename.endswith(".env"):
            continue
        path = os.path.join(profiles_dir, filename)
        if not os.path.isfile(path):
            continue
        profile_name = filename[: -len(".env")]
        if not profile_name:
            continue
        profiles.append(
            {
                "name": profile_name,
                "path": path,
                "relative_path": _framework_relative_path(path),
            }
        )
    return profiles


def _adapter_profile_keys(adapter_name):
    keys = set(VM_DISTRIBUTED_ADAPTER_KEYS)
    for path in (
        _adapter_deployer_config_example_path(adapter_name),
        _adapter_deployer_config_path(adapter_name),
    ):
        keys.update(load_raw_deployer_config(path).keys())
    return frozenset(keys)


def _configuration_profile_target_for_key(key, topology="vm-distributed", adapter_name="inesdata"):
    normalized = str(key or "").strip().upper()
    if not normalized:
        return ""
    if _vm_distributed_profile_sensitive_key(normalized):
        return "sensitive"
    if normalized in ENVIRONMENT_PROFILE_METADATA_KEYS:
        return "metadata"
    normalized_topology = normalize_topology(topology)
    topology_keys = set(TOPOLOGY_OVERLAY_KEYS.get(normalized_topology, frozenset()))
    if normalized_topology == "vm-distributed":
        topology_keys.update(VM_DISTRIBUTED_PROFILE_TOPOLOGY_KEYS)
    if normalized in topology_keys:
        return "topology"
    if normalized in ENVIRONMENT_PROFILE_INFRA_KEYS:
        return "infrastructure"
    if normalized in _adapter_profile_keys(adapter_name):
        return "adapter"
    if normalized.startswith("DS_"):
        return "adapter"
    return ""


def _vm_distributed_profile_target_for_key(key):
    return _configuration_profile_target_for_key(
        key,
        topology="vm-distributed",
        adapter_name="inesdata",
    )


def _validate_configuration_profile_scope(profile_values, topology="vm-distributed", adapter_name="inesdata"):
    selected_topology = normalize_topology(topology)
    selected_adapter = str(adapter_name or "").strip().lower() or "inesdata"
    errors = []
    profile_topology = str(dict(profile_values or {}).get("PROFILE_TOPOLOGY") or "").strip()
    if profile_topology and normalize_topology(profile_topology) != selected_topology:
        errors.append(
            {
                "key": "PROFILE_TOPOLOGY",
                "reason": "topology-mismatch",
                "message": (
                    f"Profile targets topology '{normalize_topology(profile_topology)}' "
                    f"but this run targets '{selected_topology}'."
                ),
            }
        )
    profile_adapter = str(dict(profile_values or {}).get("PROFILE_ADAPTER") or "").strip().lower()
    if profile_adapter and profile_adapter != selected_adapter:
        errors.append(
            {
                "key": "PROFILE_ADAPTER",
                "reason": "adapter-mismatch",
                "message": (
                    f"Profile targets adapter '{profile_adapter}' "
                    f"but this run targets '{selected_adapter}'."
                ),
            }
        )
    return errors


def _split_configuration_profile_updates(profile_values, topology="vm-distributed", adapter_name="inesdata"):
    grouped = {
        "metadata": {},
        "infrastructure": {},
        "topology": {},
        "adapter": {},
    }
    rejected = []
    for key, value in sorted(dict(profile_values or {}).items()):
        target = _configuration_profile_target_for_key(
            key,
            topology=topology,
            adapter_name=adapter_name,
        )
        if target == "sensitive":
            rejected.append(
                {
                    "key": key,
                    "reason": "sensitive-key",
                    "message": "Sensitive values must stay out of local configuration profiles.",
                }
            )
            continue
        if target not in grouped:
            rejected.append(
                {
                    "key": key,
                    "reason": "unknown-key",
                    "message": "This key is not supported by local configuration profiles.",
                }
            )
            continue
        grouped[target][key] = value
    return grouped, rejected


def _split_vm_distributed_profile_updates(profile_values):
    grouped, rejected = _split_configuration_profile_updates(
        profile_values,
        topology="vm-distributed",
        adapter_name="inesdata",
    )
    grouped.pop("metadata", None)
    return grouped, rejected


def _configuration_profile_preflight(topology, adapter_name, infrastructure_path, topology_path, adapter_path):
    normalized_topology = normalize_topology(topology)
    if normalized_topology == "vm-distributed":
        return _vm_distributed_configuration_preflight(
            load_raw_deployer_config(infrastructure_path),
            load_raw_deployer_config(topology_path),
            load_raw_deployer_config(adapter_path),
        )
    return {
        "status": "applied",
        "checks": [
            {
                "name": "Configuration profile",
                "status": "ready",
                "detail": f"applied to {normalized_topology}/{adapter_name}",
            }
        ],
        "missing": [],
        "warnings": [],
    }


def apply_environment_configuration_profile(profile_path, topology="vm-distributed", adapter_name="inesdata"):
    selected_topology = normalize_topology(topology)
    selected_adapter = str(adapter_name or "").strip().lower() or "inesdata"
    profile_values, parse_errors = _load_vm_distributed_profile(profile_path)
    if parse_errors:
        return {
            "status": "failed",
            "reason": "invalid-profile",
            "topology": selected_topology,
            "adapter": selected_adapter,
            "errors": parse_errors,
        }
    if not profile_values:
        return {
            "status": "failed",
            "reason": "empty-profile",
            "topology": selected_topology,
            "adapter": selected_adapter,
            "errors": [{"line": 0, "message": "Profile does not contain any KEY=VALUE entries."}],
        }

    scope_errors = _validate_configuration_profile_scope(
        profile_values,
        topology=selected_topology,
        adapter_name=selected_adapter,
    )
    grouped, rejected = _split_configuration_profile_updates(
        profile_values,
        topology=selected_topology,
        adapter_name=selected_adapter,
    )
    rejected = scope_errors + rejected
    if rejected:
        return {
            "status": "failed",
            "reason": "profile-has-unsupported-keys",
            "topology": selected_topology,
            "adapter": selected_adapter,
            "rejected": rejected,
        }

    _seed_infrastructure_deployer_config_if_missing()
    topology_path = _seed_infrastructure_topology_config_if_missing(selected_topology)
    adapter_path = _seed_adapter_deployer_config_if_missing(selected_adapter)

    if grouped["infrastructure"]:
        _write_key_value_updates(
            _infrastructure_deployer_config_path(),
            grouped["infrastructure"],
            sorted(ENVIRONMENT_PROFILE_INFRA_KEYS),
        )
    if grouped["topology"]:
        _write_key_value_updates(
            topology_path,
            grouped["topology"],
            sorted(
                set(TOPOLOGY_OVERLAY_KEYS.get(selected_topology, frozenset()))
                | (set(VM_DISTRIBUTED_TOPOLOGY_KEYS) if selected_topology == "vm-distributed" else set())
            ),
        )
    if grouped["adapter"]:
        _write_key_value_updates(
            adapter_path,
            grouped["adapter"],
            sorted(_adapter_profile_keys(selected_adapter)),
        )

    preflight = _configuration_profile_preflight(
        selected_topology,
        selected_adapter,
        _infrastructure_deployer_config_path(),
        topology_path,
        adapter_path,
    )
    return {
        "status": "applied" if preflight.get("status") == "ready" else preflight.get("status", "applied"),
        "topology": selected_topology,
        "adapter": selected_adapter,
        "profile": os.path.abspath(os.path.expanduser(str(profile_path or "").strip())),
        "updated_files": [
            path
            for path, updates in (
                (_infrastructure_deployer_config_path(), grouped["infrastructure"]),
                (topology_path, grouped["topology"]),
                (adapter_path, grouped["adapter"]),
            )
            if updates
        ],
        "updated_keys": {
            group: sorted(updates)
            for group, updates in grouped.items()
            if updates and group != "metadata"
        },
        "preflight": preflight,
    }


def apply_vm_distributed_configuration_profile(profile_path, adapter_name="inesdata"):
    return apply_environment_configuration_profile(
        profile_path,
        topology="vm-distributed",
        adapter_name=adapter_name,
    )


def _vm_distributed_profile_path():
    return _environment_profile_path()


def _current_environment_profile_display():
    profile_path = _vm_distributed_profile_path()
    return f"{_environment_profile_name()} ({_framework_relative_path(profile_path)})"


def _select_environment_profile_interactively():
    profiles = _available_environment_profiles()
    current_name = _environment_profile_name()
    print()
    print("Local configuration profiles")
    print(f"Current profile: {_current_environment_profile_display()}")
    print(f"Profiles directory: {_framework_relative_path(_environment_profiles_dir())}")
    if profiles:
        print()
        for index, profile in enumerate(profiles, start=1):
            marker = "*" if profile["name"] == current_name else " "
            print(f"{index} - {profile['name']} {marker} ({profile['relative_path']})")
    else:
        print()
        print("No local profiles found yet.")
        print("W -> 1 will create the selected profile if it does not exist.")

    print()
    print("Enter a listed number or a profile name. Press Enter to cancel.")
    answer = _interactive_read("Profile: ").strip()
    if not answer:
        print("Profile selection cancelled.")
        return {
            "status": "cancelled",
            "profile": current_name,
            "path": _vm_distributed_profile_path(),
        }

    selected_name = ""
    if answer.isdigit() and profiles:
        selected_index = int(answer)
        if 1 <= selected_index <= len(profiles):
            selected_name = profiles[selected_index - 1]["name"]
        else:
            print("Profile selection ignored: number out of range.")
            return {
                "status": "failed",
                "reason": "out-of-range",
                "profile": current_name,
                "path": _vm_distributed_profile_path(),
            }
    else:
        selected_name = _environment_profile_name(answer)

    os.environ["PIONERA_ENVIRONMENT_PROFILE"] = selected_name
    selected_path = _environment_profile_path(selected_name)
    print(f"Selected profile: {selected_name} ({_framework_relative_path(selected_path)})")
    if not os.path.isfile(selected_path):
        print("This profile does not exist yet. W -> 1 will create it as a template.")
    return {
        "status": "selected",
        "profile": selected_name,
        "path": selected_path,
    }


def _read_vm_distributed_profile_content(profile_path):
    with open(profile_path, encoding="utf-8") as handle:
        return handle.read()


VM_DISTRIBUTED_PROFILE_TEMPLATE_KEYS = (
    "PROFILE_TOPOLOGY",
    "PROFILE_ADAPTER",
    "ENVIRONMENT_NAME",
    "FRAMEWORK_EXECUTION_MODE",
    "DOMAIN_BASE",
    "DS_DOMAIN_BASE",
    "TOPOLOGY_ROUTING_MODE",
    "KEYCLOAK_FRONTEND_URL",
    "KEYCLOAK_PUBLIC_URL",
    "MINIO_API_PUBLIC_URL",
    "MINIO_CONSOLE_PUBLIC_URL",
    "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES_ENABLED",
    "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES",
    "COMPONENTS_PUBLIC_BASE_URL",
    "COMPONENTS_PUBLIC_PATH_REWRITE",
    "VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER",
    "COMPONENTS_IMAGE_PULL_POLICY",
    "ONTOLOGY_HUB_IMAGE_REF",
    "AI_MODEL_HUB_IMAGE_REF",
    "SEMANTIC_VIRTUALIZATION_IMAGE_REF",
    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_REF",
    "AI_MODEL_HUB_MODEL_SERVER_IMAGE",
    "AI_MODEL_HUB_MODEL_SERVER_MODE",
    "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR",
    "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY",
    "AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH",
    "AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH",
    "AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT",
    "AI_MODEL_HUB_MODEL_SERVER_DOCKER_BASE_IMAGE",
    "AI_MODEL_HUB_MODEL_SERVER_UVICORN_APP",
    "AI_MODEL_HUB_MODEL_SERVER_IMAGE_PULL_POLICY",
    "AI_MODEL_HUB_MODEL_SERVER_COPY_EXCLUDES",
    "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
    "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
    "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_URL",
    "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_DISCOVERY_PATH",
    "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINTS",
    "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_PAYLOAD",
    "VM_EXTERNAL_IP",
    "VM_COMMON_IP",
    "VM_DATASPACE_IP",
    "VM_PROVIDER_IP",
    "VM_CONSUMER_IP",
    "VM_CONNECTORS_IP",
    "VM_COMPONENTS_IP",
    "VM_OBSERVABILITY_IP",
    "INGRESS_EXTERNAL_IP",
    "VM_PUBLIC_PROXY_IP",
    "VM_PROVIDER_K8S_NODE",
    "VM_CONSUMER_K8S_NODE",
    "CLUSTER_TYPE",
    "K3S_KUBECONFIG",
    "K3S_KUBECONFIG_COMMON",
    "K3S_KUBECONFIG_PROVIDER",
    "K3S_KUBECONFIG_CONSUMER",
    "K3S_KUBECONFIG_COMPONENTS",
    "K3S_INSTALL_EXEC",
    "K3S_SERVICE_NAME",
    "K3S_INGRESS_CONTROLLER",
    "K3S_INGRESS_SERVICE_TYPE",
    "K3S_INGRESS_HTTP_NODEPORT",
    "K3S_REPAIR_ON_LEVEL1",
    "K3S_WRITE_KUBECONFIG_MODE",
    "VM_PROVIDER_CONNECTORS",
    "VM_CONSUMER_CONNECTORS",
    "VM_PROVIDER_INGRESS_HTTP_PORT",
    "VM_CONSUMER_INGRESS_HTTP_PORT",
    "VM_PROVIDER_INGRESS_NODEPORT",
    "VM_CONSUMER_INGRESS_NODEPORT",
    "VM_COMMON_PUBLIC_URL",
    "VM_PROVIDER_PUBLIC_URL",
    "VM_CONSUMER_PUBLIC_URL",
    "VM_COMMON_HTTP_URL",
    "VM_PROVIDER_HTTP_URL",
    "VM_CONSUMER_HTTP_URL",
    "CONNECTOR_PROTOCOL_ADDRESS_MODE",
    "VM_SSH_USER",
    "SSH_ACCESS_MODE",
    "SSH_BASTION_HOST",
    "SSH_BASTION_PORT",
    "SSH_BASTION_USER",
    "SSH_BASTION_IDENTITY_FILE",
    "SSH_IDENTITY_FILE",
    "SSH_CONNECT_TIMEOUT_SECONDS",
    "VM_COMMON_SSH_HOST",
    "VM_COMMON_SSH_PORT",
    "VM_COMMON_SSH_USER",
    "VM_COMPONENTS_SSH_HOST",
    "VM_COMPONENTS_SSH_PORT",
    "VM_COMPONENTS_SSH_USER",
    "VM_PROVIDER_SSH_HOST",
    "VM_PROVIDER_SSH_PORT",
    "VM_PROVIDER_SSH_USER",
    "VM_CONSUMER_SSH_HOST",
    "VM_CONSUMER_SSH_PORT",
    "VM_CONSUMER_SSH_USER",
    "KEYCLOAK_BOOTSTRAP_PORT_FORWARD",
    "VM_DISTRIBUTED_EXECUTION_HOST",
    "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH",
    "VM_DISTRIBUTED_INFER_LOCAL_WORKDIR",
    "VM_DISTRIBUTED_KUBECONFIG_AUTO_LOCALIZE",
    "VM_DISTRIBUTED_KUBECONFIG_DIR",
    "VM_DISTRIBUTED_KUBECONFIG_SYNC",
    "VM_DISTRIBUTED_REMOTE_KUBECONFIG",
    "VM_DISTRIBUTED_HTTP_PREFLIGHT_TLS_VERIFY",
    "VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE",
    "VM_DISTRIBUTED_SSH_KEY_COMMENT",
    "VM_DISTRIBUTED_SSH_MANAGED_MARKER",
    "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY",
    "VM_DISTRIBUTED_DEPLOYMENT_MODE",
    "VM_DISTRIBUTED_PREFLIGHT_DRY_RUN",
    "VM_DISTRIBUTED_K3S_TUNNEL_MODE",
    "VM_DISTRIBUTED_K3S_API_REMOTE_PORT",
    "VM_DISTRIBUTED_K3S_TUNNEL_RECREATE",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE",
    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY",
    "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE",
    "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP",
    "VM_DISTRIBUTED_REMOTE_NGINX_INTERACTIVE",
    "DS_1_NAME",
    "DS_1_NAMESPACE",
    "NAMESPACE_PROFILE",
    "DS_1_REGISTRATION_NAMESPACE",
    "DS_1_PROVIDER_NAMESPACE",
    "DS_1_CONSUMER_NAMESPACE",
    "COMMON_SERVICES_NAMESPACE",
    "COMPONENTS_NAMESPACE",
    "DS_1_CONNECTORS",
    "DS_1_CONNECTOR_NAMESPACES",
    "DS_1_VALIDATION_PAIRS",
    "LEVEL4_CONNECTOR_RECONCILIATION_MODE",
    "COMPONENTS",
)

VM_SINGLE_PROFILE_TEMPLATE_KEYS = (
    "PROFILE_TOPOLOGY",
    "PROFILE_ADAPTER",
    "ENVIRONMENT_NAME",
    "FRAMEWORK_EXECUTION_MODE",
    "DOMAIN_BASE",
    "DS_DOMAIN_BASE",
    "KEYCLOAK_FRONTEND_URL",
    "KEYCLOAK_PUBLIC_URL",
    "MINIO_API_PUBLIC_URL",
    "MINIO_CONSOLE_PUBLIC_URL",
    "VM_SINGLE_PUBLIC_URL",
    "VM_SINGLE_HTTP_URL",
    "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX",
    "COMPONENTS_PUBLIC_BASE_URL",
    "COMPONENTS_PUBLIC_PATH_REWRITE",
    "VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER",
    "ONTOLOGY_HUB_PUBLIC_URL",
    "AI_MODEL_HUB_PUBLIC_URL",
    "SEMANTIC_VIRTUALIZATION_PUBLIC_URL",
    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL",
    "COMPONENTS_IMAGE_PULL_POLICY",
    "ONTOLOGY_HUB_IMAGE_REF",
    "AI_MODEL_HUB_IMAGE_REF",
    "SEMANTIC_VIRTUALIZATION_IMAGE_REF",
    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_REF",
    "AI_MODEL_HUB_MODEL_SERVER_IMAGE",
    "AI_MODEL_HUB_MODEL_SERVER_MODE",
    "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR",
    "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY",
    "AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH",
    "AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH",
    "AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT",
    "AI_MODEL_HUB_MODEL_SERVER_DOCKER_BASE_IMAGE",
    "AI_MODEL_HUB_MODEL_SERVER_UVICORN_APP",
    "AI_MODEL_HUB_MODEL_SERVER_IMAGE_PULL_POLICY",
    "AI_MODEL_HUB_MODEL_SERVER_COPY_EXCLUDES",
    "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
    "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
    "VM_EXTERNAL_IP",
    "VM_COMMON_IP",
    "VM_DATASPACE_IP",
    "VM_CONNECTORS_IP",
    "VM_COMPONENTS_IP",
    "INGRESS_EXTERNAL_IP",
    "CLUSTER_TYPE",
    "K3S_KUBECONFIG",
    "K3S_INSTALL_EXEC",
    "K3S_SERVICE_NAME",
    "K3S_INGRESS_CONTROLLER",
    "K3S_INGRESS_SERVICE_TYPE",
    "K3S_REPAIR_ON_LEVEL1",
    "K3S_WRITE_KUBECONFIG_MODE",
    "VM_SINGLE_LOCAL_KUBECONFIG",
    "VM_SINGLE_REMOTE_KUBECONFIG",
    "VM_SINGLE_K3S_TUNNEL_MODE",
    "VM_SINGLE_K3S_API_LOCAL_PORT",
    "VM_SINGLE_K3S_API_REMOTE_PORT",
    "VM_SSH_USER",
    "SSH_ACCESS_MODE",
    "SSH_BASTION_HOST",
    "SSH_BASTION_PORT",
    "SSH_BASTION_USER",
    "SSH_BASTION_IDENTITY_FILE",
    "SSH_IDENTITY_FILE",
    "SSH_CONNECT_TIMEOUT_SECONDS",
    "VM_SINGLE_SSH_HOST",
    "VM_SINGLE_SSH_PORT",
    "VM_SINGLE_SSH_USER",
    "VM_SINGLE_SSH_IDENTITY_FILE",
    "VM_SINGLE_SSH_BOOTSTRAP_MODE",
    "VM_SINGLE_SSH_KEY_COMMENT",
    "VM_SINGLE_SSH_MANAGED_MARKER",
    "VM_SINGLE_SSH_KNOWN_HOSTS_STRATEGY",
    "VM_SINGLE_LEVEL_EXECUTION_MODE",
    "VM_SINGLE_REMOTE_PYTHON",
    "VM_SINGLE_REMOTE_WORKDIR",
    "VM_SINGLE_WORKSPACE_SYNC",
    "VM_SINGLE_WORKSPACE_SYNC_DELETE",
    "VM_SINGLE_WORKSPACE_SYNC_EXCLUDES",
    "DS_1_NAME",
    "DS_1_NAMESPACE",
    "DS_1_REGISTRATION_NAMESPACE",
    "DS_1_PROVIDER_NAMESPACE",
    "DS_1_CONSUMER_NAMESPACE",
    "COMMON_SERVICES_NAMESPACE",
    "COMPONENTS_NAMESPACE",
    "NAMESPACE_PROFILE",
    "DS_1_CONNECTORS",
    "DS_1_CONNECTOR_NAMESPACES",
    "DS_1_VALIDATION_PAIRS",
    "LEVEL4_CONNECTOR_RECONCILIATION_MODE",
    "COMPONENTS",
)


def _vm_distributed_profile_template_keys(topology="vm-distributed", adapter_name="inesdata"):
    selected_topology = normalize_topology(topology)
    selected_adapter = str(adapter_name or "").strip().lower() or "inesdata"
    keys = list(VM_DISTRIBUTED_PROFILE_TEMPLATE_KEYS)
    if selected_topology == "vm-single":
        keys = list(VM_SINGLE_PROFILE_TEMPLATE_KEYS)
    elif selected_topology != "vm-distributed":
        keys = [
            "PROFILE_TOPOLOGY",
            "PROFILE_ADAPTER",
            "ENVIRONMENT_NAME",
            "FRAMEWORK_EXECUTION_MODE",
            "DOMAIN_BASE",
            "DS_DOMAIN_BASE",
            "VM_EXTERNAL_IP",
            "VM_SINGLE_SSH_HOST",
            "VM_SSH_USER",
            "SSH_ACCESS_MODE",
            "SSH_BASTION_HOST",
            "SSH_BASTION_PORT",
            "SSH_BASTION_USER",
            "SSH_BASTION_IDENTITY_FILE",
            "K3S_KUBECONFIG",
            "DS_1_NAME",
            "DS_1_CONNECTORS",
            "DS_1_VALIDATION_PAIRS",
        ]
    if selected_adapter == "edc":
        keys.extend(("EDC_DASHBOARD_ENABLED", "EDC_CONNECTOR_NAMES"))
    return tuple(dict.fromkeys(keys))


def _vm_distributed_profile_template_content(topology="vm-distributed", adapter_name="inesdata"):
    selected_topology = normalize_topology(topology)
    selected_adapter = str(adapter_name or "").strip().lower() or "inesdata"
    if selected_topology == "vm-single":
        sections = (
            (
                "Local validation-environment profile.\n"
                "This file is ignored by Git and must not contain passwords, tokens or private keys.",
                ("PROFILE_TOPOLOGY", "PROFILE_ADAPTER", "ENVIRONMENT_NAME", "FRAMEWORK_EXECUTION_MODE"),
            ),
            (
                "Public domain and common routes",
                (
                    "DOMAIN_BASE",
                    "DS_DOMAIN_BASE",
                    "VM_SINGLE_PUBLIC_URL",
                    "VM_SINGLE_HTTP_URL",
                    "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX",
                    "KEYCLOAK_FRONTEND_URL",
                    "KEYCLOAK_PUBLIC_URL",
                    "MINIO_API_PUBLIC_URL",
                    "MINIO_CONSOLE_PUBLIC_URL",
                ),
            ),
            (
                "Component public routes",
                (
                    "COMPONENTS_PUBLIC_BASE_URL",
                    "COMPONENTS_PUBLIC_PATH_REWRITE",
                    "VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER",
                    "ONTOLOGY_HUB_PUBLIC_URL",
                    "AI_MODEL_HUB_PUBLIC_URL",
                    "SEMANTIC_VIRTUALIZATION_PUBLIC_URL",
                    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL",
                ),
            ),
            (
                "Component images",
                (
                    "COMPONENTS_IMAGE_PULL_POLICY",
                    "ONTOLOGY_HUB_IMAGE_REF",
                    "AI_MODEL_HUB_IMAGE_REF",
                    "SEMANTIC_VIRTUALIZATION_IMAGE_REF",
                    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_REF",
                ),
            ),
            (
                "AI Model Hub model server",
                (
                    "AI_MODEL_HUB_MODEL_SERVER_IMAGE",
                    "AI_MODEL_HUB_MODEL_SERVER_MODE",
                    "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR",
                    "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY",
                    "AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH",
                    "AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH",
                    "AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT",
                    "AI_MODEL_HUB_MODEL_SERVER_DOCKER_BASE_IMAGE",
                    "AI_MODEL_HUB_MODEL_SERVER_UVICORN_APP",
                    "AI_MODEL_HUB_MODEL_SERVER_IMAGE_PULL_POLICY",
                    "AI_MODEL_HUB_MODEL_SERVER_COPY_EXCLUDES",
                    "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
                    "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
                ),
            ),
            (
                "VM placement",
                (
                    "VM_EXTERNAL_IP",
                    "VM_COMMON_IP",
                    "VM_DATASPACE_IP",
                    "VM_CONNECTORS_IP",
                    "VM_COMPONENTS_IP",
                    "INGRESS_EXTERNAL_IP",
                ),
            ),
            (
                "Kubernetes runtime",
                (
                    "CLUSTER_TYPE",
                    "K3S_KUBECONFIG",
                    "K3S_INSTALL_EXEC",
                    "K3S_SERVICE_NAME",
                    "K3S_INGRESS_CONTROLLER",
                    "K3S_INGRESS_SERVICE_TYPE",
                    "K3S_REPAIR_ON_LEVEL1",
                    "K3S_WRITE_KUBECONFIG_MODE",
                    "VM_SINGLE_LOCAL_KUBECONFIG",
                    "VM_SINGLE_REMOTE_KUBECONFIG",
                    "VM_SINGLE_K3S_TUNNEL_MODE",
                    "VM_SINGLE_K3S_API_LOCAL_PORT",
                    "VM_SINGLE_K3S_API_REMOTE_PORT",
                ),
            ),
            (
                "SSH access",
                (
                    "VM_SSH_USER",
                    "SSH_ACCESS_MODE",
                    "SSH_BASTION_HOST",
                    "SSH_BASTION_PORT",
                    "SSH_BASTION_USER",
                    "SSH_BASTION_IDENTITY_FILE",
                    "SSH_IDENTITY_FILE",
                    "SSH_CONNECT_TIMEOUT_SECONDS",
                    "VM_SINGLE_SSH_HOST",
                    "VM_SINGLE_SSH_PORT",
                    "VM_SINGLE_SSH_USER",
                    "VM_SINGLE_SSH_IDENTITY_FILE",
                    "VM_SINGLE_SSH_BOOTSTRAP_MODE",
                    "VM_SINGLE_SSH_KEY_COMMENT",
                    "VM_SINGLE_SSH_MANAGED_MARKER",
                    "VM_SINGLE_SSH_KNOWN_HOSTS_STRATEGY",
                ),
            ),
            (
                "Execution mode",
                (
                    "VM_SINGLE_LEVEL_EXECUTION_MODE",
                    "VM_SINGLE_REMOTE_PYTHON",
                    "VM_SINGLE_REMOTE_WORKDIR",
                    "VM_SINGLE_WORKSPACE_SYNC",
                    "VM_SINGLE_WORKSPACE_SYNC_DELETE",
                    "VM_SINGLE_WORKSPACE_SYNC_EXCLUDES",
                ),
            ),
            (
                "Dataspace and connector inventory",
                (
                    "DS_1_NAME",
                    "DS_1_NAMESPACE",
                    "NAMESPACE_PROFILE",
                    "DS_1_REGISTRATION_NAMESPACE",
                    "DS_1_PROVIDER_NAMESPACE",
                    "DS_1_CONSUMER_NAMESPACE",
                    "COMMON_SERVICES_NAMESPACE",
                    "COMPONENTS_NAMESPACE",
                    "DS_1_CONNECTORS",
                    "DS_1_CONNECTOR_NAMESPACES",
                    "DS_1_VALIDATION_PAIRS",
                    "LEVEL4_CONNECTOR_RECONCILIATION_MODE",
                    "COMPONENTS",
                ),
            ),
        )
        rendered = []
        emitted = set()
        for title, keys in sections:
            for comment_line in str(title).splitlines():
                rendered.append(f"# {comment_line}")
            for key in keys:
                if key in emitted:
                    continue
                emitted.add(key)
                rendered.append(f"{key}=")
            rendered.append("")
        if selected_adapter == "edc":
            rendered.append("# EDC adapter options")
            rendered.append("EDC_DASHBOARD_ENABLED=")
            rendered.append("EDC_CONNECTOR_NAMES=")
            rendered.append("")
        return "\n".join(rendered).rstrip() + "\n"

    if selected_topology != "vm-distributed":
        return "".join(f"{key}=\n" for key in _vm_distributed_profile_template_keys(topology, selected_adapter))

    sections = (
        (
            "Local validation-environment profile.\n"
            "This file is ignored by Git and must not contain passwords, tokens or private keys.",
            ("PROFILE_TOPOLOGY", "PROFILE_ADAPTER", "ENVIRONMENT_NAME", "FRAMEWORK_EXECUTION_MODE"),
        ),
        (
            "Common and dataspace domains",
            ("DOMAIN_BASE", "DS_DOMAIN_BASE", "TOPOLOGY_ROUTING_MODE"),
        ),
        (
            "Common service public routes",
            (
                "KEYCLOAK_FRONTEND_URL",
                "KEYCLOAK_PUBLIC_URL",
                "MINIO_API_PUBLIC_URL",
                "MINIO_CONSOLE_PUBLIC_URL",
                "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES_ENABLED",
                "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES",
                "COMPONENTS_PUBLIC_BASE_URL",
                "COMPONENTS_PUBLIC_PATH_REWRITE",
                "VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER",
            ),
        ),
        (
            "Component images",
            (
                "COMPONENTS_IMAGE_PULL_POLICY",
                "ONTOLOGY_HUB_IMAGE_REF",
                "AI_MODEL_HUB_IMAGE_REF",
                "SEMANTIC_VIRTUALIZATION_IMAGE_REF",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_REF",
            ),
        ),
        (
            "AI Model Hub model server",
            (
                "AI_MODEL_HUB_MODEL_SERVER_IMAGE",
                "AI_MODEL_HUB_MODEL_SERVER_MODE",
                "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR",
                "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY",
                "AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH",
                "AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH",
                "AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT",
                "AI_MODEL_HUB_MODEL_SERVER_DOCKER_BASE_IMAGE",
                "AI_MODEL_HUB_MODEL_SERVER_UVICORN_APP",
                "AI_MODEL_HUB_MODEL_SERVER_IMAGE_PULL_POLICY",
                "AI_MODEL_HUB_MODEL_SERVER_COPY_EXCLUDES",
                "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
                "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
            ),
        ),
        (
            "VM placement",
            (
                "VM_EXTERNAL_IP",
                "VM_COMMON_IP",
                "VM_DATASPACE_IP",
                "VM_PROVIDER_IP",
                "VM_CONSUMER_IP",
                "VM_CONNECTORS_IP",
                "VM_COMPONENTS_IP",
                "VM_OBSERVABILITY_IP",
                "INGRESS_EXTERNAL_IP",
                "VM_PUBLIC_PROXY_IP",
                "VM_PROVIDER_K8S_NODE",
                "VM_CONSUMER_K8S_NODE",
            ),
        ),
        (
            "Kubernetes access",
            (
                "CLUSTER_TYPE",
                "K3S_KUBECONFIG",
                "K3S_KUBECONFIG_COMMON",
                "K3S_KUBECONFIG_PROVIDER",
                "K3S_KUBECONFIG_CONSUMER",
                "K3S_KUBECONFIG_COMPONENTS",
                "K3S_INSTALL_EXEC",
                "K3S_SERVICE_NAME",
                "K3S_INGRESS_CONTROLLER",
                "K3S_INGRESS_SERVICE_TYPE",
                "K3S_INGRESS_HTTP_NODEPORT",
                "K3S_REPAIR_ON_LEVEL1",
                "K3S_WRITE_KUBECONFIG_MODE",
            ),
        ),
        (
            "Connector placement and public routes",
            (
                "VM_PROVIDER_CONNECTORS",
                "VM_CONSUMER_CONNECTORS",
                "VM_PROVIDER_INGRESS_HTTP_PORT",
                "VM_CONSUMER_INGRESS_HTTP_PORT",
                "VM_PROVIDER_INGRESS_NODEPORT",
                "VM_CONSUMER_INGRESS_NODEPORT",
                "VM_COMMON_PUBLIC_URL",
                "VM_PROVIDER_PUBLIC_URL",
                "VM_CONSUMER_PUBLIC_URL",
                "VM_COMMON_HTTP_URL",
                "VM_PROVIDER_HTTP_URL",
                "VM_CONSUMER_HTTP_URL",
                "CONNECTOR_PROTOCOL_ADDRESS_MODE",
            ),
        ),
        (
            "SSH metadata",
            (
                "VM_SSH_USER",
                "SSH_ACCESS_MODE",
                "SSH_BASTION_HOST",
                "SSH_BASTION_PORT",
                "SSH_BASTION_USER",
                "SSH_BASTION_IDENTITY_FILE",
                "SSH_IDENTITY_FILE",
                "SSH_CONNECT_TIMEOUT_SECONDS",
                "VM_COMMON_SSH_HOST",
                "VM_COMMON_SSH_PORT",
                "VM_COMMON_SSH_USER",
                "VM_COMPONENTS_SSH_HOST",
                "VM_COMPONENTS_SSH_PORT",
                "VM_COMPONENTS_SSH_USER",
                "VM_PROVIDER_SSH_HOST",
                "VM_PROVIDER_SSH_PORT",
                "VM_PROVIDER_SSH_USER",
                "VM_CONSUMER_SSH_HOST",
                "VM_CONSUMER_SSH_PORT",
                "VM_CONSUMER_SSH_USER",
            ),
        ),
        (
            "Orchestration behavior",
            (
                "KEYCLOAK_BOOTSTRAP_PORT_FORWARD",
                "VM_DISTRIBUTED_EXECUTION_HOST",
                "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH",
                "VM_DISTRIBUTED_INFER_LOCAL_WORKDIR",
                "VM_DISTRIBUTED_KUBECONFIG_AUTO_LOCALIZE",
                "VM_DISTRIBUTED_KUBECONFIG_DIR",
                "VM_DISTRIBUTED_KUBECONFIG_SYNC",
                "VM_DISTRIBUTED_REMOTE_KUBECONFIG",
                "VM_DISTRIBUTED_HTTP_PREFLIGHT_TLS_VERIFY",
                "VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE",
                "VM_DISTRIBUTED_SSH_KEY_COMMENT",
                "VM_DISTRIBUTED_SSH_MANAGED_MARKER",
                "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY",
                "VM_DISTRIBUTED_DEPLOYMENT_MODE",
                "VM_DISTRIBUTED_PREFLIGHT_DRY_RUN",
                "VM_DISTRIBUTED_K3S_TUNNEL_MODE",
                "VM_DISTRIBUTED_K3S_API_REMOTE_PORT",
                "VM_DISTRIBUTED_K3S_TUNNEL_RECREATE",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY",
                "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE",
                "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP",
            ),
        ),
        (
            "Dataspace and connector inventory",
            (
                "DS_1_NAME",
                "DS_1_NAMESPACE",
                "NAMESPACE_PROFILE",
                "DS_1_REGISTRATION_NAMESPACE",
                "DS_1_PROVIDER_NAMESPACE",
                "DS_1_CONSUMER_NAMESPACE",
                "COMMON_SERVICES_NAMESPACE",
                "COMPONENTS_NAMESPACE",
                "DS_1_CONNECTORS",
                "DS_1_CONNECTOR_NAMESPACES",
                "DS_1_VALIDATION_PAIRS",
                "LEVEL4_CONNECTOR_RECONCILIATION_MODE",
                "COMPONENTS",
            ),
        ),
    )
    rendered = []
    emitted = set()
    for title, keys in sections:
        for comment_line in str(title).splitlines():
            rendered.append(f"# {comment_line}")
        for key in keys:
            if key in emitted:
                continue
            emitted.add(key)
            rendered.append(f"{key}=")
        rendered.append("")
    if selected_adapter == "edc":
        rendered.append("# EDC adapter options")
        rendered.append("EDC_DASHBOARD_ENABLED=")
        rendered.append("EDC_CONNECTOR_NAMES=")
        rendered.append("")
    return "\n".join(rendered).rstrip() + "\n"


def _ensure_environment_profile_file(profile_name=None, topology="vm-distributed", adapter_name="inesdata"):
    profile_path = _environment_profile_path(profile_name)
    if os.path.isfile(profile_path):
        return {"status": "exists", "path": profile_path}
    os.makedirs(os.path.dirname(profile_path), exist_ok=True)
    with open(profile_path, "w", encoding="utf-8") as handle:
        handle.write(
            _vm_distributed_profile_template_content(
                topology=topology,
                adapter_name=adapter_name,
            )
        )
    return {"status": "created", "path": profile_path}


def _ensure_pionera_environment_profile_file(topology="vm-distributed", adapter_name="inesdata"):
    return _ensure_environment_profile_file(
        DEFAULT_ENVIRONMENT_PROFILE_NAME,
        topology=topology,
        adapter_name=adapter_name,
    )


def _ensure_vm_distributed_profile_file(adapter_name="inesdata"):
    pionera_state = _ensure_pionera_environment_profile_file(
        topology="vm-distributed",
        adapter_name=adapter_name,
    )
    current_name = _environment_profile_name()
    if current_name == DEFAULT_ENVIRONMENT_PROFILE_NAME:
        return pionera_state
    return _ensure_environment_profile_file(
        current_name,
        topology="vm-distributed",
        adapter_name=adapter_name,
    )


def _load_vm_distributed_wizard_profile_suggestions(adapter_name=""):
    profile_state = _ensure_vm_distributed_profile_file(adapter_name=adapter_name)
    profile_path = profile_state["path"]
    if profile_state.get("status") == "created":
        return {
            "status": "created",
            "path": profile_path,
            "content": _read_vm_distributed_profile_content(profile_path),
            "values": {},
        }

    profile_values, parse_errors = _load_vm_distributed_profile(profile_path)
    if parse_errors:
        return {
            "status": "failed",
            "path": profile_path,
            "reason": "invalid-profile",
            "errors": parse_errors,
            "values": {},
        }
    if not profile_values:
        return {
            "status": "template",
            "path": profile_path,
            "content": _read_vm_distributed_profile_content(profile_path),
            "values": {},
        }
    scope_errors = _validate_configuration_profile_scope(
        profile_values,
        topology="vm-distributed",
        adapter_name=adapter_name,
    )
    _grouped, rejected = _split_configuration_profile_updates(
        profile_values,
        topology="vm-distributed",
        adapter_name=adapter_name,
    )
    rejected = scope_errors + rejected
    if rejected:
        return {
            "status": "failed",
            "path": profile_path,
            "reason": "profile-has-unsupported-keys",
            "rejected": rejected,
            "values": {},
        }
    return {
        "status": "loaded",
        "path": profile_path,
        "content": _read_vm_distributed_profile_content(profile_path),
        "values": profile_values,
    }


def _print_vm_distributed_wizard_profile_suggestions(profile):
    payload = dict(profile or {})
    status = str(payload.get("status") or "not-found")
    if status in {"not-found", "created", "template"}:
        print()
        if status == "created":
            print("Configuration profile created.")
        elif status == "template":
            print("Configuration profile exists but has no active KEY=VALUE entries.")
        else:
            print("Configuration profile: not found.")
        print(f"Profile location: {_framework_relative_path(payload.get('path') or _vm_distributed_profile_path())}")
        if status in {"created", "template"}:
            print("Fill this file, then run W -> 1 again to review and apply it.")
        return

    print()
    if status == "loaded":
        print(f"Configuration profile detected: {_framework_relative_path(payload.get('path'))}")
        print("Profile content:")
        print("-" * 50)
        content = str(payload.get("content") or "").rstrip()
        print(content or "(empty)")
        print("-" * 50)
        print("This profile contains only supported non-sensitive keys.")
        return

    print(f"Configuration profile ignored: {_framework_relative_path(payload.get('path'))}")
    if payload.get("reason"):
        print(f"Reason: {payload.get('reason')}")
    for item in list(payload.get("errors") or []):
        line = item.get("line")
        prefix = f"line {line}: " if line else ""
        print(f"- {prefix}{item.get('message')}")
    for item in list(payload.get("rejected") or []):
        print(f"- {item.get('key')}: {item.get('message')}")


def _vm_distributed_profile_suggestion(profile_values, key):
    if key in dict(profile_values or {}):
        return dict(profile_values or {}).get(key)
    return None


def _print_vm_distributed_profile_result(result):
    payload = dict(result or {})
    print()
    print("vm-distributed profile result:")
    print(f"  Status: {payload.get('status') or 'unknown'}")
    if payload.get("reason"):
        print(f"  Reason: {payload.get('reason')}")
    if payload.get("profile"):
        print(f"  Profile: {payload.get('profile')}")
    errors = list(payload.get("errors") or [])
    if errors:
        print("  Errors:")
        for item in errors:
            line = item.get("line")
            prefix = f"line {line}: " if line else ""
            print(f"  - {prefix}{item.get('message')}")
    rejected = list(payload.get("rejected") or [])
    if rejected:
        print("  Rejected keys:")
        for item in rejected:
            print(f"  - {item.get('key')}: {item.get('message')}")
    updated_files = list(payload.get("updated_files") or [])
    if updated_files:
        print("  Updated files:")
        for path in updated_files:
            print(f"  - {path}")
    updated_keys = dict(payload.get("updated_keys") or {})
    if updated_keys:
        print("  Updated key groups:")
        for group, keys in updated_keys.items():
            print(f"  - {group}: {', '.join(keys)}")
    if payload.get("preflight"):
        _print_vm_distributed_preflight(payload.get("preflight"))


def _run_vm_distributed_configuration_wizard_impl(current_adapter=None, adapter_registry=None):
    registry = adapter_registry or ADAPTER_REGISTRY
    selected_adapter = _interactive_require_adapter_selection(
        current_adapter,
        adapter_registry=registry,
    )
    if not selected_adapter:
        return {"status": "cancelled", "topology": "vm-distributed"}

    print()
    print("=" * 50)
    print("VM-DISTRIBUTED CONFIGURATION")
    print("=" * 50)
    print("Type ? in any field to show what the value means and Ubuntu discovery commands.")
    print("Local .config files will be updated; versioned .example files are not overwritten.")
    print()

    _seed_infrastructure_deployer_config_if_missing()
    topology_path = _seed_infrastructure_topology_config_if_missing("vm-distributed")
    adapter_path = _seed_adapter_deployer_config_if_missing(selected_adapter)

    infrastructure_config = load_raw_deployer_config(_infrastructure_deployer_config_path())
    topology_config = load_raw_deployer_config(topology_path)
    adapter_config = load_raw_deployer_config(adapter_path)
    effective_infrastructure_config = _effective_topology_scoped_infrastructure_config(
        infrastructure_config,
        topology_config,
        topology="vm-distributed",
    )
    profile_suggestions = _load_vm_distributed_wizard_profile_suggestions(selected_adapter)
    _print_vm_distributed_wizard_profile_suggestions(profile_suggestions)
    profile_values = dict(profile_suggestions.get("values") or {})
    if profile_suggestions.get("status") == "loaded":
        if _interactive_confirm("Apply this profile now?", default=False):
            result = apply_vm_distributed_configuration_profile(
                profile_suggestions.get("path"),
                adapter_name=selected_adapter,
            )
            _print_vm_distributed_profile_result(result)
            print()
            print("Next suggested step: W -> 4 (non-destructive SSH/HTTP preflight).")
            return result
        print("Profile not applied. Returning to the main menu without changes.")
        return {
            "status": "cancelled",
            "reason": "profile-not-applied",
            "topology": "vm-distributed",
            "adapter": selected_adapter,
            "profile": os.path.abspath(os.path.expanduser(str(profile_suggestions.get("path") or ""))),
        }

    def profile_value(key):
        return _vm_distributed_profile_suggestion(profile_values, key)

    domain_base = _prompt_vm_distributed_value(
        "Base domain for common services",
        current=topology_config.get("DOMAIN_BASE") or infrastructure_config.get("DOMAIN_BASE"),
        default="validation.example.local",
        required=True,
        help_topic="common-domain",
        profile_value=profile_value("DOMAIN_BASE"),
    )
    ds_domain_base = _prompt_vm_distributed_value(
        "Base domain for dataspace/connectors",
        current=topology_config.get("DS_DOMAIN_BASE") or infrastructure_config.get("DS_DOMAIN_BASE"),
        default=f"ds.{domain_base}" if domain_base else "",
        required=True,
        help_topic="dataspace-domain",
        profile_value=profile_value("DS_DOMAIN_BASE"),
    )
    framework_execution_mode = _prompt_vm_distributed_value(
        "Framework execution mode (auto/orchestrator/target-vm)",
        current=topology_config.get("FRAMEWORK_EXECUTION_MODE"),
        default="auto",
        required=True,
        help_topic="framework-execution",
        profile_value=profile_value("FRAMEWORK_EXECUTION_MODE"),
    )
    routing_mode = _prompt_vm_distributed_value(
        "Topology routing mode",
        current=topology_config.get("TOPOLOGY_ROUTING_MODE") or infrastructure_config.get("TOPOLOGY_ROUTING_MODE"),
        default="host",
        required=True,
        help_topic="routing",
        profile_value=profile_value("TOPOLOGY_ROUTING_MODE"),
    )

    common_ip = _prompt_vm_distributed_value(
        "Common services VM IP/DNS",
        current=topology_config.get("VM_COMMON_IP"),
        default=topology_config.get("VM_EXTERNAL_IP"),
        required=True,
        help_topic="common-address",
        profile_value=profile_value("VM_COMMON_IP") or profile_value("VM_EXTERNAL_IP"),
    )
    provider_ip = _prompt_vm_distributed_value(
        "Provider-side connector VM IP/DNS",
        current=topology_config.get("VM_PROVIDER_IP"),
        default=topology_config.get("VM_CONNECTORS_IP"),
        required=True,
        help_topic="provider-address",
        profile_value=profile_value("VM_PROVIDER_IP") or profile_value("VM_CONNECTORS_IP"),
    )
    consumer_ip = _prompt_vm_distributed_value(
        "Consumer-side connector VM IP/DNS",
        current=topology_config.get("VM_CONSUMER_IP"),
        default=provider_ip,
        required=True,
        help_topic="consumer-address",
        profile_value=profile_value("VM_CONSUMER_IP"),
    )
    components_ip = _prompt_vm_distributed_value(
        "Components VM IP/DNS",
        current=topology_config.get("VM_COMPONENTS_IP"),
        default=common_ip,
        required=False,
        help_topic="components-address",
        profile_value=profile_value("VM_COMPONENTS_IP"),
    )
    ingress_ip = _prompt_vm_distributed_value(
        "Ingress/public IP or DNS",
        current=topology_config.get("INGRESS_EXTERNAL_IP"),
        default=common_ip,
        required=False,
        help_topic="ingress-address",
        profile_value=profile_value("INGRESS_EXTERNAL_IP"),
    )
    ssh_user = _prompt_vm_distributed_value(
        "SSH user for remote NGINX sync",
        current=topology_config.get("VM_SSH_USER"),
        default="",
        required=False,
        help_topic="ssh-user",
        profile_value=profile_value("VM_SSH_USER"),
    )

    ssh_access_mode = _prompt_vm_distributed_value(
        "SSH access mode (blank/direct/bastion)",
        current=topology_config.get("SSH_ACCESS_MODE"),
        default="",
        required=False,
        help_topic="ssh-access",
        profile_value=profile_value("SSH_ACCESS_MODE"),
    )
    ssh_access_mode = str(ssh_access_mode or "").strip().lower().replace("_", "-")
    ssh_bastion_host = topology_config.get("SSH_BASTION_HOST") or ""
    ssh_bastion_port = topology_config.get("SSH_BASTION_PORT") or "2222"
    ssh_bastion_user = topology_config.get("SSH_BASTION_USER") or ""
    ssh_bastion_identity_file = topology_config.get("SSH_BASTION_IDENTITY_FILE") or ""
    common_ssh_host = topology_config.get("VM_COMMON_SSH_HOST") or ""
    common_ssh_port = topology_config.get("VM_COMMON_SSH_PORT") or "22"
    common_ssh_user = topology_config.get("VM_COMMON_SSH_USER") or ""
    provider_ssh_host = topology_config.get("VM_PROVIDER_SSH_HOST") or ""
    provider_ssh_port = topology_config.get("VM_PROVIDER_SSH_PORT") or "22"
    provider_ssh_user = topology_config.get("VM_PROVIDER_SSH_USER") or ""
    consumer_ssh_host = topology_config.get("VM_CONSUMER_SSH_HOST") or ""
    consumer_ssh_port = topology_config.get("VM_CONSUMER_SSH_PORT") or "22"
    consumer_ssh_user = topology_config.get("VM_CONSUMER_SSH_USER") or ""
    if ssh_access_mode in {"direct", "bastion"}:
        if ssh_access_mode == "bastion":
            ssh_bastion_host = _prompt_vm_distributed_value(
                "SSH bastion host",
                current=ssh_bastion_host,
                default="",
                required=True,
                help_topic="bastion",
                profile_value=profile_value("SSH_BASTION_HOST"),
            )
            ssh_bastion_port = _prompt_vm_distributed_value(
                "SSH bastion port",
                current=ssh_bastion_port,
                default="2222",
                required=False,
                help_topic="bastion",
                profile_value=profile_value("SSH_BASTION_PORT"),
            )
            ssh_bastion_user = _prompt_vm_distributed_value(
                "SSH bastion user",
                current=ssh_bastion_user,
                default="",
                required=False,
                help_topic="bastion",
                profile_value=profile_value("SSH_BASTION_USER"),
            )
            ssh_bastion_identity_file = _prompt_vm_distributed_value(
                "SSH bastion identity file",
                current=ssh_bastion_identity_file,
                default="",
                required=False,
                help_topic="bastion",
                profile_value=profile_value("SSH_BASTION_IDENTITY_FILE"),
            )
        common_ssh_host = _prompt_vm_distributed_value(
            "Common services SSH host/IP",
            current=common_ssh_host,
            default=common_ip,
            required=True,
            help_topic="common-ssh",
            profile_value=profile_value("VM_COMMON_SSH_HOST"),
        )
        common_ssh_port = _prompt_vm_distributed_value(
            "Common services SSH port",
            current=common_ssh_port,
            default="22",
            required=False,
            help_topic="common-ssh",
            profile_value=profile_value("VM_COMMON_SSH_PORT"),
        )
        common_ssh_user = _prompt_vm_distributed_value(
            "Common services SSH user",
            current=common_ssh_user,
            default="",
            required=False,
            help_topic="common-ssh",
            profile_value=profile_value("VM_COMMON_SSH_USER"),
        )
        provider_ssh_host = _prompt_vm_distributed_value(
            "Provider VM SSH host/IP",
            current=provider_ssh_host,
            default=provider_ip,
            required=True,
            help_topic="provider-ssh",
            profile_value=profile_value("VM_PROVIDER_SSH_HOST"),
        )
        provider_ssh_port = _prompt_vm_distributed_value(
            "Provider VM SSH port",
            current=provider_ssh_port,
            default="22",
            required=False,
            help_topic="provider-ssh",
            profile_value=profile_value("VM_PROVIDER_SSH_PORT"),
        )
        provider_ssh_user = _prompt_vm_distributed_value(
            "Provider VM SSH user",
            current=provider_ssh_user,
            default="",
            required=False,
            help_topic="provider-ssh",
            profile_value=profile_value("VM_PROVIDER_SSH_USER"),
        )
        consumer_ssh_host = _prompt_vm_distributed_value(
            "Consumer VM SSH host/IP",
            current=consumer_ssh_host,
            default=consumer_ip,
            required=True,
            help_topic="consumer-ssh",
            profile_value=profile_value("VM_CONSUMER_SSH_HOST"),
        )
        consumer_ssh_port = _prompt_vm_distributed_value(
            "Consumer VM SSH port",
            current=consumer_ssh_port,
            default="22",
            required=False,
            help_topic="consumer-ssh",
            profile_value=profile_value("VM_CONSUMER_SSH_PORT"),
        )
        consumer_ssh_user = _prompt_vm_distributed_value(
            "Consumer VM SSH user",
            current=consumer_ssh_user,
            default="",
            required=False,
            help_topic="consumer-ssh",
            profile_value=profile_value("VM_CONSUMER_SSH_USER"),
        )

    common_kubeconfig = _prompt_vm_distributed_value(
        "Common services kubeconfig path",
        current=topology_config.get("K3S_KUBECONFIG_COMMON") or topology_config.get("K3S_KUBECONFIG"),
        default="/etc/rancher/k3s/k3s.yaml",
        required=True,
        help_topic="common-kubeconfig",
        profile_value=profile_value("K3S_KUBECONFIG_COMMON") or profile_value("K3S_KUBECONFIG"),
    )
    provider_kubeconfig = _prompt_vm_distributed_value(
        "Provider-side kubeconfig path",
        current=topology_config.get("K3S_KUBECONFIG_PROVIDER"),
        default=common_kubeconfig,
        required=True,
        help_topic="provider-kubeconfig",
        profile_value=profile_value("K3S_KUBECONFIG_PROVIDER"),
    )
    consumer_kubeconfig = _prompt_vm_distributed_value(
        "Consumer-side kubeconfig path",
        current=topology_config.get("K3S_KUBECONFIG_CONSUMER"),
        default=provider_kubeconfig,
        required=True,
        help_topic="consumer-kubeconfig",
        profile_value=profile_value("K3S_KUBECONFIG_CONSUMER"),
    )
    components_kubeconfig = _prompt_vm_distributed_value(
        "Components kubeconfig path",
        current=topology_config.get("K3S_KUBECONFIG_COMPONENTS"),
        default=common_kubeconfig,
        required=True,
        help_topic="components-kubeconfig",
        profile_value=profile_value("K3S_KUBECONFIG_COMPONENTS"),
    )

    dataspace_name = _prompt_vm_distributed_value(
        "Dataspace name",
        current=adapter_config.get("DS_1_NAME"),
        default="pionera",
        required=True,
        help_topic="dataspace",
        profile_value=profile_value("DS_1_NAME"),
    )
    connectors = _prompt_vm_distributed_value(
        "Connector inventory (comma-separated short names)",
        current=adapter_config.get("DS_1_CONNECTORS"),
        default="citycounciledc,companyedc" if selected_adapter == "edc" else "org2,org3",
        required=True,
        help_topic="connector-inventory",
        profile_value=profile_value("DS_1_CONNECTORS"),
    )
    connector_namespaces = _prompt_vm_distributed_value(
        "Connector locations (connector:group, comma-separated)",
        current=adapter_config.get("DS_1_CONNECTOR_NAMESPACES"),
        default=_default_vm_distributed_connector_locations(connectors),
        required=False,
        help_topic="connector-locations",
        profile_value=profile_value("DS_1_CONNECTOR_NAMESPACES"),
    )
    validation_pairs = _prompt_vm_distributed_value(
        "Validation pairs (source>target, comma-separated)",
        current=adapter_config.get("DS_1_VALIDATION_PAIRS"),
        default=_default_vm_distributed_validation_pairs(connectors),
        required=False,
        help_topic="validation-pairs",
        profile_value=profile_value("DS_1_VALIDATION_PAIRS"),
    )
    reconciliation_mode = _prompt_vm_distributed_value(
        "Level 4 connector reconciliation mode (full/additive)",
        current=adapter_config.get("LEVEL4_CONNECTOR_RECONCILIATION_MODE"),
        default="full",
        required=True,
        help_topic="reconciliation",
        profile_value=profile_value("LEVEL4_CONNECTOR_RECONCILIATION_MODE"),
    )

    common_service_updates = _vm_distributed_common_service_public_updates(
        domain_base,
        {
            **effective_infrastructure_config,
            **topology_config,
            "DOMAIN_BASE": domain_base,
            "DS_DOMAIN_BASE": ds_domain_base,
        },
    )
    public_url_updates = resolve_vm_distributed_public_urls(
        {
            **effective_infrastructure_config,
            **topology_config,
            "DOMAIN_BASE": domain_base,
            "DS_DOMAIN_BASE": ds_domain_base,
        }
    )
    topology_updates = {
        "DOMAIN_BASE": domain_base,
        "DS_DOMAIN_BASE": ds_domain_base,
        "FRAMEWORK_EXECUTION_MODE": _normalized_framework_execution_mode(
            {"FRAMEWORK_EXECUTION_MODE": framework_execution_mode}
        ),
        **common_service_updates,
        "VM_EXTERNAL_IP": common_ip,
        "VM_COMMON_IP": common_ip,
        "VM_DATASPACE_IP": common_ip,
        "VM_PROVIDER_IP": provider_ip,
        "VM_CONSUMER_IP": consumer_ip,
        "VM_PROVIDER_K8S_NODE": topology_config.get("VM_PROVIDER_K8S_NODE") or "",
        "VM_CONSUMER_K8S_NODE": topology_config.get("VM_CONSUMER_K8S_NODE") or "",
        "VM_CONNECTORS_IP": provider_ip,
        "VM_COMPONENTS_IP": components_ip or common_ip,
        "VM_OBSERVABILITY_IP": components_ip or common_ip,
        "VM_SSH_USER": ssh_user,
        "INGRESS_EXTERNAL_IP": ingress_ip or common_ip,
        "CLUSTER_TYPE": "k3s",
        "K3S_KUBECONFIG": common_kubeconfig,
        "K3S_KUBECONFIG_COMMON": common_kubeconfig,
        "K3S_KUBECONFIG_PROVIDER": provider_kubeconfig,
        "K3S_KUBECONFIG_CONSUMER": consumer_kubeconfig,
        "K3S_KUBECONFIG_COMPONENTS": components_kubeconfig,
        "K3S_INSTALL_EXEC": topology_config.get("K3S_INSTALL_EXEC") or "--disable=traefik",
        "K3S_SERVICE_NAME": topology_config.get("K3S_SERVICE_NAME") or "k3s",
        "K3S_INGRESS_CONTROLLER": topology_config.get("K3S_INGRESS_CONTROLLER") or "ingress-nginx",
        "K3S_INGRESS_SERVICE_TYPE": topology_config.get("K3S_INGRESS_SERVICE_TYPE") or "LoadBalancer",
        "K3S_REPAIR_ON_LEVEL1": topology_config.get("K3S_REPAIR_ON_LEVEL1") or "prompt",
        "K3S_WRITE_KUBECONFIG_MODE": topology_config.get("K3S_WRITE_KUBECONFIG_MODE") or "0644",
        "TOPOLOGY_ROUTING_MODE": routing_mode,
        "VM_PROVIDER_CONNECTORS": ",".join(
            item.split(":", 1)[0].strip()
            for item in connector_namespaces.split(",")
            if ":" in item and item.split(":", 1)[1].strip().lower() == "provider"
        ),
        "VM_CONSUMER_CONNECTORS": ",".join(
            item.split(":", 1)[0].strip()
            for item in connector_namespaces.split(",")
            if ":" in item and item.split(":", 1)[1].strip().lower() == "consumer"
        ),
        "SSH_ACCESS_MODE": ssh_access_mode,
        "SSH_BASTION_HOST": ssh_bastion_host,
        "SSH_BASTION_PORT": ssh_bastion_port,
        "SSH_BASTION_USER": ssh_bastion_user,
        "SSH_BASTION_IDENTITY_FILE": ssh_bastion_identity_file,
        "SSH_IDENTITY_FILE": topology_config.get("SSH_IDENTITY_FILE") or "",
        "SSH_CONNECT_TIMEOUT_SECONDS": topology_config.get("SSH_CONNECT_TIMEOUT_SECONDS") or "5",
        "VM_DISTRIBUTED_SSH_IDENTITY_FILE": topology_config.get("VM_DISTRIBUTED_SSH_IDENTITY_FILE") or "",
        "VM_DISTRIBUTED_EXECUTION_HOST": topology_config.get("VM_DISTRIBUTED_EXECUTION_HOST") or "auto",
        "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH": topology_config.get("VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH") or "true",
        "VM_DISTRIBUTED_INFER_LOCAL_WORKDIR": topology_config.get("VM_DISTRIBUTED_INFER_LOCAL_WORKDIR") or "true",
        "VM_DISTRIBUTED_KUBECONFIG_AUTO_LOCALIZE": topology_config.get("VM_DISTRIBUTED_KUBECONFIG_AUTO_LOCALIZE") or "true",
        "VM_DISTRIBUTED_KUBECONFIG_DIR": topology_config.get("VM_DISTRIBUTED_KUBECONFIG_DIR") or "~/.kube",
        "VM_DISTRIBUTED_KUBECONFIG_SYNC": topology_config.get("VM_DISTRIBUTED_KUBECONFIG_SYNC") or "auto",
        "VM_DISTRIBUTED_REMOTE_KUBECONFIG": (
            topology_config.get("VM_DISTRIBUTED_REMOTE_KUBECONFIG") or "/etc/rancher/k3s/k3s.yaml"
        ),
        "VM_COMMON_REMOTE_KUBECONFIG": topology_config.get("VM_COMMON_REMOTE_KUBECONFIG") or "",
        "VM_PROVIDER_REMOTE_KUBECONFIG": topology_config.get("VM_PROVIDER_REMOTE_KUBECONFIG") or "",
        "VM_CONSUMER_REMOTE_KUBECONFIG": topology_config.get("VM_CONSUMER_REMOTE_KUBECONFIG") or "",
        "VM_COMPONENTS_REMOTE_KUBECONFIG": topology_config.get("VM_COMPONENTS_REMOTE_KUBECONFIG") or "",
        "VM_DISTRIBUTED_HTTP_PREFLIGHT_TLS_VERIFY": (
            topology_config.get("VM_DISTRIBUTED_HTTP_PREFLIGHT_TLS_VERIFY") or "auto"
        ),
        "VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE": topology_config.get("VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE") or "manual",
        "VM_DISTRIBUTED_SSH_KEY_COMMENT": (
            topology_config.get("VM_DISTRIBUTED_SSH_KEY_COMMENT")
            or "validation-environment-vm-distributed"
        ),
        "VM_DISTRIBUTED_SSH_MANAGED_MARKER": (
            topology_config.get("VM_DISTRIBUTED_SSH_MANAGED_MARKER")
            or "validation-environment-vm-distributed"
        ),
        "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY": (
            topology_config.get("VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY")
            or "accept-new"
        ),
        "VM_DISTRIBUTED_DEPLOYMENT_MODE": topology_config.get("VM_DISTRIBUTED_DEPLOYMENT_MODE") or "orchestrator",
        "VM_DISTRIBUTED_PREFLIGHT_DRY_RUN": topology_config.get("VM_DISTRIBUTED_PREFLIGHT_DRY_RUN") or "true",
        "VM_DISTRIBUTED_K3S_TUNNEL_MODE": topology_config.get("VM_DISTRIBUTED_K3S_TUNNEL_MODE") or "auto",
        "VM_DISTRIBUTED_K3S_API_REMOTE_PORT": topology_config.get("VM_DISTRIBUTED_K3S_API_REMOTE_PORT") or "6443",
        "VM_DISTRIBUTED_K3S_TUNNEL_RECREATE": topology_config.get("VM_DISTRIBUTED_K3S_TUNNEL_RECREATE") or "auto",
        "VM_COMMON_K3S_API_LOCAL_PORT": topology_config.get("VM_COMMON_K3S_API_LOCAL_PORT") or "6443",
        "VM_PROVIDER_K3S_API_LOCAL_PORT": topology_config.get("VM_PROVIDER_K3S_API_LOCAL_PORT") or "26443",
        "VM_CONSUMER_K3S_API_LOCAL_PORT": topology_config.get("VM_CONSUMER_K3S_API_LOCAL_PORT") or "36443",
        "VM_COMPONENTS_K3S_API_LOCAL_PORT": topology_config.get("VM_COMPONENTS_K3S_API_LOCAL_PORT") or "6443",
        "VM_REMOTE_WORKDIR": topology_config.get("VM_REMOTE_WORKDIR") or "",
        "VM_COMMON_REMOTE_WORKDIR": topology_config.get("VM_COMMON_REMOTE_WORKDIR") or topology_config.get("VM_REMOTE_WORKDIR") or "",
        "VM_PROVIDER_REMOTE_WORKDIR": topology_config.get("VM_PROVIDER_REMOTE_WORKDIR") or topology_config.get("VM_REMOTE_WORKDIR") or "",
        "VM_CONSUMER_REMOTE_WORKDIR": topology_config.get("VM_CONSUMER_REMOTE_WORKDIR") or topology_config.get("VM_REMOTE_WORKDIR") or "",
        "VM_COMMON_PUBLIC_URL": public_url_updates.get("VM_COMMON_PUBLIC_URL") or "",
        "VM_PROVIDER_PUBLIC_URL": public_url_updates.get("VM_PROVIDER_PUBLIC_URL") or "",
        "VM_CONSUMER_PUBLIC_URL": public_url_updates.get("VM_CONSUMER_PUBLIC_URL") or "",
        "KEYCLOAK_FRONTEND_URL": (
            public_url_updates.get("KEYCLOAK_FRONTEND_URL")
            or _usable_vm_public_url_config_value(topology_config.get("KEYCLOAK_FRONTEND_URL"))
        ),
        "KEYCLOAK_PUBLIC_URL": (
            public_url_updates.get("KEYCLOAK_PUBLIC_URL")
            or _usable_vm_public_url_config_value(topology_config.get("KEYCLOAK_PUBLIC_URL"))
        ),
        "MINIO_API_PUBLIC_URL": _usable_vm_public_url_config_value(topology_config.get("MINIO_API_PUBLIC_URL")),
        "MINIO_CONSOLE_PUBLIC_URL": public_url_updates.get("MINIO_CONSOLE_PUBLIC_URL") or "",
        "MINIO_PUBLIC_URL": _usable_vm_public_url_config_value(topology_config.get("MINIO_PUBLIC_URL")),
        "COMPONENTS_PUBLIC_BASE_URL": public_url_updates.get("COMPONENTS_PUBLIC_BASE_URL") or "",
        "COMPONENTS_PUBLIC_PATH_REWRITE": topology_config.get("COMPONENTS_PUBLIC_PATH_REWRITE") or "true",
        "VM_COMMON_HTTP_URL": topology_config.get("VM_COMMON_HTTP_URL") or (f"http://{common_ip}" if common_ip else ""),
        "VM_PROVIDER_HTTP_URL": topology_config.get("VM_PROVIDER_HTTP_URL") or (f"http://{provider_ip}" if provider_ip else ""),
        "VM_CONSUMER_HTTP_URL": topology_config.get("VM_CONSUMER_HTTP_URL") or (f"http://{consumer_ip}" if consumer_ip else ""),
        "VM_COMMON_SSH_HOST": common_ssh_host,
        "VM_COMMON_SSH_PORT": common_ssh_port,
        "VM_COMMON_SSH_USER": common_ssh_user,
        "VM_COMMON_SSH_IDENTITY_FILE": topology_config.get("VM_COMMON_SSH_IDENTITY_FILE") or "",
        "VM_COMMON_SSH_ACCESS_MODE": topology_config.get("VM_COMMON_SSH_ACCESS_MODE") or "",
        "VM_COMMON_SSH_BASTION_HOST": topology_config.get("VM_COMMON_SSH_BASTION_HOST") or "",
        "VM_COMMON_SSH_BASTION_PORT": topology_config.get("VM_COMMON_SSH_BASTION_PORT") or "2222",
        "VM_COMMON_SSH_BASTION_USER": topology_config.get("VM_COMMON_SSH_BASTION_USER") or "",
        "VM_COMMON_SSH_BASTION_IDENTITY_FILE": topology_config.get("VM_COMMON_SSH_BASTION_IDENTITY_FILE") or "",
        "VM_COMPONENTS_SSH_HOST": topology_config.get("VM_COMPONENTS_SSH_HOST") or common_ssh_host,
        "VM_COMPONENTS_SSH_PORT": topology_config.get("VM_COMPONENTS_SSH_PORT") or common_ssh_port,
        "VM_COMPONENTS_SSH_USER": topology_config.get("VM_COMPONENTS_SSH_USER") or common_ssh_user,
        "VM_COMPONENTS_SSH_IDENTITY_FILE": topology_config.get("VM_COMPONENTS_SSH_IDENTITY_FILE") or "",
        "VM_COMPONENTS_SSH_ACCESS_MODE": topology_config.get("VM_COMPONENTS_SSH_ACCESS_MODE") or "",
        "VM_COMPONENTS_SSH_BASTION_HOST": topology_config.get("VM_COMPONENTS_SSH_BASTION_HOST") or "",
        "VM_COMPONENTS_SSH_BASTION_PORT": topology_config.get("VM_COMPONENTS_SSH_BASTION_PORT") or "2222",
        "VM_COMPONENTS_SSH_BASTION_USER": topology_config.get("VM_COMPONENTS_SSH_BASTION_USER") or "",
        "VM_COMPONENTS_SSH_BASTION_IDENTITY_FILE": topology_config.get("VM_COMPONENTS_SSH_BASTION_IDENTITY_FILE") or "",
        "VM_PROVIDER_SSH_HOST": provider_ssh_host,
        "VM_PROVIDER_SSH_PORT": provider_ssh_port,
        "VM_PROVIDER_SSH_USER": provider_ssh_user,
        "VM_PROVIDER_SSH_IDENTITY_FILE": topology_config.get("VM_PROVIDER_SSH_IDENTITY_FILE") or "",
        "VM_PROVIDER_SSH_ACCESS_MODE": topology_config.get("VM_PROVIDER_SSH_ACCESS_MODE") or "",
        "VM_PROVIDER_SSH_BASTION_HOST": topology_config.get("VM_PROVIDER_SSH_BASTION_HOST") or "",
        "VM_PROVIDER_SSH_BASTION_PORT": topology_config.get("VM_PROVIDER_SSH_BASTION_PORT") or "2222",
        "VM_PROVIDER_SSH_BASTION_USER": topology_config.get("VM_PROVIDER_SSH_BASTION_USER") or "",
        "VM_PROVIDER_SSH_BASTION_IDENTITY_FILE": topology_config.get("VM_PROVIDER_SSH_BASTION_IDENTITY_FILE") or "",
        "VM_CONSUMER_SSH_HOST": consumer_ssh_host,
        "VM_CONSUMER_SSH_PORT": consumer_ssh_port,
        "VM_CONSUMER_SSH_USER": consumer_ssh_user,
        "VM_CONSUMER_SSH_IDENTITY_FILE": topology_config.get("VM_CONSUMER_SSH_IDENTITY_FILE") or "",
        "VM_CONSUMER_SSH_ACCESS_MODE": topology_config.get("VM_CONSUMER_SSH_ACCESS_MODE") or "",
        "VM_CONSUMER_SSH_BASTION_HOST": topology_config.get("VM_CONSUMER_SSH_BASTION_HOST") or "",
        "VM_CONSUMER_SSH_BASTION_PORT": topology_config.get("VM_CONSUMER_SSH_BASTION_PORT") or "2222",
        "VM_CONSUMER_SSH_BASTION_USER": topology_config.get("VM_CONSUMER_SSH_BASTION_USER") or "",
        "VM_CONSUMER_SSH_BASTION_IDENTITY_FILE": topology_config.get("VM_CONSUMER_SSH_BASTION_IDENTITY_FILE") or "",
    }
    adapter_updates = {
        "DS_1_NAME": dataspace_name,
        "DS_1_CONNECTORS": connectors,
        "DS_1_CONNECTOR_NAMESPACES": connector_namespaces,
        "DS_1_VALIDATION_PAIRS": validation_pairs,
        "LEVEL4_CONNECTOR_RECONCILIATION_MODE": _normalized_reconciliation_mode(reconciliation_mode) or "full",
    }

    if not _interactive_confirm("Save this vm-distributed configuration now?", default=True):
        print("vm-distributed configuration not saved.")
        print("Returning to the VM-DISTRIBUTED assistant; choose B or Q there to leave it.")
        return {"status": "cancelled", "adapter": selected_adapter, "topology": "vm-distributed"}

    _write_key_value_updates(
        topology_path,
        topology_updates,
        VM_DISTRIBUTED_TOPOLOGY_KEYS,
    )
    _write_key_value_updates(
        adapter_path,
        adapter_updates,
        VM_DISTRIBUTED_ADAPTER_KEYS,
    )

    preflight = _vm_distributed_configuration_preflight(
        load_raw_deployer_config(_infrastructure_deployer_config_path()),
        load_raw_deployer_config(topology_path),
        load_raw_deployer_config(adapter_path),
    )
    _print_vm_distributed_preflight(preflight)
    print()
    print("Updated files:")
    for path in (topology_path, adapter_path):
        print(f"- {_framework_relative_path(path)}")

    return {
        "status": "prepared" if preflight["status"] == "ready" else preflight["status"],
        "adapter": selected_adapter,
        "topology": "vm-distributed",
        "config_files": [
            _framework_relative_path(topology_path),
            _framework_relative_path(adapter_path),
        ],
        "preflight": preflight,
    }


def _run_vm_distributed_configuration_wizard(current_adapter=None, adapter_registry=None):
    return _run_vm_distributed_configuration_wizard_impl(
        current_adapter=current_adapter,
        adapter_registry=adapter_registry,
    )


def _vm_distributed_configuration_needs_attention(adapter_name=None):
    if not str(adapter_name or "").strip():
        return False
    topology_path = _infrastructure_topology_config_path("vm-distributed")
    adapter_path = _adapter_deployer_config_path(adapter_name) if adapter_name else ""
    infrastructure_config = load_raw_deployer_config(_infrastructure_deployer_config_path())
    topology_config = load_raw_deployer_config(topology_path)
    adapter_config = load_raw_deployer_config(adapter_path) if adapter_path else {}
    preflight = _vm_distributed_configuration_preflight(
        infrastructure_config,
        topology_config,
        adapter_config,
    )
    return preflight.get("status") != "ready"


def _interactive_confirm_vm_distributed_configuration(prompt, default=True):
    default_label = "Y/n" if default else "y/N"
    answer = _interactive_read(f"{prompt} ({default_label}): ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "s", "si", "sí"}


def _offer_vm_distributed_configuration(current_adapter=None, adapter_registry=None):
    if not str(current_adapter or "").strip():
        return current_adapter, None
    if not _vm_distributed_configuration_needs_attention(current_adapter):
        return current_adapter, None
    print()
    print("vm-distributed configuration is incomplete or needs review.")
    configure_now = _interactive_confirm_vm_distributed_configuration(
        "Configure vm-distributed now?",
        default=True,
    )
    if not configure_now:
        return current_adapter, None
    result = _run_vm_distributed_configuration_wizard(
        current_adapter=current_adapter,
        adapter_registry=adapter_registry,
    )
    if isinstance(result, dict):
        current_adapter = result.get("adapter") or current_adapter
    return current_adapter, result


def _load_vm_distributed_configuration_bundle(adapter_name=None):
    topology_path = _infrastructure_topology_config_path("vm-distributed")
    adapter_path = _adapter_deployer_config_path(adapter_name) if adapter_name else ""
    return {
        "infrastructure": load_raw_deployer_config(_infrastructure_deployer_config_path()),
        "topology": load_raw_deployer_config(topology_path),
        "adapter": load_raw_deployer_config(adapter_path) if adapter_path else {},
        "paths": {
            "infrastructure": _framework_relative_path(_infrastructure_deployer_config_path()),
            "topology": _framework_relative_path(topology_path),
            "adapter": _framework_relative_path(adapter_path) if adapter_path else "",
        },
    }


def _load_vm_single_configuration_bundle(adapter_name=None):
    topology_path = _infrastructure_topology_config_path("vm-single")
    adapter_path = _adapter_deployer_config_path(adapter_name) if adapter_name else ""
    return {
        "infrastructure": load_raw_deployer_config(_infrastructure_deployer_config_path()),
        "topology": load_raw_deployer_config(topology_path),
        "adapter": load_raw_deployer_config(adapter_path) if adapter_path else {},
        "paths": {
            "infrastructure": _framework_relative_path(_infrastructure_deployer_config_path()),
            "topology": _framework_relative_path(topology_path),
            "adapter": _framework_relative_path(adapter_path) if adapter_path else "",
        },
    }


def _current_vm_single_topology_plan(adapter_name=None):
    bundle = _load_vm_single_configuration_bundle(adapter_name=adapter_name)
    plan = _build_vm_single_topology_plan(
        bundle["infrastructure"],
        bundle["topology"],
        bundle["adapter"],
    )
    plan["config_files"] = bundle["paths"]
    return plan


def _local_host_addresses():
    addresses = {"127.0.0.1", "::1"}
    for hostname in {_safe_local_hostname()}:
        if not hostname:
            continue
        addresses.add(hostname)
        addresses.update(_resolve_host_addresses(hostname))
    try:
        completed = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if completed.returncode == 0:
            addresses.update(str(completed.stdout or "").split())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {address.strip() for address in addresses if str(address or "").strip()}


def _looks_like_ip_address(value):
    try:
        ipaddress.ip_address(str(value or "").strip())
        return True
    except ValueError:
        return False


def _resolve_host_addresses(host):
    value = str(host or "").strip()
    if not value:
        return set()
    addresses = {value}
    if _looks_like_ip_address(value):
        return addresses
    try:
        completed = subprocess.run(
            ["getent", "ahosts", value],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {address.strip() for address in addresses if str(address or "").strip()}
    if completed.returncode == 0:
        for raw_line in str(completed.stdout or "").splitlines():
            parts = raw_line.split()
            if parts:
                addresses.add(parts[0])
    return {address.strip() for address in addresses if str(address or "").strip()}


def _vm_single_running_on_target(plan):
    payload = dict(plan or {})
    vms = [item for item in list(payload.get("vms") or []) if isinstance(item, dict)]
    vm = vms[0] if vms else {}
    target_values = {
        str(vm.get("address") or "").strip(),
        str(((vm.get("ssh") or {}).get("host")) or "").strip(),
    }
    target_values.update(
        str(item.get("host") or "").strip()
        for item in list((payload.get("ssh_bootstrap") or {}).get("targets") or [])
        if isinstance(item, dict)
    )
    aliases = _vm_distributed_host_aliases()
    for value in list(target_values):
        if value and value.lower() in aliases:
            return True

    local_addresses = _local_host_addresses()
    target_addresses = set()
    for value in target_values:
        target_addresses.update(_resolve_host_addresses(value))
    return bool(local_addresses.intersection(target_addresses))


def _vm_single_remote_kubeconfig_path(topology_config):
    return _vm_distributed_config_value(
        topology_config,
        "VM_SINGLE_REMOTE_KUBECONFIG",
        default="/etc/rancher/k3s/k3s.yaml",
    ) or "/etc/rancher/k3s/k3s.yaml"


def _vm_single_local_kubeconfig_path(topology_config):
    configured = _vm_distributed_config_value(
        topology_config,
        "VM_SINGLE_LOCAL_KUBECONFIG",
        "K3S_KUBECONFIG",
    )
    if not configured or configured.startswith("/etc/rancher/"):
        configured = "~/.kube/vm-single-k3s.yaml"
    return os.path.abspath(os.path.expanduser(configured))


def _vm_single_effective_kubeconfig_path(topology_config, adapter_name=None):
    config = dict(topology_config or {})
    try:
        bundle = _load_vm_single_configuration_bundle(adapter_name=adapter_name)
        plan = _build_vm_single_topology_plan(
            bundle["infrastructure"],
            config or bundle["topology"],
            bundle["adapter"],
        )
        if _vm_single_running_on_target(plan):
            return _vm_single_remote_kubeconfig_path(config or bundle["topology"])
    except Exception:
        pass
    return _vm_single_local_kubeconfig_path(config)


def _ensure_vm_single_k3s_runtime_config(topology_config):
    runtime = build_cluster_runtime(topology_config or {}, topology=VM_SINGLE_TOPOLOGY)
    if runtime.get("cluster_type") != "k3s":
        raise RuntimeError(
            "Topology 'vm-single' must use k3s. "
            "Set CLUSTER_TYPE=k3s in deployers/infrastructure/topologies/vm-single.config "
            "or in the selected .profiles/*.env profile."
        )
    return runtime


def _vm_single_k3s_api_remote_port(topology_config):
    return _vm_distributed_config_value(
        topology_config,
        "VM_SINGLE_K3S_API_REMOTE_PORT",
        default="6443",
    ) or "6443"


def _vm_single_k3s_api_local_port(topology_config):
    configured = _vm_distributed_config_value(topology_config, "VM_SINGLE_K3S_API_LOCAL_PORT")
    if configured:
        return int(configured)
    kubeconfig = _vm_single_local_kubeconfig_path(topology_config)
    port = _kubeconfig_loopback_port(_kubeconfig_server(kubeconfig))
    return int(port or 46443)


def _vm_single_k3s_tunnel_mode(topology_config):
    raw_value = _vm_distributed_config_value(
        topology_config,
        "VM_SINGLE_K3S_TUNNEL_MODE",
        default="auto",
    ).lower().replace("_", "-")
    aliases = {
        "1": "auto",
        "true": "auto",
        "yes": "auto",
        "on": "auto",
        "enabled": "auto",
        "0": "disabled",
        "false": "disabled",
        "no": "disabled",
        "off": "disabled",
    }
    return aliases.get(raw_value, raw_value)


def _vm_single_should_prepare_k3s_tunnel(level_id, plan, topology_config):
    if os.environ.get("PIONERA_VM_SINGLE_REMOTE_LEVEL_ACTIVE") == "true":
        return False
    if os.environ.get("PIONERA_LEVEL_RUNTIME_ENV_ACTIVE") == "true":
        return False
    if int(level_id) not in {1, 2, 3, 4, 5, 6}:
        return False
    try:
        runtime = _ensure_vm_single_k3s_runtime_config(topology_config)
    except Exception:
        return False
    mode = _normalized_vm_single_level_execution_mode(topology_config)
    if mode == "remote":
        return False
    if mode in {"local", "off", "disabled", "false", "0", "no"}:
        return False
    return not _vm_single_running_on_target(plan)


def _vm_single_should_run_level_remotely(level_id, plan):
    if os.environ.get("PIONERA_VM_SINGLE_REMOTE_LEVEL_ACTIVE") == "true":
        return False
    if int(level_id) not in {1, 2, 3, 4, 5, 6}:
        return False
    topology = _load_vm_single_configuration_bundle(adapter_name=None).get("topology") or {}
    mode = _normalized_vm_single_level_execution_mode(topology)
    if mode in {"local", "off", "disabled", "false", "0", "no"}:
        return False
    if mode == "remote":
        return True
    if mode in {"auto", "tunnel"}:
        return False
    raise RuntimeError(
        "VM_SINGLE_LEVEL_EXECUTION_MODE must be local, tunnel, remote or auto."
    )


def _normalized_vm_single_workspace_sync_mode(topology_config):
    raw_value = (
        os.getenv("PIONERA_VM_SINGLE_WORKSPACE_SYNC")
        or _vm_distributed_config_value(topology_config, "VM_SINGLE_WORKSPACE_SYNC", default="auto")
    ).strip().lower().replace("_", "-")
    aliases = {
        "1": "auto",
        "true": "auto",
        "yes": "auto",
        "on": "auto",
        "enabled": "auto",
        "0": "disabled",
        "false": "disabled",
        "no": "disabled",
        "off": "disabled",
    }
    return aliases.get(raw_value, raw_value)


def _vm_single_workspace_sync_delete_enabled(topology_config):
    raw_value = (
        os.getenv("PIONERA_VM_SINGLE_WORKSPACE_SYNC_DELETE")
        or _vm_distributed_config_value(topology_config, "VM_SINGLE_WORKSPACE_SYNC_DELETE", default="false")
    )
    return str(raw_value or "").strip().lower() in {"1", "true", "yes", "on"}


def _vm_single_workspace_sync_excludes(topology_config):
    default_excludes = [
        ".git/",
        ".venv/",
        "**/.venv/",
        "**/__pycache__/",
        "**/node_modules/",
        "**/.pytest_cache/",
        "**/.mypy_cache/",
        "**/.ruff_cache/",
        "experiments/",
        "context/deliverables/logs/",
        "*.log",
        ".env",
        ".env.*",
        "deployers/*/deployments/DEV/*/credentials-*.json",
        "deployers/*/deployments/DEV/*/policy-*.json",
    ]
    configured = _vm_distributed_config_value(topology_config, "VM_SINGLE_WORKSPACE_SYNC_EXCLUDES")
    extra = [
        item.strip()
        for item in configured.replace(";", ",").split(",")
        if item.strip()
    ]
    return default_excludes + extra


def _vm_single_workspace_sync_ssh_parts(plan):
    payload = dict(plan or {})
    vms = [item for item in list(payload.get("vms") or []) if isinstance(item, dict)]
    vm = vms[0] if vms else {}
    command = _vm_distributed_build_ssh_command(payload, vm)
    if not command or len(command) < 2:
        return [], ""
    return command[:-1], command[-1]


def _vm_single_k3s_tunnel_command(plan, topology_config, local_port):
    payload = dict(plan or {})
    vms = [item for item in list(payload.get("vms") or []) if isinstance(item, dict)]
    vm = vms[0] if vms else {}
    command = _vm_distributed_build_ssh_command(payload, vm)
    if not command:
        return []
    remote_port = _vm_single_k3s_api_remote_port(topology_config)
    tunnel_args = [
        "-N",
        "-L",
        f"127.0.0.1:{int(local_port)}:127.0.0.1:{remote_port}",
        "-o",
        "ExitOnForwardFailure=yes",
    ]
    return command[:1] + tunnel_args + command[1:]


def _vm_single_mapping_editor_tunnel_mode(topology_config):
    raw_value = _vm_distributed_config_value(
        topology_config,
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_MODE",
        default="auto",
    ).lower().replace("_", "-")
    aliases = {
        "1": "auto",
        "true": "auto",
        "yes": "auto",
        "on": "auto",
        "enabled": "auto",
        "0": "disabled",
        "false": "disabled",
        "no": "disabled",
        "off": "disabled",
    }
    return aliases.get(raw_value, raw_value)


def _vm_single_mapping_editor_host_port(topology_config):
    configured = _vm_distributed_config_value(
        topology_config,
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST_PORT",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_PORT",
        "MAPPING_EDITOR_HOST_PORT",
        "MAPPING_EDITOR_PUBLIC_PORT",
    )
    if configured:
        try:
            return int(str(configured).strip())
        except (TypeError, ValueError):
            return 0
    url = _vm_distributed_config_value(
        topology_config,
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL",
        "MAPPING_EDITOR_PUBLIC_URL",
        "MAPPING_EDITOR_URL",
    )
    try:
        parsed = urllib.parse.urlparse(url if "://" in str(url) else f"//{url}")
    except Exception:
        return 0
    return int(parsed.port or 0)


def _vm_single_mapping_editor_tunnel_local_port(topology_config):
    configured = _vm_distributed_config_value(
        topology_config,
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_LOCAL_PORT",
        "MAPPING_EDITOR_TUNNEL_LOCAL_PORT",
    )
    if configured:
        try:
            return int(str(configured).strip())
        except (TypeError, ValueError):
            return 0
    return _vm_single_mapping_editor_host_port(topology_config)


def _vm_single_mapping_editor_tunnel_remote_host(topology_config):
    return (
        _vm_distributed_config_value(
            topology_config,
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_REMOTE_HOST",
            "MAPPING_EDITOR_TUNNEL_REMOTE_HOST",
            default="127.0.0.1",
        )
        or "127.0.0.1"
    )


_VM_SINGLE_MAPPING_EDITOR_PORT_FORWARD_PROCESSES = []


def _cleanup_vm_single_mapping_editor_port_forwards():
    for item in list(_VM_SINGLE_MAPPING_EDITOR_PORT_FORWARD_PROCESSES):
        process = getattr(item, "process", None)
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        for attr in ("stdout_file", "stderr_file"):
            handle = getattr(item, attr, None)
            if handle:
                try:
                    handle.close()
                except OSError:
                    pass
        try:
            _VM_SINGLE_MAPPING_EDITOR_PORT_FORWARD_PROCESSES.remove(item)
        except ValueError:
            pass


atexit.register(_cleanup_vm_single_mapping_editor_port_forwards)


def _reserve_loopback_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _vm_single_mapping_editor_service_namespace(topology_config):
    return (
        _vm_distributed_config_value(
            topology_config,
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NAMESPACE",
            "SEMANTIC_VIRTUALIZATION_NAMESPACE",
            "COMPONENTS_NAMESPACE",
            "NS_COMPONENTS",
            default="components",
        )
        or "components"
    ).strip()


def _vm_single_mapping_editor_service_name(topology_config):
    configured = _vm_distributed_config_value(
        topology_config,
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_NAME",
        "MAPPING_EDITOR_SERVICE_NAME",
    )
    if configured:
        return configured.strip()
    dataspace = (
        _vm_distributed_config_value(
            topology_config,
            "DS_NAME",
            "DS_1_NAME",
            "DATASPACE_NAME",
            default="pionera",
        )
        or "pionera"
    ).strip()
    return f"{dataspace}-semantic-virtualization-editor"


def _vm_single_mapping_editor_service_port(topology_config):
    configured = _vm_distributed_config_value(
        topology_config,
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_PORT",
        "MAPPING_EDITOR_SERVICE_PORT",
        default="8501",
    )
    try:
        return int(str(configured or "8501").strip())
    except (TypeError, ValueError):
        return 8501


def _vm_single_mapping_editor_is_k3s(topology_config):
    try:
        runtime = build_cluster_runtime(topology_config or {}, topology=VM_SINGLE_TOPOLOGY)
    except Exception:
        return str((topology_config or {}).get("CLUSTER_TYPE") or "").strip().lower() == "k3s"
    return runtime.get("cluster_type") == "k3s"


def _vm_single_mapping_editor_health_url(url):
    return f"{str(url or '').rstrip('/')}/_stcore/health"


def _vm_single_mapping_editor_http_ready(url, timeout_seconds=2):
    if not url:
        return False
    try:
        response = requests.get(
            _vm_single_mapping_editor_health_url(url),
            timeout=max(float(timeout_seconds), 0.5),
        )
    except requests.RequestException:
        return False
    return int(getattr(response, "status_code", 0) or 0) == 200


def _vm_single_mapping_editor_port_forward_command(topology_config, local_port):
    namespace = _vm_single_mapping_editor_service_namespace(topology_config)
    service_name = _vm_single_mapping_editor_service_name(topology_config)
    service_port = _vm_single_mapping_editor_service_port(topology_config)
    return [
        "kubectl",
        "port-forward",
        "--address",
        "127.0.0.1",
        "-n",
        namespace,
        f"svc/{service_name}",
        f"{int(local_port)}:{int(service_port)}",
    ]


def _ensure_vm_single_mapping_editor_kubectl_port_forward(topology_config):
    preferred_port = _vm_single_mapping_editor_tunnel_local_port(topology_config)
    candidate_ports = [int(preferred_port)] if preferred_port else []
    candidate_ports.append(_reserve_loopback_port())
    last_failure = None

    for index, candidate_port in enumerate(candidate_ports):
        local_port = int(candidate_port or _reserve_loopback_port())
        url = f"http://127.0.0.1:{local_port}"
        if _vm_single_mapping_editor_http_ready(url):
            return {
                "status": "ready",
                "mode": "kubectl-port-forward",
                "local_port": local_port,
                "url": url,
            }
        if _local_tcp_port_open(local_port):
            if index == 0:
                continue
            local_port = _reserve_loopback_port()
            url = f"http://127.0.0.1:{local_port}"

        command = _vm_single_mapping_editor_port_forward_command(topology_config, local_port)
        env = os.environ.copy()
        kubeconfig = _vm_single_effective_kubeconfig_path(topology_config)
        if kubeconfig:
            env["KUBECONFIG"] = kubeconfig
        stdout_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            stdout_file.close()
            stderr_file.close()
            last_failure = {
                "status": "failed",
                "mode": "kubectl-port-forward",
                "reason": "kubectl-port-forward-start-failed",
                "url": url,
                "command": _vm_distributed_format_command(command),
                "error": str(exc),
            }
            continue

        proc = types.SimpleNamespace(
            process=process,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
        )
        deadline = time.time() + 25
        while time.time() < deadline:
            if _vm_single_mapping_editor_http_ready(url, timeout_seconds=0.5):
                _VM_SINGLE_MAPPING_EDITOR_PORT_FORWARD_PROCESSES.append(proc)
                return {
                    "status": "started",
                    "mode": "kubectl-port-forward",
                    "local_port": local_port,
                    "service": _vm_single_mapping_editor_service_name(topology_config),
                    "namespace": _vm_single_mapping_editor_service_namespace(topology_config),
                    "service_port": _vm_single_mapping_editor_service_port(topology_config),
                    "url": url,
                    "command": _vm_distributed_format_command(command),
                    "pid": getattr(process, "pid", None),
                }
            if process.poll() is not None:
                break
            time.sleep(0.25)

        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        for handle in (stdout_file, stderr_file):
            try:
                handle.seek(0)
            except OSError:
                pass
        stdout = stdout_file.read() if stdout_file else ""
        stderr = stderr_file.read() if stderr_file else ""
        stdout_file.close()
        stderr_file.close()
        error_text = (stderr or stdout or "Streamlit health endpoint did not become ready").strip()
        last_failure = {
            "status": "failed",
            "mode": "kubectl-port-forward",
            "reason": "kubectl-port-forward-timeout",
            "url": url,
            "command": _vm_distributed_format_command(command),
            "error": error_text[:500],
        }
        if "address already in use" in error_text.lower() or "unable to listen" in error_text.lower():
            continue

    return last_failure or {
        "status": "failed",
        "mode": "kubectl-port-forward",
        "reason": "kubectl-port-forward-unavailable",
    }


def _vm_single_mapping_editor_exposure_mode(topology_config):
    raw_value = _vm_distributed_config_value(
        topology_config,
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_EXPOSURE_MODE",
        "MAPPING_EDITOR_EXPOSURE_MODE",
        default="",
    ).lower().replace("_", "-")
    if raw_value:
        return raw_value
    if _vm_single_mapping_editor_host_port(topology_config):
        return "host-port"
    return "ingress"


def _vm_single_mapping_editor_public_url(topology_config):
    return str(
        _vm_distributed_config_value(
            topology_config,
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL",
            "MAPPING_EDITOR_PUBLIC_URL",
        )
        or ""
    ).strip()


def _vm_single_mapping_editor_has_dedicated_public_url(topology_config):
    url = _vm_single_mapping_editor_public_url(topology_config)
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        return False
    return host not in {"localhost", "127.0.0.1", "::1"}


def _vm_single_mapping_editor_should_use_tunnel(plan, topology_config):
    if os.environ.get("PIONERA_VM_SINGLE_REMOTE_LEVEL_ACTIVE") == "true":
        return False
    if os.environ.get("PIONERA_LEVEL_RUNTIME_ENV_ACTIVE") == "true":
        return False
    if _vm_single_running_on_target(plan):
        return False
    mode = _vm_single_mapping_editor_tunnel_mode(topology_config)
    if mode in {"manual", "disabled", "skip", "off"}:
        return False
    if mode == "always":
        return True
    if _vm_single_mapping_editor_has_dedicated_public_url(topology_config):
        return False
    exposure = _vm_single_mapping_editor_exposure_mode(topology_config)
    return exposure in {"direct", "host-port", "hostport", "vm-port"}


def _vm_single_mapping_editor_tunnel_command(plan, topology_config, local_port, remote_host, remote_port):
    payload = dict(plan or {})
    vms = [item for item in list(payload.get("vms") or []) if isinstance(item, dict)]
    vm = vms[0] if vms else {}
    command = _vm_distributed_build_ssh_command(payload, vm)
    if not command:
        return []
    tunnel_args = [
        "-N",
        "-L",
        f"127.0.0.1:{int(local_port)}:{remote_host}:{int(remote_port)}",
        "-o",
        "ExitOnForwardFailure=yes",
    ]
    return command[:1] + tunnel_args + command[1:]


def _ensure_vm_single_mapping_editor_tunnel(plan, topology_config):
    if _vm_single_mapping_editor_is_k3s(topology_config):
        return _ensure_vm_single_mapping_editor_kubectl_port_forward(topology_config)

    remote_port = _vm_single_mapping_editor_host_port(topology_config)
    local_port = _vm_single_mapping_editor_tunnel_local_port(topology_config)
    remote_host = _vm_single_mapping_editor_tunnel_remote_host(topology_config)
    if not remote_port or not local_port:
        return {"status": "skipped", "reason": "missing-mapping-editor-port"}
    if _local_tcp_port_open(local_port):
        return {
            "status": "ready",
            "local_port": local_port,
            "remote_host": remote_host,
            "remote_port": remote_port,
            "url": f"http://127.0.0.1:{int(local_port)}",
        }

    command = _vm_single_mapping_editor_tunnel_command(
        plan,
        topology_config,
        local_port,
        remote_host,
        remote_port,
    )
    if not command:
        return {
            "status": "failed",
            "reason": "missing-ssh-config",
            "local_port": local_port,
            "remote_host": remote_host,
            "remote_port": remote_port,
        }

    proc = _run_vm_distributed_background_ssh_command(command, timeout_seconds=20)
    if proc.returncode not in {None, 0}:
        return {
            "status": "failed",
            "reason": "ssh-tunnel-failed",
            "local_port": local_port,
            "remote_host": remote_host,
            "remote_port": remote_port,
            "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
            "error": (proc.stderr or proc.stdout or "").strip()[:500],
        }

    deadline = time.time() + 20
    while time.time() < deadline:
        if _local_tcp_port_open(local_port):
            _close_vm_distributed_background_ssh_process_files(proc)
            return {
                "status": "started",
                "local_port": local_port,
                "remote_host": remote_host,
                "remote_port": remote_port,
                "url": f"http://127.0.0.1:{int(local_port)}",
                "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
                "pid": getattr(getattr(proc, "process", None), "pid", None),
            }
        process = getattr(proc, "process", None)
        if process and process.poll() is not None:
            proc = _vm_distributed_background_ssh_process_output(proc)
            return {
                "status": "failed",
                "reason": "ssh-tunnel-failed",
                "local_port": local_port,
                "remote_host": remote_host,
                "remote_port": remote_port,
                "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
                "error": (proc.stderr or proc.stdout or f"ssh exited with {proc.returncode}").strip()[:500],
            }
        time.sleep(0.25)

    _terminate_vm_distributed_background_ssh_process(proc)
    return {
        "status": "failed",
        "reason": "ssh-tunnel-timeout",
        "local_port": local_port,
        "remote_host": remote_host,
        "remote_port": remote_port,
        "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
    }


def _vm_single_component_validation_tunnel_environment(config):
    topology_config = dict(config or {})
    plan_bundle = _load_vm_single_configuration_bundle(adapter_name=None)
    plan = _build_vm_single_topology_plan(
        plan_bundle["infrastructure"],
        plan_bundle["topology"],
        plan_bundle["adapter"],
    )
    effective_topology = {**dict(plan_bundle.get("topology") or {}), **topology_config}
    if not _vm_single_mapping_editor_should_use_tunnel(plan, effective_topology):
        return {}
    tunnel = _ensure_vm_single_mapping_editor_tunnel(plan, effective_topology)
    status = str(tunnel.get("status") or "").strip().lower()
    if status not in {"ready", "started"}:
        reason = tunnel.get("reason") or tunnel.get("error") or "tunnel unavailable"
        command = tunnel.get("command")
        suffix = f" Command: {command}" if command else ""
        print(
            "Warning: vm-single mapping editor tunnel could not be prepared. "
            f"Semantic Virtualization editor UI tests may fail. {reason}.{suffix}"
        )
        return {}
    url = str(tunnel.get("url") or "").rstrip("/")
    if not url:
        return {}
    print(f"vm-single mapping editor tunnel ready: {url}")
    return {
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_BASE_URL": url,
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL": url,
        "MAPPING_EDITOR_BASE_URL": url,
    }


def _ensure_vm_single_k3s_tunnel(plan, topology_config):
    local_port = _vm_single_k3s_api_local_port(topology_config)
    if _local_tcp_port_open(local_port):
        return {"status": "ready", "local_port": local_port}

    mode = _vm_single_k3s_tunnel_mode(topology_config)
    if mode in {"manual", "disabled", "skip"}:
        return {
            "status": "missing",
            "reason": "tunnel-mode-disabled",
            "local_port": local_port,
        }

    command = _vm_single_k3s_tunnel_command(plan, topology_config, local_port)
    if not command:
        return {
            "status": "failed",
            "reason": "missing-ssh-config",
            "local_port": local_port,
        }

    proc = _run_vm_distributed_background_ssh_command(command, timeout_seconds=20)
    if proc.returncode not in {None, 0}:
        return {
            "status": "failed",
            "reason": "ssh-tunnel-failed",
            "local_port": local_port,
            "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
            "error": (proc.stderr or proc.stdout or "").strip()[:500],
        }

    deadline = time.time() + 20
    while time.time() < deadline:
        if _local_tcp_port_open(local_port):
            _close_vm_distributed_background_ssh_process_files(proc)
            return {
                "status": "started",
                "local_port": local_port,
                "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
                "pid": getattr(getattr(proc, "process", None), "pid", None),
            }
        process = getattr(proc, "process", None)
        if process and process.poll() is not None:
            proc = _vm_distributed_background_ssh_process_output(proc)
            return {
                "status": "failed",
                "reason": "ssh-tunnel-failed",
                "local_port": local_port,
                "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
                "error": (proc.stderr or proc.stdout or f"ssh exited with {proc.returncode}").strip()[:500],
            }
        time.sleep(0.25)

    _terminate_vm_distributed_background_ssh_process(proc)
    return {
        "status": "failed",
        "reason": "ssh-tunnel-timeout",
        "local_port": local_port,
        "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
    }


def _render_vm_single_local_kubeconfig(remote_kubeconfig, local_port):
    return _render_k3s_kubeconfig_with_server(
        remote_kubeconfig,
        f"https://127.0.0.1:{int(local_port)}",
    )


def _fetch_vm_single_remote_kubeconfig(plan, topology_config, local_port, command_runner=None):
    remote_path = _vm_single_remote_kubeconfig_path(topology_config)
    local_path = _vm_single_local_kubeconfig_path(topology_config)
    remote_path_q = shlex.quote(remote_path)
    remote_shell = "\n".join(
        [
            "set -eu",
            f"if test -r {remote_path_q}; then",
            f"  cat {remote_path_q}",
            f"elif sudo -n test -r {remote_path_q}; then",
            f"  sudo -n cat {remote_path_q}",
            "else",
            f"  echo 'Remote k3s kubeconfig is not readable: {remote_path}' >&2",
            "  exit 65",
            "fi",
        ]
    )
    payload = dict(plan or {})
    vms = [item for item in list(payload.get("vms") or []) if isinstance(item, dict)]
    vm = vms[0] if vms else {}
    command = _vm_distributed_build_ssh_command(payload, vm, remote_command=remote_shell)
    if not command:
        raise RuntimeError("Cannot fetch vm-single kubeconfig because the SSH command could not be built.")

    runner = command_runner or subprocess.run
    completed = runner(command, capture_output=True, text=True, check=False)
    if int(getattr(completed, "returncode", 1) or 0) != 0:
        detail = (getattr(completed, "stderr", "") or getattr(completed, "stdout", "") or "").strip()
        raise RuntimeError(
            "Could not fetch the remote vm-single k3s kubeconfig. "
            f"{detail or 'Remote command failed.'}"
        )

    rendered = _render_vm_single_local_kubeconfig(getattr(completed, "stdout", "") or "", local_port)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    os.chmod(local_path, 0o600)
    return {
        "status": "written",
        "local_path": local_path,
        "remote_path": remote_path,
        "server": f"https://127.0.0.1:{int(local_port)}",
    }


def _ensure_vm_single_k3s_api_access(adapter_name=None, command_runner=None):
    bundle = _load_vm_single_configuration_bundle(adapter_name=adapter_name)
    plan = _build_vm_single_topology_plan(
        bundle["infrastructure"],
        bundle["topology"],
        bundle["adapter"],
    )
    if _vm_single_running_on_target(plan):
        return {
            "status": "local-target",
            "kubeconfig": _vm_single_remote_kubeconfig_path(bundle["topology"]),
            "tunnel": {"status": "skipped", "reason": "running-on-target"},
        }

    ssh_bootstrap = dict(plan.get("ssh_bootstrap") or {})
    if str(ssh_bootstrap.get("status") or "").strip().lower() != "ready":
        warnings = "; ".join(str(item) for item in list(ssh_bootstrap.get("warnings") or []))
        raise RuntimeError(
            "Cannot prepare vm-single Kubernetes access because SSH is not fully configured. "
            f"{warnings or 'Run ssh-access reconcile first.'}"
        )

    local_port = _vm_single_k3s_api_local_port(bundle["topology"])
    kubeconfig_result = _fetch_vm_single_remote_kubeconfig(
        plan,
        bundle["topology"],
        local_port,
        command_runner=command_runner,
    )
    tunnel_result = _ensure_vm_single_k3s_tunnel(plan, bundle["topology"])
    if tunnel_result.get("status") in {"failed", "missing"}:
        reason = tunnel_result.get("reason") or "tunnel unavailable"
        command = tunnel_result.get("command")
        suffix = f" Command: {command}" if command else ""
        raise RuntimeError(
            "Cannot prepare vm-single Kubernetes access because the k3s API tunnel is not available. "
            f"{reason}.{suffix}"
        )

    check = _vm_distributed_kubeconfig_check("vm-single", kubeconfig_result["local_path"], timeout_seconds=12)
    if check.get("status") != "ready":
        raise RuntimeError(
            "Cannot prepare vm-single Kubernetes access because kubectl cannot reach the tunneled k3s API. "
            f"{check.get('detail') or 'unreachable'}"
        )

    return {
        "status": "ready",
        "kubeconfig": kubeconfig_result["local_path"],
        "kubeconfig_sync": kubeconfig_result,
        "tunnel": tunnel_result,
        "check": check,
    }


def _vm_single_k3s_remote_prepare_shell(topology_config):
    remote_kubeconfig = _vm_single_remote_kubeconfig_path(topology_config)
    service_name = _vm_distributed_config_value(topology_config, "K3S_SERVICE_NAME", default="k3s") or "k3s"
    install_exec = _vm_distributed_config_value(
        topology_config,
        "K3S_INSTALL_EXEC",
        default="--disable=traefik",
    ) or "--disable=traefik"
    kubeconfig_mode = _vm_distributed_config_value(
        topology_config,
        "K3S_WRITE_KUBECONFIG_MODE",
        default="0644",
    ) or "0644"
    install_exec_args = " ".join(shlex.quote(part) for part in shlex.split(install_exec))
    remote_kubeconfig_q = shlex.quote(remote_kubeconfig)
    service_name_q = shlex.quote(service_name)
    kubeconfig_mode_q = shlex.quote(kubeconfig_mode)
    return "\n".join(
        [
            "set -eu",
            "needs_install=0",
            "command -v k3s >/dev/null 2>&1 || needs_install=1",
            f"systemctl is-active --quiet {service_name_q} || needs_install=1",
            f"test -f {remote_kubeconfig_q} || needs_install=1",
            'if [ "$needs_install" = "1" ]; then',
            "  echo 'Installing or repairing k3s on vm-single...'",
            f"  curl -sfL https://get.k3s.io | sudo sh -s - {install_exec_args}",
            "else",
            "  echo 'k3s already installed on vm-single.'",
            "fi",
            "if systemctl list-unit-files k3s-agent.service --no-pager >/dev/null 2>&1; then",
            "  sudo systemctl stop k3s-agent >/dev/null 2>&1 || true",
            "  sudo systemctl disable k3s-agent >/dev/null 2>&1 || true",
            "fi",
            f"sudo systemctl start {service_name_q}",
            f"sudo chmod {kubeconfig_mode_q} {remote_kubeconfig_q}",
            f"systemctl is-active {service_name_q}",
            f"test -r {remote_kubeconfig_q}",
        ]
    )


def _vm_single_run_local_command(command, label, *, env=None, capture=True, required=True):
    rendered = _vm_distributed_format_command(command)
    print(f"Executing: {rendered}")
    completed = subprocess.run(
        command,
        env=env,
        capture_output=capture,
        text=True,
        check=False,
    )
    if required and int(completed.returncode or 0) != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"{label} failed. {detail}")
    return completed


def _install_vm_single_ingress_nginx(adapter, topology_config, kubeconfig):
    env = os.environ.copy()
    env["KUBECONFIG"] = kubeconfig
    service_type = _vm_distributed_config_value(
        topology_config,
        "K3S_INGRESS_SERVICE_TYPE",
        default="LoadBalancer",
    ) or "LoadBalancer"

    if not shutil.which("kubectl"):
        raise RuntimeError("kubectl is required on the operator machine to manage vm-single through the tunnel.")
    if not shutil.which("helm"):
        raise RuntimeError("Helm is required on the operator machine to manage vm-single through the tunnel.")

    print("\nInstalling or reconciling ingress-nginx in vm-single k3s...")
    _vm_single_run_local_command(
        ["helm", "repo", "add", "ingress-nginx", "https://kubernetes.github.io/ingress-nginx"],
        "helm repo add ingress-nginx",
        env=env,
        required=False,
    )
    _vm_single_run_local_command(["helm", "repo", "update"], "helm repo update", env=env)
    status = _vm_single_run_local_command(
        ["helm", "status", "ingress-nginx", "-n", "ingress-nginx"],
        "helm status ingress-nginx",
        env=env,
        required=False,
    )
    if int(status.returncode or 0) != 0:
        existing = _vm_single_run_local_command(
            [
                "kubectl",
                "get",
                "deployment",
                "ingress-nginx-controller",
                "-n",
                "ingress-nginx",
                "-o",
                "name",
            ],
            "kubectl get ingress-nginx deployment",
            env=env,
            required=False,
        )
        if int(existing.returncode or 0) != 0 or not (existing.stdout or "").strip():
            _vm_single_run_local_command(
                [
                    "helm",
                    "install",
                    "ingress-nginx",
                    "ingress-nginx/ingress-nginx",
                    "-n",
                    "ingress-nginx",
                    "--create-namespace",
                    "--set",
                    f"controller.service.type={service_type}",
                    "--set",
                    "controller.watchIngressWithoutClass=true",
                    "--set",
                    "controller.allowSnippetAnnotations=true",
                    "--set",
                    "controller.config.allow-snippet-annotations=true",
                    "--set",
                    "controller.config.annotations-risk-level=Critical",
                    "--wait",
                    "--timeout",
                    "180s",
                ],
                "helm install ingress-nginx",
                env=env,
            )
        else:
            print("ingress-nginx resources already exist outside Helm; reusing them.")
    else:
        print("ingress-nginx already installed.")

    infrastructure = getattr(adapter, "infrastructure", None)
    with _temporary_environment({"KUBECONFIG": kubeconfig}):
        patch_service = getattr(infrastructure, "_patch_k3s_ingress_nginx_service", None)
        if callable(patch_service):
            patch_service(service_type)
        patch_configmap = getattr(infrastructure, "_patch_ingress_nginx_configmap", None)
        if callable(patch_configmap):
            patch_configmap()


def _vm_single_k3s_preflight_checks(kubeconfig):
    env = os.environ.copy()
    env["KUBECONFIG"] = kubeconfig
    checks = []

    def check(command, label, *, validator=None, failure_message=None):
        completed = _vm_single_run_local_command(command, label, env=env, required=False)
        detail = (completed.stdout or completed.stderr or "").strip()
        ok = int(completed.returncode or 0) == 0 and bool(detail)
        if ok and callable(validator):
            ok = bool(validator(detail))
        checks.append(
            {
                "label": label,
                "command": _vm_distributed_format_command(command),
                "status": "passed" if ok else "failed",
                "detail": detail,
            }
        )
        if not ok:
            raise RuntimeError(failure_message or f"Level 1 vm-single preflight failed during {label}")
        return detail

    check(["kubectl", "version", "--client=true"], "kubectl client version")
    current_context = check(["kubectl", "config", "current-context"], "kubectl current context")
    check(["kubectl", "cluster-info"], "cluster info")
    check(["kubectl", "get", "nodes", "--no-headers"], "cluster nodes")
    check(["kubectl", "get", "ingressclass", "-o", "name"], "ingress classes")
    check(["kubectl", "get", "storageclass", "-o", "name"], "storage classes")
    check(
        ["kubectl", "auth", "can-i", "create", "namespace"],
        "create namespace permission",
        validator=lambda detail: detail.strip().lower() in {"yes", "true"},
        failure_message="the active kubectl identity cannot create namespaces",
    )
    return current_context, checks


def _run_vm_single_level1_via_ssh_tunnel(adapter, adapter_name):
    bundle = _load_vm_single_configuration_bundle(adapter_name=adapter_name)
    plan = _build_vm_single_topology_plan(
        bundle["infrastructure"],
        bundle["topology"],
        bundle["adapter"],
    )
    ssh_bootstrap = dict(plan.get("ssh_bootstrap") or {})
    if str(ssh_bootstrap.get("status") or "").strip().lower() != "ready":
        warnings = "; ".join(str(item) for item in list(ssh_bootstrap.get("warnings") or []))
        raise RuntimeError(
            "Cannot prepare vm-single Level 1 from WSL because SSH is not fully configured. "
            f"{warnings or 'Run ssh-access reconcile first.'}"
        )

    print("vm-single Level 1 will prepare k3s on the VM over SSH.")
    print("The framework stays on this machine; Kubernetes access will use an SSH tunnel.")
    remote_shell = _vm_single_k3s_remote_prepare_shell(bundle["topology"])
    command = _vm_single_remote_ssh_command(plan, remote_shell)
    if not command:
        raise RuntimeError("Cannot prepare vm-single Level 1 because the target SSH command could not be built.")
    completed = subprocess.run(command, check=False)
    if int(getattr(completed, "returncode", 1) or 0) != 0:
        raise RuntimeError("Remote vm-single k3s preparation failed. Check the SSH output above before retrying.")

    access = _ensure_vm_single_k3s_api_access(adapter_name=adapter_name)
    _install_vm_single_ingress_nginx(adapter, bundle["topology"], access["kubeconfig"])
    current_context, checks = _vm_single_k3s_preflight_checks(access["kubeconfig"])
    infrastructure = getattr(adapter, "infrastructure", None)
    complete_level = getattr(infrastructure, "complete_level", None)
    if callable(complete_level):
        complete_level(1)
    return {
        "status": "ready",
        "mode": "ssh-tunnel-managed",
        "topology": VM_SINGLE_TOPOLOGY,
        "cluster_runtime": "k3s",
        "current_context": current_context,
        "cluster_creation": "remote-prepared",
        "kubeconfig": access["kubeconfig"],
        "tunnel": access["tunnel"],
        "checks": checks,
    }


def _sync_vm_single_remote_workspace(plan, topology_config, command_runner=None):
    mode = _normalized_vm_single_workspace_sync_mode(topology_config)
    if mode in {"disabled", "manual", "skip"}:
        return {"status": "skipped", "mode": mode}
    if mode not in {"auto", "always"}:
        raise RuntimeError("VM_SINGLE_WORKSPACE_SYNC must be auto, always, disabled or manual.")

    remote_workdir = _vm_distributed_config_value(
        topology_config,
        "VM_SINGLE_REMOTE_WORKDIR",
        "VM_REMOTE_WORKDIR",
    )
    if not remote_workdir:
        raise RuntimeError(
            "VM_SINGLE_REMOTE_WORKDIR is required to synchronize the framework workspace to vm-single."
        )
    if not shutil.which("rsync"):
        raise RuntimeError("rsync is required to synchronize the framework workspace to vm-single.")

    ssh_base, ssh_target = _vm_single_workspace_sync_ssh_parts(plan)
    if not ssh_base or not ssh_target:
        raise RuntimeError("Cannot synchronize vm-single workspace because the SSH target could not be built.")

    local_root = os.path.dirname(os.path.abspath(__file__))
    source = local_root.rstrip("/") + "/"
    destination = f"{ssh_target}:{remote_workdir.rstrip('/')}/"
    runner = command_runner or subprocess.run

    mkdir_command = _vm_distributed_build_ssh_command(
        plan,
        (plan.get("vms") or [{}])[0],
        remote_command=f"mkdir -p {shlex.quote(remote_workdir)}",
    )
    mkdir_result = runner(mkdir_command, check=False)
    if int(getattr(mkdir_result, "returncode", 1) or 0) != 0:
        raise RuntimeError("Could not create the remote vm-single framework workspace directory.")

    rsync_command = [
        "rsync",
        "-az",
        "--human-readable",
    ]
    if _vm_single_workspace_sync_delete_enabled(topology_config):
        rsync_command.append("--delete")
    for pattern in _vm_single_workspace_sync_excludes(topology_config):
        rsync_command.extend(["--exclude", pattern])
    rsync_command.extend(
        [
            "-e",
            _vm_distributed_format_command(ssh_base),
            source,
            destination,
        ]
    )

    print("Synchronizing framework workspace to vm-single VM...")
    print(f"Remote workspace: {remote_workdir}")
    rsync_result = runner(rsync_command, check=False)
    if int(getattr(rsync_result, "returncode", 1) or 0) != 0:
        raise RuntimeError("Could not synchronize the framework workspace to vm-single.")

    return {
        "status": "synced",
        "mode": mode,
        "source": source,
        "remote_workdir": remote_workdir,
        "delete": _vm_single_workspace_sync_delete_enabled(topology_config),
        "excluded": _vm_single_workspace_sync_excludes(topology_config),
    }


def _vm_single_remote_level_shell(topology_config, adapter_name, level_id):
    remote_workdir = _vm_distributed_config_value(
        topology_config,
        "VM_SINGLE_REMOTE_WORKDIR",
        "VM_REMOTE_WORKDIR",
    )
    if not remote_workdir:
        raise RuntimeError(
            "VM_SINGLE_REMOTE_WORKDIR is required to run vm-single levels remotely from WSL. "
            "Set it to the framework path inside the VM, or run the framework directly inside the VM."
        )
    python_bin = _vm_single_remote_python(topology_config)
    command = _vm_distributed_format_command(
        [
            python_bin,
            "main.py",
            adapter_name,
            "level",
            str(level_id),
            "--topology",
            VM_SINGLE_TOPOLOGY,
        ]
    )
    return "\n".join(
        [
            "set -eu",
            f"if [ ! -d {shlex.quote(remote_workdir)} ]; then",
            "  echo 'Remote framework workspace not found.' >&2",
            f"  echo 'Expected: {shlex.quote(remote_workdir)}' >&2",
            "  echo 'Synchronize the framework workspace in the VM, then rerun this level.' >&2",
            "  exit 66",
            "fi",
            f"cd {shlex.quote(remote_workdir)}",
            "export PIONERA_VM_SINGLE_REMOTE_LEVEL_ACTIVE=true",
            f"exec {command}",
        ]
    )


def _vm_single_remote_ssh_command(plan, remote_shell):
    payload = dict(plan or {})
    vms = [item for item in list(payload.get("vms") or []) if isinstance(item, dict)]
    vm = vms[0] if vms else {}
    command = _vm_distributed_build_ssh_command(payload, vm, remote_command=remote_shell)
    if command and command[0] == "ssh" and "-tt" not in command:
        command.insert(1, "-tt")
    return command


def _run_vm_single_level_remotely(
    adapter_name,
    level_id,
    *,
    command_runner=None,
):
    bundle = _load_vm_single_configuration_bundle(adapter_name=adapter_name)
    plan = _build_vm_single_topology_plan(
        bundle["infrastructure"],
        bundle["topology"],
        bundle["adapter"],
    )
    ssh_bootstrap = dict(plan.get("ssh_bootstrap") or {})
    if str(ssh_bootstrap.get("status") or "").strip().lower() != "ready":
        warnings = "; ".join(str(item) for item in list(ssh_bootstrap.get("warnings") or []))
        raise RuntimeError(
            "Cannot run vm-single levels remotely because SSH access is not fully configured. "
            f"{warnings or 'Run ssh-access reconcile first.'}"
        )

    print(
        f"vm-single Level {level_id} will run remotely on the configured VM "
        "because VM_SINGLE_LEVEL_EXECUTION_MODE is remote."
    )
    print("Remote execution keeps k3s and deployment state inside the VM.")

    runner = command_runner or subprocess.run
    workspace_sync = _sync_vm_single_remote_workspace(plan, bundle["topology"], command_runner=runner)
    remote_shell = _vm_single_remote_level_shell(bundle["topology"], adapter_name, level_id)
    command = _vm_single_remote_ssh_command(plan, remote_shell)
    if not command:
        raise RuntimeError(
            "Cannot run vm-single level remotely because the target SSH command could not be built."
        )

    completed = runner(command, check=False)
    returncode = int(getattr(completed, "returncode", 1) or 0)
    if returncode != 0:
        raise RuntimeError(
            f"Remote vm-single Level {level_id} failed with exit code {returncode}. "
            "Check the remote output above before retrying."
        )

    return {
        "level": int(level_id),
        "name": LEVEL_DESCRIPTIONS.get(int(level_id), "Unknown"),
        "status": "completed",
        "result": {
            "status": "remote_completed",
            "topology": VM_SINGLE_TOPOLOGY,
            "execution": "remote",
            "remote_workdir": _vm_distributed_config_value(
                bundle["topology"],
                "VM_SINGLE_REMOTE_WORKDIR",
                "VM_REMOTE_WORKDIR",
            ),
            "workspace_sync": workspace_sync,
            "command": _vm_distributed_format_command(_vm_distributed_public_ssh_command(command)),
        },
    }


def _current_vm_distributed_topology_plan(adapter_name=None):
    bundle = _load_vm_distributed_configuration_bundle(adapter_name=adapter_name)
    plan = _build_vm_distributed_topology_plan(
        bundle["infrastructure"],
        bundle["topology"],
        bundle["adapter"],
    )
    plan["config_files"] = bundle["paths"]
    return plan


def _print_vm_distributed_topology_plan(plan):
    vm_plan = dict(plan or {})
    print()
    print("vm-distributed topology plan:")
    print(f"  Status: {vm_plan.get('status') or 'unknown'}")
    print(f"  Execution host: {vm_plan.get('execution_host') or 'external'}")
    print(f"  Deployment mode: {vm_plan.get('deployment_mode') or 'orchestrator'}")
    print(f"  Dataspace: {vm_plan.get('dataspace') or '(not configured)'}")
    print(f"  Common domain: {vm_plan.get('domain_base') or '(not configured)'}")
    print(f"  Dataspace domain: {vm_plan.get('dataspace_domain_base') or '(not configured)'}")
    ssh_plan = dict(vm_plan.get("ssh") or {})
    print(f"  SSH mode: {ssh_plan.get('mode') or 'not-configured'}")
    if ssh_plan.get("mode") == "bastion":
        bastion = dict(ssh_plan.get("bastion") or {})
        label = _vm_distributed_ssh_target(bastion.get("user"), bastion.get("host")) or "(missing)"
        if bastion.get("port"):
            label = f"{label}:{bastion.get('port')}"
        print(f"  SSH bastion: {label}")

    print("  VMs:")
    for vm in list(vm_plan.get("vms") or []):
        ssh = dict(vm.get("ssh") or {})
        levels = ",".join(str(level) for level in list(vm.get("levels") or [])) or "-"
        print(
            f"  - {vm.get('role')}: address={vm.get('address') or '(missing)'}, "
            f"http={vm.get('http_url') or '(missing)'}, levels={levels}"
        )
        if vm.get("public_url"):
            print(f"    public: {vm.get('public_url')}")
        if vm.get("remote_workdir"):
            print(f"    remote workspace: {vm.get('remote_workdir')}")
        print(
            f"    ssh: {'configured' if ssh.get('configured') else 'not configured'}"
            + (f" ({ssh.get('command')})" if ssh.get("command") else "")
        )
    ssh_bootstrap = dict(vm_plan.get("ssh_bootstrap") or {})
    if ssh_bootstrap:
        print(
            f"  SSH bootstrap: {ssh_bootstrap.get('mode') or 'manual'} "
            f"({ssh_bootstrap.get('status') or 'unknown'})"
        )
        if ssh_bootstrap.get("identity_file"):
            print(f"    identity: {ssh_bootstrap.get('identity_file')}")

    connectors = list(vm_plan.get("connectors") or [])
    if connectors:
        print("  Connectors:")
        for item in connectors:
            print(f"  - {item.get('connector')} -> {item.get('location')}")
    pairs = list(vm_plan.get("validation_pairs") or [])
    if pairs:
        print("  Validation pairs:")
        for item in pairs:
            print(f"  - {item.get('source')} > {item.get('target')}")

    config_files = dict(vm_plan.get("config_files") or {})
    configured_files = [value for value in config_files.values() if value]
    if configured_files:
        print("  Config files:")
        for value in configured_files:
            print(f"  - {value}")


def _print_vm_distributed_preflight_results(title, result):
    payload = dict(result or {})
    def _status_label(status):
        raw_status = str(status or "unknown").strip() or "unknown"
        normalized = raw_status.lower()
        if normalized in {"passed", "ready", "completed", "updated"} or normalized.endswith("-ok"):
            return _console_color(raw_status, "32")
        if normalized in {"failed", "error", "unavailable"} or normalized.endswith("-failed"):
            return _console_color(raw_status, "31")
        if normalized in {"warning", "passed-with-warnings", "needs-review", "missing"}:
            return _console_color(raw_status, "33")
        if normalized in {"skipped", "not-applicable"}:
            return _console_color(raw_status, "90")
        return _console_color(raw_status, "36")

    def _detail_label(label, status):
        normalized = str(status or "").strip().lower()
        if label == "error" or normalized in {"failed", "error"}:
            return _console_color(label, "31")
        if label == "warning" or normalized in {"warning", "passed-with-warnings"}:
            return _console_color(label, "33")
        return label

    print()
    print(f"{title}: {_status_label(payload.get('status'))}")
    reason = payload.get("reason")
    if reason:
        print(f"  Reason: {reason}")
    for item in list(payload.get("vms") or []):
        item_status = item.get("status") or "unknown"
        line = f"  - {item.get('role')}: {_status_label(item_status)}"
        if item.get("host"):
            line += f" ({item.get('host')})"
        if item.get("url"):
            line += f" ({item.get('url')})"
        if item.get("status_code"):
            line += f" HTTP {item.get('status_code')}"
        if item.get("reason"):
            line += f" [{item.get('reason')}]"
        print(line)
        facts = dict(item.get("facts") or {})
        if facts:
            for key in ("hostname", "user", "os", "ips", "docker", "containerd", "kubectl", "k3s", "remote_workdir", "http_local"):
                if facts.get(key):
                    print(f"    {key}: {facts[key]}")
        if item.get("detail"):
            label = "warning" if str(item.get("status") or "").lower() == "warning" else "detail"
            print(f"    {_detail_label(label, item.get('status'))}: {item.get('detail')}")
        if item.get("error"):
            label = "error" if str(item.get("status") or "").lower() == "failed" else "detail"
            print(f"    {_detail_label(label, item.get('status'))}: {item.get('error')}")


def _print_vm_distributed_manual_commands(plan):
    vm_plan = dict(plan or {})
    print()
    print("Non-destructive manual checks for vm-distributed:")
    for vm in list(vm_plan.get("vms") or []):
        ssh_command = str((vm.get("ssh") or {}).get("command") or "").strip()
        print(f"- {vm.get('role')}:")
        if ssh_command:
            print(f"  {ssh_command}")
        if vm.get("http_url"):
            print(f"  curl -I {shlex.quote(str(vm.get('http_url')))}")
    print("- Hosts plan:")
    print("  python3 main.py <adapter> hosts --topology vm-distributed --dry-run")
    print("- Deployment preview:")
    print("  python3 main.py <adapter> deploy --topology vm-distributed --dry-run")


def _print_vm_distributed_assistant_menu(current_adapter=None):
    print()
    print("=" * 50)
    print("VM-DISTRIBUTED ASSISTANT")
    print("=" * 50)
    print(f"Adapter: {current_adapter or '(not selected)'}")
    print(f"Profile: {_current_environment_profile_display()}")
    print("P - Select local configuration profile")
    print("1 - Configure/update local vm-distributed .config files")
    print("2 - Show configured topology and static preflight")
    print("3 - Preview deployment and hosts plan")
    print("4 - Run non-destructive SSH/HTTP preflight")
    print("5 - Show manual check commands")
    print("6 - Guided SSH access setup")
    print("7 - Local SSH key self-test")
    print("8 - Prepare local k3s kubeconfigs")
    print("9 - Show runtime artifact paths")
    print("B/Q - Back")
    print("=" * 50)


def _run_vm_distributed_assistant(
    current_adapter=None,
    adapter_registry=None,
    deployer_registry=None,
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
):
    registry = adapter_registry or ADAPTER_REGISTRY
    while True:
        _print_vm_distributed_assistant_menu(current_adapter=current_adapter)
        choice = _interactive_read("\nSelection: ").strip().upper()
        if not choice or choice in {"B", "Q"}:
            return {"status": "completed", "adapter": current_adapter, "topology": "vm-distributed"}

        if choice == "P":
            _select_environment_profile_interactively()
            continue

        if choice == "1":
            result = _run_vm_distributed_configuration_wizard(
                current_adapter=current_adapter,
                adapter_registry=registry,
            )
            if isinstance(result, dict):
                current_adapter = result.get("adapter") or current_adapter
                _print_action_result(result)
            continue

        if choice == "2":
            selected_adapter = _interactive_require_adapter_selection(
                current_adapter,
                adapter_registry=registry,
            )
            if not selected_adapter:
                continue
            current_adapter = selected_adapter
            plan = _current_vm_distributed_topology_plan(adapter_name=current_adapter)
            _print_vm_distributed_topology_plan(plan)
            _print_vm_distributed_preflight(plan.get("configuration_preflight"))
            continue

        if choice == "3":
            selected_adapter = _interactive_require_adapter_selection(
                current_adapter,
                adapter_registry=registry,
            )
            if not selected_adapter:
                continue
            current_adapter = selected_adapter
            plan = _current_vm_distributed_topology_plan(adapter_name=current_adapter)
            _print_vm_distributed_topology_plan(plan)
            preview = build_dry_run_preview(
                adapter_name=current_adapter,
                command="deploy",
                adapter_registry=registry,
                deployer_registry=deployer_registry,
                validation_engine_cls=validation_engine_cls,
                metrics_collector_cls=metrics_collector_cls,
                experiment_storage=experiment_storage,
                topology="vm-distributed",
                include_deployer_dry_run=True,
            )
            _print_action_result(preview)
            continue

        if choice == "4":
            selected_adapter = _interactive_require_adapter_selection(
                current_adapter,
                adapter_registry=registry,
            )
            if not selected_adapter:
                continue
            current_adapter = selected_adapter
            local_prep = _ensure_vm_distributed_local_kubeconfigs()
            if local_prep.get("status") in {"updated", "failed"}:
                _print_vm_distributed_kubeconfig_sync_result(local_prep)
            wrapper_prep = _ensure_k3s_kubectl_wrapper()
            if wrapper_prep.get("reason") == "k3s-kubectl-wrapper":
                print(f"Local kubectl wrapper: {wrapper_prep.get('status')} ({wrapper_prep.get('path')})")
            plan = _current_vm_distributed_topology_plan(adapter_name=current_adapter)
            _print_vm_distributed_topology_plan(plan)
            print()
            print("This preflight uses SSH BatchMode and HTTP GET only. It may prepare local kubeconfigs/runtime wrappers, but it does not install packages, change firewall rules or deploy resources.")
            if not _interactive_confirm("Run remote vm-distributed preflight now?", default=False):
                print("Remote preflight cancelled.")
                continue
            ssh_result = run_vm_distributed_remote_preflight(plan)
            http_result = run_vm_distributed_http_preflight(plan)
            _print_vm_distributed_preflight_results("SSH preflight", ssh_result)
            _print_vm_distributed_preflight_results("HTTP preflight", http_result)
            continue

        if choice == "5":
            selected_adapter = _interactive_require_adapter_selection(
                current_adapter,
                adapter_registry=registry,
            )
            if not selected_adapter:
                continue
            current_adapter = selected_adapter
            plan = _current_vm_distributed_topology_plan(adapter_name=current_adapter)
            _print_vm_distributed_manual_commands(plan)
            continue

        if choice == "6":
            selected_adapter = _interactive_require_adapter_selection(
                current_adapter,
                adapter_registry=registry,
            )
            if not selected_adapter:
                continue
            current_adapter = selected_adapter
            result = _run_vm_distributed_ssh_access_assistant(
                build_adapter(current_adapter, adapter_registry=registry, topology="vm-distributed"),
                deployer_name=current_adapter,
                topology="vm-distributed",
            )
            if isinstance(result, dict) and result.get("status") == "needs-review":
                message = str(result.get("message") or "").strip()
                if message:
                    print(message)
                plan_result = result.get("plan") if isinstance(result.get("plan"), dict) else result
                _print_vm_distributed_ssh_access_result(plan_result, show_interactive_guide=False)
            continue

        if choice == "7":
            selected_adapter = _interactive_require_adapter_selection(
                current_adapter,
                adapter_registry=registry,
            )
            if not selected_adapter:
                continue
            current_adapter = selected_adapter
            result = run_ssh_access(
                build_adapter(current_adapter, adapter_registry=registry, topology="vm-distributed"),
                deployer_name=current_adapter,
                topology="vm-distributed",
                action="self-test",
            )
            _print_vm_distributed_ssh_key_self_test_result(result)
            continue

        if choice == "8":
            selected_adapter = _interactive_require_adapter_selection(
                current_adapter,
                adapter_registry=registry,
            )
            if not selected_adapter:
                continue
            current_adapter = selected_adapter
            result = _ensure_vm_distributed_local_kubeconfigs()
            _print_vm_distributed_kubeconfig_sync_result(result)
            if result.get("status") == "failed":
                print("Kubeconfig preparation failed. Fix the issue above before running levels 2-6.")
            continue

        if choice == "9":
            selected_adapter = _interactive_require_adapter_selection(
                current_adapter,
                adapter_registry=registry,
            )
            if not selected_adapter:
                continue
            current_adapter = selected_adapter
            adapter = build_adapter(current_adapter, adapter_registry=registry, topology="vm-distributed")
            _print_runtime_artifact_paths(
                run_runtime_artifact_paths(
                    adapter,
                    deployer_name=current_adapter,
                    deployer_registry=deployer_registry,
                    topology="vm-distributed",
                )
            )
            continue

        print("Invalid vm-distributed assistant selection.")


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


def _shared_common_services_resetter(infrastructure):
    resetter = getattr(infrastructure, "reset_local_shared_common_services", None)
    if not callable(resetter):
        resetter = getattr(infrastructure, "reset_common_services_for_level4_repair", None)
    if not callable(resetter):
        raise RuntimeError(
            "Shared infrastructure does not expose a controlled common-services reset operation."
        )
    return resetter


def _level2_common_services_reset_runtime(topology):
    normalized_topology = normalize_topology(topology)
    if normalized_topology == VM_DISTRIBUTED_TOPOLOGY:
        kubeconfig_sync = _ensure_vm_distributed_local_kubeconfigs(
            roles=_vm_distributed_level_kubeconfig_roles(2),
        )
        _raise_vm_distributed_kubeconfig_sync_failure(kubeconfig_sync)
        if kubeconfig_sync.get("status") == "updated":
            _print_vm_distributed_kubeconfig_sync_result(kubeconfig_sync)

    environment_overrides = _topology_runtime_environment_overrides(
        normalized_topology,
        level=2,
        role="common" if normalized_topology == VM_DISTRIBUTED_TOPOLOGY else None,
    )
    if not environment_overrides:
        return contextlib.nullcontext()

    environment_overrides["PIONERA_LEVEL_RUNTIME_ENV_ACTIVE"] = "true"
    return _temporary_environment(environment_overrides)


def _reset_shared_common_services_for_level2(infrastructure, reason, topology="local"):
    resetter = _shared_common_services_resetter(infrastructure)
    with _level2_common_services_reset_runtime(topology):
        if not resetter(reason=reason):
            raise RuntimeError("Could not reset shared common services safely.")


def _vm_topology_vault_artifact_gap(infrastructure, topology):
    if normalize_topology(topology) not in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
        return None

    resolver = getattr(infrastructure, "_vault_keys_artifact_path", None)
    if not callable(resolver):
        return None

    scoped_path = str(resolver() or "").strip()
    if not scoped_path:
        return None

    config = getattr(infrastructure, "config", None)
    script_dir_getter = getattr(config, "script_dir", None)
    root = script_dir_getter() if callable(script_dir_getter) else None
    legacy_path = str(runtime_artifacts.legacy_vault_keys_path(root=root))
    if os.path.abspath(scoped_path) == os.path.abspath(legacy_path):
        return None
    if os.path.exists(scoped_path) or not os.path.exists(legacy_path):
        return None

    return {
        "scoped_path": _framework_relative_path(scoped_path),
        "legacy_path": _framework_relative_path(legacy_path),
    }


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
    normalized_topology = normalize_topology(topology)
    execution_context = _interactive_execution_context(topology)
    adapter = build_adapter(
        shared_adapter_name,
        adapter_registry=adapter_registry,
        dry_run=False,
        topology=topology,
    )

    infrastructure = getattr(adapter, "infrastructure", None)
    vault_gap = _vm_topology_vault_artifact_gap(infrastructure, topology)
    if vault_gap:
        print()
        print("Topology-scoped Vault keys are missing for the active topology.")
        print("A legacy Vault keys artifact exists, but it is ignored to avoid mixing topology state.")
        print(f"Expected scoped artifact: {vault_gap['scoped_path']}")
        print(f"Ignored legacy artifact: {vault_gap['legacy_path']}")
        if not _interactive_confirm(
            f"Recreate shared common services now ({execution_context})? "
            "This resets common-srvs for all adapters in this cluster.",
            default=False,
        ):
            print("Level 2 cancelled.")
            return None
        _reset_shared_common_services_for_level2(
            infrastructure,
            reason="Interactive Level 2 recreate requested for topology-scoped Vault artifact",
            topology=topology,
        )

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
                public_access_result = None
                if normalized_topology in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}:
                    sync_public_access = getattr(infrastructure, "sync_vm_distributed_public_access", None)
                    if callable(sync_public_access):
                        print(f"Reconciling {normalized_topology} public access for reused common services...")
                        try:
                            public_access_result = sync_public_access(topology=normalized_topology)
                        except TypeError:
                            public_access_result = sync_public_access()
                        except Exception as exc:
                            print(f"Warning: {normalized_topology} public access reconciliation failed: {exc}")
                            public_access_result = {"status": "failed", "error": str(exc)}
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
                if public_access_result is not None:
                    payload["result"]["public_access"] = public_access_result
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

            _reset_shared_common_services_for_level2(
                infrastructure,
                reason="Interactive Level 2 recreate requested",
                topology=topology,
            )

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

    if normalize_topology(topology) == VM_SINGLE_TOPOLOGY and not _should_interactive_vm_single_hosts_preflight(context):
        return {"deployer_name": resolved_deployer_name} if resolved_deployer_name else {}

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


def _run_interoperability_tests_menu_interactive(
    current_adapter,
    *,
    adapter_registry=None,
    deployer_registry=None,
    topology="local",
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    kafka_manager_cls=KafkaManager,
):
    selected_adapter = _interactive_require_adapter_selection(
        current_adapter,
        adapter_registry=adapter_registry,
    )
    if not selected_adapter:
        return None

    print()
    print("INTEROPERABILITY TESTS")
    print("1 - Newman connector interoperability tests")
    print("2 - Kafka transfer interoperability tests")
    print("B - Back")
    choice = _interactive_read("Selection: ").strip().upper()
    if choice in {"", "B", "BACK"}:
        return {"status": "cancelled", "adapter": selected_adapter, "topology": topology}

    adapter = build_adapter(
        selected_adapter,
        adapter_registry=adapter_registry,
        topology=topology,
    )
    execution_context = _interactive_execution_context(topology, selected_adapter)
    if choice == "1":
        if not _interactive_confirm(
            f"Run Newman interoperability tests ({execution_context})?",
            default=False,
        ):
            print("Newman interoperability tests cancelled.")
            return {"status": "cancelled", "adapter": selected_adapter, "topology": topology}
        return run_interoperability_newman_tests(
            adapter,
            deployer_name=selected_adapter,
            deployer_registry=deployer_registry,
            topology=topology,
            validation_engine_cls=validation_engine_cls,
            metrics_collector_cls=metrics_collector_cls,
            experiment_storage=experiment_storage,
        )

    if choice == "2":
        if not _interactive_confirm(
            f"Run Kafka transfer interoperability tests ({execution_context})?",
            default=False,
        ):
            print("Kafka transfer interoperability tests cancelled.")
            return {"status": "cancelled", "adapter": selected_adapter, "topology": topology}
        return run_interoperability_kafka_tests(
            adapter,
            deployer_name=selected_adapter,
            deployer_registry=deployer_registry,
            topology=topology,
            experiment_storage=experiment_storage,
            kafka_manager_cls=kafka_manager_cls,
        )

    print("Invalid interoperability test selection.")
    return {"status": "cancelled", "adapter": selected_adapter, "topology": topology}


def _csv_tokens(raw_value):
    tokens = []
    for token in str(raw_value or "").split(","):
        item = token.strip()
        if item and item not in tokens:
            tokens.append(item)
    return tokens


def _connector_short_name_from_full(connector, dataspace_name):
    value = str(connector or "").strip()
    dataspace = str(dataspace_name or "").strip()
    prefix = "conn-"
    suffix = f"-{dataspace}" if dataspace else ""
    if value.startswith(prefix) and suffix and value.endswith(suffix):
        return value[len(prefix) : -len(suffix)]
    if value.startswith(prefix):
        return value[len(prefix) :]
    return value


def _connector_full_name_from_short(connector, dataspace_name):
    parsed = parse_connector_list(connector, dataspace_name)
    return parsed[0] if parsed else ""


def _default_connector_location_for_add(existing_mapping, existing_connectors):
    provider_count = sum(1 for value in existing_mapping.values() if str(value).strip().lower() == "provider")
    consumer_count = sum(1 for value in existing_mapping.values() if str(value).strip().lower() == "consumer")
    if not existing_mapping:
        connector_count = len(list(existing_connectors or []))
        if connector_count == 1:
            return "consumer"
    return "provider" if provider_count <= consumer_count else "consumer"


def _default_connector_location_mapping_tokens(connectors, dataspace_name):
    tokens = []
    for index, connector in enumerate(list(connectors or [])):
        short_name = _connector_short_name_from_full(connector, dataspace_name)
        role = "provider" if index % 2 == 0 else "consumer"
        tokens.append(f"{short_name}:{role}")
    return tokens


def _build_add_connector_inventory_plan(adapter_config, connector_name, location, validation_pair=""):
    config = dict(adapter_config or {})
    dataspace_name = str(config.get("DS_1_NAME") or config.get("DS_NAME") or "").strip()
    short_name = str(connector_name or "").strip()
    if not dataspace_name:
        return {
            "status": "failed",
            "reason": "missing-dataspace",
            "message": "DS_1_NAME is required before adding a connector.",
        }
    if not short_name:
        return {
            "status": "cancelled",
            "reason": "empty-connector-name",
            "message": "Connector name was empty.",
        }
    if "," in short_name or ":" in short_name or ">" in short_name or "=" in short_name:
        return {
            "status": "failed",
            "reason": "invalid-connector-name",
            "message": "Use one connector short name without commas, colons or pair separators.",
        }

    existing_tokens = _csv_tokens(config.get("DS_1_CONNECTORS"))
    existing_connectors = parse_connector_list(config.get("DS_1_CONNECTORS"), dataspace_name)
    new_connector = _connector_full_name_from_short(short_name, dataspace_name)
    if not new_connector:
        return {
            "status": "failed",
            "reason": "invalid-connector-name",
            "message": "Connector name could not be normalized.",
        }
    if new_connector in existing_connectors:
        return {
            "status": "exists",
            "adapter_updates": {},
            "dataspace": dataspace_name,
            "connector": new_connector,
            "connector_short_name": _connector_short_name_from_full(new_connector, dataspace_name),
            "message": f"Connector {new_connector} is already present in DS_1_CONNECTORS.",
        }

    connector_tokens = [*existing_tokens, short_name]
    connector_full_set = set([*existing_connectors, new_connector])
    mapping_raw = str(config.get("DS_1_CONNECTOR_NAMESPACES") or "").strip()
    mapping = parse_connector_mapping(mapping_raw, dataspace_name)
    mapping_tokens = _csv_tokens(mapping_raw)
    selected_location = str(location or "").strip().lower()
    if not selected_location:
        selected_location = _default_connector_location_for_add(mapping, existing_connectors)
    if selected_location not in {"provider", "consumer", "dataspace"}:
        selected_location = str(location or "").strip()
    if not selected_location:
        selected_location = "provider"
    if not mapping_tokens and existing_connectors:
        mapping_tokens = _default_connector_location_mapping_tokens(existing_connectors, dataspace_name)
        mapping = parse_connector_mapping(",".join(mapping_tokens), dataspace_name)
    if new_connector not in mapping:
        mapping_tokens.append(f"{short_name}:{selected_location}")

    pair_tokens = _csv_tokens(config.get("DS_1_VALIDATION_PAIRS"))
    pair_raw = str(validation_pair or "").strip()
    added_pair = ""
    if pair_raw and pair_raw.lower() not in {"none", "skip", "-"}:
        parsed_pairs = parse_connector_pairs(pair_raw, dataspace_name)
        if len(parsed_pairs) != 1:
            return {
                "status": "failed",
                "reason": "invalid-validation-pair",
                "message": "Validation pair must use source>target, for example partnera>org3.",
            }
        source, target = parsed_pairs[0]
        missing = [connector for connector in (source, target) if connector not in connector_full_set]
        if missing:
            return {
                "status": "failed",
                "reason": "unknown-validation-pair-connector",
                "message": (
                    "Validation pair references connectors outside the updated inventory: "
                    + ", ".join(missing)
                ),
            }
        existing_pairs = parse_connector_pairs(config.get("DS_1_VALIDATION_PAIRS"), dataspace_name)
        if (source, target) not in existing_pairs:
            pair_tokens.append(pair_raw)
            added_pair = pair_raw

    updates = {
        "DS_1_CONNECTORS": ",".join(connector_tokens),
        "DS_1_CONNECTOR_NAMESPACES": ",".join(mapping_tokens),
        "LEVEL4_CONNECTOR_RECONCILIATION_MODE": "additive",
    }
    if pair_tokens:
        updates["DS_1_VALIDATION_PAIRS"] = ",".join(pair_tokens)

    return {
        "status": "planned",
        "dataspace": dataspace_name,
        "connector": new_connector,
        "connector_short_name": short_name,
        "location": selected_location,
        "validation_pair": added_pair,
        "adapter_updates": updates,
        "existing_connectors": existing_connectors,
        "updated_connectors": [*existing_connectors, new_connector],
    }


def _print_add_connector_plan(plan, adapter_name, topology):
    print()
    print("ADD CONNECTOR PLAN")
    print(f"Adapter: {adapter_name}")
    print(f"Topology: {topology}")
    print(f"Dataspace: {plan.get('dataspace')}")
    print(f"New connector: {plan.get('connector')}")
    if plan.get("location"):
        print(f"Placement: {plan.get('location')}")
    if plan.get("validation_pair"):
        print(f"Validation pair to add: {plan.get('validation_pair')}")
    else:
        print("Validation pair to add: none")
    print()
    print("Configuration updates:")
    for key, value in sorted(dict(plan.get("adapter_updates") or {}).items()):
        print(f"- {key}={value}")


def _run_add_connector_interactive(
    current_adapter,
    *,
    adapter_registry=None,
    deployer_registry=None,
    topology="local",
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
):
    selected_adapter = _interactive_require_adapter_selection(
        current_adapter,
        adapter_registry=adapter_registry,
    )
    if not selected_adapter:
        return None

    adapter_path = _seed_adapter_deployer_config_if_missing(selected_adapter)
    adapter_config = load_raw_deployer_config(adapter_path)
    dataspace_name = str(adapter_config.get("DS_1_NAME") or adapter_config.get("DS_NAME") or "").strip()
    existing_connectors = parse_connector_list(adapter_config.get("DS_1_CONNECTORS"), dataspace_name)

    print()
    print("ADD CONNECTOR TO EXISTING DATASPACE")
    print("This updates the connector inventory and runs Level 4 in additive mode when confirmed.")
    if dataspace_name:
        print(f"Dataspace: {dataspace_name}")
    if existing_connectors:
        print("Current connectors:")
        for connector in existing_connectors:
            print(f"- {_connector_short_name_from_full(connector, dataspace_name)} ({connector})")
    else:
        print("Current connectors: none configured")

    connector_name = _interactive_read("New connector short name (blank to cancel): ").strip()
    if not connector_name:
        print("Add connector cancelled.")
        return {"status": "cancelled", "adapter": selected_adapter, "topology": topology}

    existing_mapping = parse_connector_mapping(adapter_config.get("DS_1_CONNECTOR_NAMESPACES"), dataspace_name)
    default_location = _default_connector_location_for_add(existing_mapping, existing_connectors)
    location = _interactive_read(
        f"Placement group (provider/consumer/dataspace or custom) [{default_location}]: "
    ).strip() or default_location

    default_pair = ""
    if existing_connectors:
        first_existing = _connector_short_name_from_full(existing_connectors[0], dataspace_name)
        default_pair = f"{connector_name}>{first_existing}"
    validation_pair = ""
    if default_pair:
        validation_pair = _interactive_read(
            f"Validation pair involving the new connector [{default_pair}, none=skip]: "
        ).strip()
        if not validation_pair:
            validation_pair = default_pair
    else:
        validation_pair = _interactive_read("Validation pair involving the new connector (source>target, blank=skip): ").strip()

    plan = _build_add_connector_inventory_plan(
        adapter_config,
        connector_name,
        location,
        validation_pair=validation_pair,
    )
    if plan.get("status") == "exists":
        print(plan.get("message"))
        return {"status": "skipped", "adapter": selected_adapter, "topology": topology, "reason": "connector-exists"}
    if plan.get("status") != "planned":
        print(plan.get("message") or "Could not prepare add connector plan.")
        return {
            "status": "failed",
            "adapter": selected_adapter,
            "topology": topology,
            "reason": plan.get("reason") or "plan-failed",
        }

    _print_add_connector_plan(plan, selected_adapter, topology)
    if not _interactive_confirm("Apply these connector inventory changes?", default=False):
        print("Add connector cancelled before writing configuration.")
        return {"status": "cancelled", "adapter": selected_adapter, "topology": topology}

    _write_key_value_updates(
        adapter_path,
        plan["adapter_updates"],
        sorted(_adapter_profile_keys(selected_adapter)),
    )
    print(f"Updated adapter configuration: {_framework_relative_path(adapter_path)}")

    result = {
        "status": "prepared",
        "adapter": selected_adapter,
        "topology": topology,
        "connector": plan.get("connector"),
        "updated_keys": sorted(plan["adapter_updates"]),
        "config_file": _framework_relative_path(adapter_path),
    }

    if not _interactive_confirm(
        f"Run Level 4 in additive mode now ({_interactive_execution_context(topology, selected_adapter)})?",
        default=False,
    ):
        print("Level 4 not run. You can run Level 4 later; it is now configured in additive mode.")
        return result

    if not _interactive_ensure_hosts_ready_for_levels(
        selected_adapter,
        levels=[4],
        adapter_registry=adapter_registry,
        deployer_registry=deployer_registry,
        topology=topology,
    ):
        result["status"] = "prepared"
        result["level_4"] = {"status": "skipped", "reason": "hosts-not-ready"}
        return result

    level_result = run_levels(
        selected_adapter,
        levels=[4],
        adapter_registry=adapter_registry,
        deployer_registry=deployer_registry,
        topology=topology,
        validation_engine_cls=validation_engine_cls,
        metrics_collector_cls=metrics_collector_cls,
        experiment_storage=experiment_storage,
    )
    result["status"] = "completed"
    result["level_4"] = level_result
    return result


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
    print("W - vm-distributed assistant")
    print("P - Preview deployment plan")
    print("H - Plan/apply hosts entries")
    print("U - Show available access URLs")
    print("J - Add connector to existing dataspace")
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
    print("[Validation]")
    print("I - INESData UI Tests (Normal/Live/Debug)")
    print("N - EDC UI Tests (Normal/Live/Debug)")
    print("O - Ontology Hub UI Tests (Normal/Live/Debug)")
    print("A - AI Model Hub UI Tests (Normal/Live/Debug)")
    print("V - Semantic Virtualization UI Tests (Normal/Live/Debug)")
    print("F - Dataspace Interoperability Tests (Newman/Kafka)")
    print("Y - Run Test by ID (Playwright/API)")
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
    print("K - Use when vm-single is active and you want to confirm or persist the k3s runtime for this menu session.")
    print("W - Use before selecting vm-distributed to open the configuration wizard, or with vm-distributed active to open the assistant.")
    print("    The assistant can write ignored .config files, show the VM plan, preview hosts/deployment, run non-destructive checks, show artifact paths, and guide SSH setup.")
    print("P - Use before deploying to inspect the plan without changing the environment.")
    print("    If Levels 3-6 need an adapter and none has been chosen yet, the menu asks for one automatically.")
    print("H - Use to inspect or apply local hosts entries needed by the selected adapter.")
    print("    It shows concrete hostnames, the sync result, and in menu mode can offer to apply the plan immediately.")
    print("U - Use to print access URLs derived from the selected adapter config in a readable format.")
    print("    Useful after Levels 2-5 when you want portal, connector, component or MinIO access details without searching files manually.")
    print("J - Use when an existing dataspace needs one more connector without recreating healthy connectors.")
    print("    It updates the connector inventory, switches Level 4 to additive mode, shows a plan, and can run Level 4 after confirmation.")
    print("G - Use to inspect an external INESData validation target without deploying PIONERA resources.")
    print("    The current runner validates the target YAML and can run enabled read-only Playwright project specs.")
    print("E - Use to open a local, read-only dashboard for previous validation experiments.")
    print("    It lists experiments, summarizes long JSON artifacts, and serves reports only on 127.0.0.1.")
    print(
        "M - Use when you only need metrics or standalone benchmarks. "
        "It does not replace Level 6 validation; Kafka E2E validation is opt-in in Level 6."
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
    print("[Validation]")
    print("I - Use to validate the INESData portal experience and component integrations through INESData.")
    print("N - Use to validate the EDC dashboard experience and component integrations through EDC.")
    print("O - Use when Ontology Hub UI changed or after deploying ontology-related components.")
    print("    This runs Ontology Hub component suites, not the INESData integration validation.")
    print("A - Use when AI Model Hub UI changed or after deploying AI Model Hub components.")
    print("    This runs AI Model Hub component suites, not the INESData integration validation.")
    print("V - Use when Semantic Virtualization UI/API browser reachability changed or after deploying the virtualizer.")
    print("    This runs Semantic Virtualization component/editor suites, not the INESData integration validation.")
    print("F - Use to run interoperability suites independently of full Level 6.")
    print("    The sub-menu separates Newman connector tests from Kafka transfer tests.")
    print("    Kafka still requires explicit confirmation because it can take significantly longer.")
    print("Y - Use to run one mapped automated test by its audit/test ID.")
    print("    The framework resolves whether the selected ID belongs to Playwright UI or component API validation.")
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

    available_cluster_types = ("k3s",)
    try:
        current = normalize_cluster_type(
            current_runtime or _resolve_interactive_cluster_runtime(normalized_topology).get("cluster_type"),
            topology=normalized_topology,
        )
    except ValueError:
        current = "k3s"

    print()
    print("Available cluster runtimes for vm-single:")
    for index, cluster_type in enumerate(available_cluster_types, start=1):
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

    if index < 0 or index >= len(available_cluster_types):
        print("Invalid selection.")
        return current
    return available_cluster_types[index]


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
    previous = _normalized_previous_cluster_runtime(previous_runtime)
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


_INTERACTIVE_RUNTIME_ENV_KEYS = {
    "KUBECONFIG",
    "PIONERA_KUBECONFIG_ROLE",
    "KUBECTL_INSECURE_SKIP_TLS_VERIFY",
    "HELM_KUBEINSECURE_SKIP_TLS_VERIFY",
}


def _apply_interactive_topology_runtime_environment(topology="local"):
    """Apply session-scoped kubectl environment for the active interactive topology."""

    for key in _INTERACTIVE_RUNTIME_ENV_KEYS:
        os.environ.pop(key, None)

    overrides = _topology_runtime_environment_overrides(topology)
    for key, value in overrides.items():
        if value is not None and str(value).strip():
            os.environ[key] = str(value)
    return overrides


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
    if not current_adapter or normalized_topology not in {LOCAL_TOPOLOGY, "vm-single", VM_DISTRIBUTED_TOPOLOGY}:
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
    if normalized_topology == "vm-single" and not _should_interactive_vm_single_hosts_preflight(context):
        return True
    if normalized_topology == VM_DISTRIBUTED_TOPOLOGY and not _should_interactive_vm_distributed_hosts_preflight(context):
        return True
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


def _should_interactive_vm_single_hosts_preflight(context):
    config = dict(getattr(context, "config", {}) or {})
    values = {"TOPOLOGY": "vm-single", **config}
    public_urls = resolve_vm_distributed_public_urls(values)
    for key in ("VM_COMMON_PUBLIC_URL", "VM_SINGLE_PUBLIC_URL", "VM_SINGLE_HTTP_URL"):
        if _usable_vm_public_url_config_value(public_urls.get(key) or values.get(key)):
            return False
    return True


def _should_interactive_vm_distributed_hosts_preflight(context):
    config = dict(getattr(context, "config", {}) or {})
    execution_host = _normalized_vm_distributed_execution_host(config)
    if execution_host != "common-services":
        return False

    hosts_file = _interactive_hosts_file_path()
    if not hosts_file or _is_windows_hosts_file(hosts_file):
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
        if normalized in {"completed_with_validation_failures", "completed-with-validation-failures"}:
            return "Completed with validation failures"
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
        if normalized in {"partial", "partially-passed", "passed-with-warnings"}:
            return "Partial"
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

        validation_status = str(payload.get("validation_status") or "").strip().lower()
        if validation_status:
            lines.append(f"Validation: {_console_result_label(validation_status)}")
        else:
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
            reconciled_public_hostnames = list(hosts_sync.get("reconciled_public_hostnames") or [])
            if reconciled_public_hostnames:
                lines.append(f"Hosts public names reconciled: {len(reconciled_public_hostnames)}")

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


def _generate_framework_dashboard(experiment_dir):
    try:
        experiment = inspect_experiment(experiment_dir)
        dashboard_path = build_experiment_dashboard(experiment)
    except Exception as exc:
        print(f"[WARNING] Could not generate framework dashboard: {exc}")
        return {
            "status": "failed",
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
    print(f"Framework dashboard saved to {dashboard_path}")
    return {
        "status": "generated",
        "path": str(dashboard_path),
    }


def _generate_level6_une_0087_alignment(experiment_dir):
    if not experiment_dir:
        return {
            "status": "skipped",
            "reason": "missing-experiment-dir",
        }
    try:
        alignment = write_une_0087_alignment(experiment_dir)
    except Exception as exc:
        print(f"[WARNING] Could not generate UNE 0087 alignment: {exc}")
        return {
            "status": "failed",
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }

    summary = alignment.get("summary") if isinstance(alignment, dict) else {}
    statuses = summary.get("statuses") if isinstance(summary, dict) else {}
    print(
        "UNE 0087 alignment generated: "
        f"covered={statuses.get('covered', 0)}, "
        f"partial={statuses.get('partially_covered', 0)}, "
        f"missing={statuses.get('not_covered', 0)}"
    )
    _print_level6_une_0087_checklist(alignment, experiment_dir)
    return {
        "status": "generated",
        "artifacts": [
            "une_0087_alignment.json",
            "une_0087_alignment.md",
        ],
        "summary": summary,
    }


def _print_level6_une_0087_checklist(alignment, experiment_dir=None):
    rows = format_une_0087_console_summary(alignment)
    if not rows:
        return

    markdown_path = os.path.join(str(experiment_dir), "une_0087_alignment.md") if experiment_dir else "une_0087_alignment.md"

    print()
    print(_console_color("UNE 0087 summary", "33;1"))
    print("Non-certifying support checklist. Full criteria details are available in the Markdown report.")
    print(
        tabulate(
            rows,
            headers="keys",
            tablefmt="github",
            disable_numparse=True,
        )
    )
    print(f"Detailed UNE report: {markdown_path}")


def _offer_open_level6_dashboard(framework_report):
    if not _env_flag("PIONERA_LEVEL6_PROMPT_OPEN_REPORT", True):
        return
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return
    if not isinstance(framework_report, dict):
        return

    dashboard_path = framework_report.get("path")
    if not dashboard_path:
        return
    dashboard_path = os.path.abspath(str(dashboard_path))
    if not os.path.exists(dashboard_path):
        return
    framework_report_dir = os.path.dirname(dashboard_path)
    experiment_dir = os.path.dirname(framework_report_dir)
    if not os.path.isdir(experiment_dir):
        return
    if not _interactive_confirm("Open Level 6 dashboard report now?", default=False):
        return

    try:
        server = launch_static_report_server(experiment_dir)
    except Exception as exc:
        print(f"Could not open Level 6 dashboard report: {exc}")
        return

    url = f"{server['url']}/framework-report/index.html"
    print()
    print("Level 6 dashboard available at:")
    print(url)
    print(f"Dashboard file: {dashboard_path}")
    print("The local server is bound to 127.0.0.1 and stays alive while this framework process is running.")
    if not server.get("ready"):
        print("The dashboard server is still starting. If the browser does not open, use the URL above.")
    _open_dashboard_url_with_wsl_file_fallback(url, dashboard_path, server_ready=bool(server.get("ready")))


def _open_dashboard_url_with_wsl_file_fallback(url, dashboard_path, *, server_ready=True):
    if server_ready:
        open_result = open_local_url(url)
        if open_result.get("opened"):
            print(f"Opened in the default browser through {open_result.get('method')}.")
            return
        print(f"Could not open the browser automatically: {open_result.get('reason')}")

    wsl_file_url = wsl_file_url_for_path(dashboard_path)
    if not wsl_file_url:
        return

    print("WSL file URL fallback:")
    print(wsl_file_url)
    fallback_result = open_local_url(wsl_file_url)
    if fallback_result.get("opened"):
        print(f"Opened WSL file URL through {fallback_result.get('method')}.")
    else:
        print(f"Could not open the WSL file URL automatically: {fallback_result.get('reason')}")


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
    _open_dashboard_url_with_wsl_file_fallback(url, dashboard_path, server_ready=bool(server.get("ready")))


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


def _run_legacy_menu_action(action_name, current_adapter="inesdata", topology="local"):
    """Run compatibility menu shortcuts through the migrated main.py modules."""
    migrated_actions = {
        "bootstrap": local_menu_tools.run_framework_bootstrap_interactive,
        "doctor": local_menu_tools.run_framework_doctor,
        "recover": local_menu_tools.run_connector_recovery_after_wsl_restart,
        "cleanup": local_menu_tools.run_workspace_cleanup_interactive,
        "inesdata_ui": ui_interactive_menu.run_inesdata_ui_tests_interactive,
        "edc_ui": ui_interactive_menu.run_edc_ui_tests_interactive,
        "ontology_hub_ui": ui_interactive_menu.run_ontology_hub_ui_tests_interactive,
        "ai_model_hub_ui": ui_interactive_menu.run_ai_model_hub_ui_tests_interactive,
        "semantic_virtualization_ui": ui_interactive_menu.run_semantic_virtualization_ui_tests_interactive,
    }
    if action_name == "validation_test_by_id":
        return ui_interactive_menu.run_validation_test_by_id_interactive(
            adapter_name=current_adapter,
            topology=topology,
        )
    if action_name == "validation_api_test_by_id":
        return ui_interactive_menu.run_validation_api_test_by_id_interactive(
            adapter_name=current_adapter,
            topology=topology,
        )
    if action_name == "local_images":
        return local_menu_tools.run_local_images_workflow_interactive(active_adapter=current_adapter)

    migrated_action = migrated_actions.get(action_name)
    if callable(migrated_action):
        if action_name == "edc_ui":
            current_adapter = "edc"
        normalized_topology = normalize_topology(topology or LOCAL_TOPOLOGY)
        runtime_env = {
            "PIONERA_TOPOLOGY": normalized_topology,
            "INESDATA_TOPOLOGY": normalized_topology,
            "UI_TOPOLOGY": normalized_topology,
        }
        if current_adapter:
            runtime_env["PIONERA_ADAPTER"] = current_adapter
            runtime_env["UI_ADAPTER"] = current_adapter
            runtime_env["AI_MODEL_HUB_COMPONENT_ADAPTER"] = current_adapter
        with _temporary_environment(runtime_env):
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
    original_runtime_env = {
        key: (key in os.environ, os.environ.get(key))
        for key in _INTERACTIVE_RUNTIME_ENV_KEYS
    }

    def restore_cluster_type_env():
        if original_cluster_type_env_present:
            os.environ["PIONERA_CLUSTER_TYPE"] = original_cluster_type_env
        else:
            os.environ.pop("PIONERA_CLUSTER_TYPE", None)
        for key, (was_present, old_value) in original_runtime_env.items():
            if was_present:
                os.environ[key] = old_value
            else:
                os.environ.pop(key, None)

    def activate_interactive_topology(selected_topology):
        nonlocal topology, current_adapter

        topology = selected_topology
        print(f"Active topology set to {topology}.")
        normalized = normalize_topology(topology)

        if normalized == "vm-single":
            previous_runtime = _interactive_cluster_runtime_label(topology)
            selected_runtime = "k3s"
            switch_result = _try_vm_single_cluster_runtime_switch(
                selected_runtime,
                previous_runtime=previous_runtime,
            )
            if not switch_result.get("allowed"):
                return False
            _set_session_cluster_runtime_override(selected_runtime)
            _apply_interactive_topology_runtime_environment(topology)
            return True

        if normalized == "vm-distributed":
            _apply_interactive_topology_runtime_environment(topology)
            current_adapter, config_result = _offer_vm_distributed_configuration(
                current_adapter=current_adapter,
                adapter_registry=registry,
            )
            if config_result is not None:
                _print_action_result(config_result)
            return True

        _apply_interactive_topology_runtime_environment(topology)
        return True

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
                if not activate_interactive_topology(selected_topology):
                    return {"status": "exited", "adapter": current_adapter, "topology": topology}

        _apply_interactive_topology_runtime_environment(topology)

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
                        if not activate_interactive_topology(selected_topology):
                            continue
                    continue

                if choice == "K":
                    previous_runtime = _interactive_cluster_runtime_label(topology)
                    selected_runtime = _select_cluster_runtime_interactive(
                        topology=topology,
                    )
                    if normalize_topology(topology) == "vm-single":
                        switch_result = _try_vm_single_cluster_runtime_switch(
                            selected_runtime,
                            previous_runtime=previous_runtime,
                        )
                        if not switch_result.get("allowed"):
                            continue
                        _set_session_cluster_runtime_override(selected_runtime)
                        _apply_interactive_topology_runtime_environment(topology)
                        _offer_persist_vm_single_cluster_runtime(selected_runtime, previous_runtime=previous_runtime)
                    continue

                if choice == "W":
                    if normalize_topology(topology) != "vm-distributed":
                        if _interactive_confirm("Switch active topology to vm-distributed for this configuration?", default=True):
                            topology = "vm-distributed"
                            print("Active topology set to vm-distributed.")
                            _apply_interactive_topology_runtime_environment(topology)
                        else:
                            print("vm-distributed configuration cancelled.")
                            continue
                        result = _run_vm_distributed_configuration_wizard(
                            current_adapter=current_adapter,
                            adapter_registry=registry,
                        )
                        if isinstance(result, dict):
                            current_adapter = result.get("adapter") or current_adapter
                            _print_action_result(result)
                        continue
                    result = _run_vm_distributed_assistant(
                        current_adapter=current_adapter,
                        adapter_registry=registry,
                        deployer_registry=deployer_registry,
                        validation_engine_cls=validation_engine_cls,
                        metrics_collector_cls=metrics_collector_cls,
                        experiment_storage=experiment_storage,
                    )
                    if isinstance(result, dict):
                        current_adapter = result.get("adapter") or current_adapter
                    continue

                if normalize_topology(topology) == "vm-single" and _menu_action_requires_vm_single_address(choice):
                    if not _interactive_offer_vm_single_address_configuration(required=True):
                        continue

                if (
                    normalize_topology(topology) == "vm-distributed"
                    and _menu_action_benefits_from_vm_distributed_configuration(choice)
                    and _vm_distributed_configuration_needs_attention(current_adapter)
                ):
                    current_adapter, config_result = _offer_vm_distributed_configuration(
                        current_adapter=current_adapter,
                        adapter_registry=registry,
                    )
                    if config_result is not None:
                        _print_action_result(config_result)

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

                if choice == "F":
                    result = _run_interoperability_tests_menu_interactive(
                        current_adapter,
                        adapter_registry=registry,
                        deployer_registry=deployer_registry,
                        topology=topology,
                        validation_engine_cls=validation_engine_cls,
                        metrics_collector_cls=metrics_collector_cls,
                        experiment_storage=experiment_storage,
                        kafka_manager_cls=kafka_manager_cls,
                    )
                    if result is not None:
                        current_adapter = result.get("adapter") or current_adapter
                        _print_action_result(result)
                    continue

                if choice == "J":
                    result = _run_add_connector_interactive(
                        current_adapter,
                        adapter_registry=registry,
                        deployer_registry=deployer_registry,
                        topology=topology,
                        validation_engine_cls=validation_engine_cls,
                        metrics_collector_cls=metrics_collector_cls,
                        experiment_storage=experiment_storage,
                    )
                    if result is not None:
                        current_adapter = result.get("adapter") or current_adapter
                        _print_action_result(result)
                    continue

                if choice == "I":
                    _run_legacy_menu_action("inesdata_ui", current_adapter=current_adapter, topology=topology)
                    continue

                if choice == "N":
                    current_adapter = "edc"
                    _run_legacy_menu_action("edc_ui", current_adapter=current_adapter, topology=topology)
                    continue

                if choice == "O":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    _run_legacy_menu_action("ontology_hub_ui", current_adapter=current_adapter, topology=topology)
                    continue

                if choice == "A":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    _run_legacy_menu_action("ai_model_hub_ui", current_adapter=current_adapter, topology=topology)
                    continue

                if choice == "V":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    _run_legacy_menu_action("semantic_virtualization_ui", current_adapter=current_adapter, topology=topology)
                    continue

                if choice in {"Y", "Z"}:
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    _run_legacy_menu_action(
                        "validation_test_by_id",
                        current_adapter=current_adapter,
                        topology=topology,
                    )
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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON for commands that have a human-readable default output.",
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
        framework_report = _generate_framework_dashboard(ExperimentLoader.experiment_dir(experiment_id))
        return {
            "experiment_dir": ExperimentLoader.experiment_dir(experiment_id),
            "summary": summary,
            "framework_report": framework_report,
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
    if command == "public-access":
        if len(args.extra) > 1 or (args.extra and args.extra[0] != "reconcile"):
            parser.error("public-access only supports the optional 'reconcile' action")
    elif command == "level":
        if len(args.extra) != 1 or not _is_supported_level_token(args.extra[0]):
            parser.error("level expects exactly one supported level number")
    elif command == "ssh-access":
        if len(args.extra) > 1 or (
            args.extra
            and args.extra[0] not in {"plan", "reconcile", "assistant", "wizard", "self-test", "key-self-test"}
        ):
            parser.error("ssh-access only supports the optional 'plan', 'reconcile', 'assistant' or 'self-test' action")
    elif args.extra:
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

    if command == "level":
        level_id = int(args.extra[0])
        result = run_levels(
            args.adapter,
            levels=[level_id],
            adapter_registry=registry,
            deployer_registry=deployer_registry,
            topology=args.topology,
            validation_engine_cls=validation_engine_cls,
            metrics_collector_cls=metrics_collector_cls,
            experiment_storage=experiment_storage,
            baseline=args.baseline,
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_action_result(result)
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

    if command == "public-access":
        try:
            result = run_public_access(
                adapter,
                deployer_name=args.adapter,
                topology=args.topology,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2, default=str))
        return result

    if command == "ssh-access":
        ssh_action = args.extra[0] if args.extra else "plan"
        if ssh_action == "wizard":
            ssh_action = "assistant"
        if ssh_action == "key-self-test":
            ssh_action = "self-test"
        if ssh_action == "assistant":
            result = _run_vm_distributed_ssh_access_assistant(
                adapter,
                deployer_name=args.adapter,
                topology=args.topology,
            )
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            elif result.get("status") == "needs-review" and isinstance(result.get("plan"), dict):
                _print_vm_distributed_ssh_access_result(result["plan"])
            return result
        try:
            result = run_ssh_access(
                adapter,
                deployer_name=args.adapter,
                topology=args.topology,
                action=ssh_action,
            )
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        elif ssh_action == "self-test":
            _print_vm_distributed_ssh_key_self_test_result(result)
        else:
            _print_vm_distributed_ssh_access_result(result)
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
