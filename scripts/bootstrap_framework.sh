#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_VENV_DIR="$ROOT_DIR/.venv"
ROOT_PYTHON_BIN="$ROOT_VENV_DIR/bin/python"
ROOT_REQUIREMENTS="$ROOT_DIR/requirements.txt"
ROOT_PACKAGE_JSON="$ROOT_DIR/package.json"
UI_DIR="$ROOT_DIR/validation/ui"
UI_PACKAGE_JSON="$UI_DIR/package.json"
INFRASTRUCTURE_CONFIG_DIR="$ROOT_DIR/deployers/infrastructure"
INFRASTRUCTURE_CONFIG="$INFRASTRUCTURE_CONFIG_DIR/deployer.config"
INFRASTRUCTURE_CONFIG_EXAMPLE="$INFRASTRUCTURE_CONFIG_DIR/deployer.config.example"
INESDATA_CONFIG_DIR="$ROOT_DIR/deployers/inesdata"
INESDATA_CONFIG="$INESDATA_CONFIG_DIR/deployer.config"
INESDATA_CONFIG_EXAMPLE="$INESDATA_CONFIG_DIR/deployer.config.example"
EDC_CONFIG_DIR="$ROOT_DIR/deployers/edc"
EDC_CONFIG="$EDC_CONFIG_DIR/deployer.config"
EDC_CONFIG_EXAMPLE="$EDC_CONFIG_DIR/deployer.config.example"

PLAYWRIGHT_SYSTEM_DEPS_MODE=auto
SKIP_PLAYWRIGHT=false
SKIP_ROOT_NODE=false
SKIP_UI_NODE=false
SKIP_DEPLOYER_CONFIG_INIT=false
MIN_PYTHON_VERSION="3.10"
MIN_NODE_MAJOR_VERSION="18"
MIN_JAVA_MAJOR_VERSION="17"

log() {
  printf '[bootstrap] %s\n' "$*"
}

fail() {
  printf '[bootstrap] ERROR: %s\n' "$*" >&2
  exit 1
}

python_version_string() {
  local python_bin="$1"
  "$python_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'
}

python_supports_framework() {
  local python_bin="$1"
  "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

node_version_string() {
  node --version 2>/dev/null || printf 'not found\n'
}

node_supports_framework() {
  command -v node >/dev/null 2>&1 || return 1
  node -e "const major = Number(process.versions.node.split('.')[0]); process.exit(major >= $MIN_NODE_MAJOR_VERSION ? 0 : 1)" >/dev/null 2>&1
}

node_install_hint() {
  case "$(uname -s)" in
    Linux)
      printf "Install Node.js %s+ with npm before rerunning bootstrap. On Ubuntu VM: sudo apt-get update && sudo apt-get install -y nodejs npm" "$MIN_NODE_MAJOR_VERSION"
      ;;
    Darwin)
      printf "Install Node.js %s+ with npm before rerunning bootstrap. On macOS: brew install node" "$MIN_NODE_MAJOR_VERSION"
      ;;
    *)
      printf "Install Node.js %s+ with npm before rerunning bootstrap." "$MIN_NODE_MAJOR_VERSION"
      ;;
  esac
}

java_version_string() {
  local line
  if IFS= read -r line < <(java -version 2>&1); then
    printf '%s\n' "$line"
  else
    printf 'not found\n'
  fi
}

java_major_version() {
  local line version major
  while IFS= read -r line; do
    if [[ "$line" =~ version[[:space:]]+\"([^\"]+)\" || "$line" =~ version[[:space:]]+([^[:space:]]+) ]]; then
      version="${BASH_REMATCH[1]}"
      if [[ "$version" =~ ^1\.([0-9]+) ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
        return 0
      fi
      major="${version%%.*}"
      printf '%s\n' "$major"
      return 0
    fi
  done < <(java -version 2>&1)
  return 1
}

java_supports_framework() {
  command -v java >/dev/null 2>&1 || return 1
  local major
  major="$(java_major_version)"
  [[ "$major" =~ ^[0-9]+$ ]] || return 1
  [[ "$major" -ge "$MIN_JAVA_MAJOR_VERSION" ]]
}

java_install_hint() {
  case "$(uname -s)" in
    Linux)
      printf "Install Java %s+ before running connector image builds. On Ubuntu VM: sudo apt-get update && sudo apt-get install -y openjdk-%s-jdk" "$MIN_JAVA_MAJOR_VERSION" "$MIN_JAVA_MAJOR_VERSION"
      ;;
    Darwin)
      printf "Install Java %s+ before running connector image builds. On macOS: brew install openjdk@%s" "$MIN_JAVA_MAJOR_VERSION" "$MIN_JAVA_MAJOR_VERSION"
      ;;
    *)
      printf "Install Java %s+ before running connector image builds." "$MIN_JAVA_MAJOR_VERSION"
      ;;
  esac
}

can_install_ubuntu_system_deps() {
  [[ "$(uname -s)" == "Linux" ]] || return 1
  [[ "$PLAYWRIGHT_SYSTEM_DEPS_MODE" != "without" ]] || return 1
  command -v apt-get >/dev/null 2>&1 || return 1
}

run_with_sudo_if_needed() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
    return
  fi
  command -v sudo >/dev/null 2>&1 || fail "sudo is required to install missing system dependencies."
  sudo "$@"
}

