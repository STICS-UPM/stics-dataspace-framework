#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$ADAPTER_DIR/../.." && pwd)"

BUILD_SCRIPT="$SCRIPT_DIR/build_images.sh"
MANIFESTS_DIR="${MANIFESTS_DIR:-/tmp/inesdata-manifests}"
OVERRIDES_DIR="$ADAPTER_DIR/build/local-overrides"

DEFAULT_PLATFORM_DIR="$ROOT_DIR/inesdata-testing"
if [[ ! -d "$DEFAULT_PLATFORM_DIR/dataspace" && -d "$ROOT_DIR/deployers/inesdata/dataspace" ]]; then
  DEFAULT_PLATFORM_DIR="$ROOT_DIR/deployers/inesdata"
fi

PLATFORM_DIR="${PLATFORM_DIR:-$DEFAULT_PLATFORM_DIR}"
K8S_NAMESPACE="${K8S_NAMESPACE:-demo}"
MINIKUBE_PROFILE="${MINIKUBE_PROFILE:-minikube}"
CLUSTER_RUNTIME="${CLUSTER_RUNTIME:-minikube}"
K3S_IMAGE_IMPORT_COMMAND="${K3S_IMAGE_IMPORT_COMMAND:-sudo k3s ctr -n k8s.io images import}"
LOCAL_REGISTRY_HOST="${LOCAL_REGISTRY_HOST:-local}"
LOCAL_NAMESPACE="${LOCAL_NAMESPACE:-inesdata}"

DRY_RUN=1
RUN_DEPLOY=1
RUN_BUILD=1
RUN_LOAD=1
MANIFEST_FILE=""
TARGET="TODO"
PRUNE_REPLACED_IMAGES=1
PRESERVE_DEPLOYED_VALUES=0
PRESERVE_DEPLOYED_RELEASES=0
PRESERVE_SKIPPED_RELEASES=()
LEGACY_DATASPACE_TARGET="__legacy-dataspace__"
LEGACY_CONNECTORS_TARGET="__legacy-connectors__"

usage() {
  cat <<'EOF'
Usage: local_build_load_deploy.sh [--apply] [--manifest <path>] [--platform-dir <path>] [--namespace <name>]
                                 [--minikube-profile <name>] [--cluster-runtime <minikube|k3s>]
                                 [--skip-build] [--skip-load] [--skip-deploy] [--build-only]
                                 [--target TODO|CHANGED|connector|connector-interface|registration-service|public-portal-backend|public-portal-frontend]
                                 [--component <value>]

Options:
  --apply                     Execute build/load/deploy actions (default is dry-run).
  --manifest <path>           Use an existing build manifest TSV.
  --platform-dir <path>       Path to local INESData deployer artifacts (default: ./deployers/inesdata).
  --namespace <name>          Kubernetes namespace and dataspace name (default: demo).
  --minikube-profile <name>   Minikube profile name (default: minikube).
  --cluster-runtime <value>   Cluster runtime used for local image loading: minikube or k3s (default: minikube).
  --skip-build                Skip image build, use provided/latest manifest.
  --skip-load                 Skip loading images into the cluster runtime.
  --skip-deploy               Build and load images, but do not run helm upgrade.
  --build-only                Build images only (equivalent to --skip-load --skip-deploy).
  --target <value>            Update target. Use TODO for all images, CHANGED for modified source components, or one component key.
  --component <value>         Alias for --target (kept for backwards compatibility).
  --deploy-target <target>    Deprecated alias; mapped to --target when possible.
  --preserve-values           Redeploy only existing releases with --reuse-values; never reinstall with base values.
  --preserve-data             Alias for --preserve-values.
  --no-prune                  Keep replaced images in minikube cache (default prunes replaced image tags).
  -h, --help                  Show help.

Environment variables:
  PLATFORM_DIR
  K8S_NAMESPACE
  MINIKUBE_PROFILE
  CLUSTER_RUNTIME
  K3S_IMAGE_IMPORT_COMMAND
  LOCAL_REGISTRY_HOST
  LOCAL_NAMESPACE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      DRY_RUN=0
      shift
      ;;
    --manifest)
      MANIFEST_FILE="${2:-}"
      shift 2
      ;;
    --platform-dir)
      PLATFORM_DIR="${2:-}"
      shift 2
      ;;
    --namespace)
      K8S_NAMESPACE="${2:-}"
      shift 2
      ;;
    --minikube-profile)
      MINIKUBE_PROFILE="${2:-}"
      shift 2
      ;;
    --cluster-runtime)
      CLUSTER_RUNTIME="${2:-}"
      shift 2
      ;;
    --skip-build)
      RUN_BUILD=0
      shift
      ;;
    --skip-load)
      RUN_LOAD=0
      shift
      ;;
    --skip-deploy)
      RUN_DEPLOY=0
      shift
      ;;
    --build-only)
      RUN_LOAD=0
      RUN_DEPLOY=0
      shift
      ;;
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --component)
      TARGET="${2:-}"
      shift 2
      ;;
    --no-prune)
      PRUNE_REPLACED_IMAGES=0
      shift
      ;;
    --preserve-values|--preserve-data)
      PRESERVE_DEPLOYED_VALUES=1
      shift
      ;;
    --deploy-target)
      legacy_target="${2:-}"
      case "$legacy_target" in
        all)
          TARGET="TODO"
          ;;
        dataspace)
          TARGET="$LEGACY_DATASPACE_TARGET"
          ;;
        connectors)
          TARGET="$LEGACY_CONNECTORS_TARGET"
          ;;
        connector-interface|connector|registration-service|public-portal-backend|public-portal-frontend)
          TARGET="$legacy_target"
          ;;
        *)
          echo "Unsupported legacy --deploy-target value: $legacy_target" >&2
          echo "Use --target TODO|connector|connector-interface|registration-service|public-portal-backend|public-portal-frontend" >&2
          exit 1
          ;;
      esac
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] $*"
  else
    eval "$@"
  fi
}

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

