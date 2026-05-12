#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCES_DIR="$ADAPTER_DIR/sources"

MODE="initial"
NAMESPACE="demo"
MINIKUBE_PROFILE="minikube"
REGISTRY_HOST="local"
REGISTRY_NAMESPACE="inesdata"
IMAGE_TAG="dev"
MANIFEST_FILE="${MANIFESTS_DIR:-/tmp/inesdata-manifests}/images-fast-step1.tsv"
COMPONENTS_CSV=""
REFRESH_RUNTIME=0
SKIP_MINIKUBE_LOAD=0
GRADLE_MAX_WORKERS="${GRADLE_MAX_WORKERS:-1}"
GRADLE_COMMON_ARGS="${GRADLE_COMMON_ARGS:---no-daemon --no-parallel -Dorg.gradle.workers.max=$GRADLE_MAX_WORKERS}"

COMPONENT_KEYS=(
  connector
  connector-interface
  registration-service
  public-portal-backend
  public-portal-frontend
)

usage() {
  cat <<'EOF'
Usage: fast_step1_images.sh [options]

Options:
  --mode <initial|changed>         Execution mode (default: initial)
  --namespace <name>               Kubernetes namespace for runtime refresh (default: demo)
  --minikube-profile <name>        Minikube profile (default: minikube)
  --registry-host <host>           Image registry host prefix (default: local)
  --registry-namespace <name>      Image registry namespace (default: inesdata)
  --image-tag <tag>                Stable tag to keep one image per component (default: dev)
  --manifest <path>                Output manifest TSV path
  --components <csv>               Optional component list override
  --refresh-runtime                Restart relevant deployments/pods after load
  --skip-minikube-load             Build only (do not load into minikube)
  -h, --help                       Show this help

Examples:
  Initial clean+build+load:
    fast_step1_images.sh --mode initial

  Changed components only + rollout refresh:
    fast_step1_images.sh --mode changed --refresh-runtime
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --namespace)
      NAMESPACE="${2:-}"
      shift 2
      ;;
    --minikube-profile)
      MINIKUBE_PROFILE="${2:-}"
      shift 2
      ;;
    --registry-host)
      REGISTRY_HOST="${2:-}"
      shift 2
      ;;
    --registry-namespace)
      REGISTRY_NAMESPACE="${2:-}"
      shift 2
      ;;
    --image-tag)
      IMAGE_TAG="${2:-}"
      shift 2
      ;;
    --manifest)
      MANIFEST_FILE="${2:-}"
      shift 2
      ;;
    --components)
      COMPONENTS_CSV="${2:-}"
      shift 2
      ;;
    --refresh-runtime)
      REFRESH_RUNTIME=1
      shift
      ;;
    --skip-minikube-load)
      SKIP_MINIKUBE_LOAD=1
      shift
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

if [[ "$MODE" != "initial" && "$MODE" != "changed" ]]; then
  echo "Invalid --mode value: $MODE" >&2
  exit 1
fi

declare -A SRC_DIR=(
  ["connector"]="$SOURCES_DIR/inesdata-connector"
  ["connector-interface"]="$SOURCES_DIR/inesdata-connector-interface"
  ["registration-service"]="$SOURCES_DIR/inesdata-registration-service"
  ["public-portal-backend"]="$SOURCES_DIR/inesdata-public-portal-backend"
  ["public-portal-frontend"]="$SOURCES_DIR/inesdata-public-portal-frontend"
)

declare -A DOCKERFILE=(
  ["connector"]="docker/Dockerfile"
  ["connector-interface"]="docker/Dockerfile"
  ["registration-service"]="docker/Dockerfile"
  ["public-portal-backend"]="Dockerfile"
  ["public-portal-frontend"]="docker/Dockerfile"
)

declare -A IMAGE_NAME=(
  ["connector"]="inesdata-connector"
  ["connector-interface"]="inesdata-connector-interface"
  ["registration-service"]="inesdata-registration-service"
  ["public-portal-backend"]="inesdata-public-portal-backend"
  ["public-portal-frontend"]="inesdata-public-portal-frontend"
)

