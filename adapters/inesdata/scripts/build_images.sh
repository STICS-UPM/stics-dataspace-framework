#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCES_DIR="$ADAPTER_DIR/sources"
MANIFESTS_DIR="${MANIFESTS_DIR:-/tmp/inesdata-manifests}"
DRY_RUN=1
TARGET="TODO"
MANIFEST_FILE_OVERRIDE=""
APPEND_MANIFEST=0
REGISTRY_HOST="${REGISTRY_HOST:-ghcr.io}"
REGISTRY_NAMESPACE="${REGISTRY_NAMESPACE:-inesdata}"
GRADLE_MAX_WORKERS="${GRADLE_MAX_WORKERS:-1}"
GRADLE_COMMON_ARGS="${GRADLE_COMMON_ARGS:---no-daemon --no-parallel -Dorg.gradle.workers.max=$GRADLE_MAX_WORKERS}"
LOCAL_DOCKERFILE_FIXUPS="${INESDATA_LOCAL_DOCKERFILE_FIXUPS:-true}"
DOCKER_CMD="${DOCKER_CMD:-${PIONERA_DOCKER_CMD:-}}"
DOCKER_BUILD_EXTRA_ARGS="${INESDATA_DOCKER_BUILD_EXTRA_ARGS:-${PIONERA_DOCKER_BUILD_EXTRA_ARGS:-}}"
DOCKER_BUILD_NO_CACHE="${INESDATA_DOCKER_BUILD_NO_CACHE:-${PIONERA_DOCKER_BUILD_NO_CACHE:-false}}"
TEMP_DOCKERFILES=()
EFFECTIVE_DOCKERFILE=""

cleanup_temp_dockerfiles() {
  local path
  for path in "${TEMP_DOCKERFILES[@]}"; do
    if [[ -n "$path" && -f "$path" ]]; then
      rm -f "$path"
    fi
  done
}

trap cleanup_temp_dockerfiles EXIT

usage() {
  cat <<'EOF'
Usage: build_images.sh [--apply] [--target <TODO|CHANGED|component>] [--manifest <path>] [--append-manifest]
                       [--registry-host <host>] [--namespace <name>]

Options:
  --apply               Execute docker build (default is dry-run).
  --target <value>      Build target. Use TODO for all components, CHANGED for modified source components, or one component key.
  --component <name>    Deprecated alias for --target <name>.
  --manifest <path>     Write output manifest to a specific path.
  --append-manifest     Append rows to an existing manifest file (header created if missing).
  --registry-host       Registry hostname. Default: ghcr.io
  --namespace           Registry namespace/org/user. Default: inesdata

Environment variables:
  REGISTRY_HOST
  REGISTRY_NAMESPACE
  MANIFESTS_DIR (default: /tmp/inesdata-manifests)
  GRADLE_MAX_WORKERS (default: 1)
  GRADLE_COMMON_ARGS (default: --no-daemon --no-parallel -Dorg.gradle.workers.max=<GRADLE_MAX_WORKERS>)
  INESDATA_LOCAL_DOCKERFILE_FIXUPS (default: true; use temporary Dockerfiles without modifying sources)
  DOCKER_CMD / PIONERA_DOCKER_CMD (default: docker, or Docker Desktop docker.exe on WSL)
  INESDATA_DOCKER_BUILD_EXTRA_ARGS / PIONERA_DOCKER_BUILD_EXTRA_ARGS
  INESDATA_DOCKER_BUILD_NO_CACHE / PIONERA_DOCKER_BUILD_NO_CACHE (default: false)

Component keys:
  connector
  connector-interface
  registration-service
  public-portal-backend
  public-portal-frontend
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      DRY_RUN=0
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
    --manifest)
      MANIFEST_FILE_OVERRIDE="${2:-}"
      shift 2
      ;;
    --append-manifest)
      APPEND_MANIFEST=1
      shift
      ;;
    --registry-host)
      REGISTRY_HOST="${2:-}"
      shift 2
      ;;
    --namespace)
      REGISTRY_NAMESPACE="${2:-}"
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

ALL_COMPONENTS=(
  connector
  connector-interface
  registration-service
  public-portal-backend
  public-portal-frontend
)

if [[ -z "$TARGET" ]]; then
  echo "Missing --target value" >&2
  usage
  exit 1
fi

if [[ "$TARGET" != "TODO" && "$TARGET" != "CHANGED" ]]; then
  is_valid_target=0
  for c in "${ALL_COMPONENTS[@]}"; do
    if [[ "$TARGET" == "$c" ]]; then
      is_valid_target=1
      break
    fi
  done
  if [[ "$is_valid_target" -ne 1 ]]; then
    echo "Invalid --target value: $TARGET" >&2
    usage
    exit 1
  fi