resolve_manifest() {
  if [[ -n "$MANIFEST_FILE" ]]; then
    return
  fi
  MANIFEST_FILE="$(ls -1t "$MANIFESTS_DIR"/images-*.tsv 2>/dev/null | head -n 1 || true)"
}

require_file() {
  local p="$1"
  if [[ ! -f "$p" ]]; then
    echo "Required file not found: $p" >&2
    exit 1
  fi
}

release_exists() {
  local release="$1"
  local namespace="$2"
  helm status "$release" -n "$namespace" >/dev/null 2>&1
}

helm_upgrade_with_local_override() {
  local release="$1"
  local chart_dir="$2"
  local override_file="$3"
  local base_values_file="$4"
  local reuse_existing="$5"

  if [[ "$PRESERVE_DEPLOYED_VALUES" -eq 1 ]]; then
    if release_exists "$release" "$K8S_NAMESPACE"; then
      echo "Preserving deployed values for Helm release '$release'"
      run_cmd "helm upgrade --install \"$release\" \"$chart_dir\" -n \"$K8S_NAMESPACE\" --create-namespace --reuse-values -f \"$override_file\""
      PRESERVE_DEPLOYED_RELEASES=$((PRESERVE_DEPLOYED_RELEASES + 1))
    else
      echo "Skipping Helm release '$release' because it is not deployed in namespace '$K8S_NAMESPACE'."
      echo "Run the corresponding framework level first if this component must be created."
      PRESERVE_SKIPPED_RELEASES+=("$release")
    fi
    return
  fi

  if [[ "$reuse_existing" == "yes" ]] && release_exists "$release" "$K8S_NAMESPACE"; then
    run_cmd "helm upgrade --install \"$release\" \"$chart_dir\" -n \"$K8S_NAMESPACE\" --create-namespace --reuse-values -f \"$override_file\""
  else
    run_cmd "helm upgrade --install \"$release\" \"$chart_dir\" -n \"$K8S_NAMESPACE\" --create-namespace -f \"$base_values_file\" -f \"$override_file\""
  fi
}

ALL_COMPONENTS=(
  connector
  connector-interface
  registration-service
  public-portal-backend
  public-portal-frontend
)

declare -A SRC_DIR_BY_COMPONENT=(
  ["connector"]="$ADAPTER_DIR/sources/inesdata-connector"
  ["connector-interface"]="$ADAPTER_DIR/sources/inesdata-connector-interface"
  ["registration-service"]="$ADAPTER_DIR/sources/inesdata-registration-service"
  ["public-portal-backend"]="$ADAPTER_DIR/sources/inesdata-public-portal-backend"
  ["public-portal-frontend"]="$ADAPTER_DIR/sources/inesdata-public-portal-frontend"
)

