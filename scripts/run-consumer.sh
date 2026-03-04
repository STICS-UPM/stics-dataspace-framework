#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
OUT_LOG="${LOG_DIR}/consumer.out.log"
ERR_LOG="${LOG_DIR}/consumer.err.log"

java -Dedc.fs.config="${ROOT_DIR}/resources/configuration/consumer-configuration.properties" \
  -jar "${ROOT_DIR}/connector/build/libs/connector.jar" \
  > >(tee -a "${OUT_LOG}") \
  2> >(tee -a "${ERR_LOG}" >&2)
