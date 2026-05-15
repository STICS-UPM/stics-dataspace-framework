import json
import os
import subprocess
import sys
import getpass
from datetime import datetime
from pathlib import Path

import yaml

from adapters.inesdata.adapter import InesdataAdapter
from adapters.inesdata.config import InesdataConfig
from framework.experiment_storage import ExperimentStorage
from validation.components.ontology_hub.functional.runtime_preparation import (
    prepare_ontology_hub_for_functional,
)
from validation.orchestration import ui as orchestration_ui


LEVEL6_UI_SMOKE_SPECS = orchestration_ui.LEVEL6_UI_SMOKE_SPECS
LEVEL6_UI_DATASPACE_SPECS = orchestration_ui.LEVEL6_UI_DATASPACE_SPECS
LEVEL6_UI_OPS_SPEC = orchestration_ui.LEVEL6_UI_OPS_SPEC
LEVEL6_UI_OPS_CONFIG = orchestration_ui.LEVEL6_UI_OPS_CONFIG


def project_root():
    return Path(__file__).resolve().parents[2]


def _default_inesdata_adapter():
    return InesdataAdapter()


def _ui_runtime_env_from_adapter(adapter):
    env = dict(os.environ)
    config_loader = getattr(adapter, "load_deployer_config", None)
    config = config_loader() if callable(config_loader) else {}
    if not isinstance(config, dict):
        config = {}

    keycloak_url = str(config.get("KC_INTERNAL_URL") or config.get("KC_URL") or "").strip()
    if keycloak_url:
        env.setdefault("UI_KEYCLOAK_URL", keycloak_url)

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


def _run_ontology_hub_ui_tests(mode):
    from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime

    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    base_dir = str(project_root() / "experiments" / experiment_id / "components" / "ontology-hub" / "ui")
    output_dir = os.path.join(base_dir, "test-results")
    html_report_dir = os.path.join(base_dir, "playwright-report")
    blob_report_dir = os.path.join(base_dir, "blob-report")
    json_report_file = os.path.join(base_dir, "results.json")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(html_report_dir, exist_ok=True)
    os.makedirs(blob_report_dir, exist_ok=True)

    runtime = resolve_ontology_hub_runtime()
    runtime_path = os.path.join(base_dir, "resolved_runtime.json")
    _write_json(runtime_path, runtime)

    env = {
        **os.environ,
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
        "../components/ontology_hub/integration/playwright.config.js",
        "--workers=1",
    ]
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning Ontology Hub UI tests (artifacts in {base_dir})\n")
    try:
        subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return None


def _run_ontology_hub_ui_functional(mode):
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

    runtime = resolve_ontology_hub_runtime()
    if not prepare_ontology_hub_for_functional(runtime):
        print("\nOntology Hub Functional preparation failed. Execution aborted.\n")
        return None

    runtime_path = os.path.join(base_dir, "resolved_runtime.json")
    _write_json(runtime_path, runtime)

    env = {
        **os.environ,
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
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning Ontology Hub Functional (artifacts in {base_dir})\n")
    try:
        subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return None


def run_ontology_hub_ui_tests_interactive():
    """Run Ontology Hub Playwright UI tests in normal/live/debug modes."""
    while True:
        print("\n" + "=" * 50)
        print("ONTOLOGY HUB UI TESTS")
        print("=" * 50)
        mode = _resolve_ui_mode()
        if mode is None:
            return None

        while True:
            print("\nSelect Ontology Hub UI suite:")
            print("1 - Ontology Hub Component Integration")
            print("2 - Ontology Hub Functional")
            print("B - Back")
            try:
                suite_choice = input("\nSuite: ").strip().upper()
            except EOFError:
                print("\nNo input. Returning to previous menu.\n")
                return None

            if suite_choice == "B":
                return None
            if suite_choice == "1":
                _run_ontology_hub_ui_tests(mode)
                return None
            if suite_choice == "2":
                _run_ontology_hub_ui_functional(mode)
                return None

            print("\nInvalid selection. Please try again.\n")


def _run_ontology_hub_ui_integration_with_inesdata(mode):
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
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning Ontology Hub Integration with INESData ({mode['label']}, artifacts in {base_dir})\n")
    try:
        subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return None


def _resolve_ai_model_hub_base_url(adapter=None):
    adapter = adapter or _default_inesdata_adapter()
    deployer_config = adapter.load_deployer_config() or {}
    ds_name = (
        os.environ.get("UI_DATASPACE")
        or deployer_config.get("DS_1_NAME")
        or InesdataConfig.dataspace_name()
        or "demo"
    ).strip()
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


def _resolve_semantic_virtualization_base_url(adapter=None):
    adapter = adapter or _default_inesdata_adapter()
    deployer_config = adapter.load_deployer_config() or {}
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


def _run_semantic_virtualization_ui_tests(mode):
    base_url = _resolve_semantic_virtualization_base_url()
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
        "SEMANTIC_VIRTUALIZATION_BASE_URL": base_url,
        "PLAYWRIGHT_OUTPUT_DIR": output_dir,
        "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
        "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
        "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
        "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
        "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
    }
    env.update(mode.get("env") or {})
    cmd = [
        "./node_modules/.bin/playwright",
        "test",
        "--config",
        "../components/semantic_virtualization/ui/playwright.config.js",
        "--workers=1",
    ]
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning Semantic Virtualization UI tests (artifacts in {base_dir})\n")
    try:
        subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return None


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


def _run_semantic_virtualization_ui_integration_with_inesdata(mode):
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
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning Semantic Virtualization Integration with INESData ({mode['label']}, artifacts in {base_dir})\n")
    try:
        subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return None


def _run_ai_model_hub_ui_functional(mode):
    base_url = _resolve_ai_model_hub_base_url()
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
        "AI_MODEL_HUB_ENABLE_UI_VALIDATION": "1",
        "AI_MODEL_HUB_BASE_URL": base_url,
        "PLAYWRIGHT_OUTPUT_DIR": output_dir,
        "PLAYWRIGHT_HTML_REPORT_DIR": html_report_dir,
        "PLAYWRIGHT_BLOB_REPORT_DIR": blob_report_dir,
        "PLAYWRIGHT_JSON_REPORT_FILE": json_report_file,
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
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning AI Model Hub Functional UI tests (artifacts in {base_dir})\n")
    try:
        subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return None


def _run_ai_model_hub_ui_integration(mode):
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
        "--workers=1",
    ]
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning AI Model Hub Integration with INESData ({mode['label']}, artifacts in {base_dir})\n")
    try:
        subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return None


def _run_ai_model_observer_ui_integration(mode):
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
        "--workers=1",
    ]
    cmd.extend(mode.get("args") or [])

    print(f"\nRunning AI Model Observer / Clearing House ({mode['label']}, artifacts in {base_dir})\n")
    try:
        subprocess.run(cmd, cwd=str(project_root() / "validation" / "ui"), env=env)
    finally:
        _cleanup_playwright_processes()
    return None


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