component_has_changes() {
  local repo_dir="$1"

  if [[ ! -d "$repo_dir" ]]; then
    return 1
  fi

  if ! git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    # Without git metadata, prefer rebuilding instead of silently skipping.
    return 0
  fi

  if [[ -n "$(git -C "$repo_dir" status --porcelain -- .)" ]]; then
    return 0
  fi

  return 1
}

detect_changed_components() {
  changed_components=()
  for component in "${ALL_COMPONENTS[@]}"; do
    if component_has_changes "${SRC_DIR_BY_COMPONENT[$component]}"; then
      changed_components+=("$component")
    fi
  done
}

has_required_component() {
  local target_component="$1"
  local component
  for component in "${required_components[@]}"; do
    if [[ "$component" == "$target_component" ]]; then
      return 0
    fi
  done
  return 1
}

image_component_name() {
  local image_ref="$1"
  local last_segment
  last_segment="${image_ref##*/}"
  last_segment="${last_segment%%@*}"
  echo "${last_segment%%:*}"
}

capture_namespace_images() {
  local output_file="$1"
  if kubectl get namespace "$K8S_NAMESPACE" >/dev/null 2>&1; then
    kubectl get deploy -n "$K8S_NAMESPACE" -o jsonpath='{range .items[*]}{range .spec.template.spec.containers[*]}{.image}{"\n"}{end}{end}' \
      | sed '/^$/d' | sort -u > "$output_file"
  else
    : > "$output_file"
  fi
}

capture_cluster_images() {
  local output_file="$1"
  kubectl get deploy -A -o jsonpath='{range .items[*]}{range .spec.template.spec.containers[*]}{.image}{"\n"}{end}{end}' \
    2>/dev/null | sed '/^$/d' | sort -u > "$output_file"
}

prune_replaced_images() {
  local before_file="$1"
  local after_file="$2"
  local current_image
  local current_name
  local key
  local name_matches_target
  local rm_output

  if [[ ! -s "$before_file" ]]; then
    return
  fi

  while IFS= read -r current_image; do
    [[ -z "$current_image" ]] && continue
    current_name="$(image_component_name "$current_image")"

    name_matches_target=0
    for key in "${required_components[@]}"; do
      if [[ "$current_name" == "$(image_component_name "${IMAGE_BY_COMPONENT[$key]}")" ]]; then
        name_matches_target=1
        break
      fi
    done
    if [[ "$name_matches_target" -ne 1 ]]; then
      continue
    fi

    if grep -Fxq "$current_image" "$after_file"; then
      continue
    fi

    echo "Pruning replaced image: $current_image"

    if [[ "$CLUSTER_RUNTIME" == "k3s" ]]; then
      echo "Skipping prune for k3s-imported image: $current_image"
      continue
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
      run_cmd "minikube -p \"$MINIKUBE_PROFILE\" image rm \"$current_image\""
      continue
    fi

    if rm_output="$(minikube -p "$MINIKUBE_PROFILE" image rm "$current_image" 2>&1)"; then
      continue
    fi

    if echo "$rm_output" | grep -qi "is using its referenced image"; then
      echo "Skipping prune for in-use image: $current_image"
      continue
    fi

    if echo "$rm_output" | grep -qi "No such image"; then
      continue
    fi

    echo "Warning: failed to prune image: $current_image"
    echo "$rm_output"
  done < "$before_file"
}

load_image_into_k3s() {
  local full_image="$1"
  local archive_file

  archive_file="$(mktemp "${TMPDIR:-/tmp}/inesdata-image-XXXXXX.tar")"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    run_cmd "docker save \"$full_image\" -o \"$archive_file\""
    run_cmd "$K3S_IMAGE_IMPORT_COMMAND \"$archive_file\""
    run_cmd "rm -f \"$archive_file\""
    return
  fi

  docker save "$full_image" -o "$archive_file"
  # shellcheck disable=SC2086
  if ! $K3S_IMAGE_IMPORT_COMMAND "$archive_file"; then
    rm -f "$archive_file"
    return 1
  fi
  rm -f "$archive_file"
}

load_image_into_runtime() {
  local full_image="$1"

  case "$CLUSTER_RUNTIME" in
    minikube)
      run_cmd "minikube -p \"$MINIKUBE_PROFILE\" image load \"$full_image\""
      ;;
    k3s)
      load_image_into_k3s "$full_image"
      ;;
  esac
}

normalize_cluster_runtime

