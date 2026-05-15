#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_SCRIPT="${ROOT_DIR}/tools/benchmark-model-server.py"
PID_DIR="${ROOT_DIR}/tools/.benchmark-model-pids"
LOG_DIR="${ROOT_DIR}/logs/benchmark-models"

mkdir -p "${PID_DIR}" "${LOG_DIR}"

start_variant() {
  local variant="$1"
  local port="$2"
  local pid_file="${PID_DIR}/${variant}.pid"
  local log_file="${LOG_DIR}/${variant}.log"

  if [[ -f "${pid_file}" ]]; then
    local old_pid
    old_pid="$(cat "${pid_file}")"
    if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
      echo "[skip] ${variant} already running (pid ${old_pid})"
      return
    fi
    rm -f "${pid_file}"
  fi

  MODEL_VARIANT="${variant}" PORT="${port}" nohup python3 "${SERVER_SCRIPT}" >"${log_file}" 2>&1 &
  local pid=$!
  echo "${pid}" >"${pid_file}"

  for _ in $(seq 1 40); do
    if curl -fsS "http://localhost:${port}/health" >/dev/null 2>&1; then
      echo "[ok] ${variant} on :${port} (pid ${pid})"
      return
    fi
    sleep 0.1
  done

  echo "[error] ${variant} did not become healthy on :${port}. Check ${log_file}" >&2
  return 1
}

start_variant "text-keyword-v1" 9201
start_variant "text-bayes-v1" 9202
start_variant "text-linear-v1" 9203
start_variant "tabular-linear-v1" 9301
start_variant "tabular-tree-v1" 9302

echo "All benchmark model servers are running."
echo "Logs: ${LOG_DIR}"
