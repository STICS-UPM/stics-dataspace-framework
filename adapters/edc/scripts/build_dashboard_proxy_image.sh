#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRAMEWORK_ROOT="$(cd "$ADAPTER_DIR/../.." && pwd)"
BUILD_DIR="$ADAPTER_DIR/build"
DOCKERFILE="$BUILD_DIR/docker/dashboard-proxy.Dockerfile"
SERVER_FILE="$BUILD_DIR/dashboard-proxy/server.py"
CONTEXT_DIR="$BUILD_DIR/dashboard-proxy-image-context"
IMAGE_NAME="${PIONERA_EDC_DASHBOARD_PROXY_IMAGE_NAME:-validation-environment/edc-dashboard-proxy}"
IMAGE_TAG="${PIONERA_EDC_DASHBOARD_PROXY_IMAGE_TAG:-latest}"
MINIKUBE_PROFILE="${MINIKUBE_PROFILE:-minikube}"
CLUSTER_RUNTIME="${CLUSTER_RUNTIME:-minikube}"
K3S_IMAGE_IMPORT_COMMAND="${K3S_IMAGE_IMPORT_COMMAND:-sudo k3s ctr -n k8s.io images import}"
K3S_REMOTE_IMPORT_HOST="${K3S_REMOTE_IMPORT_HOST:-}"
REMOTE_K3S_IMPORT_HELPER="$FRAMEWORK_ROOT/deployers/shared/lib/remote_k3s_image_import_cli.py"

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

remove_minikube_image_if_present() {
  local image_ref="$1"

  if command -v minikube >/dev/null 2>&1; then
    minikube -p "$MINIKUBE_PROFILE" ssh "docker image rm -f '$image_ref' >/dev/null 2>&1 || true"
  fi
}

load_image_into_k3s() {
  local image_ref="$1"
  local archive_file

  archive_file="$(mktemp "${TMPDIR:-/tmp}/edc-dashboard-proxy-image-XXXXXX.tar")"
  docker save "$image_ref" -o "$archive_file"
  if [[ -n "$K3S_REMOTE_IMPORT_HOST" ]]; then
    if ! python3 "$REMOTE_K3S_IMPORT_HELPER" --archive "$archive_file" --image "$image_ref"; then
      rm -f "$archive_file"
      return 1
    fi
  # shellcheck disable=SC2086
  elif ! $K3S_IMAGE_IMPORT_COMMAND "$archive_file"; then
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

if [[ "$APPLY" != true ]]; then
  echo "Dashboard proxy image build preview"
  echo "  dockerfile: $DOCKERFILE"
  echo "  server: $SERVER_FILE"
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

if [[ ! -f "$DOCKERFILE" ]]; then
  echo "Dashboard proxy Dockerfile not found in $DOCKERFILE" >&2
  exit 1
fi

if [[ ! -f "$SERVER_FILE" ]]; then
  echo "Dashboard proxy server not found in $SERVER_FILE" >&2
  exit 1
fi

rm -rf "$CONTEXT_DIR"
mkdir -p "$CONTEXT_DIR"
cp "$SERVER_FILE" "$CONTEXT_DIR/server.py"

docker build -f "$DOCKERFILE" -t "$IMAGE_NAME:$IMAGE_TAG" "$CONTEXT_DIR"

case "$CLUSTER_RUNTIME" in
  minikube)
    if command -v minikube >/dev/null 2>&1; then
      remove_minikube_image_if_present "$IMAGE_NAME:$IMAGE_TAG"
      minikube -p "$MINIKUBE_PROFILE" image load "$IMAGE_NAME:$IMAGE_TAG" >/dev/null
    fi
    ;;
  k3s)
    load_image_into_k3s "$IMAGE_NAME:$IMAGE_TAG"
    ;;
esac

echo "Dashboard proxy image ready: $IMAGE_NAME:$IMAGE_TAG"
