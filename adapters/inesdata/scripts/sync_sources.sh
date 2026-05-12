#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCES_DIR="$ADAPTER_DIR/sources"
DRY_RUN=1
ONLY_REPO=""

usage() {
  cat <<'EOF'
Usage: sync_sources.sh [--apply] [--repo <name>]

Options:
  --apply        Execute clone/pull actions (default is dry-run).
  --repo <name>  Restrict sync to one repository key.

Repository keys:
  connector
  connector-interface
  registration-service
  public-portal-backend
  public-portal-frontend
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      DRY_RUN=0
      shift
      ;;
    --repo)
      ONLY_REPO="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

mkdir -p "$SOURCES_DIR"

declare -A REPOS=(
  ["connector"]="https://github.com/INESData/inesdata-connector.git"
  ["connector-interface"]="https://github.com/INESData/inesdata-connector-interface.git"
  ["registration-service"]="https://github.com/INESData/inesdata-registration-service.git"
  ["public-portal-backend"]="https://github.com/INESData/inesdata-public-portal-backend.git"
  ["public-portal-frontend"]="https://github.com/INESData/inesdata-public-portal-frontend.git"
)

declare -A BRANCHES=(
  ["connector"]="develop"
  ["connector-interface"]="develop"
  ["registration-service"]="develop"
  ["public-portal-backend"]="develop"
  ["public-portal-frontend"]="develop"
)

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] $*"
  else
    eval "$@"
  fi
}

echo "Sources directory: $SOURCES_DIR"
echo "Mode: $([[ "$DRY_RUN" -eq 1 ]] && echo "dry-run" || echo "apply")"

for key in connector connector-interface registration-service public-portal-backend public-portal-frontend; do
  if [[ -n "$ONLY_REPO" && "$ONLY_REPO" != "$key" ]]; then
    continue
  fi

  repo_url="${REPOS[$key]}"
  branch="${BRANCHES[$key]}"
  target_dir="$SOURCES_DIR/inesdata-$key"

  echo
  echo "== $key =="

  if [[ ! -d "$target_dir/.git" ]]; then
    run_cmd "git clone --branch $branch $repo_url $target_dir"
    continue
  fi

  run_cmd "git -C $target_dir fetch origin"
  run_cmd "git -C $target_dir checkout $branch"
  run_cmd "git -C $target_dir pull --ff-only origin $branch"
done
