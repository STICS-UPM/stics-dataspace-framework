#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

TARGET_DIR="$ADAPTER_DIR/sources/connector"
CACHE_DIR="$ADAPTER_DIR/sources/dashboard"
DEFAULT_GIT_URL="https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard"
DEFAULT_SOURCE_SUBDIR="asset-filter-template"

APPLY=0
SOURCE_REPO=""
GIT_URL="$DEFAULT_GIT_URL"
SOURCE_SUBDIR="${PIONERA_EDC_REFERENCE_REPO_SUBDIR:-$DEFAULT_SOURCE_SUBDIR}"

usage() {
  cat <<'EOF'
Usage: sync_sources.sh [--apply] [--source <path>] [--git-url <url>] [--source-subdir <path>]

Synchronize the local EDC connector source used by adapters/edc.

Options:
  --apply           Execute the synchronization. Default is dry-run.
  --source <path>   Use a local source directory instead of GitHub.
  --git-url <url>   Override the Git upstream URL used when cloning/updating.
  --source-subdir <path>
                    Connector subdirectory inside the upstream repository when
                    --source or --git-url points to the dashboard repository root.
  -h, --help        Show this help message.
EOF
}

run_cmd() {
  local cmd="$1"
  echo "+ $cmd"
  if [[ "$APPLY" -eq 1 ]]; then
    bash -lc "$cmd"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --source)
      SOURCE_REPO="${2:-}"
      shift 2
      ;;
    --git-url)
      GIT_URL="${2:-}"
      shift 2
      ;;
    --source-subdir|--sync-subdir)
      SOURCE_SUBDIR="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

mkdir -p "$(dirname "$TARGET_DIR")"

echo "EDC adapter dir: $ADAPTER_DIR"
echo "Target dir:      $TARGET_DIR"
echo "Source subdir:   $SOURCE_SUBDIR"
if [[ -n "$SOURCE_REPO" ]]; then
  echo "Source repo:     $SOURCE_REPO"
else
  echo "Git upstream:    $GIT_URL"
  echo "Git cache:       $CACHE_DIR"
fi

validate_connector_root() {
  local root_dir="$1"
  if [[ ! -f "$root_dir/settings.gradle.kts" || ! -f "$root_dir/gradlew" ]]; then
    echo "Connector source not found in expected directory: $root_dir" >&2
    exit 1
  fi
}

resolve_connector_source() {
  local root_dir="$1"
  if [[ -f "$root_dir/settings.gradle.kts" && -f "$root_dir/gradlew" ]]; then
    printf '%s\n' "$root_dir"
    return 0
  fi
  if [[ -f "$root_dir/$SOURCE_SUBDIR/settings.gradle.kts" && -f "$root_dir/$SOURCE_SUBDIR/gradlew" ]]; then
    printf '%s\n' "$root_dir/$SOURCE_SUBDIR"
    return 0
  fi
  echo "Connector source not found in $root_dir or $root_dir/$SOURCE_SUBDIR" >&2
  exit 1
}

copy_connector_source() {
  local copy_source="$1"
  if [[ -z "$copy_source" || ! -d "$copy_source" ]]; then
    echo "Connector source not found: $copy_source" >&2
    exit 1
  fi

  if command -v rsync >/dev/null 2>&1; then
    run_cmd "mkdir -p \"$TARGET_DIR\""
    run_cmd "rsync -a --delete --exclude .git --exclude .gradle --exclude .gradle-user-home --exclude build --exclude logs --exclude __pycache__ \"$copy_source\"/ \"$TARGET_DIR\"/"
  else
    run_cmd "rm -rf \"$TARGET_DIR\""
    run_cmd "mkdir -p \"$TARGET_DIR\""
    run_cmd "cp -a \"$copy_source\"/. \"$TARGET_DIR\"/"
    run_cmd "rm -rf \"$TARGET_DIR/.git\" \"$TARGET_DIR/.gradle\" \"$TARGET_DIR/.gradle-user-home\" \"$TARGET_DIR/build\" \"$TARGET_DIR/logs\""
    run_cmd "find \"$TARGET_DIR\" -type d \\( -name build -o -name __pycache__ \\) -prune -exec rm -rf {} +"
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    validate_connector_root "$TARGET_DIR"
  fi

  echo "Source synchronization complete."
}

sync_from_local_source() {
  if [[ -z "$SOURCE_REPO" || ! -d "$SOURCE_REPO" ]]; then
    echo "Source repository not found: $SOURCE_REPO" >&2
    exit 1
  fi

  local copy_source
  copy_source="$(resolve_connector_source "$SOURCE_REPO")"
  copy_connector_source "$copy_source"
}

sync_from_git_upstream() {
  if [[ -d "$CACHE_DIR/.git" ]]; then
    run_cmd "git -C \"$CACHE_DIR\" remote set-url origin \"$GIT_URL\""
    run_cmd "git -C \"$CACHE_DIR\" fetch --all --tags"
    run_cmd "git -C \"$CACHE_DIR\" pull --ff-only"
  else
    run_cmd "rm -rf \"$CACHE_DIR\""
    run_cmd "git clone \"$GIT_URL\" \"$CACHE_DIR\""
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    local copy_source
    copy_source="$(resolve_connector_source "$CACHE_DIR")"
    copy_connector_source "$copy_source"
  fi

  echo "Git synchronization complete."
}

if [[ -n "$SOURCE_REPO" ]]; then
  sync_from_local_source
else
  sync_from_git_upstream
fi

if [[ -f "$TARGET_DIR/gradlew" ]]; then
  run_cmd "chmod +x \"$TARGET_DIR/gradlew\""
fi