fi

mkdir -p "$MANIFESTS_DIR"

if [[ -n "$MANIFEST_FILE_OVERRIDE" ]]; then
  MANIFEST_FILE="$MANIFEST_FILE_OVERRIDE"
else
  TS_UTC="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
  MANIFEST_FILE="$MANIFESTS_DIR/images-$TS_UTC.tsv"
fi

if [[ "$APPEND_MANIFEST" -eq 1 ]]; then
  mkdir -p "$(dirname "$MANIFEST_FILE")"
fi

if [[ "$APPEND_MANIFEST" -eq 0 || ! -f "$MANIFEST_FILE" ]]; then
  echo -e "component\trepo_dir\timage\ttag\tfull_image\tbuild_cmd" > "$MANIFEST_FILE"
fi

declare -A SRC_DIR=(
  ["connector"]="$SOURCES_DIR/inesdata-connector"
  ["connector-interface"]="$SOURCES_DIR/inesdata-connector-interface"
  ["registration-service"]="$SOURCES_DIR/inesdata-registration-service"
  ["public-portal-backend"]="$SOURCES_DIR/inesdata-public-portal-backend"
  ["public-portal-frontend"]="$SOURCES_DIR/inesdata-public-portal-frontend"
)

declare -A IMAGE_NAME=(
  ["connector"]="inesdata-connector"
  ["connector-interface"]="inesdata-connector-interface"
  ["registration-service"]="inesdata-registration-service"
  ["public-portal-backend"]="inesdata-public-portal-backend"
  ["public-portal-frontend"]="inesdata-public-portal-frontend"
)

declare -A DOCKERFILE=(
  ["connector"]="docker/Dockerfile"
  ["connector-interface"]="docker/Dockerfile"
  ["registration-service"]="docker/Dockerfile"
  ["public-portal-backend"]="Dockerfile"
  ["public-portal-frontend"]="docker/Dockerfile"
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

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] $*"
  else
    eval "$@"
  fi
}

resolve_docker_cmd() {
  if [[ -n "${DOCKER_CMD:-}" ]]; then
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    DOCKER_CMD="docker"
    return
  fi
  if [[ -x "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]]; then
    DOCKER_CMD="/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
    return
  fi
  DOCKER_CMD="docker"
}

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

dockerfile_for_build() {
  local component="$1"
  local repo_dir="$2"
  local dockerfile="$3"
  local source_dockerfile="$repo_dir/$dockerfile"
  local dockerfile_dir
  local override_rel
  local override_dockerfile

  if ! is_truthy "$LOCAL_DOCKERFILE_FIXUPS"; then
    EFFECTIVE_DOCKERFILE="$dockerfile"
    return
  fi

  case "$component" in
    connector|connector-interface)
      ;;
    *)
      EFFECTIVE_DOCKERFILE="$dockerfile"
      return
      ;;
  esac

  if [[ ! -f "$source_dockerfile" ]]; then
    EFFECTIVE_DOCKERFILE="$dockerfile"
    return
  fi

  dockerfile_dir="$(dirname "$dockerfile")"
  override_rel="$dockerfile_dir/.pionera-${component}.Dockerfile"
  override_dockerfile="$repo_dir/$override_rel"
  mkdir -p "$(dirname "$override_dockerfile")"
  cp "$source_dockerfile" "$override_dockerfile"
  TEMP_DOCKERFILES+=("$override_dockerfile")

  case "$component" in
    connector)
      sed -i 's/adduser --no-create-home --disabled-password --ingroup/adduser --no-create-home --disabled-password --gecos "" --ingroup/' "$override_dockerfile"
      ;;
    connector-interface)
      sed -i 's/FROM node:18\.16-alpine as builder/FROM node:18.20-alpine as builder/' "$override_dockerfile"
      ;;
  esac

  EFFECTIVE_DOCKERFILE="$override_rel"
}

