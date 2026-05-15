#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"

# Default config is provider profile; pass a config path as first arg to override.
CONFIG_FILE="${1:-${ROOT_DIR}/resources/configuration/provider-configuration.properties}"
CONFIG_BASENAME="$(basename "${CONFIG_FILE}")"
if [[ "${CONFIG_BASENAME}" == *"consumer"* ]]; then
  PROFILE="consumer"
elif [[ "${CONFIG_BASENAME}" == *"provider"* ]]; then
  PROFILE="provider"
else
  PROFILE="custom"
fi
OUT_LOG="${LOG_DIR}/final-connector-${PROFILE}.out.log"
ERR_LOG="${LOG_DIR}/final-connector-${PROFILE}.err.log"

java -Dedc.fs.config="${CONFIG_FILE}" \
  -jar "${ROOT_DIR}/final-connector/build/libs/connector.jar" \
  > >(tee -a "${OUT_LOG}") \
  2> >(tee -a "${ERR_LOG}" >&2)
