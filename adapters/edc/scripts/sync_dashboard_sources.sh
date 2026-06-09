#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCES_DIR="$ADAPTER_DIR/sources"
TARGET_DIR="$SOURCES_DIR/dashboard"
DEFAULT_REPO_URL="https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard"
DEFAULT_REPO_REF="a4cb3e659e1fd3abfa9516a036c261b19432ec13"

APPLY=false
SOURCE_URL="$DEFAULT_REPO_URL"
SOURCE_REF="${PIONERA_EDC_DASHBOARD_REPO_REF:-${EDC_DASHBOARD_REPO_REF:-$DEFAULT_REPO_REF}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --source)
      SOURCE_URL="${2:?Missing value for --source}"
      shift 2
      ;;
    --ref|--revision|--commit)
      SOURCE_REF="${2:?Missing value for $1}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$SOURCES_DIR"

if [[ "$APPLY" != true ]]; then
  echo "Dashboard source sync preview"
  echo "  source: $SOURCE_URL"
  echo "  ref:    $SOURCE_REF"
  echo "  target: $TARGET_DIR"
  exit 0
fi

if [[ -d "$TARGET_DIR/.git" ]] && [[ "$(git -C "$TARGET_DIR" rev-parse --show-toplevel 2>/dev/null || true)" == "$(cd "$TARGET_DIR" && pwd)" ]]; then
  git -C "$TARGET_DIR" remote set-url origin "$SOURCE_URL"
  git -C "$TARGET_DIR" fetch origin
else
  if [[ -e "$TARGET_DIR" ]]; then
    if find "$TARGET_DIR" -mindepth 1 -maxdepth 1 | grep -q .; then
      echo "Dashboard source target exists but is not a Git working tree: $TARGET_DIR" >&2
      echo "Move it before synchronizing the official dashboard source." >&2
      exit 1
    fi
    rmdir "$TARGET_DIR"
  fi
  git clone "$SOURCE_URL" "$TARGET_DIR"
fi

if [[ -n "$SOURCE_REF" ]]; then
  current_head="$(git -C "$TARGET_DIR" rev-parse HEAD 2>/dev/null || true)"
  requested_head="$(git -C "$TARGET_DIR" rev-parse --verify "$SOURCE_REF^{commit}" 2>/dev/null || true)"
  if [[ -n "$current_head" && -n "$requested_head" && "$current_head" == "$requested_head" ]]; then
    echo "Dashboard sources already at requested ref $SOURCE_REF; keeping local changes."
  else
    if ! git -C "$TARGET_DIR" diff --quiet || ! git -C "$TARGET_DIR" diff --cached --quiet; then
      echo "Dashboard source tree has local changes. Refusing to checkout $SOURCE_REF." >&2
      echo "Clean or move adapters/edc/sources/dashboard before synchronizing." >&2
      exit 1
    fi
    git -C "$TARGET_DIR" checkout --detach "$SOURCE_REF"
  fi
else
  current_branch="$(git -C "$TARGET_DIR" rev-parse --abbrev-ref HEAD)"
  git -C "$TARGET_DIR" pull --ff-only origin "$current_branch"
fi

echo "Dashboard sources ready at $TARGET_DIR"
