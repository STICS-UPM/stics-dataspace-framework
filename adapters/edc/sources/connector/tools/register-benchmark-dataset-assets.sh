#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSET_DIR="${ROOT_DIR}/resources/requests/ai-datasets"
MANAGEMENT_URL="${1:-http://localhost:19193/management/v3/assets}"

requests=(
  "create-asset-benchmark-dataset-text-positive-v1.json"
  "create-asset-benchmark-dataset-text-negative-v1.json"
  "create-asset-benchmark-dataset-text-neutral-v1.json"
  "create-asset-benchmark-dataset-tabular-a-v1.json"
  "create-asset-benchmark-dataset-tabular-b-v1.json"
)

for req in "${requests[@]}"; do
  echo "[create] ${req}"
  curl -fsS -d @"${ASSET_DIR}/${req}" \
    -H 'content-type: application/json' \
    "${MANAGEMENT_URL}" | jq .
done

echo "Registered 5 benchmark dataset assets to ${MANAGEMENT_URL}."
