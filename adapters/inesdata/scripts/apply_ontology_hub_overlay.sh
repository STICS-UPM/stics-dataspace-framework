#!/usr/bin/env bash
# Applies the STICS-specific overlay (branding config, funding footer) onto
# the synced Ontology-Hub source, so these customizations survive a fresh
# `git clone`/re-sync from the upstream ProyectoPIONERA/Ontology-Hub repo.
#
# Mirrors the pattern used in adapters/edc/scripts/apply_overlays.sh for the
# EDC dashboard, scoped to Ontology-Hub.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OVERLAY_DIR="$ADAPTER_DIR/overlays/ontology-hub"
SOURCE_DIR="$ADAPTER_DIR/sources/Ontology-Hub"

APPLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --source-dir)
      SOURCE_DIR="${2:?Missing value for --source-dir}"
      shift 2
      ;;
    -h|--help)
      echo "Usage: apply_ontology_hub_overlay.sh [--apply] [--source-dir <path>]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "Ontology-Hub source not found: $SOURCE_DIR" >&2
  echo "Clone it first: git clone https://github.com/ProyectoPIONERA/Ontology-Hub.git '$SOURCE_DIR'" >&2
  exit 1
fi

if [[ "$APPLY" -ne 1 ]]; then
  echo "Overlay preview"
  echo "  source: $OVERLAY_DIR"
  echo "  target: $SOURCE_DIR"
  echo "  files:"
  (cd "$OVERLAY_DIR" && find . -type f | sed 's/^/    /')
  echo "Re-run with --apply to copy these files onto the target."
  exit 0
fi

rsync -a "$OVERLAY_DIR"/ "$SOURCE_DIR"/
echo "Ontology-Hub overlay applied to $SOURCE_DIR"
