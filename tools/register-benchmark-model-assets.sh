#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSET_DIR="${ROOT_DIR}/resources/requests/ai-models"
MANAGEMENT_URL="${1:-http://localhost:19193/management/v3/assets}"

requests=(
  "create-asset-infer-benchmark-text-keyword-v1.json"
  "create-asset-infer-benchmark-text-bayes-v1.json"
  "create-asset-infer-benchmark-text-linear-v1.json"
  "create-asset-infer-benchmark-tabular-linear-v1.json"
  "create-asset-infer-benchmark-tabular-tree-v1.json"
)

for req in "${requests[@]}"; do
  echo "[create] ${req}"
  curl -fsS -d @"${ASSET_DIR}/${req}" \
    -H 'content-type: application/json' \
    "${MANAGEMENT_URL}" | jq .
done

echo "Registered 5 benchmark inference assets to ${MANAGEMENT_URL}."
