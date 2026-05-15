#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

"${ROOT_DIR}/gradlew" :connector:build :provider-proxy-data-plane:build