component_has_changes() {
  local repo_dir="$1"

  if [[ ! -d "$repo_dir" ]]; then
    return 1
  fi

  if ! git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    # If git metadata is unavailable, treat as changed to avoid skipping local sources.
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
  local should_prebuild=0

  if [[ -z "$artifact_rel" ]]; then
    return
  fi

  artifact_ref="$(artifact_reference_path "$artifact_path")"

  if [[ -z "$artifact_ref" ]]; then
    should_prebuild=1
  elif component_has_changes "$repo_dir"; then
    should_prebuild=1
  elif artifact_is_stale "$artifact_ref" "$repo_dir"; then
    should_prebuild=1
  fi

  if [[ "$should_prebuild" -ne 1 ]]; then
    return
  fi

  if [[ -z "$prebuild_args" ]]; then
    echo "Missing required artifact for $component: $artifact_path" >&2
    exit 1
  fi

  echo "Preparing artifacts for $component ($artifact_rel)"
  run_cmd "mkdir -p \"$gradle_user_home\""
  if [[ -f "$repo_dir/gradlew" && ! -x "$repo_dir/gradlew" ]]; then
    run_cmd "chmod +x \"$repo_dir/gradlew\""
  fi
  run_cmd "cd \"$repo_dir\" && GRADLE_USER_HOME=\"$gradle_user_home\" ./gradlew $GRADLE_COMMON_ARGS $prebuild_args"

  if [[ "$DRY_RUN" -eq 0 ]] && ! artifact_exists "$artifact_path"; then
    echo "Artifact still missing after prebuild for $component: $artifact_path" >&2
    exit 1
  fi
}

echo "Sources directory: $SOURCES_DIR"
echo "Manifest: $MANIFEST_FILE"
echo "Mode: $([[ "$DRY_RUN" -eq 1 ]] && echo "dry-run" || echo "apply")"
echo "Registry host: $REGISTRY_HOST"
echo "Registry namespace: $REGISTRY_NAMESPACE"
echo "Target: $TARGET"
echo "Gradle args: $GRADLE_COMMON_ARGS"
resolve_docker_cmd
echo "Docker command: $DOCKER_CMD"
if is_truthy "$DOCKER_BUILD_NO_CACHE"; then
  echo "Docker build cache: disabled"
else
  echo "Docker build cache: enabled"
fi
if [[ -n "${DOCKER_BUILD_EXTRA_ARGS:-}" ]]; then
  echo "Docker build extra args: $DOCKER_BUILD_EXTRA_ARGS"
fi

if [[ "$TARGET" == "TODO" ]]; then
  selected_components=("${ALL_COMPONENTS[@]}")
elif [[ "$TARGET" == "CHANGED" ]]; then
  selected_components=()
  for component in "${ALL_COMPONENTS[@]}"; do
    if component_has_changes "${SRC_DIR[$component]}"; then
      selected_components+=("$component")
    fi
  done

  if [[ "${#selected_components[@]}" -eq 0 ]]; then
    echo "No changed components detected under $SOURCES_DIR."
    echo "Build manifest generated: $MANIFEST_FILE"
    exit 0
  fi
else
  selected_components=("$TARGET")
fi

for component in "${selected_components[@]}"; do

  repo_dir="${SRC_DIR[$component]}"
  image="$REGISTRY_HOST/$REGISTRY_NAMESPACE/${IMAGE_NAME[$component]}"
  dockerfile="${DOCKERFILE[$component]}"
  extra_args="${EXTRA_ARGS[$component]}"

  if [[ ! -d "$repo_dir" ]]; then
    echo "Skipping $component: missing source directory at $repo_dir"
    continue
  fi

  prepare_component_artifacts "$component" "$repo_dir"

  date_tag="$(date -u +%Y%m%d)"
  if shortsha="$(git -C "$repo_dir" rev-parse --short HEAD 2>/dev/null)"; then
    if [[ -z "$(git -C "$repo_dir" status --porcelain -- .)" ]]; then
      tag="$date_tag-$shortsha"
    else
      dirty_stamp="$(date -u +%H%M%S)"
      tag="$date_tag-$shortsha-dirty-$dirty_stamp"
    fi
  else
    # Sources can be provided as plain directories without .git metadata.
    tag="$(date -u +%Y%m%d-%H%M%S)-local"
  fi
  full_image="$image:$tag"

  dockerfile_for_build "$component" "$repo_dir" "$dockerfile"
  effective_dockerfile="$EFFECTIVE_DOCKERFILE"
  docker_cmd_q="$(printf '%q' "$DOCKER_CMD")"
  cache_args=""
  if is_truthy "$DOCKER_BUILD_NO_CACHE"; then
    cache_args="--no-cache"
  fi
  build_cmd="$docker_cmd_q build $cache_args $DOCKER_BUILD_EXTRA_ARGS -f $effective_dockerfile -t $full_image $extra_args ."
  echo -e "$component\t$repo_dir\t$image\t$tag\t$full_image\t$build_cmd" >> "$MANIFEST_FILE"

  echo
  echo "== $component =="
  run_cmd "cd $repo_dir && $build_cmd"
done

echo
echo "Build manifest generated: $MANIFEST_FILE"