install_node_system_deps_if_possible() {
  can_install_ubuntu_system_deps || return 1

  log "Node.js/npm tooling is missing or too old; installing Ubuntu packages"
  run_with_sudo_if_needed apt-get update
  run_with_sudo_if_needed apt-get install -y nodejs npm
}

install_java_system_deps_if_possible() {
  can_install_ubuntu_system_deps || return 1

  log "Java $MIN_JAVA_MAJOR_VERSION+ tooling is missing or too old; installing Ubuntu packages"
  run_with_sudo_if_needed apt-get update
  run_with_sudo_if_needed apt-get install -y "openjdk-$MIN_JAVA_MAJOR_VERSION-jdk"
}

require_node_tooling() {
  local needs_npm=false
  local needs_npx=false

  if [[ "$SKIP_ROOT_NODE" == false || "$SKIP_UI_NODE" == false ]]; then
    needs_npm=true
  fi
  if [[ "$SKIP_PLAYWRIGHT" == false ]]; then
    needs_npx=true
  fi
  if [[ "$needs_npm" == false && "$needs_npx" == false ]]; then
    return 0
  fi

  if ! command -v node >/dev/null 2>&1 || ! node_supports_framework || ! command -v npm >/dev/null 2>&1 || { [[ "$needs_npx" == true ]] && ! command -v npx >/dev/null 2>&1; }; then
    install_node_system_deps_if_possible || true
  fi

  command -v node >/dev/null 2>&1 || fail "Node.js $MIN_NODE_MAJOR_VERSION+ is required for Newman/Playwright validation. $(node_install_hint)"
  node_supports_framework || fail "Node.js $MIN_NODE_MAJOR_VERSION+ is required for Newman/Playwright validation. Current version: $(node_version_string). $(node_install_hint)"

  if [[ "$needs_npm" == true ]]; then
    command -v npm >/dev/null 2>&1 || fail "npm is required for Newman/Playwright validation. $(node_install_hint)"
  fi
  if [[ "$needs_npx" == true ]]; then
    command -v npx >/dev/null 2>&1 || fail "npx is required for Playwright browser installation. $(node_install_hint)"
  fi
}

require_java_tooling() {
  if ! java_supports_framework; then
    install_java_system_deps_if_possible || true
  fi

  command -v java >/dev/null 2>&1 || fail "Java $MIN_JAVA_MAJOR_VERSION+ is required for local connector image builds. $(java_install_hint)"
  java_supports_framework || fail "Java $MIN_JAVA_MAJOR_VERSION+ is required for local connector image builds. Current version: $(java_version_string). $(java_install_hint)"
}

find_bootstrap_python() {
  local requested_python_bin="${PIONERA_PYTHON_BIN:-}"
  local candidate=""

  if [[ -n "$requested_python_bin" ]]; then
    command -v "$requested_python_bin" >/dev/null 2>&1 || fail "PIONERA_PYTHON_BIN points to a command that was not found: $requested_python_bin"
    python_supports_framework "$requested_python_bin" || fail "PIONERA_PYTHON_BIN=$requested_python_bin uses Python $(python_version_string "$requested_python_bin"), but the framework requires Python $MIN_PYTHON_VERSION+"
    printf '%s\n' "$requested_python_bin"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1 && python_supports_framework python3; then
    printf 'python3\n'
    return 0
  fi

  for candidate in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1 && python_supports_framework "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  if command -v python3 >/dev/null 2>&1; then
    fail "Python $MIN_PYTHON_VERSION+ is required. The current python3 is $(python_version_string python3). On macOS, install a newer interpreter (for example 'brew install python@3.11') and rerun with PIONERA_PYTHON_BIN=python3.11 bash scripts/bootstrap_framework.sh"
  fi

  fail "Python $MIN_PYTHON_VERSION+ is required. Install Python 3.10 or newer and rerun the bootstrap. On macOS, for example: brew install python@3.11"
}

usage() {
  cat <<'EOF'
Usage: bash scripts/bootstrap_framework.sh [options]

Prepare the local framework workspace from a fresh machine checkout.

Options:
  --with-system-deps        Force 'npx playwright install --with-deps'
  --without-system-deps     Do not install Playwright system dependencies
  --skip-playwright         Skip Playwright browser installation
  --skip-root-node          Skip 'npm install' in the repo root
  --skip-ui-node            Skip 'npm install' in validation/ui
  --skip-deployer-config    Do not create deployer.config files from the example files
  -h, --help                Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-system-deps)
      PLAYWRIGHT_SYSTEM_DEPS_MODE=with
      shift
      ;;
    --without-system-deps)
      PLAYWRIGHT_SYSTEM_DEPS_MODE=without
      shift
      ;;
    --skip-playwright)
      SKIP_PLAYWRIGHT=true
      shift
      ;;
    --skip-root-node)
      SKIP_ROOT_NODE=true
      shift
      ;;
    --skip-ui-node)
      SKIP_UI_NODE=true
      shift
      ;;
    --skip-deployer-config)
      SKIP_DEPLOYER_CONFIG_INIT=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

