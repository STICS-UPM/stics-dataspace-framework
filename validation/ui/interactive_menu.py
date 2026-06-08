import json
import os
import re
import subprocess
import sys
import getpass
import contextlib
import importlib
from datetime import datetime
from pathlib import Path

import yaml

from adapters.inesdata.adapter import InesdataAdapter
from adapters.inesdata.config import InesdataConfig
from deployers.inesdata.access_urls import connector_public_base_url, resolved_public_urls_for_config
from deployers.shared.lib.components import configured_component_public_url
from deployers.shared.lib.cluster_runtime import build_cluster_runtime
from deployers.shared.lib.topology import VM_SINGLE_TOPOLOGY, normalize_topology
from framework.experiment_storage import ExperimentStorage
from validation.components.ontology_hub.functional.runtime_preparation import (
    prepare_ontology_hub_for_functional,
)
from validation.components.console_output import print_component_case_results, print_component_suite_header
from validation.orchestration import ui as orchestration_ui


LEVEL6_UI_SMOKE_SPECS = orchestration_ui.LEVEL6_UI_SMOKE_SPECS
LEVEL6_UI_DATASPACE_SPECS = orchestration_ui.LEVEL6_UI_DATASPACE_SPECS
LEVEL6_UI_OPS_SPEC = orchestration_ui.LEVEL6_UI_OPS_SPEC
LEVEL6_UI_OPS_CONFIG = orchestration_ui.LEVEL6_UI_OPS_CONFIG
EDC_UI_CORE_SPECS = (
    os.path.join("adapters", "edc", "specs", "01-login-readiness.spec.ts"),
    os.path.join("adapters", "edc", "specs", "02-navigation-smoke.spec.ts"),
    os.path.join("adapters", "edc", "specs", "03-provider-setup.spec.ts"),
    os.path.join("adapters", "edc", "specs", "03b-provider-policy-create.spec.ts"),
    os.path.join("adapters", "edc", "specs", "03c-provider-contract-definition-create.spec.ts"),
    os.path.join("adapters", "edc", "specs", "04-consumer-catalog.spec.ts"),
    os.path.join("adapters", "edc", "specs", "03-consumer-negotiation.spec.ts"),
    os.path.join("adapters", "edc", "specs", "04-consumer-transfer.spec.ts"),
    os.path.join("adapters", "edc", "specs", "05-consumer-transfer-storage.spec.ts"),
    os.path.join("adapters", "edc", "specs", "05-e2e-transfer-flow.spec.ts"),
    os.path.join("adapters", "edc", "specs", "06b-minio-bucket-visibility.spec.ts"),
)
EDC_UI_ONTOLOGY_HUB_SPECS = (
    os.path.join("adapters", "edc", "specs", "08-ontology-hub-edc-readonly.spec.ts"),
)
EDC_UI_AI_MODEL_HUB_SPECS = (
    os.path.join("adapters", "edc", "specs", "09-ai-model-hub-httpdata.spec.ts"),
    os.path.join("adapters", "edc", "specs", "11-ai-model-browser.spec.ts"),
    os.path.join("adapters", "edc", "specs", "12-ai-model-execution.spec.ts"),
    os.path.join("adapters", "edc", "specs", "13-ai-model-benchmarking.spec.ts"),
    os.path.join("adapters", "edc", "specs", "14-ai-model-daimo-vocabulary.spec.ts"),
    os.path.join("adapters", "edc", "specs", "15-ai-model-external-execution.spec.ts"),
)
EDC_UI_SEMANTIC_VIRTUALIZATION_SPECS = (
    os.path.join("adapters", "edc", "specs", "07-semantic-virtualization-httpdata.spec.ts"),
)
EDC_UI_AI_MODEL_OBSERVER_SPECS = (
    os.path.join("adapters", "edc", "specs", "10-ai-model-observer.spec.ts"),
    os.path.join("adapters", "edc", "specs", "16-ai-model-observer-participant-summary.spec.ts"),
)

SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TEST_IDS = frozenset(
    {
        "PT5-VS-07",
        "PT5-VS-08",
        "SV-UI-04",
        "SV-UI-05",
        "SV-UI-06",
        "SV-UI-07",
        "SV-UI-08",
        "SV-UI-10",
    }
)


def project_root():
    return Path(__file__).resolve().parents[2]


