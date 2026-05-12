"""Local interactive tools used by the framework menu."""

from __future__ import annotations

import os
import re
import shutil
import shlex
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime

from tabulate import tabulate


FRAMEWORK_BOOTSTRAP_SCRIPT_REL_PATH = os.path.join("scripts", "bootstrap_framework.sh")
CLEAN_WORKSPACE_SCRIPT_REL_PATH = os.path.join("scripts", "clean_workspace.sh")
LOCAL_WORKFLOW_SCRIPT_REL_PATH = os.path.join(
    "adapters", "inesdata", "scripts", "local_build_load_deploy.sh"
)
MIN_FRAMEWORK_PYTHON = (3, 10)
FRAMEWORK_DOCTOR_SYSTEM_COMMANDS = (
    ("python3", ["python3", "--version"], "Instala Python 3 y el paquete venv del sistema."),
    ("git", ["git", "--version"], "Instala Git en la máquina anfitriona."),
    ("docker", ["docker", "--version"], "Instala Docker y verifica que el daemon esté accesible."),
    ("minikube", ["minikube", "version"], "Instala Minikube para usar los niveles 1-6."),
    ("helm", ["helm", "version", "--short"], "Instala Helm para desplegar charts."),
    ("kubectl", ["kubectl", "version", "--client=true"], "Instala kubectl para operar el clúster."),
    ("psql", ["psql", "--version"], "Instala el cliente de PostgreSQL."),
    ("node", ["node", "--version"], "Instala Node.js para Newman y Playwright."),
    ("npm", ["npm", "--version"], "Instala npm junto con Node.js."),
)


def _playwright_bootstrap_remediation() -> str:
    if sys.platform.startswith("linux"):
        return f"Run: bash {FRAMEWORK_BOOTSTRAP_SCRIPT_REL_PATH} (installs Playwright with system dependencies on Linux/WSL)"
    return f"Run: bash {FRAMEWORK_BOOTSTRAP_SCRIPT_REL_PATH}"


def _playwright_browser_remediation() -> str:
    if sys.platform.startswith("linux"):
        return "Run: cd validation/ui && npx playwright install --with-deps"
    return "Run: cd validation/ui && npx playwright install"


def _python_bootstrap_remediation() -> str:
    if sys.platform == "darwin":
        return (
            "Install Python 3.10+ (for example: brew install python@3.11) "
            "and rerun bootstrap. If needed: "
            f"PIONERA_PYTHON_BIN=python3.11 bash {FRAMEWORK_BOOTSTRAP_SCRIPT_REL_PATH}"
        )
    return f"Use Python 3.10+ and rerun bootstrap: bash {FRAMEWORK_BOOTSTRAP_SCRIPT_REL_PATH}"


def _parse_python_version(version_text: str) -> tuple[int, int, int] | None:
    match = re.search(r"Python\s+(\d+)\.(\d+)(?:\.(\d+))?", version_text or "")
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return major, minor, patch


def _python_version_supported(version_text: str) -> bool:
    parsed = _parse_python_version(version_text)
    if not parsed:
        return False
    return parsed >= MIN_FRAMEWORK_PYTHON


@dataclass(frozen=True)
class LocalImageRecipe:
    """Explicit local-image build recipe exposed by the developer menu."""

    key: str
    adapter: str
    label: str
    source_rel_path: str
    image_ref: str
    workflow_component: str = ""
    script_rel_path: str = ""
    script_args: tuple[str, ...] = ()
    dockerfile_rel_path: str = ""
    context_rel_path: str = ""
    build_args: tuple[tuple[str, str], ...] = ()
    loads_minikube: bool = False
    restart_deployment_template: str = ""
    description: str = ""


def project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _is_wsl() -> bool:
    try:
        with open("/proc/version", "r", encoding="utf-8") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def get_hosts_path() -> str | None:
    if _is_wsl():
        return "/mnt/c/Windows/System32/drivers/etc/hosts"
    if sys.platform.startswith("linux"):
        return "/etc/hosts"
    if sys.platform == "darwin":
        return "/private/etc/hosts"
    return None


def _run_command_capture(args, cwd=None):
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    return result.returncode, output


def _doctor_item(category, name, status, details, remediation=None):
    return {
        "category": category,
        "name": name,
        "status": status,
        "details": details,
        "remediation": remediation,
    }


