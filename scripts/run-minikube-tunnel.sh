#!/usr/bin/env bash
set -euo pipefail

# Ask for sudo password once and keep it in memory while this script runs.
read -r -s -p "[sudo] password for $(whoami): " SUDO_PASSWORD
echo

if ! printf '%s\n' "$SUDO_PASSWORD" | sudo -S -p '' -v; then
  echo "Invalid sudo password."
  exit 1
fi

# Keep sudo ticket alive while the tunnel is running.
keep_sudo_alive() {
  while true; do
    if ! printf '%s\n' "$SUDO_PASSWORD" | sudo -S -p '' -v; then
      echo "Failed to refresh sudo credentials." >&2
      exit 1
    fi
    sleep 50
  done
}

keep_sudo_alive &
KEEPALIVE_PID=$!

cleanup() {
  kill "$KEEPALIVE_PID" 2>/dev/null || true
  unset SUDO_PASSWORD
}
trap cleanup EXIT INT TERM

minikube tunnel