def _default_inesdata_adapter():
    topology = _normalize_topology(
        os.environ.get("UI_TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or os.environ.get("INESDATA_TOPOLOGY")
        or "local"
    )
    return InesdataAdapter(topology=topology)


def _ui_runtime_env_from_adapter(adapter):
    env = dict(os.environ)
    config_loader = getattr(adapter, "load_deployer_config", None)
    config = config_loader() if callable(config_loader) else {}
    if not isinstance(config, dict):
        config = {}

    keycloak_url = str(
        config.get("KEYCLOAK_FRONTEND_URL")
        or config.get("KEYCLOAK_PUBLIC_URL")
        or config.get("KC_INTERNAL_URL")
        or config.get("KC_URL")
        or ""
    ).strip()
    if keycloak_url:
        env.setdefault("UI_KEYCLOAK_URL", keycloak_url)

    local_store_label = str(config.get("INESDATA_LOCAL_STORE_LABEL") or "").strip()
    if local_store_label:
        env.setdefault("UI_INESDATA_LOCAL_STORE_LABEL", local_store_label)

    return env


def _cleanup_playwright_processes():
    subprocess.run(
        "pkill -f '(chrome|chromium).*playwright' || true",
        shell=True,
        check=False,
    )


def _headed_browser_display_available(env=None):
    if not sys.platform.startswith("linux"):
        return True
    runtime_env = env or os.environ
    return bool(runtime_env.get("DISPLAY") or runtime_env.get("WAYLAND_DISPLAY"))


def _parse_key_value_file(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return values
    return values


def _display_candidate_vm_host(env=None):
    runtime_env = env or os.environ
    ssh_connection = str(runtime_env.get("SSH_CONNECTION") or "").strip()
    ssh_parts = ssh_connection.split()
    if len(ssh_parts) >= 3 and ssh_parts[2]:
        return ssh_parts[2]

    candidate_files = [
        project_root() / "deployers" / "infrastructure" / "topologies" / "vm-single.config",
        project_root() / "deployers" / "infrastructure" / "deployer.config",
    ]
    for config_file in candidate_files:
        values = _parse_key_value_file(config_file)
        for key in ("VM_EXTERNAL_IP", "VM_SINGLE_IP", "VM_SINGLE_ADDRESS", "INGRESS_EXTERNAL_IP", "HOSTS_ADDRESS"):
            value = str(values.get(key) or "").strip()
            if value and value.upper() not in {"X", "AUTO", "REPLACE_ME"}:
                return value
    return "<VM_IP>"


def _display_candidate_ssh_user(env=None):
    runtime_env = env or os.environ
    return str(runtime_env.get("USER") or runtime_env.get("LOGNAME") or getpass.getuser() or "user").strip() or "user"


def _print_headed_browser_display_guidance(label):
    ssh_user = _display_candidate_ssh_user()
    vm_host = _display_candidate_vm_host()
    ssh_target = f"{ssh_user}@{vm_host}"
    print(
        "\nCannot run UI mode "
        f"'{label}' from this shell because no graphical display is available."
    )
    print("Playwright headed mode needs an X11/Wayland display inside the machine where it runs.")
    print("\nRecommended workflow:")
    print("1. From Windows, use WSL to open the SSH session. WSLg usually provides the X server.")
    print("   If WSLg is not available, start a Windows X server first, such as VcXsrv or X410.")
    print("   On macOS, install and start XQuartz before opening the SSH session.")
    print("   On a Linux desktop, an X11/Wayland display is usually already available.")
    print("2. From that local terminal, connect to the inferred current VM with X11 forwarding:")
    print(f"   ssh -Y {ssh_target}")
    print("   If your access requires a jump host, keep your normal -J/ProxyJump route and add -Y:")
    print(f"   ssh -Y -J <jump-user>@<jump-host>:<jump-port> {ssh_target}")
    print("3. Inside the VM shell opened by that command, verify that the display was forwarded:")
    print("   echo $DISPLAY")
    print("4. If DISPLAY is not empty, enter the framework, activate Python, and start the menu:")
    print("   cd ~/Validation-Environment")
    print("   source .venv/bin/activate")
    print("   python3 main.py")
    print("5. Select Live or Debug again from the UI validation menu.")
    print("\nIf DISPLAY is still empty in the VM, the SSH forwarding did not reach the final machine.")
    print("Check the local X server, the jump host, and X11Forwarding/xauth on each SSH hop.")
    print("Use Normal mode for reproducible validation when visual browser playback is not required.")
    print("For non-visible headed compatibility only, run the whole command under xvfb-run.\n")


def _resolve_ui_mode():
    while True:
        print("\nSelect UI mode:")
        print("1 - Normal (headless)")
        print("2 - Live (headed)")
        print("3 - Debug (PWDEBUG=1, headed)")
        print("B - Back")
        try:
            choice = input("\nMode: ").strip().upper()
        except EOFError:
            print("\nNo input. Returning to previous menu.\n")
            return None
        if choice == "B":
            return None
        if choice not in {"1", "2", "3"}:
            print("\nInvalid selection. Please try again.\n")
            continue
        if choice == "1":
            return {"label": "normal", "args": [], "env": {}}
        if choice == "2":
            if not _headed_browser_display_available():
                _print_headed_browser_display_guidance("live")
                continue
            return {
                "label": "live",
                "args": ["--headed"],
                "env": {
                    "PLAYWRIGHT_HEADED_GPU_FIX": "1",
                    "PLAYWRIGHT_INTERACTION_MARKERS": "1",
                    "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": "350",
                },
            }
        if not _headed_browser_display_available():
            _print_headed_browser_display_guidance("debug")
            continue
        return {
            "label": "debug",
            "args": ["--headed", "--debug"],
            "env": {
                "PWDEBUG": "1",
                "PLAYWRIGHT_HEADED_GPU_FIX": "1",
                "PLAYWRIGHT_INTERACTION_MARKERS": "1",
                "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": "350",
            },
        }


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _playwright_grep_for_id(test_id):
    normalized = str(test_id or "").strip()
    if not normalized:
        return ""
    return rf"{re.escape(normalized)}\b"


def _append_playwright_grep(command, test_grep=None):
    grep = str(test_grep or "").strip()
    if grep:
        command.extend(["--grep", grep])


def _summarize_playwright_json_report(json_report_file):
    summary = {
        "expected": 0,
        "unexpected": 0,
        "flaky": 0,
        "skipped": 0,
        "total": None,
        "errors": [],
    }
    try:
        with open(json_report_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle) or {}
    except (OSError, json.JSONDecodeError):
        return summary

    stats = payload.get("stats") or {}
    for key in ("expected", "unexpected", "flaky", "skipped"):
        try:
            summary[key] = int(stats.get(key) or 0)
        except (TypeError, ValueError):
            summary[key] = 0
    summary["total"] = sum(summary[key] for key in ("expected", "unexpected", "flaky", "skipped"))

    errors = []
    for error in payload.get("errors") or []:
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("stack") or "").strip()
        else:
            message = str(error or "").strip()
        if message:
            errors.append(message.splitlines()[0])
    summary["errors"] = errors
    return summary


def _finalize_playwright_run(label, completed_process, json_report_file, html_report_dir, test_grep=None):
    summary = _summarize_playwright_json_report(json_report_file)
    returncode = getattr(completed_process, "returncode", None)
    total = summary.get("total")
    report_index = os.path.join(html_report_dir, "index.html")

    if total is None:
        print(f"\nPlaywright result could not be read for {label}.")
        if returncode is not None:
            print(f"Playwright exit code: {returncode}")
    elif total == 0:
        print(f"\nPlaywright did not find tests for {label}.")
        if test_grep:
            print(f"Applied filter: {test_grep}")
        for error in summary.get("errors") or []:
            print(f"Playwright error: {error}")
    elif returncode == 0:
        print(
            "\nPlaywright result: "
            f"{summary['expected']}/{total} passed, "
            f"{summary['unexpected']} failed, {summary['skipped']} skipped"
        )
    else:
        print(
            "\nPlaywright result: "
            f"{summary['expected']}/{total} passed, "
            f"{summary['unexpected']} failed, {summary['skipped']} skipped "
            f"(exit code {returncode})"
        )

    if os.path.isfile(report_index):
        print(f"Playwright HTML report: {report_index}")
        print(f"Open with: npx playwright show-report {html_report_dir}\n")
    else:
        print(f"Playwright HTML report was not generated at {report_index}\n")

    return {
        "returncode": returncode,
        "summary": summary,
        "html_report": report_index if os.path.isfile(report_index) else None,
    }


def _run_ontology_hub_ui_functional(mode, test_grep=None, adapter_name=None, topology=None):
    from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime

    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    base_dir = str(project_root() / "experiments" / experiment_id / "components" / "ontology-hub" / "functional")
    output_dir = os.path.join(base_dir, "test-results")
    html_report_dir = os.path.join(base_dir, "playwright-report")
    blob_report_dir = os.path.join(base_dir, "blob-report")
    json_report_file = os.path.join(base_dir, "results.json")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(html_report_dir, exist_ok=True)
    os.makedirs(blob_report_dir, exist_ok=True)

    runtime_env = _ontology_hub_functional_runtime_env(adapter_name=adapter_name, topology=topology)
    runtime = resolve_ontology_hub_runtime(environ={**os.environ, **runtime_env})
    if not prepare_ontology_hub_for_functional(runtime):
        print("\nOntology Hub Functional preparation failed. Execution aborted.\n")
        return None

    runtime_path = os.path.join(base_dir, "resolved_runtime.json")
    _write_json(runtime_path, runtime)

    env = {
        **os.environ,
        **runtime_env,
        "ONTOLOGY_HUB_BASE_URL": runtime.get("baseUrl", ""),
        "ONTOLOGY_HUB_RUNTIME_FILE": runtime_path,
        "ONTOLOGY_HUB_UI_WORKERS": "1",
        "PLAYWRIGHT_OUTPUT_DIR": output_dir,
        "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
        "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
        "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
    }
    env.update(mode.get("env") or {})
    cmd = [
        "./node_modules/.bin/playwright",
        "test",
        "--config",
        "../components/ontology_hub/functional/playwright.config.js",
        "--workers=1",
    ]
    _append_playwright_grep(cmd, test_grep)
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning Ontology Hub Functional (artifacts in {base_dir})\n")
    completed = None
    try:
        completed = subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return _finalize_playwright_run(
        "Ontology Hub Functional",
        completed,
        json_report_file,
        html_report_dir,
        test_grep=test_grep,
    )


def run_ontology_hub_ui_tests_interactive():
    """Run Ontology Hub Playwright UI tests in normal/live/debug modes."""
    print("\n" + "=" * 50)
    print("ONTOLOGY HUB UI TESTS")
    print("=" * 50)
    mode = _resolve_ui_mode()
    if mode is None:
        return None

    _run_ontology_hub_ui_functional(mode)
    return None


def _run_ontology_hub_ui_integration_with_inesdata(mode, test_grep=None):
    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    base_dir = str(project_root() / "experiments" / experiment_id / "components" / "ontology-hub" / "inesdata-ui")
    output_dir = os.path.join(base_dir, "test-results")
    html_report_dir = os.path.join(base_dir, "playwright-report")
    blob_report_dir = os.path.join(base_dir, "blob-report")
    json_report_file = os.path.join(base_dir, "results.json")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(html_report_dir, exist_ok=True)
    os.makedirs(blob_report_dir, exist_ok=True)

    env = _ui_runtime_env_from_adapter(_default_inesdata_adapter())
    env.update(
        {
            "UI_ONTOLOGY_HUB_INESDATA_DEMO": "1",
            "PLAYWRIGHT_OUTPUT_DIR": output_dir,
            "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
            "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
            "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
            "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
            "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
        }
    )
    env.update(mode.get("env") or {})
    cmd = [
        "./node_modules/.bin/playwright",
        "test",
        "--config",
        "playwright.inesdata.config.ts",
        "adapters/inesdata/specs/08-ontology-hub-inesdata-readonly.spec.ts",
        "--workers=1",
    ]
    _append_playwright_grep(cmd, test_grep)
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning Ontology Hub Integration with INESData ({mode['label']}, artifacts in {base_dir})\n")
    completed = None
    try:
        completed = subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return _finalize_playwright_run(
        "Ontology Hub Integration with INESData",
        completed,
        json_report_file,
        html_report_dir,
        test_grep=test_grep,
    )


def _resolve_ai_model_hub_base_url(adapter=None):
    adapter = adapter or _default_inesdata_adapter()
    adapter_config = adapter.load_deployer_config() or {}
    if not isinstance(adapter_config, dict):
        adapter_config = {}
    topology = _normalize_topology(
        os.environ.get("UI_TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or os.environ.get("INESDATA_TOPOLOGY")
        or adapter_config.get("TOPOLOGY")
        or adapter_config.get("PIONERA_TOPOLOGY")
        or adapter_config.get("INESDATA_TOPOLOGY")
    )
    deployer_config = {
        **_infrastructure_runtime_config(topology),
        **adapter_config,
        "TOPOLOGY": topology,
        "PIONERA_TOPOLOGY": topology,
        "INESDATA_TOPOLOGY": topology,
    }
    deployer_config.update(resolved_public_urls_for_config(deployer_config))
    ds_name = (
        os.environ.get("UI_DATASPACE")
        or deployer_config.get("DS_1_NAME")
        or InesdataConfig.dataspace_name()
        or "demo"
    ).strip()

    public_url = configured_component_public_url(
        "ai-model-hub",
        deployer_config,
        dataspace_name=ds_name,
    )
    if public_url:
        return public_url.rstrip("/")

    ds_domain = (
        deployer_config.get("DS_DOMAIN_BASE")
        or "dev.ds.dataspaceunit.upm"
    ).strip()

    chart_dir = project_root() / "deployers" / "shared" / "components" / "ai-model-hub"
    values_path = chart_dir / f"values-{ds_name}.yaml"
    if not values_path.is_file():
        values_path = chart_dir / "values.yaml"

    host = ""
    if values_path.is_file():
        with open(values_path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        ingress = payload.get("ingress") or {}
        if ingress.get("enabled") and ingress.get("host"):
            host = str(ingress.get("host") or "").strip()

    if not host and ds_name and ds_domain:
        host = f"ai-model-hub-{ds_name}.{ds_domain}"

    if not host:
        return ""
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    return f"http://{host}".rstrip("/")


def _normalize_topology(value):
    topology = str(value or "local").strip().lower().replace("_", "-")
    return topology if topology in {"local", "vm-single", "vm-distributed"} else "local"


def _connector_full_name(connector, dataspace):
    value = str(connector or "").strip()
    if not value:
        return ""
    if value.startswith("conn-"):
        return value
    return f"conn-{value}-{dataspace}"


def _first_config_value(config, public_urls, *keys):
    for key in keys:
        value = str((config or {}).get(key) or "").strip()
        if value:
            return value.rstrip("/")
        value = str((public_urls or {}).get(key) or "").strip()
        if value:
            return value.rstrip("/")
    return ""


def _keycloak_base_without_realm(url, dataspace):
    normalized = str(url or "").strip().rstrip("/")
    if not normalized:
        return ""
    realm_suffix = f"/realms/{dataspace}"
    if dataspace and normalized.endswith(realm_suffix):
        normalized = normalized[: -len(realm_suffix)]
    if normalized.endswith("/realms/master"):
        normalized = normalized[: -len("/realms/master")]
    return normalized.rstrip("/")


def _infrastructure_runtime_config(topology):
    root = project_root()
    values = {}
    for config_path in (
        root / "deployers" / "infrastructure" / "deployer.config",
        root / "deployers" / "infrastructure" / "topologies" / f"{_normalize_topology(topology)}.config",
    ):
        values.update(_parse_key_value_file(config_path))
    return values


def _ontology_hub_functional_runtime_env(adapter=None, adapter_name=None, topology=None):
    normalized_adapter = str(adapter_name or os.environ.get("PIONERA_ADAPTER") or "inesdata").strip().lower()
    adapter = adapter or _build_validation_adapter(adapter_name=normalized_adapter, topology=topology)
    config_loader = getattr(adapter, "load_deployer_config", None)
    adapter_config = config_loader() if callable(config_loader) else {}
    if not isinstance(adapter_config, dict):
        adapter_config = {}

    normalized_topology = _normalize_topology(
        topology
        or os.environ.get("UI_TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or os.environ.get("INESDATA_TOPOLOGY")
        or adapter_config.get("TOPOLOGY")
        or adapter_config.get("PIONERA_TOPOLOGY")
        or adapter_config.get("INESDATA_TOPOLOGY")
    )
    deployer_config = {
        **_infrastructure_runtime_config(normalized_topology),
        **adapter_config,
        "TOPOLOGY": normalized_topology,
        "PIONERA_TOPOLOGY": normalized_topology,
        "INESDATA_TOPOLOGY": normalized_topology,
    }
    deployer_config.update(resolved_public_urls_for_config(deployer_config))

    dataspace = str(
        os.environ.get("UI_DATASPACE")
        or deployer_config.get("DS_1_NAME")
        or InesdataConfig.dataspace_name()
        or "demo"
    ).strip()
    ds_domain = str(
        os.environ.get("UI_DS_DOMAIN")
        or deployer_config.get("DS_DOMAIN_BASE")
        or "dev.ds.dataspaceunit.upm"
    ).strip()
    explicit_base_url = str(
        os.environ.get("ONTOLOGY_HUB_BASE_URL")
        or os.environ.get("ONTOLOGY_HUB_PUBLIC_URL")
        or deployer_config.get("ONTOLOGY_HUB_PUBLIC_URL")
        or deployer_config.get("ONTOLOGY_HUB_URL")
        or ""
    ).strip()
    base_url = explicit_base_url or configured_component_public_url(
        "ontology-hub",
        deployer_config,
        dataspace_name=dataspace,
    )
    if not base_url and dataspace and ds_domain:
        base_url = f"http://ontology-hub-{dataspace}.{ds_domain}"

    env = {
        "PIONERA_ADAPTER": normalized_adapter,
        "UI_ADAPTER": normalized_adapter,
        "PIONERA_TOPOLOGY": normalized_topology,
        "INESDATA_TOPOLOGY": normalized_topology,
        "UI_TOPOLOGY": normalized_topology,
        "UI_DATASPACE": dataspace,
        "UI_DS_DOMAIN": ds_domain,
        "ONTOLOGY_HUB_BASE_URL": base_url.rstrip("/") if base_url else "",
        "ONTOLOGY_HUB_COMPONENTS_NAMESPACE": str(
            deployer_config.get("COMPONENTS_NAMESPACE") or "components"
        ).strip(),
    }
    for key in (
        "ONTOLOGY_HUB_RELEASE_NAME",
        "ONTOLOGY_HUB_COMPONENT_DATASPACE_NAME",
        "ONTOLOGY_HUB_SELF_HOST_SERVICE_NAME",
        "ONTOLOGY_HUB_SELF_HOST_NAMESPACE",
        "ONTOLOGY_HUB_SELF_HOST_SERVICE_PORT",
        "ONTOLOGY_HUB_SELF_HOST_PORT",
        "ONTOLOGY_HUB_SERVICE_NAME",
        "ONTOLOGY_HUB_SERVICE_NAMESPACE",
        "ONTOLOGY_HUB_SERVICE_PORT",
    ):
        value = str(deployer_config.get(key) or "").strip()
        if value:
            env[key] = value
    return {key: value for key, value in env.items() if str(value or "").strip()}


def _ai_model_hub_functional_runtime_env(adapter=None, adapter_name=None):
    normalized_adapter = str(adapter_name or os.environ.get("PIONERA_ADAPTER") or "inesdata").strip().lower()
    adapter = adapter or _build_validation_adapter(adapter_name=normalized_adapter)
    normalized_adapter = _adapter_name_from_instance(adapter, fallback=normalized_adapter)
    config_loader = getattr(adapter, "load_deployer_config", None)
    adapter_config = config_loader() if callable(config_loader) else {}
    if not isinstance(adapter_config, dict):
        adapter_config = {}

    topology = _normalize_topology(
        os.environ.get("UI_TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or os.environ.get("INESDATA_TOPOLOGY")
        or adapter_config.get("TOPOLOGY")
        or adapter_config.get("PIONERA_TOPOLOGY")
        or adapter_config.get("INESDATA_TOPOLOGY")
    )
    config = {
        **_infrastructure_runtime_config(topology),
        **adapter_config,
        "TOPOLOGY": topology,
        "PIONERA_TOPOLOGY": topology,
        "INESDATA_TOPOLOGY": topology,
    }
    dataspace = str(
        os.environ.get("UI_DATASPACE")
        or config.get("DS_1_NAME")
        or InesdataConfig.dataspace_name()
        or "demo"
    ).strip()
    ds_domain = str(
        os.environ.get("UI_DS_DOMAIN")
        or config.get("DS_DOMAIN_BASE")
        or "dev.ds.dataspaceunit.upm"
    ).strip()
    public_config = {**config, "TOPOLOGY": topology}
    public_urls = resolved_public_urls_for_config(public_config)
    keycloak_url = _keycloak_base_without_realm(
        _first_config_value(
            public_config,
            public_urls,
            "KEYCLOAK_FRONTEND_URL",
            "KEYCLOAK_PUBLIC_URL",
            "KC_INTERNAL_URL",
            "KC_URL",
        ),
        dataspace,
    )

    connectors = [
        _connector_full_name(value, dataspace)
        for value in str(config.get("DS_1_CONNECTORS") or "").split(",")
        if str(value or "").strip()
    ]
    provider = connectors[0] if connectors else ""
    consumer = connectors[1] if len(connectors) > 1 else ""

    def connector_base(connector):
        if not connector:
            return ""
        public_base = connector_public_base_url(connector, dataspace, public_config)
        if public_base:
            return public_base.rstrip("/")
        if ds_domain:
            return f"http://{connector}.{ds_domain}"
        return ""

    def connector_api_base(connector):
        if not connector:
            return ""
        if normalized_adapter == "edc":
            public_api_builder = getattr(getattr(adapter, "connectors", None), "_edc_connector_public_api_base_url", None)
            if callable(public_api_builder):
                public_api_base = str(public_api_builder(connector) or "").strip().rstrip("/")
                if public_api_base:
                    return public_api_base
        return connector_base(connector)

    env = {
        "PIONERA_ADAPTER": normalized_adapter,
        "UI_ADAPTER": normalized_adapter,
        "AI_MODEL_HUB_COMPONENT_ADAPTER": normalized_adapter,
        "PIONERA_TOPOLOGY": topology,
        "INESDATA_TOPOLOGY": topology,
        "UI_TOPOLOGY": topology,
        "UI_DATASPACE": dataspace,
        "UI_DS_DOMAIN": ds_domain,
    }
    if keycloak_url:
        env["AI_MODEL_HUB_KEYCLOAK_URL"] = keycloak_url
    if provider:
        base = connector_api_base(provider)
        env.update(
            {
                "AI_MODEL_HUB_PROVIDER_CONNECTOR_ID": provider,
                "AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL": f"{base}/management" if base else "",
                "AI_MODEL_HUB_PROVIDER_PROTOCOL_URL": f"{base}/protocol" if base else "",
                "AI_MODEL_HUB_PROVIDER_DEFAULT_URL": f"{base}/api" if base else "",
            }
        )
    if consumer:
        base = connector_api_base(consumer)
        env.update(
            {
                "AI_MODEL_HUB_CONSUMER_CONNECTOR_ID": consumer,
                "AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL": f"{base}/management" if base else "",
                "AI_MODEL_HUB_CONSUMER_PROTOCOL_URL": f"{base}/protocol" if base else "",
                "AI_MODEL_HUB_CONSUMER_DEFAULT_URL": f"{base}/api" if base else "",
            }
        )
    return {key: value for key, value in env.items() if str(value or "").strip()}


def _resolve_semantic_virtualization_base_url(adapter=None, topology=None):
    normalized_topology = _normalize_topology(
        topology
        or os.environ.get("UI_TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or os.environ.get("INESDATA_TOPOLOGY")
        or "local"
    )
    adapter = adapter or _build_validation_adapter(topology=normalized_topology)
    adapter_config = adapter.load_deployer_config() or {}
    if not isinstance(adapter_config, dict):
        adapter_config = {}
    deployer_config = {
        **_infrastructure_runtime_config(normalized_topology),
        **adapter_config,
        "TOPOLOGY": normalized_topology,
        "PIONERA_TOPOLOGY": normalized_topology,
        "INESDATA_TOPOLOGY": normalized_topology,
    }
    deployer_config.update(resolved_public_urls_for_config(deployer_config))
    ds_name = (
        os.environ.get("UI_DATASPACE")
        or deployer_config.get("DS_1_NAME")
        or InesdataConfig.dataspace_name()
        or "demo"
    ).strip()
    ds_domain = (
        os.environ.get("UI_DS_DOMAIN")
        or deployer_config.get("DS_DOMAIN_BASE")
        or "dev.ds.dataspaceunit.upm"
    ).strip()

    explicit_url = (
        os.environ.get("SEMANTIC_VIRTUALIZATION_BASE_URL")
        or os.environ.get("SEMANTIC_VIRTUALIZATION_PUBLIC_URL")
        or ""
    ).strip()
    if explicit_url:
        return explicit_url.rstrip("/")

    public_url = configured_component_public_url(
        "semantic-virtualization",
        deployer_config,
        dataspace_name=ds_name,
    )
    if public_url:
        return public_url.rstrip("/")

    chart_dir = project_root() / "deployers" / "shared" / "components" / "semantic-virtualization"
    values_path = chart_dir / f"values-{ds_name}.yaml"
    if not values_path.is_file():
        values_path = chart_dir / "values.yaml"

    host = ""
    if values_path.is_file():
        with open(values_path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        ingress = payload.get("ingress") or {}
        if ingress.get("enabled") and ingress.get("host"):
            host = str(ingress.get("host") or "").strip()

    if not host and ds_name and ds_domain:
        host = f"semantic-virtualization-{ds_name}.{ds_domain}"

    if not host:
        return ""
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    return f"http://{host}".rstrip("/")


def _main_validation_runtime_module():
    current_main = sys.modules.get("__main__")
    required = (
        "_load_effective_infrastructure_deployer_config",
        "_vm_single_component_validation_tunnel_environment",
    )
    if current_main is not None and all(hasattr(current_main, name) for name in required):
        return current_main
    return importlib.import_module("main")


def _semantic_virtualization_test_grep_needs_mapping_editor(test_grep=None):
    raw_grep = str(test_grep or "").strip()
    if not raw_grep:
        return True
    normalized = re.sub(r"\\(.)", r"\1", raw_grep.upper())
    return any(test_id in normalized for test_id in SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TEST_IDS)


def _semantic_virtualization_vm_single_menu_environment(topology=None, test_grep=None, needs_mapping_editor=None):
    normalized_topology = normalize_topology(topology or os.environ.get("PIONERA_TOPOLOGY") or "local")
    if normalized_topology != VM_SINGLE_TOPOLOGY:
        return {}
    if needs_mapping_editor is None:
        needs_mapping_editor = _semantic_virtualization_test_grep_needs_mapping_editor(test_grep)
    if not needs_mapping_editor:
        return {}

    try:
        main_runtime = _main_validation_runtime_module()
        load_config = getattr(main_runtime, "_load_effective_infrastructure_deployer_config", None)
        prepare_tunnel_env = getattr(main_runtime, "_vm_single_component_validation_tunnel_environment", None)
        if not callable(load_config) or not callable(prepare_tunnel_env):
            return {}
        config = load_config(topology=VM_SINGLE_TOPOLOGY)
        return prepare_tunnel_env(config) or {}
    except Exception as exc:
        print(
            "Warning: vm-single mapping editor tunnel could not be prepared for the validation menu. "
            f"Semantic Virtualization editor UI tests may fail. {exc}"
        )
        return {}


def _run_semantic_virtualization_ui_tests(
    mode,
    test_grep=None,
    adapter_name=None,
    topology=None,
    needs_mapping_editor=None,
):
    normalized_adapter = str(adapter_name or os.environ.get("PIONERA_ADAPTER") or "inesdata").strip().lower()
    normalized_topology = normalize_topology(topology or os.environ.get("PIONERA_TOPOLOGY") or "local")
    mapping_editor_needed = (
        _semantic_virtualization_test_grep_needs_mapping_editor(test_grep)
        if needs_mapping_editor is None
        else bool(needs_mapping_editor)
    )
    base_url = _resolve_semantic_virtualization_base_url(
        adapter=_build_validation_adapter(adapter_name=normalized_adapter, topology=normalized_topology),
        topology=normalized_topology,
    )
    if not base_url:
        print("Semantic Virtualization base URL could not be resolved; aborting.")
        return None

    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    base_dir = str(project_root() / "experiments" / experiment_id / "components" / "semantic-virtualization" / "ui")
    output_dir = os.path.join(base_dir, "test-results")
    html_report_dir = os.path.join(base_dir, "playwright-report")
    blob_report_dir = os.path.join(base_dir, "blob-report")
    json_report_file = os.path.join(base_dir, "results.json")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(html_report_dir, exist_ok=True)
    os.makedirs(blob_report_dir, exist_ok=True)

    env = {
        **os.environ,
        "PIONERA_ADAPTER": normalized_adapter,
        "UI_ADAPTER": normalized_adapter,
        "PIONERA_TOPOLOGY": normalized_topology,
        "INESDATA_TOPOLOGY": normalized_topology,
        "UI_TOPOLOGY": normalized_topology,
        "SEMANTIC_VIRTUALIZATION_BASE_URL": base_url,
        "PLAYWRIGHT_OUTPUT_DIR": output_dir,
        "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
        "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
        "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
        "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
        "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
    }
    if normalized_topology == VM_SINGLE_TOPOLOGY and mapping_editor_needed:
        env["SEMANTIC_VIRTUALIZATION_ENABLE_UI_VALIDATION"] = "1"
        env["SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI"] = "1"
    env.update(
        _semantic_virtualization_vm_single_menu_environment(
            topology=normalized_topology,
            test_grep=test_grep,
            needs_mapping_editor=mapping_editor_needed,
        )
    )
    env.update(mode.get("env") or {})
    cmd = [
        "./node_modules/.bin/playwright",
        "test",
        "--config",
        "../components/semantic_virtualization/ui/playwright.config.js",
        "--workers=1",
    ]
    _append_playwright_grep(cmd, test_grep)
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning Semantic Virtualization UI tests (artifacts in {base_dir})\n")
    completed = None
    try:
        completed = subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return _finalize_playwright_run(
        "Semantic Virtualization UI tests",
        completed,
        json_report_file,
        html_report_dir,
        test_grep=test_grep,
    )


def run_semantic_virtualization_ui_tests_interactive():
    """Run Semantic Virtualization Playwright UI tests in normal/live/debug modes."""
    while True:
        print("\n" + "=" * 50)
        print("SEMANTIC VIRTUALIZATION UI TESTS")
        print("=" * 50)
        mode = _resolve_ui_mode()
        if mode is None:
            return None
        _run_semantic_virtualization_ui_tests(mode)
        return None


def _run_semantic_virtualization_ui_integration_with_inesdata(mode, test_grep=None):
    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    base_dir = str(
        project_root() / "experiments" / experiment_id / "components" / "semantic-virtualization" / "inesdata-ui"
    )
    output_dir = os.path.join(base_dir, "test-results")
    html_report_dir = os.path.join(base_dir, "playwright-report")
    blob_report_dir = os.path.join(base_dir, "blob-report")
    json_report_file = os.path.join(base_dir, "results.json")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(html_report_dir, exist_ok=True)
    os.makedirs(blob_report_dir, exist_ok=True)

    env = _ui_runtime_env_from_adapter(_default_inesdata_adapter())
    env.update(
        {
            "UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO": "1",
            "PLAYWRIGHT_OUTPUT_DIR": output_dir,
            "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
            "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
            "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
            "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
            "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
        }
    )
    env.update(mode.get("env") or {})
    cmd = [
        "./node_modules/.bin/playwright",
        "test",
        "--config",
        "playwright.inesdata.config.ts",
        "adapters/inesdata/specs/07-semantic-virtualization-httpdata.spec.ts",
        "--workers=1",
    ]
    _append_playwright_grep(cmd, test_grep)
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning Semantic Virtualization Integration with INESData ({mode['label']}, artifacts in {base_dir})\n")
    completed = None
    try:
        completed = subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return _finalize_playwright_run(
        "Semantic Virtualization Integration with INESData",
        completed,
        json_report_file,
        html_report_dir,
        test_grep=test_grep,
    )


def _run_ai_model_hub_ui_functional(mode, test_grep=None, adapter_name=None, topology=None):
    normalized_adapter = str(adapter_name or os.environ.get("PIONERA_ADAPTER") or "inesdata").strip().lower()
    normalized_topology = normalize_topology(topology or os.environ.get("PIONERA_TOPOLOGY") or "local")
    adapter = _build_validation_adapter(adapter_name=normalized_adapter, topology=normalized_topology)
    base_url = _resolve_ai_model_hub_base_url(adapter)
    if not base_url:
        print("AI Model Hub base URL could not be resolved; aborting.")
        return None

    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    base_dir = str(project_root() / "experiments" / experiment_id / "components" / "ai-model-hub" / "ui")
    output_dir = os.path.join(base_dir, "test-results")
    html_report_dir = os.path.join(base_dir, "playwright-report")
    blob_report_dir = os.path.join(base_dir, "blob-report")
    json_report_file = os.path.join(base_dir, "results.json")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(html_report_dir, exist_ok=True)
    os.makedirs(blob_report_dir, exist_ok=True)

    env = {
        **os.environ,
        **_ai_model_hub_functional_runtime_env(adapter, adapter_name=normalized_adapter),
        "AI_MODEL_HUB_ENABLE_UI_VALIDATION": "1",
        "AI_MODEL_HUB_ENABLE_BENCHMARKING_UI_DEMO": os.environ.get("AI_MODEL_HUB_ENABLE_BENCHMARKING_UI_DEMO", "1"),
        "AI_MODEL_HUB_BASE_URL": base_url,
        "PLAYWRIGHT_OUTPUT_DIR": output_dir,
        "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
        "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
        "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
        "PIONERA_PLAYWRIGHT_SUITE_NAME": "AI Model Hub functional",
        "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
        "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
    }
    env.update(mode.get("env") or {})
    cmd = [
        "./node_modules/.bin/playwright",
        "test",
        "--config",
        "../components/ai_model_hub/ui/playwright.config.js",
    ]
    _append_playwright_grep(cmd, test_grep)
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning AI Model Hub Functional UI tests (artifacts in {base_dir})\n")
    completed = None
    try:
        completed = subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return _finalize_playwright_run(
        "AI Model Hub Functional UI tests",
        completed,
        json_report_file,
        html_report_dir,
        test_grep=test_grep,
    )


def _run_ai_model_hub_ui_integration(mode, test_grep=None):
    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    base_dir = str(project_root() / "experiments" / experiment_id / "components" / "ai-model-hub" / "inesdata-ui")
    output_dir = os.path.join(base_dir, "test-results")
    html_report_dir = os.path.join(base_dir, "playwright-report")
    blob_report_dir = os.path.join(base_dir, "blob-report")
    json_report_file = os.path.join(base_dir, "results.json")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(html_report_dir, exist_ok=True)
    os.makedirs(blob_report_dir, exist_ok=True)

    env = _ui_runtime_env_from_adapter(_default_inesdata_adapter())
    env.update(
        {
            "UI_AI_MODEL_HUB_HTTPDATA_DEMO": "1",
            "PLAYWRIGHT_OUTPUT_DIR": output_dir,
            "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
            "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
            "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
            "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
            "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
        }
    )
    env.update(mode.get("env") or {})
    cmd = [
        "./node_modules/.bin/playwright",
        "test",
        "--config",
        "playwright.inesdata.config.ts",
        "adapters/inesdata/specs/09-ai-model-hub-httpdata.spec.ts",
        "adapters/inesdata/specs/11-ai-model-browser.spec.ts",
        "adapters/inesdata/specs/12-ai-model-execution.spec.ts",
        "adapters/inesdata/specs/13-ai-model-benchmarking.spec.ts",
        "adapters/inesdata/specs/14-ai-model-daimo-vocabulary.spec.ts",
        "adapters/inesdata/specs/15-ai-model-external-execution.spec.ts",
        "--workers=1",
    ]
    _append_playwright_grep(cmd, test_grep)
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning AI Model Hub Integration with INESData ({mode['label']}, artifacts in {base_dir})\n")
    completed = None
    try:
        completed = subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return _finalize_playwright_run(
        "AI Model Hub Integration with INESData",
        completed,
        json_report_file,
        html_report_dir,
        test_grep=test_grep,
    )


def _run_ai_model_observer_ui_integration(mode, test_grep=None):
    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    base_dir = str(project_root() / "experiments" / experiment_id / "components" / "ai-model-hub" / "observer-ui")
    output_dir = os.path.join(base_dir, "test-results")
    html_report_dir = os.path.join(base_dir, "playwright-report")
    blob_report_dir = os.path.join(base_dir, "blob-report")
    json_report_file = os.path.join(base_dir, "results.json")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(html_report_dir, exist_ok=True)
    os.makedirs(blob_report_dir, exist_ok=True)

    env = _ui_runtime_env_from_adapter(_default_inesdata_adapter())
    env.update(
        {
            "UI_AI_MODEL_OBSERVER_DEMO": "1",
            "PLAYWRIGHT_OUTPUT_DIR": output_dir,
            "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
            "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
            "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
            "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
            "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
        }
    )
    env.update(mode.get("env") or {})
    cmd = [
        "./node_modules/.bin/playwright",
        "test",
        "--config",
        "playwright.inesdata.config.ts",
        "adapters/inesdata/specs/10-ai-model-observer.spec.ts",
        "adapters/inesdata/specs/16-ai-model-observer-participant-summary.spec.ts",
        "--workers=1",
    ]
    _append_playwright_grep(cmd, test_grep)
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning AI Model Observer / Clearing House ({mode['label']}, artifacts in {base_dir})\n")
    completed = None
    try:
        completed = subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return _finalize_playwright_run(
        "AI Model Observer / Clearing House",
        completed,
        json_report_file,
        html_report_dir,
        test_grep=test_grep,
    )


def run_ai_model_hub_ui_tests_interactive():
    """Run AI Model Hub Playwright UI tests in normal/live/debug modes."""
    while True:
        print("\n" + "=" * 50)
        print("AI MODEL HUB UI TESTS")
        print("=" * 50)
        mode = _resolve_ui_mode()
        if mode is None:
            return None
        _run_ai_model_hub_ui_functional(mode)
        return None


def _build_level6_ui_artifact_paths(experiment_dir, connector):
    return orchestration_ui.build_ui_artifact_paths(experiment_dir, connector)


def _build_level6_ui_ops_artifact_paths(experiment_dir):
    return orchestration_ui.build_ui_ops_artifact_paths(experiment_dir)


def _build_level6_ui_dataspace_artifact_paths(experiment_dir, provider_connector, consumer_connector):
    return orchestration_ui.build_ui_dataspace_artifact_paths(
        experiment_dir,
        provider_connector,
        consumer_connector,
    )


def _enrich_level6_ui_result(result):
    try:
        from validation.ui.reporting import enrich_level6_ui_result
    except Exception as exc:
        enriched = dict(result or {})
        enriched["reporting_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return enriched

    try:
        return enrich_level6_ui_result(result or {})
    except Exception as exc:
        enriched = dict(result or {})
        enriched["reporting_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return enriched


def _aggregate_level6_ui_results(ui_results, experiment_dir):
    try:
        from validation.ui.reporting import aggregate_level6_ui_results
    except Exception as exc:
        return {
            "scope": "dataspace_ui",
            "status": "not_run" if not ui_results else "skipped",
            "summary": {
                "total": len(list(ui_results or [])),
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "not_run": 0 if ui_results else 1,
            },
            "suite_runs": [],
            "executed_cases": [],
            "dataspace_cases": [],
            "support_checks": [],
            "ops_checks": [],
            "execution_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "dataspace_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "support_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "ops_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "catalog_coverage_summary": {
                "dataspace_cases": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "support_checks": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "ops_checks": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            },
            "evidence_index": [],
            "findings": [],
            "catalog_alignment": {},
            "artifacts": {},
            "reporting_error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }

    try:
        return aggregate_level6_ui_results(ui_results or [], experiment_dir=experiment_dir)
    except Exception as exc:
        return {
            "scope": "dataspace_ui",
            "status": "not_run" if not ui_results else "skipped",
            "summary": {
                "total": len(list(ui_results or [])),
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "not_run": 0 if ui_results else 1,
            },
            "suite_runs": [],
            "executed_cases": [],
            "dataspace_cases": [],
            "support_checks": [],
            "ops_checks": [],
            "execution_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "dataspace_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "support_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "ops_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "catalog_coverage_summary": {
                "dataspace_cases": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "support_checks": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "ops_checks": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            },
            "evidence_index": [],
            "findings": [],
            "catalog_alignment": {},
            "artifacts": {},
            "reporting_error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


def _save_interactive_core_ui_experiment_state(
    experiment_dir,
    connectors,
    *,
    mode,
    ui_results=None,
):
    ui_validation = _aggregate_level6_ui_results(
        ui_results or [],
        experiment_dir=experiment_dir,
    )
    payload = {
        "status": "completed",
        "timestamp": datetime.now().isoformat(),
        "source": "validation.ui.interactive_menu:interactive-core-ui",
        "mode": (mode or {}).get("label"),
        "connectors": list(connectors or []),
        "ui_results": list(ui_results or []),
        "ui_validation": ui_validation,
    }
    ExperimentStorage.save(payload, experiment_dir=experiment_dir)
    return payload


def _level6_ui_ops_suite_available(ui_test_dir):
    return orchestration_ui.ui_ops_suite_available(ui_test_dir)


def _run_level6_ui_smoke(
    ui_test_dir,
    connector,
    portal_url,
    portal_user,
    portal_pass,
    experiment_dir,
    extra_args=None,
    extra_env=None,
):
    return orchestration_ui.run_ui_smoke(
        ui_test_dir,
        connector,
        portal_url,
        portal_user,
        portal_pass,
        experiment_dir,
        subprocess_module=subprocess,
        enrich_result=_enrich_level6_ui_result,
        environment=os.environ,
        extra_args=extra_args,
        extra_env=extra_env,
    )


def _run_level6_ui_dataspace(
    ui_test_dir,
    provider_connector,
    consumer_connector,
    experiment_dir,
    extra_args=None,
    extra_env=None,
):
    return orchestration_ui.run_ui_dataspace(
        ui_test_dir,
        provider_connector,
        consumer_connector,
        experiment_dir,
        subprocess_module=subprocess,
        enrich_result=_enrich_level6_ui_result,
        environment=os.environ,
        extra_args=extra_args,
        extra_env=extra_env,
    )


def _run_level6_ui_ops(
    ui_test_dir,
    provider_connector,
    consumer_connector,
    experiment_dir,
    extra_args=None,
    extra_env=None,
):
    return orchestration_ui.run_ui_ops(
        ui_test_dir,
        provider_connector,
        consumer_connector,
        experiment_dir,
        subprocess_module=subprocess,
        enrich_result=_enrich_level6_ui_result,
        environment=os.environ,
        extra_args=extra_args,
        extra_env=extra_env,
    )


def _run_core_ui_tests(mode, adapter=None):
    adapter = adapter or _default_inesdata_adapter()
    ui_test_dir = str(project_root() / "validation" / "ui")
    runtime_env = _ui_runtime_env_from_adapter(adapter)
    runtime_extra_env = {}
    if runtime_env.get("UI_KEYCLOAK_URL"):
        runtime_extra_env["UI_KEYCLOAK_URL"] = runtime_env["UI_KEYCLOAK_URL"]
    if runtime_env.get("UI_INESDATA_LOCAL_STORE_LABEL"):
        runtime_extra_env["UI_INESDATA_LOCAL_STORE_LABEL"] = runtime_env["UI_INESDATA_LOCAL_STORE_LABEL"]
    mode = {
        **mode,
        "env": {
            **runtime_extra_env,
            **(mode.get("env") or {}),
        },
    }
    return orchestration_ui.run_core_ui_tests(
        mode,
        ui_test_dir=ui_test_dir,
        ui_test_dir_exists=os.path.isdir,
        get_connectors=adapter.get_cluster_connectors,
        create_experiment_directory=ExperimentStorage.create_experiment_directory,
        load_connector_credentials=adapter.load_connector_credentials,
        build_connector_url=adapter.build_connector_url,
        run_ui_smoke=_run_level6_ui_smoke,
        run_ui_dataspace=_run_level6_ui_dataspace,
        run_ui_ops=_run_level6_ui_ops,
        ui_ops_suite_available=_level6_ui_ops_suite_available,
        save_interactive_state=_save_interactive_core_ui_experiment_state,
        environment=runtime_env,
    )


def run_inesdata_ui_tests_interactive():
    """Run INESData UI tests for core flows and component integrations."""
    while True:
        print("\n" + "=" * 50)
        print("INESDATA UI TESTS")
        print("=" * 50)
        print("1 - Core")
        print("2 - Ontology Hub Integration with INESData")
        print("3 - AI Model Hub Integration with INESData")
        print("4 - Semantic Virtualization Integration with INESData")
        print("5 - AI Model Observer / Clearing House")
        print("B - Back")

        try:
            choice = input("\nSelection: ").strip().upper()
        except EOFError:
            print("\nNo input. Returning to main menu.\n")
            return None

        if choice == "B":
            return None
        if choice not in {"1", "2", "3", "4", "5"}:
            print("\nInvalid selection. Please try again.\n")
            continue

        mode = _resolve_ui_mode()
        if mode is None:
            return None

        if choice == "1":
            _run_core_ui_tests(mode)
        elif choice == "2":
            _run_ontology_hub_ui_integration_with_inesdata(mode)
        elif choice == "3":
            _run_ai_model_hub_ui_integration(mode)
        elif choice == "4":
            _run_semantic_virtualization_ui_integration_with_inesdata(mode)
        elif choice == "5":
            _run_ai_model_observer_ui_integration(mode)
        return None


def _print_edc_ui_result(label, result):
    if not isinstance(result, dict):
        return None

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    counts = summary.get("status_counts") if isinstance(summary.get("status_counts"), dict) else {}
    total = int(summary.get("total_specs") or 0)
    passed = int(counts.get("passed") or counts.get("expected") or 0)
    failed = int(counts.get("failed") or counts.get("unexpected") or 0)
    skipped = int(counts.get("skipped") or 0)

    if total:
        print(f"\nEDC UI result for {label}: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    else:
        print(f"\nEDC UI result for {label}: no tests were recorded")

    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
    html_report_dir = artifacts.get("html_report_dir")
    report_index = os.path.join(str(html_report_dir or ""), "index.html") if html_report_dir else ""
    if report_index and os.path.isfile(report_index):
        print(f"Playwright HTML report: {report_index}")
        print(f"Open with: npx playwright show-report {html_report_dir}\n")
    elif report_index:
        print(f"Playwright HTML report was not generated at {report_index}\n")
    return result


def _run_edc_ui_specs(mode, label, specs=None, test_grep=None, topology=None):
    from deployers.edc.deployer import EdcDeployer
    from validation.ui.ui_runner import run_playwright_validation

    normalized_topology = _normalize_topology(
        topology
        or os.environ.get("UI_TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or "local"
    )
    adapter = _build_validation_adapter(adapter_name="edc", topology=normalized_topology)
    deployer = EdcDeployer(adapter=adapter, topology=normalized_topology)
    context = deployer.resolve_context(topology=normalized_topology)
    profile = deployer.get_validation_profile(context)
    cluster_runtime = build_cluster_runtime(context.config, topology=normalized_topology).get(
        "cluster_type",
        "unknown",
    )
    experiment_dir = ExperimentStorage.create_experiment_directory()
    ExperimentStorage.save_experiment_metadata(
        experiment_dir,
        context.connectors,
        adapter=adapter.__class__.__name__,
        adapter_name="edc",
        topology=normalized_topology,
        cluster_runtime=cluster_runtime,
        environment=context.environment,
    )

    extra_args = list(mode.get("args") or [])
    _append_playwright_grep(extra_args, test_grep)
    result = run_playwright_validation(
        profile=profile,
        context=context,
        experiment_dir=experiment_dir,
        specs=list(specs or []),
        extra_args=extra_args,
        extra_env=mode.get("env") or {},
    )
    return _print_edc_ui_result(label, result)


def run_edc_ui_tests_interactive():
    """Run EDC UI tests for core flows and component integrations."""
    suites = {
        "1": ("Core", EDC_UI_CORE_SPECS),
        "2": ("Ontology Hub Integration with EDC", EDC_UI_ONTOLOGY_HUB_SPECS),
        "3": ("AI Model Hub Integration with EDC", EDC_UI_AI_MODEL_HUB_SPECS),
        "4": ("Semantic Virtualization Integration with EDC", EDC_UI_SEMANTIC_VIRTUALIZATION_SPECS),
        "5": ("AI Model Observer / Clearing House", EDC_UI_AI_MODEL_OBSERVER_SPECS),
        "6": (
            "Full EDC UI suite",
            (
                *EDC_UI_CORE_SPECS,
                *EDC_UI_SEMANTIC_VIRTUALIZATION_SPECS,
                *EDC_UI_ONTOLOGY_HUB_SPECS,
                *EDC_UI_AI_MODEL_HUB_SPECS,
                *EDC_UI_AI_MODEL_OBSERVER_SPECS,
            ),
        ),
    }

    while True:
        print("\n" + "=" * 50)
        print("EDC UI TESTS")
        print("=" * 50)
        print("1 - Core")
        print("2 - Ontology Hub Integration with EDC")
        print("3 - AI Model Hub Integration with EDC")
        print("4 - Semantic Virtualization Integration with EDC")
        print("5 - AI Model Observer / Clearing House")
        print("6 - Full EDC UI suite")
        print("B - Back")

        try:
            choice = input("\nSelection: ").strip().upper()
        except EOFError:
            print("\nNo input. Returning to main menu.\n")
            return None

        if choice == "B":
            return None
        if choice not in suites:
            print("\nInvalid selection. Please try again.\n")
            continue

        mode = _resolve_ui_mode()
        if mode is None:
            return None

        label, specs = suites[choice]
        _run_edc_ui_specs(mode, label, specs)
        return None


def _safe_test_id_path(test_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(test_id or "").strip()).strip("-") or "test-by-id"


@contextlib.contextmanager
def _temporary_env(updates):
    previous = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _build_validation_adapter(adapter_name=None, topology=None):
    normalized_adapter = str(adapter_name or os.environ.get("PIONERA_ADAPTER") or "inesdata").strip().lower()
    normalized_topology = str(topology or os.environ.get("PIONERA_TOPOLOGY") or "local").strip().lower() or "local"
    if normalized_adapter == "edc":
        from adapters.edc.adapter import EdcAdapter

        return EdcAdapter(topology=normalized_topology)
    return InesdataAdapter(topology=normalized_topology)


def _adapter_name_from_instance(adapter, fallback="inesdata"):
    config = getattr(adapter, "config", None)
    adapter_name_getter = getattr(config, "adapter_name", None)
    if callable(adapter_name_getter):
        resolved = str(adapter_name_getter() or "").strip().lower()
        if resolved:
            return resolved
    class_name = adapter.__class__.__name__.lower() if adapter is not None else ""
    if "edc" in class_name:
        return "edc"
    if "inesdata" in class_name:
        return "inesdata"
    return str(fallback or "inesdata").strip().lower() or "inesdata"


def _primary_dataspace_name(adapter):
    getter = getattr(getattr(adapter, "config_adapter", None), "primary_dataspace_name", None)
    if callable(getter):
        return str(getter() or "").strip()
    config = adapter.load_deployer_config() or {}
    return str(config.get("DS_1_NAME") or config.get("DATASPACE_NAME") or "demo").strip()


def _resolve_component_api_base_url(component, *, adapter_name=None, topology=None):
    normalized_component = str(component or "").strip().lower()
    adapter = _build_validation_adapter(adapter_name=adapter_name, topology=topology)
    infer = getattr(getattr(adapter, "components", None), "infer_component_urls", None)
    if callable(infer):
        config = adapter.load_deployer_config() or {}
        urls = infer([normalized_component], ds_name=_primary_dataspace_name(adapter), deployer_config=config)
        inferred_url = str((urls or {}).get(normalized_component) or "").rstrip("/")
        if inferred_url:
            return inferred_url

    if normalized_component == "ontology-hub":
        from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime

        runtime_env = _ontology_hub_functional_runtime_env(adapter=adapter, adapter_name=adapter_name, topology=topology)
        return str(resolve_ontology_hub_runtime(environ={**os.environ, **runtime_env}).get("baseUrl") or "").rstrip("/")
    if normalized_component == "ai-model-hub":
        return _resolve_ai_model_hub_base_url(adapter)
    if normalized_component == "semantic-virtualization":
        return _resolve_semantic_virtualization_base_url(adapter)
    return ""


def _api_test_experiment_dir(test_id):
    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    return str(project_root() / "experiments" / experiment_id / "api" / "test-by-id" / _safe_test_id_path(test_id))


def _case_results_from_payload(payload):
    cases = []
    if isinstance(payload, dict):
        for key in (
            "executed_cases",
            "pt5_case_results",
            "pt5_cases",
            "support_checks",
            "functional_use_case_results",
            "functional_use_cases",
            "observer_case_results",
            "observer_cases",
            "test_cases",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                cases.extend(item for item in value if isinstance(item, dict))
        for key in ("suites", "phases"):
            value = payload.get(key)
            if isinstance(value, dict):
                for child in value.values():
                    cases.extend(_case_results_from_payload(child))
        if payload.get("test_case_id"):
            cases.append(payload)
    elif isinstance(payload, list):
        for item in payload:
            cases.extend(_case_results_from_payload(item))
    return cases


def _unique_cases(cases):
    unique = []
    seen = set()
    for index, case in enumerate(cases or []):
        case_id = str(case.get("test_case_id") or case.get("case_id") or case.get("id") or "").strip()
        status = str(((case.get("evaluation") or {}).get("status") or case.get("status") or "")).strip().lower()
        key = (case_id, status, str(case.get("source_suite") or case.get("suite") or ""), index if not case_id else "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(case)
    return unique


def _filter_cases_by_test_id(payload, test_id):
    normalized = str(test_id or "").strip().upper()
    return _unique_cases(
        [
            case
            for case in _case_results_from_payload(payload)
            if str(case.get("test_case_id") or case.get("case_id") or case.get("id") or "").strip().upper()
            == normalized
        ]
    )


def _summarize_api_cases(cases):
    summary = {"total": len(cases), "passed": 0, "failed": 0, "skipped": 0}
    for case in cases:
        status = str(((case.get("evaluation") or {}).get("status") or case.get("status") or "skipped")).lower()
        if status in {"error", "failed"}:
            summary["failed"] += 1
        elif status in {"passed", "success"}:
            summary["passed"] += 1
        else:
            summary["skipped"] += 1
    return summary


def _write_api_test_by_id_result(experiment_dir, payload):
    os.makedirs(experiment_dir, exist_ok=True)
    report_path = os.path.join(experiment_dir, "api-test-by-id-result.json")
    _write_json(report_path, payload)
    return report_path


def _run_ontology_hub_api_case(base_url, experiment_dir, test_id):
    from validation.components.ontology_hub.integration.runner import run_ontology_hub_validation

    return run_ontology_hub_validation(base_url, experiment_dir=experiment_dir, case_ids=[test_id])


def _run_ai_model_hub_preflight_api_case(base_url, experiment_dir, _test_id):
    from validation.components.ai_model_hub.runner import run_ai_model_hub_validation

    return run_ai_model_hub_validation(base_url, experiment_dir=experiment_dir)


def _run_ai_model_hub_connector_governance_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.ai_model_hub.component_runner import run_ai_model_hub_connector_governance_validation

    return run_ai_model_hub_connector_governance_validation(experiment_dir=experiment_dir)


def _run_ai_model_hub_model_execution_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.ai_model_hub.component_runner import run_ai_model_hub_model_execution_validation

    return run_ai_model_hub_model_execution_validation(experiment_dir=experiment_dir)


def _run_ai_model_hub_model_benchmarking_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.ai_model_hub.component_runner import run_ai_model_hub_model_benchmarking_validation

    return run_ai_model_hub_model_benchmarking_validation(experiment_dir=experiment_dir)


def _run_ai_model_hub_mobility_benchmarking_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.ai_model_hub.component_runner import run_ai_model_hub_mobility_benchmarking_validation

    return run_ai_model_hub_mobility_benchmarking_validation(experiment_dir=experiment_dir)


def _run_ai_model_hub_model_observer_api_case(base_url, experiment_dir, _test_id):
    from validation.components.ai_model_hub.component_runner import (
        _resolve_model_observer_base_url,
        run_ai_model_hub_model_observer_validation,
    )

    return run_ai_model_hub_model_observer_validation(
        base_url=_resolve_model_observer_base_url(base_url),
        experiment_dir=experiment_dir,
    )


def _run_semantic_virtualization_api_check_case(base_url, experiment_dir, test_id):
    from validation.components.semantic_virtualization.runner import run_semantic_virtualization_api_checks_validation

    return run_semantic_virtualization_api_checks_validation(base_url, experiment_dir=experiment_dir, case_ids=[test_id])


def _run_semantic_virtualization_mapping_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.semantic_virtualization.mapping_validation import (
        run_semantic_virtualization_mapping_validation,
    )

    return run_semantic_virtualization_mapping_validation(experiment_dir=experiment_dir)


def _run_semantic_virtualization_morph_source_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.semantic_virtualization.morph_kgv_source import run_morph_kgv_source_validation

    return run_morph_kgv_source_validation(experiment_dir=experiment_dir)


def _run_semantic_virtualization_automap_source_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.semantic_virtualization.automap_source import run_automap_source_validation

    return run_automap_source_validation(experiment_dir=experiment_dir)


def _run_semantic_virtualization_automap_execution_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.semantic_virtualization.automap_execution import (
        run_automap_deterministic_execution_validation,
    )

    return run_automap_deterministic_execution_validation(experiment_dir=experiment_dir)


def _run_gtfs_bench_source_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.semantic_virtualization.gtfs_bench_official import (
        run_gtfs_bench_official_source_validation,
    )

    return run_gtfs_bench_official_source_validation(experiment_dir=experiment_dir)


def _run_gtfs_bench_dataset_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.semantic_virtualization.gtfs_bench_dataset import (
        run_gtfs_bench_official_dataset_validation,
    )

    return run_gtfs_bench_official_dataset_validation(experiment_dir=experiment_dir)


def _run_gtfs_bench_materialization_api_case(_base_url, experiment_dir, _test_id):
    from validation.components.semantic_virtualization.gtfs_bench_materialization import (
        run_gtfs_bench_official_materialization_validation,
    )

    return run_gtfs_bench_official_materialization_validation(experiment_dir=experiment_dir)


def _api_test_routes():
    routes = {}

    def add(case_ids, *, label, component, runner, requires_base_url=True):
        for case_id in case_ids:
            normalized = str(case_id or "").strip().upper()
            if normalized:
                routes[normalized] = {
                    "id": normalized,
                    "label": label,
                    "component": component,
                    "runner": runner,
                    "requires_base_url": requires_base_url,
                }

    add(
        ["PT5-OH-08", "PT5-OH-09", "PT5-OH-13", "PT5-OH-14", "PT5-OH-15"],
        label="Ontology Hub API integration",
        component="ontology-hub",
        runner=_run_ontology_hub_api_case,
    )
    add(
        ["MH-BOOTSTRAP-01", "MH-BOOTSTRAP-02"],
        label="AI Model Hub API preflight",
        component="ai-model-hub",
        runner=_run_ai_model_hub_preflight_api_case,
    )
    add(
        ["PT5-MH-09", "PT5-MH-11", "PT5-MH-16", "PT5-MH-17", "PT5-MH-18"],
        label="AI Model Hub connector governance API",
        component="ai-model-hub",
        runner=_run_ai_model_hub_connector_governance_api_case,
        requires_base_url=False,
    )
    add(
        ["PT5-MH-10", "MH-LING-01"],
        label="AI Model Hub model execution API",
        component="ai-model-hub",
        runner=_run_ai_model_hub_model_execution_api_case,
        requires_base_url=False,
    )
    add(
        ["PT5-MH-12", "PT5-MH-13", "PT5-MH-14", "PT5-MH-15"],
        label="AI Model Hub model benchmarking API",
        component="ai-model-hub",
        runner=_run_ai_model_hub_model_benchmarking_api_case,
        requires_base_url=False,
    )
    add(
        ["MH-MOB-01"],
        label="AI Model Hub mobility benchmarking API",
        component="ai-model-hub",
        runner=_run_ai_model_hub_mobility_benchmarking_api_case,
        requires_base_url=False,
    )
    add(
        ["MH-OBS-02"],
        label="AI Model Hub observer API",
        component="ai-model-hub",
        runner=_run_ai_model_hub_model_observer_api_case,
    )
    add(
        ["SV-BOOTSTRAP-01", "SV-API-01", "SV-API-02", "SV-API-03", "SV-API-04"],
        label="Semantic Virtualization API checks",
        component="semantic-virtualization",
        runner=_run_semantic_virtualization_api_check_case,
    )
    add(
        ["PT5-VS-01", "PT5-VS-03", "PT5-VS-04", "PT5-VS-05", "PT5-VS-06", "PT5-VS-09", "PT5-VS-10", "INT-VS-OH-01"],
        label="Semantic Virtualization mapping API",
        component="semantic-virtualization",
        runner=_run_semantic_virtualization_mapping_api_case,
        requires_base_url=False,
    )
    add(
        ["SV-MORPH-KGV-01"],
        label="Semantic Virtualization morph-kgv source API",
        component="semantic-virtualization",
        runner=_run_semantic_virtualization_morph_source_api_case,
        requires_base_url=False,
    )
    add(
        ["SV-AUTOMAP-01"],
        label="Semantic Virtualization Automap source API",
        component="semantic-virtualization",
        runner=_run_semantic_virtualization_automap_source_api_case,
        requires_base_url=False,
    )
    add(
        ["SV-AUTOMAP-02"],
        label="Semantic Virtualization Automap execution API",
        component="semantic-virtualization",
        runner=_run_semantic_virtualization_automap_execution_api_case,
        requires_base_url=False,
    )
    add(
        ["SV-GTFS-BENCH-01"],
        label="Semantic Virtualization GTFS-Bench source API",
        component="semantic-virtualization",
        runner=_run_gtfs_bench_source_api_case,
        requires_base_url=False,
    )
    add(
        ["SV-GTFS-BENCH-02"],
        label="Semantic Virtualization GTFS-Bench dataset API",
        component="semantic-virtualization",
        runner=_run_gtfs_bench_dataset_api_case,
        requires_base_url=False,
    )
    add(
        ["SV-GTFS-BENCH-03"],
        label="Semantic Virtualization GTFS-Bench materialization API",
        component="semantic-virtualization",
        runner=_run_gtfs_bench_materialization_api_case,
        requires_base_url=False,
    )
    return routes


def _resolve_validation_api_test_route(test_id):
    normalized = str(test_id or "").strip().upper()
    if not normalized:
        return None
    return _api_test_routes().get(normalized)


def _select_validation_route_kind_interactive():
    while True:
        print("\nSelected ID has both Playwright UI and component API validations.")
        print("1 - Run both validations")
        print("2 - Playwright UI validation")
        print("3 - Component API validation")
        print("B - Back")
        try:
            choice = input("\nSelection: ").strip().upper()
        except EOFError:
            print("\nNo input. Returning to main menu.\n")
            return None
        if choice in {"", "1"}:
            return "both"
        if choice == "2":
            return "ui"
        if choice == "3":
            return "api"
        if choice == "B":
            return None
        print("\nInvalid selection. Please try again.\n")


def _run_validation_ui_route_by_id(route, adapter_name=None, topology=None):
    mode = _resolve_ui_mode()
    if mode is None:
        return None

    runner = route["runner"]
    if runner is _run_inesdata_ui_specs_by_id:
        return runner(
            mode,
            route,
            adapter_name=adapter_name,
            topology=topology,
        )
    if runner is _run_ai_model_hub_ui_functional:
        return runner(
            mode,
            test_grep=route.get("grep"),
            adapter_name=adapter_name,
            topology=topology,
        )
    if runner is _run_semantic_virtualization_ui_tests:
        return runner(
            mode,
            test_grep=route.get("grep"),
            adapter_name=adapter_name,
            topology=topology,
            needs_mapping_editor=route.get("needs_mapping_editor"),
        )
    if runner is _run_ontology_hub_ui_functional:
        return runner(
            mode,
            test_grep=route.get("grep"),
            adapter_name=adapter_name,
            topology=topology,
        )
    return runner(mode, test_grep=route.get("grep"))


def _run_validation_api_route_by_id(route, adapter_name=None, topology=None):
    normalized_adapter = str(adapter_name or os.environ.get("PIONERA_ADAPTER") or "inesdata").strip().lower()
    normalized_topology = str(topology or os.environ.get("PIONERA_TOPOLOGY") or "local").strip().lower() or "local"
    base_url = ""
    if route.get("requires_base_url", True):
        base_url = _resolve_component_api_base_url(
            route["component"],
            adapter_name=normalized_adapter,
            topology=normalized_topology,
        )
        if not base_url:
            print(f"\n{route['component']} base URL could not be resolved; aborting.\n")
            return None

    experiment_dir = _api_test_experiment_dir(route["id"])
    env_updates = {
        "PIONERA_ADAPTER": normalized_adapter,
        "PIONERA_TOPOLOGY": normalized_topology,
        "INESDATA_TOPOLOGY": normalized_topology,
        "AI_MODEL_HUB_COMPONENT_ADAPTER": normalized_adapter,
    }

    print_component_suite_header(f"{route['label']} ({route['id']})", "api")
    print(f"\nRunning API test {route['id']} (artifacts in {experiment_dir})\n")
    with _temporary_env(env_updates):
        result = route["runner"](base_url, experiment_dir, route["id"])

    target_cases = _filter_cases_by_test_id(result, route["id"])
    if target_cases:
        print_component_case_results(target_cases)
    else:
        print(f"  - {route['id']}: no case result was produced by the selected API runner")

    summary = _summarize_api_cases(target_cases)
    status = "failed" if summary["failed"] else "passed" if summary["passed"] else "skipped"
    report_path = _write_api_test_by_id_result(
        experiment_dir,
        {
            "test_case_id": route["id"],
            "label": route["label"],
            "component": route["component"],
            "adapter": normalized_adapter,
            "topology": normalized_topology,
            "base_url": base_url,
            "status": status,
            "summary": summary,
            "target_cases": target_cases,
            "suite_result": result,
        },
    )
    print(f"\nAPI test status: {status}")
    print(f"Result artifact: {report_path}\n")
    return {
        "status": status,
        "test_case_id": route["id"],
        "component": route["component"],
        "experiment_dir": experiment_dir,
        "report_json": report_path,
        "summary": summary,
    }


def run_validation_api_test_by_id_interactive(adapter_name=None, topology=None):
    """Run one mapped component API validation by its audit/test ID."""
    try:
        test_id = input("\nAPI Test ID: ").strip()
    except EOFError:
        print("\nNo input. Returning to main menu.\n")
        return None
    if not test_id or test_id.upper() == "B":
        return None

    route = _resolve_validation_api_test_route(test_id)
    if route is None:
        known_ids = ", ".join(sorted(_api_test_routes()))
        print(
            "\nNo component API test route is mapped for that ID yet. "
            f"Known API IDs: {known_ids}\n"
        )
        return None

    return _run_validation_api_route_by_id(route, adapter_name=adapter_name, topology=topology)


def _run_inesdata_ui_specs_by_id(mode, route, adapter_name=None, topology=None):
    test_id = route["id"]
    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    base_dir = str(
        project_root()
        / "experiments"
        / experiment_id
        / "ui"
        / "test-by-id"
        / _safe_test_id_path(test_id)
    )
    output_dir = os.path.join(base_dir, "test-results")
    html_report_dir = os.path.join(base_dir, "playwright-report")
    blob_report_dir = os.path.join(base_dir, "blob-report")
    json_report_file = os.path.join(base_dir, "results.json")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(html_report_dir, exist_ok=True)
    os.makedirs(blob_report_dir, exist_ok=True)

    normalized_adapter = str(adapter_name or os.environ.get("PIONERA_ADAPTER") or "inesdata").strip().lower()
    normalized_topology = normalize_topology(topology or os.environ.get("PIONERA_TOPOLOGY") or "local")
    env = _ui_runtime_env_from_adapter(
        _build_validation_adapter(adapter_name=normalized_adapter, topology=normalized_topology)
    )
    env.update(
        {
            "PIONERA_ADAPTER": normalized_adapter,
            "UI_ADAPTER": normalized_adapter,
            "PIONERA_TOPOLOGY": normalized_topology,
            "INESDATA_TOPOLOGY": normalized_topology,
            "UI_TOPOLOGY": normalized_topology,
            "PLAYWRIGHT_OUTPUT_DIR": output_dir,
            "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
            "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
            "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
            "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
            "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
        }
    )
    env.update(route.get("env") or {})
    env.update(mode.get("env") or {})

    cmd = [
        "./node_modules/.bin/playwright",
        "test",
        "--config",
        "playwright.inesdata.config.ts",
        *list(route["specs"]),
        "--workers=1",
    ]
    _append_playwright_grep(cmd, route.get("grep"))
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning {route['label']} ({mode['label']}, artifacts in {base_dir})\n")
    completed = None
    try:
        completed = subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return _finalize_playwright_run(
        route["label"],
        completed,
        json_report_file,
        html_report_dir,
        test_grep=route.get("grep"),
    )


def _resolve_validation_ui_test_route(test_id):
    normalized = str(test_id or "").strip().upper()
    if not normalized:
        return None

    if normalized.startswith("OH-APP-"):
        return {
            "id": normalized,
            "label": f"Ontology Hub UI test {normalized}",
            "runner": _run_ontology_hub_ui_functional,
            "grep": _playwright_grep_for_id(normalized),
        }

    if re.fullmatch(r"PT5-MH-(0[1-8]|1[2-5])", normalized) or normalized == "MH-LING-01":
        return {
            "id": normalized,
            "label": f"AI Model Hub UI test {normalized}",
            "runner": _run_ai_model_hub_ui_functional,
            "grep": _playwright_grep_for_id(normalized),
        }

    if normalized.startswith("SV-UI-") or normalized in {"PT5-VS-07", "PT5-VS-08"}:
        return {
            "id": normalized,
            "label": f"Semantic Virtualization UI test {normalized}",
            "runner": _run_semantic_virtualization_ui_tests,
            "grep": _playwright_grep_for_id(normalized),
            "needs_mapping_editor": normalized in SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TEST_IDS,
        }

    inesdata_routes = {
        "DS-UI-03": {
            "specs": ["adapters/inesdata/specs/03-provider-setup.spec.ts"],
            "grep": r"03 provider setup\b",
            "label": "INESData UI test DS-UI-03",
        },
        "DS-UI-03B": {
            "specs": ["adapters/inesdata/specs/03b-provider-policy-create.spec.ts"],
            "grep": r"03b provider setup\b",
            "label": "INESData UI test DS-UI-03B",
        },
        "DS-UI-03C": {
            "specs": ["adapters/inesdata/specs/03c-provider-contract-definition-create.spec.ts"],
            "grep": r"03c provider setup\b",
            "label": "INESData UI test DS-UI-03C",
        },
        "DS-UI-04": {
            "specs": ["adapters/inesdata/specs/04-consumer-catalog.spec.ts"],
            "grep": r"04 consumer catalog\b",
            "label": "INESData UI test DS-UI-04",
        },
        "DS-UI-05": {
            "specs": ["adapters/inesdata/specs/05-consumer-negotiation.spec.ts"],
            "grep": r"05 consumer negotiation\b",
            "label": "INESData UI test DS-UI-05",
        },
        "DS-UI-06": {
            "specs": ["adapters/inesdata/specs/06-consumer-transfer.spec.ts"],
            "grep": r"06 consumer transfer\b",
            "label": "INESData UI test DS-UI-06",
        },
        "DS-UI-SV-01": {
            "specs": ["adapters/inesdata/specs/07-semantic-virtualization-httpdata.spec.ts"],
            "grep": r"07 semantic virtualization\b",
            "label": "INESData UI test DS-UI-SV-01",
            "env": {"UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO": "1"},
        },
        "DS-UI-OH-01": {
            "specs": ["adapters/inesdata/specs/08-ontology-hub-inesdata-readonly.spec.ts"],
            "grep": r"08 ontology hub\b",
            "label": "INESData UI test DS-UI-OH-01",
            "env": {"UI_ONTOLOGY_HUB_INESDATA_DEMO": "1"},
        },
        "DS-UI-AMH-01": {
            "specs": ["adapters/inesdata/specs/09-ai-model-hub-httpdata.spec.ts"],
            "grep": r"09 AI Model Hub\b",
            "label": "INESData UI test DS-UI-AMH-01",
            "env": {"UI_AI_MODEL_HUB_HTTPDATA_DEMO": "1"},
        },
        "DS-UI-AMH-OBS-01": {
            "specs": ["adapters/inesdata/specs/10-ai-model-observer.spec.ts"],
            "grep": r"10 AI Model Observer\b",
            "label": "INESData UI test DS-UI-AMH-OBS-01",
            "env": {"UI_AI_MODEL_OBSERVER_DEMO": "1"},
        },
        "DS-UI-AMH-BROWSER-01": {
            "specs": ["adapters/inesdata/specs/11-ai-model-browser.spec.ts"],
            "grep": r"11 AI Model Browser\b",
            "label": "INESData UI test DS-UI-AMH-BROWSER-01",
            "env": {"UI_AI_MODEL_HUB_HTTPDATA_DEMO": "1"},
        },
        "DS-UI-AMH-EXEC-01": {
            "specs": ["adapters/inesdata/specs/12-ai-model-execution.spec.ts"],
            "grep": r"12 AI Model Execution\b",
            "label": "INESData UI test DS-UI-AMH-EXEC-01",
            "env": {"UI_AI_MODEL_HUB_HTTPDATA_DEMO": "1"},
        },
        "DS-UI-AMH-BENCH-01": {
            "specs": ["adapters/inesdata/specs/13-ai-model-benchmarking.spec.ts"],
            "grep": r"13 AI Model Benchmarking\b",
            "label": "INESData UI test DS-UI-AMH-BENCH-01",
            "env": {"UI_AI_MODEL_HUB_HTTPDATA_DEMO": "1"},
        },
        "DS-UI-AMH-DAIMO-01": {
            "specs": ["adapters/inesdata/specs/14-ai-model-daimo-vocabulary.spec.ts"],
            "grep": r"14 AI Model Hub DAIMO\b",
            "label": "INESData UI test DS-UI-AMH-DAIMO-01",
            "env": {"UI_AI_MODEL_HUB_HTTPDATA_DEMO": "1"},
        },
        "DS-UI-AMH-EXEC-02": {
            "specs": ["adapters/inesdata/specs/15-ai-model-external-execution.spec.ts"],
            "grep": r"15 AI Model Execution\b",
            "label": "INESData UI test DS-UI-AMH-EXEC-02",
            "env": {"UI_AI_MODEL_HUB_HTTPDATA_DEMO": "1"},
        },
        "DS-UI-AMH-OBS-02": {
            "specs": ["adapters/inesdata/specs/16-ai-model-observer-participant-summary.spec.ts"],
            "grep": r"16 AI Model Observer\b",
            "label": "INESData UI test DS-UI-AMH-OBS-02",
            "env": {"UI_AI_MODEL_OBSERVER_DEMO": "1"},
        },
    }
    route = inesdata_routes.get(normalized)
    if route:
        return {
            "id": normalized,
            "runner": _run_inesdata_ui_specs_by_id,
            **route,
        }
    return None


def run_validation_test_by_id_interactive(adapter_name=None, topology=None):
    """Run a single mapped validation by its audit/test ID."""
    try:
        test_id = input("\nTest ID: ").strip()
    except EOFError:
        print("\nNo input. Returning to main menu.\n")
        return None
    if not test_id or test_id.upper() == "B":
        return None

    ui_route = _resolve_validation_ui_test_route(test_id)
    api_route = _resolve_validation_api_test_route(test_id)
    if ui_route is not None and api_route is not None:
        choice = _select_validation_route_kind_interactive()
        if choice is None:
            return None

        results = {}
        if choice in {"both", "api"}:
            print(f"\nResolved test type: Component API ({api_route['id']})")
            results["api"] = _run_validation_api_route_by_id(
                api_route,
                adapter_name=adapter_name,
                topology=topology,
            )
        if choice in {"both", "ui"}:
            print(f"\nResolved test type: Playwright UI ({ui_route['id']})")
            results["ui"] = _run_validation_ui_route_by_id(
                ui_route,
                adapter_name=adapter_name,
                topology=topology,
            )
        return results if choice == "both" else next(iter(results.values()), None)

    if ui_route is not None:
        print(f"\nResolved test type: Playwright UI ({ui_route['id']})")
        return _run_validation_ui_route_by_id(ui_route, adapter_name=adapter_name, topology=topology)

    if api_route is not None:
        print(f"\nResolved test type: Component API ({api_route['id']})")
        return _run_validation_api_route_by_id(api_route, adapter_name=adapter_name, topology=topology)

    known_ui_ids = sorted(
        [
            "OH-APP-*",
            "PT5-MH-01..08",
            "PT5-MH-12..15",
            "MH-LING-01",
            "SV-UI-*",
            "PT5-VS-07",
            "PT5-VS-08",
            *_resolve_known_inesdata_ui_ids(),
        ]
    )
    known_api_ids = sorted(_api_test_routes())
    print(
        "\nNo automated test route is mapped for that ID yet. "
        "Run Level 6 to execute the complete validation scope.\n"
    )
    print("Known UI ID patterns/examples: " + ", ".join(known_ui_ids))
    print("Known API IDs: " + ", ".join(known_api_ids) + "\n")
    return None


def _resolve_known_inesdata_ui_ids():
    return [
        "DS-UI-03",
        "DS-UI-03B",
        "DS-UI-03C",
        "DS-UI-04",
        "DS-UI-05",
        "DS-UI-06",
        "DS-UI-SV-01",
        "DS-UI-OH-01",
        "DS-UI-AMH-01",
        "DS-UI-AMH-OBS-01",
        "DS-UI-AMH-BROWSER-01",
        "DS-UI-AMH-EXEC-01",
        "DS-UI-AMH-BENCH-01",
        "DS-UI-AMH-DAIMO-01",
        "DS-UI-AMH-EXEC-02",
        "DS-UI-AMH-OBS-02",
    ]
