#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
OUT_LOG="${LOG_DIR}/provider.out.log"
ERR_LOG="${LOG_DIR}/provider.err.log"

java -Dedc.fs.config="${ROOT_DIR}/resources/configuration/provider-configuration.properties" \
  -jar "${ROOT_DIR}/provider-proxy-data-plane/build/libs/connector.jar" \
  > >(tee -a "${OUT_LOG}") \
  2> >(tee -a "${ERR_LOG}" >&2)