echo "Mode: $([[ "$DRY_RUN" -eq 1 ]] && echo "dry-run" || echo "apply")"
echo "Platform dir: $PLATFORM_DIR"
echo "K8s namespace: $K8S_NAMESPACE"
echo "Cluster runtime: $CLUSTER_RUNTIME"
if [[ "$CLUSTER_RUNTIME" == "minikube" ]]; then
  echo "Minikube profile: $MINIKUBE_PROFILE"
else
  echo "K3s image import command: $K3S_IMAGE_IMPORT_COMMAND"
fi
echo "Local image prefix: $LOCAL_REGISTRY_HOST/$LOCAL_NAMESPACE"
echo "Target: $TARGET"
echo "Prune replaced images: $([[ "$PRUNE_REPLACED_IMAGES" -eq 1 ]] && echo "yes" || echo "no")"
echo "Preserve deployed values: $([[ "$PRESERVE_DEPLOYED_VALUES" -eq 1 ]] && echo "yes" || echo "no")"

case "$TARGET" in
  TODO|CHANGED|changed|connector|connector-interface|registration-service|public-portal-backend|public-portal-frontend|$LEGACY_DATASPACE_TARGET|$LEGACY_CONNECTORS_TARGET)
    ;;
  *)
    echo "Invalid --target value: $TARGET" >&2
    exit 1
    ;;
esac

if [[ "$TARGET" == "changed" ]]; then
  TARGET="CHANGED"
fi

changed_components=()

if [[ "$TARGET" == "CHANGED" ]]; then
  detect_changed_components
  if [[ "${#changed_components[@]}" -eq 0 ]]; then
    echo
    echo "No changed components detected under $ADAPTER_DIR/sources. Nothing to build/load/deploy."
    exit 0
  fi
fi

if [[ "$RUN_BUILD" -eq 1 ]]; then
  echo
  echo "== Build local images =="
  build_components=()
  case "$TARGET" in
    TODO)
      build_components=(TODO)
      ;;
    CHANGED)
      build_components=("${changed_components[@]}")
      ;;
    "$LEGACY_DATASPACE_TARGET")
      build_components=(registration-service public-portal-backend public-portal-frontend)
      ;;
    "$LEGACY_CONNECTORS_TARGET")
      build_components=(connector connector-interface)
      ;;
    *)
      build_components=("$TARGET")
      ;;
  esac

  mkdir -p "$MANIFESTS_DIR"
  MANIFEST_FILE="$MANIFESTS_DIR/images-local-build-load-deploy-$(date -u +%Y-%m-%dT%H-%M-%SZ).tsv"

  for build_component in "${build_components[@]}"; do
    if [[ "$DRY_RUN" -eq 1 ]]; then
      bash "$BUILD_SCRIPT" --registry-host "$LOCAL_REGISTRY_HOST" --namespace "$LOCAL_NAMESPACE" --target "$build_component" --manifest "$MANIFEST_FILE" --append-manifest
    else
      bash "$BUILD_SCRIPT" --apply --registry-host "$LOCAL_REGISTRY_HOST" --namespace "$LOCAL_NAMESPACE" --target "$build_component" --manifest "$MANIFEST_FILE" --append-manifest
    fi
  done
elif [[ "$TARGET" == "CHANGED" && -z "$MANIFEST_FILE" ]]; then
  echo "--skip-build with --target CHANGED requires --manifest <path>." >&2
  exit 1
fi

resolve_manifest
if [[ -z "$MANIFEST_FILE" ]]; then
  echo "No manifest found. Run build_images.sh first or pass --manifest." >&2
  exit 1
fi
require_file "$MANIFEST_FILE"

echo
echo "Manifest: $MANIFEST_FILE"

declare -A IMAGE_BY_COMPONENT=()
while IFS=$'\t' read -r component repo_dir image tag full_image build_cmd; do
  [[ "$component" == "component" ]] && continue
  IMAGE_BY_COMPONENT["$component"]="$full_image"
done < "$MANIFEST_FILE"

required_components=()
case "$TARGET" in
  TODO)
    required_components=(connector connector-interface registration-service public-portal-backend public-portal-frontend)
    ;;
  CHANGED)
    if [[ "${#changed_components[@]}" -gt 0 ]]; then
      required_components=("${changed_components[@]}")
    else
      while IFS=$'\t' read -r component _; do
        [[ "$component" == "component" || -z "$component" ]] && continue
        required_components+=("$component")
      done < "$MANIFEST_FILE"
    fi
    ;;
  "$LEGACY_DATASPACE_TARGET")
    required_components=(registration-service public-portal-backend public-portal-frontend)
    ;;
  "$LEGACY_CONNECTORS_TARGET")
    required_components=(connector connector-interface)
    ;;
  *)
    required_components=("$TARGET")
    ;;
