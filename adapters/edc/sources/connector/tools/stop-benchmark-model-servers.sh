#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="${ROOT_DIR}/tools/.benchmark-model-pids"

if [[ ! -d "${PID_DIR}" ]]; then
  echo "No benchmark model pid directory found."
  exit 0
fi

stopped_any=0
for pid_file in "${PID_DIR}"/*.pid; do
  [[ -e "${pid_file}" ]] || continue
  variant="$(basename "${pid_file}" .pid)"
  pid="$(cat "${pid_file}")"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    echo "[stop] ${variant} (pid ${pid})"
    stopped_any=1
  else
    echo "[stale] ${variant} pid file"
  fi
  rm -f "${pid_file}"
done

rmdir "${PID_DIR}" 2>/dev/null || true

if [[ "${stopped_any}" -eq 0 ]]; then
  echo "No running benchmark model servers found."
else
  echo "Benchmark model servers stopped."
fi