def _read_key_value_config(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                normalized = line.strip()
                if normalized and "=" in normalized and not normalized.startswith("#"):
                    key, value = normalized.split("=", 1)
                    values[key.strip()] = value.strip()
    except OSError:
        return {}
    return values


def collect_framework_doctor_report():
    """Inspect local readiness to execute the framework from a fresh machine."""
    root_dir = project_root()
    ui_dir = os.path.join(root_dir, "validation", "ui")
    root_venv_python = os.path.join(root_dir, ".venv", "bin", "python")
    local_newman = os.path.join(root_dir, "node_modules", ".bin", "newman")
    local_playwright = os.path.join(ui_dir, "node_modules", ".bin", "playwright")
    deployer_config_path = os.path.join(root_dir, "deployers", "inesdata", "deployer.config")
    deployer_example_path = os.path.join(root_dir, "deployers", "inesdata", "deployer.config.example")
    deployer_artifacts_dir = os.path.join(root_dir, "deployers", "inesdata")

    checks = []

    for command_name, version_args, remediation in FRAMEWORK_DOCTOR_SYSTEM_COMMANDS:
        resolved = shutil.which(command_name)
        if not resolved:
            checks.append(
                _doctor_item(
                    "system",
                    command_name,
                    "missing",
                    "not found in PATH",
                    remediation,
                )
            )
            continue
        return_code, version_text = _run_command_capture(version_args)
        status = "ok" if return_code == 0 else "warning"
        details = version_text.splitlines()[0].strip() if version_text else resolved
        item_remediation = remediation if return_code != 0 else None
        if command_name == "python3" and return_code == 0 and not _python_version_supported(version_text):
            status = "warning"
            details = f"{details} (framework requires Python 3.10+)"
            item_remediation = _python_bootstrap_remediation()
        checks.append(
            _doctor_item(
                "system",
                command_name,
                status,
                details,
                item_remediation,
            )
        )

    if os.path.exists(root_venv_python):
        return_code, version_text = _run_command_capture([root_venv_python, "--version"])
        venv_status = "ok" if return_code == 0 else "warning"
        venv_details = version_text or root_venv_python
        venv_remediation = f"Run: bash {FRAMEWORK_BOOTSTRAP_SCRIPT_REL_PATH}"
        if return_code == 0 and not _python_version_supported(version_text):
            venv_status = "warning"
            venv_details = f"{venv_details} (framework requires Python 3.10+)"
            venv_remediation = (
                "Remove .venv and rerun bootstrap with a supported interpreter. "
                + _python_bootstrap_remediation()
            )
        checks.append(
            _doctor_item(
                "framework",
                "root .venv",
                venv_status,
                venv_details,
                venv_remediation,
            )
        )
    else:
        checks.append(
            _doctor_item(
                "framework",
                "root .venv",
                "missing",
                f"Missing virtualenv: {root_venv_python}",
                f"Run: bash {FRAMEWORK_BOOTSTRAP_SCRIPT_REL_PATH}",
            )
        )

    active_python = os.path.abspath(sys.executable)
    active_version = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    active_supported = (sys.version_info.major, sys.version_info.minor) >= MIN_FRAMEWORK_PYTHON
    active_status = "ok" if active_python == os.path.abspath(root_venv_python) and active_supported else "warning"
    active_details = f"{active_python} ({active_version})"
    active_remediation = None
    if not active_supported:
        active_remediation = _python_bootstrap_remediation()
        active_details = f"{active_details} [framework requires Python 3.10+]"
    elif active_status != "ok":
        active_remediation = "Activate .venv before long-running deployments."
    checks.append(_doctor_item("framework", "active python", active_status, active_details, active_remediation))

    if os.path.exists(local_newman):
        return_code, version_text = _run_command_capture([local_newman, "--version"], cwd=root_dir)
        checks.append(
            _doctor_item(
                "framework",
                "newman",
                "ok" if return_code == 0 else "warning",
                version_text or local_newman,
                "Run: npm install",
            )
        )
    else:
        global_newman = shutil.which("newman")
        if global_newman:
            return_code, version_text = _run_command_capture([global_newman, "--version"], cwd=root_dir)
            checks.append(
                _doctor_item(
                    "framework",
                    "newman",
                    "ok" if return_code == 0 else "warning",
                    version_text.splitlines()[0].strip() if version_text else global_newman,
                    "Prefer a local install with: npm install",
                )
            )
        else:
            checks.append(
                _doctor_item(
                    "framework",
                    "newman",
                    "missing",
                    "Neither local nor global Newman is available",
                    "Run: npm install",
                )
            )

    if os.path.exists(local_playwright):
        return_code, version_text = _run_command_capture([local_playwright, "--version"], cwd=ui_dir)
        checks.append(
            _doctor_item(
                "ui",
                "playwright cli",
                "ok" if return_code == 0 else "warning",
                version_text.splitlines()[0].strip() if version_text else local_playwright,
                _playwright_bootstrap_remediation(),
            )
        )

        list_return_code, browser_text = _run_command_capture(
            [local_playwright, "install", "--list"],
            cwd=ui_dir,
        )
        browser_status = "ok"
        browser_details = "Playwright browsers detected"
        if list_return_code != 0:
            browser_status = "warning"
            browser_details = "Unable to query installed Playwright browsers"
        elif "Browsers:" not in browser_text:
            browser_status = "warning"
            browser_details = "Playwright browsers do not appear to be installed"
        else:
            browser_lines = [line.strip() for line in browser_text.splitlines() if line.strip().startswith("/")]
            if browser_lines:
                browser_details = browser_lines[0]
        checks.append(
            _doctor_item(
                "ui",
                "playwright browsers",
                browser_status,
                browser_details,
                _playwright_browser_remediation(),
            )
        )
    else:
        checks.append(
            _doctor_item(
                "ui",
                "playwright cli",
                "missing",
                f"Missing Playwright binary: {local_playwright}",
                _playwright_bootstrap_remediation(),
            )
        )

    if os.path.exists(deployer_config_path):
        config_values = _read_key_value_config(deployer_config_path)
        required_keys = [key for key in ("DOMAIN_BASE", "DS_DOMAIN_BASE") if not config_values.get(key)]
        status = "ok" if not required_keys else "warning"
        details = deployer_config_path
        remediation = None
        if required_keys:
            details = f"Missing required keys in INESData deployer.config: {', '.join(required_keys)}"
            remediation = f"Edit {deployer_config_path} before running the deployment levels."
        checks.append(_doctor_item("config", "deployers/inesdata/deployer.config", status, details, remediation))

        kafka_bootstrap = config_values.get("KAFKA_BOOTSTRAP_SERVERS")
        if kafka_bootstrap:
            checks.append(_doctor_item("kafka", "bootstrap servers", "ok", kafka_bootstrap, None))

        kafka_env_file = config_values.get("KAFKA_CONTAINER_ENV_FILE")
        if kafka_env_file:
            resolved_env_file = kafka_env_file
            if not os.path.isabs(resolved_env_file):
                resolved_env_file = os.path.abspath(os.path.join(root_dir, resolved_env_file))
            exists = os.path.exists(resolved_env_file)
            checks.append(
                _doctor_item(
                    "kafka",
                    "container env file",
                    "ok" if exists else "warning",
                    resolved_env_file if exists else f"Missing Kafka env file: {resolved_env_file}",
                    None if exists else "Create the Kafka env file or remove KAFKA_CONTAINER_ENV_FILE from deployers/inesdata/deployer.config.",
                )
            )
    else:
        remediation = None
        if os.path.exists(deployer_example_path):
            remediation = (
                "Run the bootstrap script or copy "
                "deployers/inesdata/deployer.config.example to deployers/inesdata/deployer.config."
            )
        checks.append(
            _doctor_item(
                "config",
                "deployers/inesdata/deployer.config",
                "missing",
                "Local INESData deployer.config is missing",
                remediation,
            )
        )

    if os.path.isdir(deployer_artifacts_dir):
        checks.append(
            _doctor_item("config", "deployers/inesdata artifacts", "ok", deployer_artifacts_dir, None)
        )
    else:
        checks.append(
            _doctor_item(
                "config",
                "deployers/inesdata artifacts",
                "warning",
                "The INESData deployer artifacts are not present in this checkout.",
                "Restore deployers/inesdata from the repository before running deployment levels.",
            )
        )

    hosts_path = get_hosts_path()
    if hosts_path and os.path.exists(hosts_path):
        writable = os.access(hosts_path, os.W_OK)
        status = "ok" if writable else "warning"
        details = f"{hosts_path} ({'writable' if writable else 'requires elevated privileges'})"
        remediation = None if writable else "Run with sufficient privileges when the framework needs to update hosts."
        checks.append(_doctor_item("config", "hosts file", status, details, remediation))
    else:
        checks.append(
            _doctor_item(
                "config",
                "hosts file",
                "warning",
                "Hosts file path is not available for automatic update on this OS.",
                "Update the required host entries manually.",
            )
        )

    if shutil.which("pgrep"):
        tunnel_result = subprocess.run(
            ["pgrep", "-af", "minikube tunnel"],
            text=True,
            capture_output=True,
            check=False,
        )
        if tunnel_result.returncode == 0 and (tunnel_result.stdout or "").strip():
            tunnel_status = "ok"
            tunnel_details = "minikube tunnel process detected"
            tunnel_remediation = None
        else:
            tunnel_status = "warning"
            tunnel_details = "minikube tunnel not detected"
            tunnel_remediation = "Before Level 3, run: minikube tunnel"
    else:
        tunnel_status = "warning"
        tunnel_details = "pgrep is not available, so the tunnel process cannot be inspected automatically"
        tunnel_remediation = "Before Level 3, verify manually that minikube tunnel is running."
    checks.append(_doctor_item("runtime", "minikube tunnel", tunnel_status, tunnel_details, tunnel_remediation))

    if any(item["status"] == "missing" for item in checks):
        overall_status = "not_ready"
    elif any(item["status"] == "warning" for item in checks):
        overall_status = "ready_with_warnings"
    else:
        overall_status = "ready"

    return {
        "status": overall_status,
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
    }


def run_framework_doctor():
    """Print a local readiness report for the framework and Level 6 validation."""
    report = collect_framework_doctor_report()

    print("\n" + "=" * 50)
    print("FRAMEWORK DOCTOR")
    print("=" * 50)
    print(f"\nOverall status: {report['status']}\n")

    rows = [
        [
            item["category"],
            item["name"],
            item["status"],
            item["details"],
        ]
        for item in report["checks"]
    ]
    print(tabulate(rows, headers=["Category", "Check", "Status", "Details"], tablefmt="github"))

    remediations = [
        f"- {item['name']}: {item['remediation']}"
        for item in report["checks"]
        if item.get("remediation") and item.get("status") != "ok"
    ]
    if remediations:
        print("\nRecommended actions:")
        print("\n".join(remediations))

    print()
    return report


def run_framework_bootstrap_interactive():
    """Run local bootstrap to prepare Python, Newman, Playwright and deployer config."""
    root_dir = project_root()
    script_path = os.path.join(root_dir, FRAMEWORK_BOOTSTRAP_SCRIPT_REL_PATH)
    if not os.path.isfile(script_path):
        print(f"\nBootstrap script not found: {script_path}\n")
        return None

    try:
        confirm = input("\nRun framework bootstrap now? (Y/N, default: Y): ").strip().upper() or "Y"
    except EOFError:
        confirm = "N"

    if confirm != "Y":
        print("\nBootstrap cancelled.\n")
        return None

    command = ["bash", script_path]
    if sys.platform.startswith("linux"):
        print("\nOn Linux/WSL this also prepares Playwright system dependencies and may request sudo privileges.")
    print(f"\nLaunching framework bootstrap: {' '.join(command)}\n")
    result = subprocess.run(command, cwd=root_dir)

    if result.returncode == 0:
        print("\nFramework bootstrap completed successfully.\n")
    else:
        print("\nFramework bootstrap failed. Check logs above.\n")

    return result.returncode


def run_workspace_cleanup_interactive():
    """Run workspace cleanup script in apply mode."""
    root_dir = project_root()
    script_path = os.path.join(root_dir, CLEAN_WORKSPACE_SCRIPT_REL_PATH)
    if not os.path.isfile(script_path):
        print(f"\nCleanup script not found: {script_path}\n")
        return None

    while True:
        print("\n" + "=" * 50)
        print("WORKSPACE CLEANUP")
        print("=" * 50)
        print("1 - Apply cleanup")
        print("    Removes __pycache__, *.pyc and tool caches")
        print("2 - Apply cleanup + include results")
        print("    Also removes experiments/, newman/ and Playwright results")
        print("B - Back")

        try:
            choice = input("\nSelection: ").strip().upper()
        except EOFError:
            print("\nNo input. Returning to main menu.\n")
            return None

        if choice == "B":
            return None

        if choice not in {"1", "2"}:
            print("\nInvalid selection. Please try again.\n")
            continue

        command = ["bash", script_path, "--apply"]
        mode_label = "cleanup"
        if choice == "2":
            command.append("--include-results")
            mode_label = "cleanup + include results"

        try:
            confirm = input(f"\nRun {mode_label}? (Y/N, default: N): ").strip().upper()
        except EOFError:
            confirm = "N"

        if confirm != "Y":
            print("\nCleanup cancelled.\n")
            return None

        print(f"\nLaunching cleanup: {' '.join(command)}\n")
        result = subprocess.run(command, cwd=root_dir)

        if result.returncode == 0:
            print("\nCleanup completed successfully.\n")
        else:
            print("\nCleanup failed. Check logs above.\n")

        return None


def _extract_repo_dir_from_adapter_config(config_path):
    """Read REPO_DIR from adapter config.py without importing adapter modules."""
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return None

    match = re.search(
        r'^\s*REPO_DIR\s*=\s*(?:os\.path\.join\(([^)]*)\)|["\']([^"\']+)["\'])',
        content,
        re.MULTILINE,
    )
    if not match:
        return None

    if match.group(2):
        repo_dir = match.group(2).strip()
        return repo_dir or None

    joined_parts = []
    for token in (match.group(1) or "").split(","):
        token = token.strip().strip('"').strip("'")
        if token:
            joined_parts.append(token)
    if not joined_parts:
        return None
    return os.path.join(*joined_parts)


def _detect_platform_dirs_from_adapter_configs():
    """Detect local deployer artifact directories from adapter REPO_DIR values."""
    root_dir = project_root()
    adapters_dir = os.path.join(root_dir, "adapters")
    platform_dirs = []
    seen = set()

    if os.path.isdir(adapters_dir):
        for adapter_name in sorted(os.listdir(adapters_dir)):
            config_path = os.path.join(adapters_dir, adapter_name, "config.py")
            if not os.path.isfile(config_path):
                continue

            repo_dir = _extract_repo_dir_from_adapter_config(config_path)
            if not repo_dir or repo_dir in seen:
                continue

            repo_abs_path = os.path.join(root_dir, repo_dir)
            if os.path.isdir(repo_abs_path):
                platform_dirs.append(repo_dir)
                seen.add(repo_dir)

    default_repo_dir = os.path.join("deployers", "inesdata")
    if os.path.isdir(os.path.join(root_dir, default_repo_dir)):
        if default_repo_dir in platform_dirs:
            platform_dirs.remove(default_repo_dir)
        platform_dirs.insert(0, default_repo_dir)

    return platform_dirs


def _local_image_recipe_catalog() -> list[LocalImageRecipe]:
    """Return the explicit image recipes supported by the framework.

    Recipes are intentionally declared instead of blindly executing every
    Dockerfile under sources. This keeps local builds auditable and reproducible.
    """
    return [
        LocalImageRecipe(
            key="inesdata/connector",
            adapter="inesdata",
            label="INESData connector",
            source_rel_path=os.path.join("adapters", "inesdata", "sources", "inesdata-connector"),
            image_ref="generated by INESData build manifest",
            workflow_component="connector",
            description="Uses the existing INESData local build/load/deploy workflow.",
        ),
        LocalImageRecipe(
            key="inesdata/connector-interface",
            adapter="inesdata",
            label="INESData connector interface",
            source_rel_path=os.path.join("adapters", "inesdata", "sources", "inesdata-connector-interface"),
            image_ref="generated by INESData build manifest",
            workflow_component="connector-interface",
            description="Uses the existing INESData local build/load/deploy workflow.",
        ),
        LocalImageRecipe(
            key="inesdata/registration-service",
            adapter="inesdata",
            label="INESData registration service",
            source_rel_path=os.path.join("adapters", "inesdata", "sources", "inesdata-registration-service"),
            image_ref="generated by INESData build manifest",
            workflow_component="registration-service",
            description="Uses the existing INESData local build/load/deploy workflow.",
        ),
        LocalImageRecipe(
            key="inesdata/public-portal-backend",
            adapter="inesdata",
            label="INESData public portal backend",
            source_rel_path=os.path.join("adapters", "inesdata", "sources", "inesdata-public-portal-backend"),
            image_ref="generated by INESData build manifest",
            workflow_component="public-portal-backend",
            description="Uses the existing INESData local build/load/deploy workflow.",
        ),
        LocalImageRecipe(
            key="inesdata/public-portal-frontend",
            adapter="inesdata",
            label="INESData public portal frontend",
            source_rel_path=os.path.join("adapters", "inesdata", "sources", "inesdata-public-portal-frontend"),
            image_ref="generated by INESData build manifest",
            workflow_component="public-portal-frontend",
            description="Uses the existing INESData local build/load/deploy workflow.",
        ),
        LocalImageRecipe(
            key="inesdata/ontology-hub",
            adapter="inesdata",
            label="Ontology Hub",
            source_rel_path=os.path.join("adapters", "inesdata", "sources", "Ontology-Hub"),
            image_ref="ontology-hub:local",
            dockerfile_rel_path=os.path.join("adapters", "inesdata", "sources", "Ontology-Hub", "Dockerfile"),
            context_rel_path=os.path.join("adapters", "inesdata", "sources", "Ontology-Hub"),
            build_args=(
                ("REPO_URL", "https://github.com/ProyectoPIONERA/Ontology-Hub-Scripts.git"),
                ("BRANCH_NAME", "dev"),
                ("REPO_NAME", "Ontology-Hub-Scripts"),
                ("REPO_PATRONES", "https://github.com/oeg-upm/GrOwEr.git"),
            ),
            restart_deployment_template="{dataspace}-ontology-hub",
            description="Builds the Level 5 Ontology Hub component image.",
        ),
        LocalImageRecipe(
            key="inesdata/ai-model-hub",
            adapter="inesdata",
            label="AI Model Hub dashboard",
            source_rel_path=os.path.join("adapters", "inesdata", "sources", "AIModelHub"),
            image_ref="eclipse-edc/data-dashboard:local",
            dockerfile_rel_path=os.path.join(
                "adapters",
                "inesdata",
                "sources",
                "AIModelHub",
                "DataDashboard",
                "Dockerfile",
            ),
            context_rel_path=os.path.join("adapters", "inesdata", "sources", "AIModelHub", "DataDashboard"),
            restart_deployment_template="{dataspace}-ai-model-hub",
            description="Builds the Level 5 AI Model Hub dashboard image.",
        ),
        LocalImageRecipe(
            key="edc/connector",
            adapter="edc",
            label="Generic EDC connector",
            source_rel_path=os.path.join("adapters", "edc", "sources", "dashboard", "asset-filter-template"),
            image_ref="validation-environment/edc-connector:local",
            script_rel_path=os.path.join("adapters", "edc", "scripts", "build_image.sh"),
            loads_minikube=True,
            description="Builds the benchmark EDC connector and loads the image into Minikube.",
        ),
        LocalImageRecipe(
            key="edc/dashboard",
            adapter="edc",
            label="EDC dashboard",
            source_rel_path=os.path.join("adapters", "edc", "sources", "dashboard"),
            image_ref="validation-environment/edc-dashboard:latest",
            script_rel_path=os.path.join("adapters", "edc", "scripts", "build_dashboard_image.sh"),
            loads_minikube=True,
            description="Uses the EDC dashboard build script and loads the image into Minikube.",
        ),
        LocalImageRecipe(
            key="edc/dashboard-proxy",
            adapter="edc",
            label="EDC dashboard proxy",
            source_rel_path=os.path.join("adapters", "edc", "build", "dashboard-proxy"),
            image_ref="validation-environment/edc-dashboard-proxy:latest",
            script_rel_path=os.path.join("adapters", "edc", "scripts", "build_dashboard_proxy_image.sh"),
            loads_minikube=True,
            description="Builds the local BFF/proxy image used by the EDC dashboard.",
        ),
    ]


def _recipe_abs_path(recipe: LocalImageRecipe, rel_path: str) -> str:
    return os.path.join(project_root(), rel_path)


def _recipe_source_exists(recipe: LocalImageRecipe) -> bool:
    return os.path.isdir(_recipe_abs_path(recipe, recipe.source_rel_path))


def _recipe_script_exists(recipe: LocalImageRecipe) -> bool:
    return bool(recipe.script_rel_path) and os.path.isfile(_recipe_abs_path(recipe, recipe.script_rel_path))


def _recipe_available(recipe: LocalImageRecipe) -> bool:
    return _recipe_source_exists(recipe) or _recipe_script_exists(recipe)


def _recipe_has_changes(recipe: LocalImageRecipe) -> bool:
    source_dir = _recipe_abs_path(recipe, recipe.source_rel_path)
    if not os.path.isdir(source_dir):
        return False

    if not os.path.isdir(os.path.join(source_dir, ".git")):
        return True

    return_code, output = _run_command_capture(["git", "-C", source_dir, "status", "--porcelain", "--", "."])
    if return_code != 0:
        return True
    return bool(output.strip())


def collect_local_image_recipes(active_adapter=None, include_missing=False) -> list[LocalImageRecipe]:
    """Collect registered recipes, optionally filtering by adapter and source presence."""
    normalized_adapter = (active_adapter or "").strip().lower()
    recipes = []
    for recipe in _local_image_recipe_catalog():
        if normalized_adapter and recipe.adapter != normalized_adapter:
            continue
        if include_missing or _recipe_available(recipe):
            recipes.append(recipe)
    return recipes


def _local_image_recipe_rows(recipes: list[LocalImageRecipe]):
    rows = []
    for recipe in recipes:
        source_status = "present" if _recipe_source_exists(recipe) else "missing"
        change_status = "changed" if _recipe_has_changes(recipe) else "clean"
        rows.append(
            [
                recipe.key,
                recipe.adapter,
                source_status,
                change_status if source_status == "present" else "-",
                recipe.image_ref,
                recipe.source_rel_path,
            ]
        )
    return rows


def print_local_image_recipes(active_adapter=None):
    """Print registered local-image recipes for the developer menu."""
    recipes = collect_local_image_recipes(active_adapter=active_adapter, include_missing=True)
    if not recipes:
        print("\nNo local image recipes registered.\n")
        return []

    print("\nRegistered local image recipes:")
    print(
        tabulate(
            _local_image_recipe_rows(recipes),
            headers=["Recipe", "Adapter", "Source", "Changes", "Image", "Source path"],
            tablefmt="github",
        )
    )
    print()
    return recipes


def _minikube_profile_for_local_images(active_adapter: str) -> str:
    env_profile = os.getenv("PIONERA_MINIKUBE_PROFILE") or os.getenv("MINIKUBE_PROFILE")
    if env_profile:
        return env_profile.strip() or "minikube"

    config_path = os.path.join(project_root(), "deployers", active_adapter, "deployer.config")
    config = _read_key_value_config(config_path)
    return (config.get("MINIKUBE_PROFILE") or "minikube").strip() or "minikube"


def _dataspace_context_for_local_images(active_adapter: str) -> dict[str, str]:
    normalized_adapter = (active_adapter or "").strip().lower()
    default_dataspace = "demoedc" if normalized_adapter == "edc" else "demo"
    config_path = os.path.join(project_root(), "deployers", active_adapter, "deployer.config")
    config = _read_key_value_config(config_path)
    dataspace = (
        config.get("DS_1_NAME")
        or config.get("DS_NAME")
        or config.get("DATASPACE_NAME")
        or default_dataspace
    ).strip() or default_dataspace
    namespace = (
        config.get("DS_1_NAMESPACE")
        or config.get("NAMESPACE")
        or dataspace
    ).strip() or dataspace
    return {"dataspace": dataspace, "namespace": namespace}


def _configured_connector_names_for_local_images(active_adapter: str) -> list[str]:
    context = _dataspace_context_for_local_images(active_adapter)
    config_path = os.path.join(project_root(), "deployers", active_adapter, "deployer.config")
    config = _read_key_value_config(config_path)
    raw_connectors = (config.get("DS_1_CONNECTORS") or "").strip()
    if not raw_connectors:
        return []

    dataspace = context["dataspace"]
    connectors = []
    for token in raw_connectors.split(","):
        name = token.strip()
        if not name:
            continue
        if name.startswith("conn-"):
            connector_name = name
        else:
            connector_name = f"conn-{name}-{dataspace}"
        if connector_name not in connectors:
            connectors.append(connector_name)
    return connectors


def _restart_registered_recipe_deployment_if_running(recipe: LocalImageRecipe) -> None:
    if not recipe.restart_deployment_template:
        return

    context = _dataspace_context_for_local_images(recipe.adapter)
    deployment_name = recipe.restart_deployment_template.format(**context)
    namespace = context["namespace"]

    return_code, _ = _run_command_capture(["kubectl", "get", "deployment", deployment_name, "-n", namespace])
    if return_code != 0:
        print(
            f"\nNo running deployment found for {recipe.key} ({deployment_name} in namespace {namespace}). "
            "Run Level 5 after loading the image if this component is not deployed yet.\n"
        )
        return

    print(f"\nRestarting deployment/{deployment_name} in namespace {namespace} to pick up {recipe.image_ref}...")
    if not _run_command_interactive(["kubectl", "rollout", "restart", f"deployment/{deployment_name}", "-n", namespace]):
        print(f"\nWarning: could not restart deployment/{deployment_name}.\n")
        return

    _run_command_interactive(
        [
            "kubectl",
            "rollout",
            "status",
            f"deployment/{deployment_name}",
            "-n",
            namespace,
            "--timeout=10m",
        ]
    )


def _edc_deployments_for_local_image_keys(recipe_keys: list[str]) -> tuple[str, list[str]]:
    context = _dataspace_context_for_local_images("edc")
    namespace = context["namespace"]
    connectors = _configured_connector_names_for_local_images("edc")
    deployments = []
    selected_keys = set(recipe_keys or [])

    for connector in connectors:
        if "edc/connector" in selected_keys:
            deployments.append(connector)
        if "edc/dashboard" in selected_keys:
            deployments.append(f"{connector}-dashboard")
        if "edc/dashboard-proxy" in selected_keys:
            deployments.append(f"{connector}-dashboard-proxy")

    deduplicated = []
    for deployment_name in deployments:
        if deployment_name not in deduplicated:
            deduplicated.append(deployment_name)
    return namespace, deduplicated


def _restart_edc_deployments_for_local_image_keys(recipe_keys: list[str]) -> None:
    namespace, deployments = _edc_deployments_for_local_image_keys(recipe_keys)
    if not deployments:
        print("\nNo EDC connector deployments were resolved. Run Level 4 after loading the images if needed.\n")
        return

    restarted = 0
    for deployment_name in deployments:
        return_code, _ = _run_command_capture(["kubectl", "get", "deployment", deployment_name, "-n", namespace])
        if return_code != 0:
            print(
                f"\nNo running EDC deployment found for {deployment_name} in namespace {namespace}. "
                "Run Level 4 after loading the image if this runtime is not deployed yet.\n"
            )
            continue

        print(f"\nRestarting EDC deployment/{deployment_name} in namespace {namespace} to pick up the local image...")
        if not _run_command_interactive(
            ["kubectl", "rollout", "restart", f"deployment/{deployment_name}", "-n", namespace]
        ):
            print(f"\nWarning: could not restart EDC deployment/{deployment_name}.\n")
            continue

        _run_command_interactive(
            [
                "kubectl",
                "rollout",
                "status",
                f"deployment/{deployment_name}",
                "-n",
                namespace,
                "--timeout=10m",
            ]
        )
        restarted += 1

    if restarted:
        print(f"\nRestarted {restarted} EDC deployment(s) with local images.\n")


def _run_command_interactive(command, cwd=None, env=None) -> bool:
    print(f"\nLaunching: {' '.join(command)}\n")
    result = subprocess.run(command, cwd=cwd or project_root(), env=env)
    return result.returncode == 0


def _shell_script_has_crlf(script_path: str) -> bool:
    try:
        with open(script_path, "rb") as handle:
            return b"\r\n" in handle.read()
    except OSError:
        return False


def _validate_local_shell_script(script_path: str) -> bool:
    if not _shell_script_has_crlf(script_path):
        return True

    rel_path = os.path.relpath(script_path, project_root())
    print(
        "\nLocal workflow script has Windows CRLF line endings and cannot be executed safely in WSL/Linux:"
    )
    print(f"  {rel_path}")
    print("Normalize it to LF, for example: dos2unix " + rel_path + "\n")
    return False


def _execute_registered_local_image_recipe(
    recipe: LocalImageRecipe,
    platform_dir=None,
    *,
    deploy=True,
    preserve_values=True,
) -> bool:
    """Build and load one registered local image recipe."""
    root_dir = project_root()
    minikube_profile = _minikube_profile_for_local_images(recipe.adapter)

    print("\n" + "-" * 50)
    print(f"Local image recipe: {recipe.key}")
    print(f"Source: {recipe.source_rel_path}")
    print(f"Image: {recipe.image_ref}")
    print("-" * 50)

    if recipe.workflow_component:
        resolved_platform_dir = platform_dir
        if not resolved_platform_dir:
            platform_dirs = _detect_platform_dirs_from_adapter_configs()
            resolved_platform_dir = platform_dirs[0] if platform_dirs else os.path.join("deployers", "inesdata")
        context = _dataspace_context_for_local_images(recipe.adapter)
        return _execute_local_images_workflow(
            [
                "--platform-dir",
                resolved_platform_dir,
                "--namespace",
                context["namespace"],
                "--component",
                recipe.workflow_component,
            ],
            deploy=deploy,
            preserve_values=preserve_values,
        )

    if recipe.script_rel_path:
        script_path = os.path.join(root_dir, recipe.script_rel_path)
        if not os.path.isfile(script_path):
            print(f"\nLocal image script not found: {script_path}\n")
            return False
        if not _validate_local_shell_script(script_path):
            return False

        command = ["bash", script_path, "--apply", *recipe.script_args]
        if recipe.key.startswith("edc/"):
            command.extend(["--minikube-profile", minikube_profile])
        if not _run_command_interactive(command, cwd=root_dir):
            print("\nImage build/load failed. Check logs above.\n")
            return False
        if deploy:
            if recipe.key.startswith("edc/"):
                _restart_edc_deployments_for_local_image_keys([recipe.key])
            else:
                _restart_registered_recipe_deployment_if_running(recipe)
        else:
            print("\nRedeploy skipped. Image was built and loaded only.\n")
        print("\nRegistered local image workflow completed successfully.\n")
        return True

    dockerfile_path = os.path.join(root_dir, recipe.dockerfile_rel_path)
    context_path = os.path.join(root_dir, recipe.context_rel_path)
    if not os.path.isfile(dockerfile_path):
        print(f"\nDockerfile not found: {dockerfile_path}\n")
        return False
    if not os.path.isdir(context_path):
        print(f"\nDocker build context not found: {context_path}\n")
        return False

    command = ["docker", "build", "-t", recipe.image_ref]
    for key, value in recipe.build_args:
        command.extend(["--build-arg", f"{key}={value}"])
    command.extend(["-f", dockerfile_path, context_path])

    if not _run_command_interactive(command, cwd=root_dir):
        print("\nImage build failed. Check logs above.\n")
        return False

    if not recipe.loads_minikube:
        load_command = ["minikube", "-p", minikube_profile, "image", "load", recipe.image_ref]
        if not _run_command_interactive(load_command, cwd=root_dir):
            print("\nImage load failed. Check logs above.\n")
            return False

    if deploy:
        _restart_registered_recipe_deployment_if_running(recipe)
    else:
        print("\nRedeploy skipped. Image was built and loaded only.\n")

    print("\nRegistered local image workflow completed successfully.\n")
    return True


def _execute_registered_local_image_recipes(
    recipes: list[LocalImageRecipe],
    platform_dir=None,
    *,
    deploy=True,
    preserve_values=True,
) -> bool:
    if not recipes:
        print("\nNo registered local image recipes selected.\n")
        return False

    ok = True
    for recipe in recipes:
        ok = (
            _execute_registered_local_image_recipe(
                recipe,
                platform_dir=platform_dir,
                deploy=deploy,
                preserve_values=preserve_values,
            )
            and ok
        )
    return ok


def _local_image_recipes_by_key(recipe_keys: list[str], active_adapter: str) -> list[LocalImageRecipe]:
    available = collect_local_image_recipes(active_adapter=active_adapter)
    by_key = {recipe.key: recipe for recipe in available}
    recipes = []
    missing = []
    for key in recipe_keys:
        recipe = by_key.get(key)
        if recipe is None:
            missing.append(key)
        else:
            recipes.append(recipe)

    if missing:
        print(f"\nMissing local image recipe(s): {', '.join(missing)}\n")
    return recipes


def _execute_edc_quick_local_image_workflow(sub_choice: str, platform_dir: str) -> bool:
    quick_recipes = {
        "1": ["edc/connector"],
        "2": ["edc/dashboard", "edc/dashboard-proxy"],
        "3": ["edc/connector", "edc/dashboard", "edc/dashboard-proxy"],
    }
    recipe_keys = quick_recipes.get(sub_choice, [])
    recipes = _local_image_recipes_by_key(recipe_keys, active_adapter="edc")
    if len(recipes) != len(recipe_keys):
        return False
    return _execute_registered_local_image_recipes(
        recipes,
        platform_dir=platform_dir,
        deploy=True,
        preserve_values=True,
    )


def _select_registered_local_image_recipe(recipes: list[LocalImageRecipe]):
    if not recipes:
        print("\nNo registered local image recipes available.\n")
        return None

    print("\nSelect registered image recipe:")
    for index, recipe in enumerate(recipes, start=1):
        changed = "changed" if _recipe_has_changes(recipe) else "clean"
        print(f"{index} - {recipe.key} ({changed}) -> {recipe.image_ref}")
    print("B - Back")

    try:
        choice = input("\nSelection: ").strip().upper()
    except EOFError:
        return None

    if not choice or choice == "B":
        return None

    try:
        index = int(choice) - 1
    except ValueError:
        print("\nInvalid selection.\n")
        return None

    if index < 0 or index >= len(recipes):
        print("\nInvalid selection.\n")
        return None
    return recipes[index]


def _confirm_local_workflow():
    """Ask for confirmation before executing local image workflows."""
    while True:
        try:
            confirm = input("\nConfirm execution? (Y/N, default: Y): ").strip().upper() or "Y"
        except EOFError:
            return False

        if confirm in ("Y", "N"):
            return confirm == "Y"

        print("Please answer Y or N.")


def _execute_local_images_workflow(extra_args, *, deploy=True, preserve_values=False):
    """Execute local build/load/deploy script with --apply and provided args."""
    root_dir = project_root()
    script_path = os.path.join(root_dir, LOCAL_WORKFLOW_SCRIPT_REL_PATH)
    if not os.path.isfile(script_path):
        print(f"\nLocal workflow script not found: {script_path}\n")
        return False
    if not _validate_local_shell_script(script_path):
        return False

    workflow_args = list(extra_args or [])
    if preserve_values and "--preserve-values" not in workflow_args and "--preserve-data" not in workflow_args:
        workflow_args.append("--preserve-values")
    if not deploy and "--skip-deploy" not in workflow_args and "--build-only" not in workflow_args:
        workflow_args.append("--skip-deploy")

    command = ["bash", script_path, "--apply", *workflow_args]

    print(f"\nLaunching local workflow: {' '.join(command)}\n")
    result = subprocess.run(command, cwd=root_dir)

    if result.returncode == 0:
        print("\nWorkflow completed successfully.\n")
        return True

    print("\nWorkflow failed. Check logs above.\n")
    return False


def run_local_images_workflow_interactive(active_adapter="inesdata"):
    """Build and deploy local images with developer-oriented sub-options."""
    platform_dirs = _detect_platform_dirs_from_adapter_configs()

    if not platform_dirs:
        print("\nNo platform dir detected from adapter REPO_DIR values.\n")
        return None

    platform_dir = platform_dirs[0]
    active_adapter = (active_adapter or "inesdata").strip().lower() or "inesdata"

    while True:
        print("\n" + "=" * 50)
        print("BUILD & DEPLOY LOCAL IMAGES")
        print("=" * 50)
        print(f"Active adapter: {active_adapter}")
        print()
        print("[Quick actions]")
        if active_adapter == "edc":
            print("Builds/loads EDC images. Running EDC deployments are restarted; data is preserved.")
            print("1 - EDC connector")
            print("2 - EDC dashboard")
            print("3 - EDC connector + dashboard")
        else:
            print("Data is preserved. Existing Helm values are reused.")
            print("1 - All local images")
            print("2 - Connectors")
            print("3 - Connector interface")
        print()
        print("[Advanced recipes]")
        print("4 - Changed recipes")
        print("5 - All recipes")
        print("6 - Pick recipe and redeploy")
        print("7 - Pick recipe, build/load only")
        print("8 - Show recipes")
        print("B - Back")

        try:
            sub_choice = input("\nSelection: ").strip().upper()
        except EOFError:
            print("\nNo input. Returning to main menu.\n")
            return None

        if sub_choice == "B":
            return None
        if sub_choice not in {"1", "2", "3", "4", "5", "6", "7", "8"}:
            print("\nInvalid selection. Please try again.\n")
            continue

        if sub_choice == "8":
            print_local_image_recipes(active_adapter=active_adapter)
            continue

        if sub_choice in {"4", "5", "6", "7"}:
            recipes = collect_local_image_recipes(active_adapter=active_adapter)
            if sub_choice == "4":
                recipes = [recipe for recipe in recipes if _recipe_has_changes(recipe)]
                if not recipes:
                    print(f"\nNo changed registered images detected for adapter '{active_adapter}'.\n")
                    return None
            elif sub_choice in {"6", "7"}:
                recipe = _select_registered_local_image_recipe(recipes)
                if recipe is None:
                    return None
                recipes = [recipe]
            deploy = sub_choice != "7"

            if not _confirm_local_workflow():
                print("\nExecution cancelled.\n")
                return None

            _execute_registered_local_image_recipes(
                recipes,
                platform_dir=platform_dir,
                deploy=deploy,
                preserve_values=True,
            )
            return None

        if not _confirm_local_workflow():
            print("\nExecution cancelled.\n")
            return None

        if active_adapter == "edc":
            _execute_edc_quick_local_image_workflow(sub_choice, platform_dir=platform_dir)
            return None

        context = _dataspace_context_for_local_images("inesdata")
        extra_args = [
            "--platform-dir",
            platform_dir,
            "--namespace",
            context["namespace"],
        ]
        if sub_choice == "2":
            extra_args += ["--component", "connector"]
        elif sub_choice == "3":
            extra_args += ["--component", "connector-interface"]

        _execute_local_images_workflow(extra_args, deploy=True, preserve_values=True)
        return None


def _is_connector_runtime_name(name):
    return (
        str(name or "").startswith("conn-")
        and "interface" not in str(name or "")
        and "inteface" not in str(name or "")
    )


def _get_connector_runtime_deployments(adapter):
    """Detect connector runtime deployments even when their pods are unhealthy."""
    namespace = adapter.config.namespace_demo()
    output = adapter.run(
        f"kubectl get deployments -n {namespace} --no-headers",
        capture=True,
    )

    if not output:
        return []

    deployments = set()
    for line in output.splitlines():
        parts = line.split()
        if not parts:
            continue

        name = parts[0]
        if _is_connector_runtime_name(name):
            deployments.add(name)

    return sorted(deployments)


def _connector_hosts_resolve(adapter, connectors):
    unresolved = []
    domain_getter = getattr(adapter.config_adapter, "ds_domain_base", None)
    domain = domain_getter() if callable(domain_getter) else ""
    if not domain:
        return unresolved

    for connector in connectors or []:
        host = f"{connector}.{domain}"
        try:
            socket.gethostbyname(host)
        except OSError:
            unresolved.append(host)

    return unresolved


def _ensure_connector_hosts(adapter, connectors):
    connector_hosts = adapter.config_adapter.generate_connector_hosts(connectors)
    if connector_hosts:
        adapter.infrastructure.manage_hosts_entries(
            connector_hosts,
            header_comment="# Dataspace Connector Hosts",
        )

    unresolved = _connector_hosts_resolve(adapter, connectors)
    if unresolved:
        joined = ", ".join(unresolved)
        raise RuntimeError(
            "Connector hostnames do not resolve locally. "
            f"Check /etc/hosts and minikube tunnel for: {joined}"
        )


def _default_inesdata_adapter():
    from adapters.inesdata.adapter import InesdataAdapter

    return InesdataAdapter(auto_mode_getter=lambda: False)


def run_connector_recovery_after_wsl_restart(adapter=None):
    """Recover Vault-backed connector runtimes after a local WSL restart."""
    adapter = adapter or _default_inesdata_adapter()
    namespace = adapter.config.namespace_demo()
    namespace_q = shlex.quote(namespace)

    print("\n" + "=" * 50)
    print("CONNECTOR RECOVERY AFTER WSL RESTART")
    print("=" * 50)
    print("\nThis flow will:")
    print("- wait for the Vault pod")
    print("- unseal Vault if needed")
    print("- refresh connector host entries")
    print("- restart connector deployments")
    print("- wait until deployments are ready again\n")

    timeout = max(getattr(adapter.config, "TIMEOUT_NAMESPACE", 90), 180)
    common_namespace = getattr(adapter.config, "NS_COMMON", "common-srvs")
    if not adapter.infrastructure.wait_for_vault_pod(common_namespace, timeout=timeout):
        print("Vault pod not detected. Recovery aborted.\n")
        return False

    if not adapter.infrastructure.ensure_vault_unsealed():
        print("Vault is sealed or unavailable. Recovery aborted.\n")
        return False

    connectors = adapter.get_cluster_connectors() or _get_connector_runtime_deployments(adapter)
    if not connectors:
        print(f"No connector runtime deployments detected in namespace '{namespace}'.\n")
        return False

    print("Connector runtimes detected:")
    print("- " + "\n- ".join(connectors))
    print()

    hosts_ready = True
    try:
        _ensure_connector_hosts(adapter, connectors)
    except Exception as exc:
        hosts_ready = False
        print(f"Warning: connector host refresh failed ({exc})")
        print("Continuing with deployment recovery and skipping HTTP validation.\n")

    for connector in connectors:
        deployment_q = shlex.quote(connector)
        if adapter.run(
            f"kubectl rollout restart deployment/{deployment_q} -n {namespace_q}",
            check=False,
        ) is None:
            print(f"Could not restart connector deployment: {connector}\n")
            return False

    for connector in connectors:
        deployment_q = shlex.quote(connector)
        if adapter.run(
            f"kubectl rollout status deployment/{deployment_q} -n {namespace_q} --timeout=180s",
            check=False,
        ) is None:
            print(f"Connector deployment did not become ready in time: {connector}\n")
            return False

    if not hosts_ready:
        print("Connector recovery completed, but local hostname validation was skipped.\n")
        return True

    if not adapter.connectors.validate_connectors_deployment(connectors):
        print("Connector recovery completed with validation errors.\n")
        return False

    print("Connector recovery completed successfully.\n")
    return True