esac

for key in "${required_components[@]}"; do
  if [[ -z "${IMAGE_BY_COMPONENT[$key]:-}" ]]; then
    echo "Missing component in manifest: $key" >&2
    exit 1
  fi
done

if [[ "$RUN_LOAD" -eq 0 && "$RUN_DEPLOY" -eq 1 ]]; then
  echo "Invalid combination: --skip-load requires --skip-deploy (or use --build-only)." >&2
  exit 1
fi

if [[ "$RUN_LOAD" -eq 0 ]]; then
  echo
  echo "Image load step skipped (--skip-load)."
  echo "Build workflow complete."
  exit 0
fi

echo
if [[ "$CLUSTER_RUNTIME" == "minikube" ]]; then
  echo "== Load images into minikube =="
else
  echo "== Load images into k3s containerd =="
fi

load_keys=()
case "$TARGET" in
  TODO)
    load_keys=(connector connector-interface registration-service public-portal-backend public-portal-frontend)
    ;;
  CHANGED)
    load_keys=("${required_components[@]}")
    ;;
  "$LEGACY_DATASPACE_TARGET")
    load_keys=(registration-service public-portal-backend public-portal-frontend)
    ;;
  "$LEGACY_CONNECTORS_TARGET")
    load_keys=(connector connector-interface)
    ;;
  *)
    load_keys=("$TARGET")
    ;;
esac

for key in "${load_keys[@]}"; do
  full_image="${IMAGE_BY_COMPONENT[$key]}"
  echo "$key -> $full_image"
  load_image_into_runtime "$full_image"
done

mkdir -p "$OVERRIDES_DIR"

CONNECTOR_OVERRIDE="$OVERRIDES_DIR/connector-local-overrides.yaml"
RS_OVERRIDE="$OVERRIDES_DIR/registration-local-overrides.yaml"
PP_OVERRIDE="$OVERRIDES_DIR/public-portal-local-overrides.yaml"

if has_required_component "connector" || has_required_component "connector-interface"; then
  : > "$CONNECTOR_OVERRIDE"

  if has_required_component "connector"; then
    cat >> "$CONNECTOR_OVERRIDE" <<EOF