declare -A EXTRA_ARGS=(
  ["connector"]="--build-arg CONNECTOR_JAR=./launchers/connector/build/libs/connector-app.jar"
  ["connector-interface"]=""
  ["registration-service"]=""
  ["public-portal-backend"]=""
  ["public-portal-frontend"]=""
)

declare -A REQUIRED_ARTIFACT=(
  ["connector"]="launchers/connector/build/libs/connector-app.jar"
  ["registration-service"]="build/libs/*.jar"
)

declare -A PREBUILD_ARGS=(
  ["connector"]="launchers:connector:build -x test"
  ["registration-service"]="bootJar -x test"
)

is_component_key() {
  local candidate="$1"
  local c
  for c in "${COMPONENT_KEYS[@]}"; do
    if [[ "$c" == "$candidate" ]]; then
      return 0
    fi
  done
  return 1
}

component_has_changes() {
  local repo_dir="$1"

  if [[ ! -d "$repo_dir" ]]; then
    return 1
  fi

  if ! git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 0
  fi

  if [[ -n "$(git -C "$repo_dir" status --porcelain -- .)" ]]; then
    return 0
  fi

  return 1
}

artifact_exists() {
  local pattern="$1"
  compgen -G "$pattern" > /dev/null
}

artifact_reference_path() {
  local pattern="$1"
  local candidate
  local newest=""

  while IFS= read -r candidate; do
    if [[ -z "$newest" || "$candidate" -nt "$newest" ]]; then
      newest="$candidate"
    fi
  done < <(compgen -G "$pattern" || true)

  printf '%s\n' "$newest"
}

artifact_is_stale() {
  local artifact_path="$1"
  local repo_dir="$2"

  if [[ -z "$artifact_path" || ! -f "$artifact_path" ]]; then
    return 1
  fi

  find "$repo_dir" \
    \( -path "*/.git" -o -path "*/.gradle" -o -path "*/.gradle-user-home" -o -path "*/build" -o -path "*/node_modules" \) -prune \
    -o -type f -newer "$artifact_path" -print -quit | grep -q .
}

prepare_component_artifacts() {
  local component="$1"
  local repo_dir="$2"
  local artifact_rel="${REQUIRED_ARTIFACT[$component]:-}"
  local prebuild_args="${PREBUILD_ARGS[$component]:-}"
  local artifact_path="$repo_dir/$artifact_rel"
  local artifact_ref=""
  local gradle_user_home="$repo_dir/.gradle-user-home"

  if [[ -z "$artifact_rel" ]]; then
    return
  fi

  artifact_ref="$(artifact_reference_path "$artifact_path")"

  if [[ -n "$artifact_ref" ]] && ! component_has_changes "$repo_dir" && ! artifact_is_stale "$artifact_ref" "$repo_dir"; then
    return
  fi

  if [[ -z "$prebuild_args" ]]; then
    echo "Missing required artifact for $component: $artifact_path" >&2
    exit 1
  fi

  echo "Preparing artifacts for $component"
  mkdir -p "$gradle_user_home"
  if [[ -f "$repo_dir/gradlew" && ! -x "$repo_dir/gradlew" ]]; then
    chmod +x "$repo_dir/gradlew"
  fi
  (cd "$repo_dir" && GRADLE_USER_HOME="$gradle_user_home" ./gradlew $GRADLE_COMMON_ARGS $prebuild_args)

  if ! artifact_exists "$artifact_path"; then
    echo "Artifact still missing after prebuild for $component: $artifact_path" >&2
    exit 1
  fi
}

minikube_profile_exists() {
  local profile="$1"
  minikube profile list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Fxq "$profile"
}

ensure_minikube_running_if_exists() {
  local profile="$1"

  if ! minikube_profile_exists "$profile"; then
    echo "Minikube profile '$profile' does not exist. Skipping minikube operations."
    return 1
  fi

  local status_output
  status_output="$(minikube -p "$profile" status 2>/dev/null || true)"
  if echo "$status_output" | grep -q "host: Running"; then
    return 0
  fi

  echo "Starting minikube profile '$profile'..."
  minikube -p "$profile" start
  return 0
}

