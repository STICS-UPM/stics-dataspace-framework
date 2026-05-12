#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFESTS_DIR="${MANIFESTS_DIR:-/tmp/inesdata-manifests}"
DRY_RUN=1
MANIFEST_FILE=""

usage() {
  cat <<'EOF'
Usage: push_images.sh [--apply] [--manifest <path>]

Options:
  --apply            Execute docker push (default is dry-run).
  --manifest <path>  Use specific manifest file. If omitted, latest is used.

Environment variables:
  MANIFESTS_DIR (default: /tmp/inesdata-manifests)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      DRY_RUN=0
      shift
      ;;
    --manifest)
      MANIFEST_FILE="${2:-}"
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

if [[ -z "$MANIFEST_FILE" ]]; then
  MANIFEST_FILE="$(ls -1t "$MANIFESTS_DIR"/images-*.tsv 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "$MANIFEST_FILE" || ! -f "$MANIFEST_FILE" ]]; then
  echo "No manifest file found. Run build_images.sh first."
  exit 1
fi

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] $*"
  else
    eval "$@"
  fi
}

echo "Manifest: $MANIFEST_FILE"
echo "Mode: $([[ "$DRY_RUN" -eq 1 ]] && echo "dry-run" || echo "apply")"

tail -n +2 "$MANIFEST_FILE" | while IFS=$'\t' read -r component repo_dir image tag full_image build_cmd; do
  echo
  echo "== $component =="
  run_cmd "docker push $full_image"
done
