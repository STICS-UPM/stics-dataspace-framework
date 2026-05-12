#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCES_DIR="$ADAPTER_DIR/sources"
TARGET_DIR="$SOURCES_DIR/dashboard"
DEFAULT_REPO_URL="https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard"

APPLY=false
SOURCE_URL="$DEFAULT_REPO_URL"

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
  echo "  target: $TARGET_DIR"
  exit 0
fi

if [[ -d "$TARGET_DIR/.git" ]]; then
  git -C "$TARGET_DIR" remote set-url origin "$SOURCE_URL"
  git -C "$TARGET_DIR" fetch origin
  current_branch="$(git -C "$TARGET_DIR" rev-parse --abbrev-ref HEAD)"
  git -C "$TARGET_DIR" pull --ff-only origin "$current_branch"
else
  rm -rf "$TARGET_DIR"
  git clone "$SOURCE_URL" "$TARGET_DIR"
fi

echo "Dashboard sources ready at $TARGET_DIR"