collect_image_refs() {
  local from="$1"
  local refs=""

  if [[ "$from" == "docker" ]]; then
    refs="$(docker images --format '{{.Repository}}:{{.Tag}}' || true)"
  else
    refs="$(minikube -p "$MINIKUBE_PROFILE" image ls 2>/dev/null || true)"
  fi

  echo "$refs" | grep -E "(inesdata-connector|inesdata-connector-interface|inesdata-registration-service|inesdata-public-portal-backend|inesdata-public-portal-frontend)" | sort -u || true
}

remove_all_inesdata_images() {
  local minikube_available=0
  if ensure_minikube_running_if_exists "$MINIKUBE_PROFILE"; then
    minikube_available=1
  fi

  local docker_refs
  docker_refs="$(collect_image_refs docker)"
  if [[ -n "$docker_refs" ]]; then
    echo "Removing INESData images from local Docker..."
    while IFS= read -r image_ref; do
      [[ -z "$image_ref" ]] && continue
      docker rmi -f "$image_ref" >/dev/null 2>&1 || true
    done <<< "$docker_refs"
  fi

  if [[ "$minikube_available" -eq 1 ]]; then
    local mini_refs
    mini_refs="$(collect_image_refs minikube)"
    if [[ -n "$mini_refs" ]]; then
      echo "Removing INESData images from minikube cache..."
      while IFS= read -r image_ref; do
        [[ -z "$image_ref" ]] && continue
        if ! minikube -p "$MINIKUBE_PROFILE" image rm "$image_ref" >/dev/null 2>&1; then
          minikube -p "$MINIKUBE_PROFILE" ssh "docker rmi -f $image_ref || true" >/dev/null 2>&1 || true
        fi
      done <<< "$mini_refs"
    fi
  fi
}

prune_component_images_before_build() {
  local full_repo="$1"

  local docker_refs
  docker_refs="$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^${full_repo}:" || true)"
  while IFS= read -r image_ref; do
    [[ -z "$image_ref" ]] && continue
    docker rmi -f "$image_ref" >/dev/null 2>&1 || true
  done <<< "$docker_refs"

  if minikube_profile_exists "$MINIKUBE_PROFILE"; then
    local mini_refs
    mini_refs="$(minikube -p "$MINIKUBE_PROFILE" image ls 2>/dev/null | grep -E "${full_repo}:" || true)"
    while IFS= read -r image_ref; do
      [[ -z "$image_ref" ]] && continue
      if ! minikube -p "$MINIKUBE_PROFILE" image rm "$image_ref" >/dev/null 2>&1; then
        minikube -p "$MINIKUBE_PROFILE" ssh "docker rmi -f $image_ref || true" >/dev/null 2>&1 || true
      fi
    done <<< "$mini_refs"
  fi
}

restart_deployments_matching() {
  local regex="$1"
  local deployments
  deployments="$(kubectl -n "$NAMESPACE" get deploy -o name 2>/dev/null | grep -E "$regex" || true)"
  if [[ -z "$deployments" ]]; then
    return
  fi

  while IFS= read -r dep; do
    [[ -z "$dep" ]] && continue
    kubectl -n "$NAMESPACE" rollout restart "$dep" >/dev/null 2>&1 || true
    kubectl -n "$NAMESPACE" rollout status "$dep" --timeout=180s >/dev/null 2>&1 || true
  done <<< "$deployments"
}

refresh_runtime_for_component() {
  local component="$1"

  case "$component" in
    connector|connector-interface)
      restart_deployments_matching '^deployment.apps/conn-'
      ;;
    registration-service)
      restart_deployments_matching 'registration-service'
      ;;
    public-portal-backend|public-portal-frontend)
      restart_deployments_matching 'public-portal|backend|frontend'
      ;;
  esac
}