require_node_tooling
require_java_tooling

should_install_playwright_system_deps() {
  case "$PLAYWRIGHT_SYSTEM_DEPS_MODE" in
    with)
      return 0
      ;;
    without)
      return 1
      ;;
  esac

  # Fresh Linux/WSL machines usually need Chromium/WebKit runtime libraries.
  # Playwright handles distro-specific packages through --with-deps.
  [[ "$(uname -s)" == "Linux" ]]
}

BOOTSTRAP_PYTHON_BIN="$(find_bootstrap_python)"
log "Using Python interpreter: $BOOTSTRAP_PYTHON_BIN ($(python_version_string "$BOOTSTRAP_PYTHON_BIN"))"

if [[ ! -d "$ROOT_VENV_DIR" ]]; then
  log "Creating root virtual environment at $ROOT_VENV_DIR"
  "$BOOTSTRAP_PYTHON_BIN" -m venv "$ROOT_VENV_DIR"
else
  log "Reusing existing root virtual environment at $ROOT_VENV_DIR"
fi

[[ -x "$ROOT_PYTHON_BIN" ]] || fail "Virtual environment python not found: $ROOT_PYTHON_BIN"
python_supports_framework "$ROOT_PYTHON_BIN" || fail "The existing virtual environment uses Python $(python_version_string "$ROOT_PYTHON_BIN"), but the framework requires Python $MIN_PYTHON_VERSION+. Remove .venv and rerun bootstrap with a supported interpreter."
[[ -f "$ROOT_REQUIREMENTS" ]] || fail "Missing requirements file: $ROOT_REQUIREMENTS"

log "Upgrading pip in the root virtual environment"
"$ROOT_PYTHON_BIN" -m pip install --upgrade pip

log "Installing Python requirements from $ROOT_REQUIREMENTS"
"$ROOT_PYTHON_BIN" -m pip install -r "$ROOT_REQUIREMENTS"

if [[ "$SKIP_ROOT_NODE" == false ]]; then
  [[ -f "$ROOT_PACKAGE_JSON" ]] || fail "Missing root package.json: $ROOT_PACKAGE_JSON"
  log "Installing root Node.js tooling (Newman)"
  (
    cd "$ROOT_DIR"
    npm install
  )
else
  log "Skipping root npm install"
fi

if [[ "$SKIP_UI_NODE" == false ]]; then
  [[ -f "$UI_PACKAGE_JSON" ]] || fail "Missing validation/ui package.json: $UI_PACKAGE_JSON"
  log "Installing validation/ui Node.js tooling (Playwright)"
  (
    cd "$UI_DIR"
    npm install
  )
else
  log "Skipping validation/ui npm install"
fi

if [[ "$SKIP_PLAYWRIGHT" == false ]]; then
  log "Installing Playwright browsers"
  (
    cd "$UI_DIR"
    if should_install_playwright_system_deps; then
      log "Installing Playwright browsers with system dependencies"
      npx playwright install --with-deps
    else
      log "Installing Playwright browsers without system dependencies"
      npx playwright install
    fi
  )
else
  log "Skipping Playwright browser installation"
fi

if [[ "$SKIP_DEPLOYER_CONFIG_INIT" == false ]]; then
  for config_pair in \
    "$INFRASTRUCTURE_CONFIG_DIR|$INFRASTRUCTURE_CONFIG|$INFRASTRUCTURE_CONFIG_EXAMPLE|deployers/infrastructure/deployer.config|deployers/infrastructure/deployer.config.example" \
    "$INESDATA_CONFIG_DIR|$INESDATA_CONFIG|$INESDATA_CONFIG_EXAMPLE|deployers/inesdata/deployer.config|deployers/inesdata/deployer.config.example" \
    "$EDC_CONFIG_DIR|$EDC_CONFIG|$EDC_CONFIG_EXAMPLE|deployers/edc/deployer.config|deployers/edc/deployer.config.example"
  do
    IFS='|' read -r config_dir config_path example_path label example_label <<<"$config_pair"
    mkdir -p "$config_dir"
    if [[ ! -f "$config_path" && -f "$example_path" ]]; then
      log "Creating $label from $example_label"
      cp "$example_path" "$config_path"
    elif [[ -f "$config_path" ]]; then
      log "Reusing existing $label"
    else
      log "$example_label not found; skipping $label initialization"
    fi
  done
else
  log "Skipping deployer.config initialization"
fi

log "Bootstrap completed"
log "Next steps:"
log "  1. Activate the root environment: source .venv/bin/activate"
log "  2. Review deployers/infrastructure/deployer.config, deployers/inesdata/deployer.config and deployers/edc/deployer.config if needed"
log "  3. Run: python3 main.py menu"