connector:
  image:
    name: ${IMAGE_BY_COMPONENT[connector]%:*}
    tag: ${IMAGE_BY_COMPONENT[connector]##*:}
EOF
  fi

  if has_required_component "connector-interface"; then
    cat >> "$CONNECTOR_OVERRIDE" <<EOF
connectorInterface:
  image:
    name: ${IMAGE_BY_COMPONENT[connector-interface]%:*}
    tag: ${IMAGE_BY_COMPONENT[connector-interface]##*:}
EOF
  fi
fi

if has_required_component "registration-service"; then
  cat > "$RS_OVERRIDE" <<EOF
registration:
  image:
    name: ${IMAGE_BY_COMPONENT[registration-service]%:*}
    tag: ${IMAGE_BY_COMPONENT[registration-service]##*:}
EOF
fi

if has_required_component "public-portal-backend" || has_required_component "public-portal-frontend"; then
  : > "$PP_OVERRIDE"

  if has_required_component "public-portal-backend"; then
    cat >> "$PP_OVERRIDE" <<EOF
backend:
  image:
    name: ${IMAGE_BY_COMPONENT[public-portal-backend]%:*}
    tag: ${IMAGE_BY_COMPONENT[public-portal-backend]##*:}
EOF
  fi

  if has_required_component "public-portal-frontend"; then
    cat >> "$PP_OVERRIDE" <<EOF
frontend:
  image:
    name: ${IMAGE_BY_COMPONENT[public-portal-frontend]%:*}
    tag: ${IMAGE_BY_COMPONENT[public-portal-frontend]##*:}
EOF
  fi
fi

if [[ "$RUN_DEPLOY" -eq 0 ]]; then
  echo
  echo "Deploy step skipped (--skip-deploy)."
  exit 0
fi

if [[ ! -d "$PLATFORM_DIR" ]]; then
  echo "Platform directory not found: $PLATFORM_DIR" >&2
  exit 1
fi

echo
echo "== Helm upgrade (local images) =="

PRE_DEPLOY_IMAGES_FILE=""
POST_DEPLOY_IMAGES_FILE=""
if [[ "$PRUNE_REPLACED_IMAGES" -eq 1 && "$DRY_RUN" -eq 0 ]]; then
  PRE_DEPLOY_IMAGES_FILE="$(mktemp)"
  capture_namespace_images "$PRE_DEPLOY_IMAGES_FILE"
fi

RS_BASE_VALUES="$PLATFORM_DIR/dataspace/registration-service/values-$K8S_NAMESPACE.yaml"
PP_BASE_VALUES="$PLATFORM_DIR/dataspace/public-portal/values-$K8S_NAMESPACE.yaml"
CONNECTOR_DIR="$PLATFORM_DIR/connector"

if has_required_component "registration-service"; then
  require_file "$RS_BASE_VALUES"
  rs_release="$K8S_NAMESPACE-dataspace-rs"
  reuse_existing="no"
  if [[ "$TARGET" == "registration-service" ]]; then
    reuse_existing="yes"
  fi
  helm_upgrade_with_local_override "$rs_release" "$PLATFORM_DIR/dataspace/registration-service" "$RS_OVERRIDE" "$RS_BASE_VALUES" "$reuse_existing"
fi

if has_required_component "public-portal-backend" || has_required_component "public-portal-frontend"; then
  require_file "$PP_BASE_VALUES"
  pp_release="$K8S_NAMESPACE-dataspace-pp"
  reuse_existing="no"
  if [[ "$TARGET" == "public-portal-backend" || "$TARGET" == "public-portal-frontend" ]]; then
    reuse_existing="yes"
  fi
  helm_upgrade_with_local_override "$pp_release" "$PLATFORM_DIR/dataspace/public-portal" "$PP_OVERRIDE" "$PP_BASE_VALUES" "$reuse_existing"
fi

if has_required_component "connector" || has_required_component "connector-interface"; then
  connector_values=()
  while IFS= read -r file; do
    connector_values+=("$file")
  done < <(find "$CONNECTOR_DIR" -maxdepth 1 -type f -name "values-*.yaml" ! -name "values.yaml" ! -name "values.yaml.tpl" | sort)

  if [[ "${#connector_values[@]}" -eq 0 ]]; then
    echo "No connector values files found in $CONNECTOR_DIR"
  else
    for values_file in "${connector_values[@]}"; do
      connector_name="$(basename "$values_file")"
      connector_name="${connector_name#values-}"
      connector_name="${connector_name%.yaml}"
      release_name="${connector_name}-${K8S_NAMESPACE}"
      reuse_existing="no"
      if [[ "$TARGET" == "connector" || "$TARGET" == "connector-interface" ]]; then
        reuse_existing="yes"
      fi
      helm_upgrade_with_local_override "$release_name" "$CONNECTOR_DIR" "$CONNECTOR_OVERRIDE" "$values_file" "$reuse_existing"
    done
  fi
fi

if [[ "$PRESERVE_DEPLOYED_VALUES" -eq 1 && "$RUN_DEPLOY" -eq 1 && "$DRY_RUN" -eq 0 && "$PRESERVE_DEPLOYED_RELEASES" -eq 0 ]]; then
  echo
  echo "No existing Helm releases were redeployed in preserve-values mode." >&2
  if [[ "${#PRESERVE_SKIPPED_RELEASES[@]}" -gt 0 ]]; then
    echo "Skipped releases: ${PRESERVE_SKIPPED_RELEASES[*]}" >&2
  fi
  echo "Run Level 4 or Level 5 first, then use this developer workflow for iterative redeploys." >&2
  exit 1
fi

if [[ "$PRUNE_REPLACED_IMAGES" -eq 1 && "$DRY_RUN" -eq 0 && -n "$PRE_DEPLOY_IMAGES_FILE" ]]; then
  POST_DEPLOY_IMAGES_FILE="$(mktemp)"
  capture_cluster_images "$POST_DEPLOY_IMAGES_FILE"
  echo
  echo "== Prune replaced images from minikube cache =="
  prune_replaced_images "$PRE_DEPLOY_IMAGES_FILE" "$POST_DEPLOY_IMAGES_FILE"
fi

echo
echo "Local build/load/deploy workflow complete."