resolve_target_components() {
  local resolved=()

  if [[ -n "$COMPONENTS_CSV" ]]; then
    IFS=',' read -r -a requested <<< "$COMPONENTS_CSV"
    local item
    for item in "${requested[@]}"; do
      item="$(echo "$item" | xargs)"
      [[ -z "$item" ]] && continue
      if ! is_component_key "$item"; then
        echo "Invalid component in --components: $item" >&2
        exit 1
      fi
      resolved+=("$item")
    done
  elif [[ "$MODE" == "initial" ]]; then
    resolved=("${COMPONENT_KEYS[@]}")
  else
    local c
    for c in "${COMPONENT_KEYS[@]}"; do
      if component_has_changes "${SRC_DIR[$c]}"; then
        resolved+=("$c")
      fi
    done
  fi

  printf '%s\n' "${resolved[@]}"
}

if [[ "$MODE" == "initial" ]]; then
  echo "Initial mode: full clean of INESData images in Docker and minikube"
  remove_all_inesdata_images
fi

mapfile -t TARGET_COMPONENTS < <(resolve_target_components)

if [[ "${#TARGET_COMPONENTS[@]}" -eq 0 ]]; then
  echo "No components selected for build."
  echo "Manifest: $MANIFEST_FILE"
  exit 0
fi

mkdir -p "$(dirname "$MANIFEST_FILE")"
MANIFEST_TMP="${MANIFEST_FILE}.tmp.$$"
cleanup_manifest_tmp() {
  rm -f "$MANIFEST_TMP" 2>/dev/null || true
}
trap cleanup_manifest_tmp EXIT
echo -e "component\trepo_dir\timage\ttag\tfull_image\tbuild_cmd" > "$MANIFEST_TMP"

BUILT_COMPONENTS=()

MINIKUBE_READY=0
if [[ "$SKIP_MINIKUBE_LOAD" -eq 0 ]]; then
  if ensure_minikube_running_if_exists "$MINIKUBE_PROFILE"; then
    MINIKUBE_READY=1
  fi
fi

for component in "${TARGET_COMPONENTS[@]}"; do
  repo_dir="${SRC_DIR[$component]}"
  dockerfile="${DOCKERFILE[$component]}"
  image_repo="$REGISTRY_HOST/$REGISTRY_NAMESPACE/${IMAGE_NAME[$component]}"
  full_image="$image_repo:$IMAGE_TAG"
  extra_args="${EXTRA_ARGS[$component]}"

  if [[ ! -d "$repo_dir" ]]; then
    echo "Source directory not found for selected component '$component': $repo_dir" >&2
    exit 1
  fi

  echo
  echo "== Building $component =="
  prune_component_images_before_build "$image_repo"
  prepare_component_artifacts "$component" "$repo_dir"

  build_cmd="docker build -f $dockerfile -t $full_image $extra_args ."
  echo -e "$component\t$repo_dir\t$image_repo\t$IMAGE_TAG\t$full_image\t$build_cmd" >> "$MANIFEST_TMP"

  (cd "$repo_dir" && eval "$build_cmd")

  if [[ "$MINIKUBE_READY" -eq 1 ]]; then
    minikube -p "$MINIKUBE_PROFILE" image load "$full_image"
  fi

  if [[ "$REFRESH_RUNTIME" -eq 1 ]]; then
    refresh_runtime_for_component "$component"
  fi

  BUILT_COMPONENTS+=("$component")
done

if [[ "${#BUILT_COMPONENTS[@]}" -ne "${#TARGET_COMPONENTS[@]}" ]]; then
  echo "Manifest validation failed: built component count does not match selected component count." >&2
  echo "Selected: ${TARGET_COMPONENTS[*]}" >&2
  echo "Built: ${BUILT_COMPONENTS[*]}" >&2
  exit 1
fi

for component in "${TARGET_COMPONENTS[@]}"; do
  if ! awk -F $'\t' -v target="$component" 'NR > 1 && $1 == target {found=1; exit} END {exit(found ? 0 : 1)}' "$MANIFEST_TMP"; then
    echo "Manifest validation failed: missing component row '$component'" >&2
    exit 1
  fi
done

mv "$MANIFEST_TMP" "$MANIFEST_FILE"
trap - EXIT

echo
echo "Fast Step 1 complete"
echo "Mode: $MODE"
echo "Components: ${TARGET_COMPONENTS[*]}"
echo "Manifest: $MANIFEST_FILE"
