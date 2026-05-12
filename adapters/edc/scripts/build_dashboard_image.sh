#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCES_DIR="$ADAPTER_DIR/sources"
DASHBOARD_REPO_DIR="$SOURCES_DIR/dashboard"
BUILD_DIR="$ADAPTER_DIR/build"
DOCKERFILE="$BUILD_DIR/docker/dashboard.Dockerfile"
NGINX_CONF="$BUILD_DIR/docker/dashboard-nginx.conf"
CONTEXT_DIR="$BUILD_DIR/dashboard-image-context"
IMAGE_NAME="${PIONERA_EDC_DASHBOARD_IMAGE_NAME:-validation-environment/edc-dashboard}"
IMAGE_TAG="${PIONERA_EDC_DASHBOARD_IMAGE_TAG:-latest}"
MINIKUBE_PROFILE="${MINIKUBE_PROFILE:-minikube}"
CLUSTER_RUNTIME="${CLUSTER_RUNTIME:-minikube}"
K3S_IMAGE_IMPORT_COMMAND="${K3S_IMAGE_IMPORT_COMMAND:-sudo k3s ctr -n k8s.io images import}"

APPLY=false

normalize_cluster_runtime() {
  CLUSTER_RUNTIME="$(printf '%s' "${CLUSTER_RUNTIME:-minikube}" | tr '[:upper:]' '[:lower:]')"
  case "$CLUSTER_RUNTIME" in
    minikube|k3s)
      ;;
    *)
      echo "Unsupported cluster runtime: $CLUSTER_RUNTIME" >&2
      echo "Supported values: minikube, k3s" >&2
      exit 1
      ;;
  esac
}

load_image_into_k3s() {
  local image_ref="$1"
  local archive_file

  archive_file="$(mktemp "${TMPDIR:-/tmp}/edc-dashboard-image-XXXXXX.tar")"
  docker save "$image_ref" -o "$archive_file"
  # shellcheck disable=SC2086
  if ! $K3S_IMAGE_IMPORT_COMMAND "$archive_file"; then
    rm -f "$archive_file"
    return 1
  fi
  rm -f "$archive_file"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --minikube-profile)
      MINIKUBE_PROFILE="${2:-}"
      shift 2
      ;;
    --cluster-runtime)
      CLUSTER_RUNTIME="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

normalize_cluster_runtime

if [[ ! -d "$DASHBOARD_REPO_DIR/.git" ]]; then
  bash "$SCRIPT_DIR/sync_dashboard_sources.sh" --apply
fi

DASHBOARD_DIR="$DASHBOARD_REPO_DIR"
if [[ -d "$DASHBOARD_REPO_DIR/DataDashboard" ]]; then
  DASHBOARD_DIR="$DASHBOARD_REPO_DIR/DataDashboard"
fi

if [[ "$APPLY" != true ]]; then
  echo "Dashboard image build preview"
  echo "  source: $DASHBOARD_DIR"
  echo "  dockerfile: $DOCKERFILE"
  echo "  nginx_conf: $NGINX_CONF"
  echo "  context: $CONTEXT_DIR"
  echo "  image: $IMAGE_NAME:$IMAGE_TAG"
  echo "  cluster_runtime: $CLUSTER_RUNTIME"
  if [[ "$CLUSTER_RUNTIME" == "minikube" ]]; then
    echo "  minikube_profile: $MINIKUBE_PROFILE"
  else
    echo "  k3s_image_import_command: $K3S_IMAGE_IMPORT_COMMAND"
  fi
  exit 0
fi

if [[ ! -f "$DASHBOARD_DIR/package.json" ]]; then
  echo "Dashboard application package.json not found in $DASHBOARD_DIR" >&2
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required to prepare the dashboard image context" >&2
  exit 1
fi

rm -rf "$CONTEXT_DIR"
mkdir -p "$CONTEXT_DIR/app"
rsync -a \
  --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude 'dist' \
  --exclude '.angular' \
  "$DASHBOARD_DIR"/ "$CONTEXT_DIR/app/"
cp "$NGINX_CONF" "$CONTEXT_DIR/dashboard-nginx.conf"

docker build -f "$DOCKERFILE" -t "$IMAGE_NAME:$IMAGE_TAG" "$CONTEXT_DIR"

case "$CLUSTER_RUNTIME" in
  minikube)
    if command -v minikube >/dev/null 2>&1; then
      minikube -p "$MINIKUBE_PROFILE" image load "$IMAGE_NAME:$IMAGE_TAG" >/dev/null
    fi
    ;;
  k3s)
    load_image_into_k3s "$IMAGE_NAME:$IMAGE_TAG"
    ;;
esac

echo "Dashboard image ready: $IMAGE_NAME:$IMAGE_TAG"
