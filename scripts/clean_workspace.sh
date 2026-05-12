#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLY=0
INCLUDE_RESULTS=0

usage() {
  cat <<'EOF'
Usage:
  bash scripts/clean_workspace.sh [--apply] [--include-results]

Options:
  --apply            Actually delete files/directories (default is dry-run)
  --include-results  Also remove local experiment/newman outputs and Playwright results

Default cleanup (safe):
  - __pycache__ directories
  - *.pyc files
  - .pytest_cache, .mypy_cache, .ruff_cache

Extended cleanup (--include-results):
  - experiments/
  - newman/
  - Playwright outputs (test-results, reports, ops-*, manual-runs)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --include-results)
      INCLUDE_RESULTS=1
      shift
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

mapfile -t TARGETS < <(
  {
    # Python cache
    find "$ROOT_DIR" \
      \( -path "*/.venv/*" -o -path "*/venv/*" -o -path "*/node_modules/*" -o -path "*/.git/*" \) -prune -o \
      -type d -name "__pycache__" -print

    find "$ROOT_DIR" \
      \( -path "*/.venv/*" -o -path "*/venv/*" -o -path "*/node_modules/*" -o -path "*/.git/*" \) -prune -o \
      -type f -name "*.pyc" -print

    find "$ROOT_DIR" \
      \( -path "*/.venv/*" -o -path "*/venv/*" -o -path "*/node_modules/*" -o -path "*/.git/*" \) -prune -o \
      -type d \( -name ".pytest_cache" -o -name ".mypy_cache" -o -name ".ruff_cache" \) -print

    # Resultados (solo si se pide explícitamente)
    if [[ "$INCLUDE_RESULTS" -eq 1 ]]; then

      # Framework outputs
      [[ -d "$ROOT_DIR/experiments" ]] && echo "$ROOT_DIR/experiments"
      [[ -d "$ROOT_DIR/newman" ]] && echo "$ROOT_DIR/newman"

      # Playwright estándar
      [[ -d "$ROOT_DIR/validation/ui/test-results" ]] && echo "$ROOT_DIR/validation/ui/test-results"
      [[ -d "$ROOT_DIR/validation/ui/playwright-report" ]] && echo "$ROOT_DIR/validation/ui/playwright-report"
      [[ -d "$ROOT_DIR/validation/ui/blob-report" ]] && echo "$ROOT_DIR/validation/ui/blob-report"

      # 👉 Playwright real en tu proyecto
      [[ -d "$ROOT_DIR/validation/ui/ops-test-results" ]] && echo "$ROOT_DIR/validation/ui/ops-test-results"
      [[ -d "$ROOT_DIR/validation/ui/ops-playwright-report" ]] && echo "$ROOT_DIR/validation/ui/ops-playwright-report"
      [[ -d "$ROOT_DIR/validation/ui/ops-blob-report" ]] && echo "$ROOT_DIR/validation/ui/ops-blob-report"

      # ejecuciones manuales (muy importante limpiarlas)
      [[ -d "$ROOT_DIR/validation/ui/manual-runs" ]] && echo "$ROOT_DIR/validation/ui/manual-runs"

    fi
  } | sort -u
)

if [[ "${#TARGETS[@]}" -eq 0 ]]; then
  echo "No cleanup targets found."
  exit 0
fi

echo "Cleanup mode: $([[ "$APPLY" -eq 1 ]] && echo "APPLY" || echo "DRY-RUN")"
echo "Targets:"
printf ' - %s\n' "${TARGETS[@]}"

if [[ "$APPLY" -eq 0 ]]; then
  echo
  echo "Dry-run finished. Re-run with --apply to remove these targets."
  exit 0
fi

# Seguridad extra: evitar borrar cosas críticas por error
for target in "${TARGETS[@]}"; do
  if [[ "$target" == "/" || "$target" == "" ]]; then
    echo "Skipping unsafe target: $target"
    continue
  fi
  rm -rf -- "$target"
done

echo
echo "Cleanup complete."