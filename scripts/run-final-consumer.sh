#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

"${ROOT_DIR}/scripts/run-final-connector.sh" \
  "${ROOT_DIR}/resources/configuration/consumer-configuration.properties"
