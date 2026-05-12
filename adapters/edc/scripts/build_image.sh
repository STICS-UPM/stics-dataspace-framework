#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SYNC_SCRIPT="$ADAPTER_DIR/scripts/sync_sources.sh"

DEFAULT_SOURCE_DIR="$ADAPTER_DIR/sources/dashboard/asset-filter-template"
SOURCE_DIR="$DEFAULT_SOURCE_DIR"
DOCKERFILE="$ADAPTER_DIR/build/docker/connector.Dockerfile"
IMAGE_NAME="validation-environment/edc-connector"
IMAGE_TAG="local"
MINIKUBE_PROFILE="minikube"
CLUSTER_RUNTIME="${CLUSTER_RUNTIME:-minikube}"
K3S_IMAGE_IMPORT_COMMAND="${K3S_IMAGE_IMPORT_COMMAND:-sudo k3s ctr -n k8s.io images import}"
GRADLE_TASK=":final-connector:shadowJar"
CONNECTOR_JAR="final-connector/build/libs/connector.jar"
CONNECTOR_RUNTIME_DIR="final-connector"

APPLY=0
FORCE_BUILD=0
SKIP_MINIKUBE_LOAD=0
SYNC_SOURCE=""
SYNC_GIT_URL="https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard"
SYNC_SUBDIR="${PIONERA_EDC_REFERENCE_REPO_SUBDIR:-asset-filter-template}"

usage() {
  cat <<'EOF'
Usage: build_image.sh [--apply] [--source-dir <path>] [--image <name>] [--tag <tag>]
                      [--dockerfile <path>] [--gradle-task <task>] [--jar-path <path>]
                      [--minikube-profile <name>] [--cluster-runtime <minikube|k3s>]
                      [--skip-minikube-load] [--force-build]
                      [--sync-source <path>] [--sync-git-url <url>] [--sync-subdir <path>]

Build the local generic EDC connector image from the benchmark connector source
provided by ProyectoPIONERA/EDC-asset-filter-dashboard.

Options:
  --apply                    Execute the build workflow. Default is dry-run.
  --source-dir <path>        Override the source directory.
  --image <name>             Image repository name.
  --tag <tag>                Image tag.
  --dockerfile <path>        Dockerfile used to package the runtime.
  --gradle-task <task>       Gradle task used to assemble the connector jar.
  --jar-path <path>          Jar path relative to the source directory.
  --minikube-profile <name>  Minikube profile used for image load.
  --cluster-runtime <value>  Cluster runtime used for local image loading: minikube or k3s.
  --skip-minikube-load       Build the image but do not load it into the cluster runtime.
  --force-build              Force rebuilding connector.jar through Gradle even if it already exists.
  --sync-source <path>       Local source directory passed through to sync_sources.sh.
  --sync-git-url <url>       Git URL passed through to sync_sources.sh.
  --sync-subdir <path>       Connector subdirectory inside the synchronized repo.
  -h, --help                 Show this help message.
EOF
}

run_cmd() {
  local cmd="$1"
  echo "+ $cmd"
  if [[ "$APPLY" -eq 1 ]]; then
    bash -lc "$cmd"
  fi
}

remove_minikube_image_if_present() {
  local image_ref="$1"
  local cmd="minikube -p \"$MINIKUBE_PROFILE\" ssh \"docker image rm -f '$image_ref' >/dev/null 2>&1 || true\""
  echo "+ $cmd"
  if [[ "$APPLY" -eq 1 ]]; then
    minikube -p "$MINIKUBE_PROFILE" ssh "docker image rm -f '$image_ref' >/dev/null 2>&1 || true"
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

load_image_into_k3s() {
  local image_ref="$1"
  local archive_file

  archive_file="$(mktemp "${TMPDIR:-/tmp}/edc-image-XXXXXX.tar")"
  run_cmd "docker save \"$image_ref\" -o \"$archive_file\""
  run_cmd "$K3S_IMAGE_IMPORT_COMMAND \"$archive_file\""
  run_cmd "rm -f \"$archive_file\""
}

load_image_into_runtime() {
  local image_ref="$1"

  case "$CLUSTER_RUNTIME" in
    minikube)
      remove_minikube_image_if_present "$image_ref"
      run_cmd "minikube -p \"$MINIKUBE_PROFILE\" image load \"$image_ref\""
      ;;
    k3s)
      load_image_into_k3s "$image_ref"
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --source-dir)
      SOURCE_DIR="${2:-}"
      shift 2
      ;;
    --image)
      IMAGE_NAME="${2:-}"
      shift 2
      ;;
    --tag)
      IMAGE_TAG="${2:-}"
      shift 2
      ;;
    --dockerfile)
      DOCKERFILE="${2:-}"
      shift 2
      ;;
    --gradle-task)
      GRADLE_TASK="${2:-}"
      shift 2
      ;;
    --jar-path)
      CONNECTOR_JAR="${2:-}"
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
    --skip-minikube-load)
      SKIP_MINIKUBE_LOAD=1
      shift
      ;;
    --force-build)
      FORCE_BUILD=1
      shift
      ;;
    --sync-source)
      SYNC_SOURCE="${2:-}"
      shift 2
      ;;
    --sync-git-url)
      SYNC_GIT_URL="${2:-}"
      shift 2
      ;;
    --sync-subdir|--source-subdir)
      SYNC_SUBDIR="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

normalize_cluster_runtime

sync_cmd=("\"$SYNC_SCRIPT\"")
if [[ -n "$SYNC_SOURCE" ]]; then
  sync_cmd+=("--source" "\"$SYNC_SOURCE\"")
fi
if [[ -n "$SYNC_GIT_URL" ]]; then
  sync_cmd+=("--git-url" "\"$SYNC_GIT_URL\"")
fi
if [[ -n "$SYNC_SUBDIR" ]]; then
  sync_cmd+=("--source-subdir" "\"$SYNC_SUBDIR\"")
fi

if [[ ! -d "$SOURCE_DIR" || ! -x "$SOURCE_DIR/gradlew" ]]; then
  if [[ -z "$SYNC_SOURCE" && "$SOURCE_DIR" != "$DEFAULT_SOURCE_DIR" ]]; then
    echo "Connector source not ready in $SOURCE_DIR." >&2
    echo "Refusing to synchronize into a custom source directory. Provide a prepared --source-dir, or pass --sync-source explicitly." >&2
    exit 1
  fi

  echo "Connector source not ready in $SOURCE_DIR. Synchronizing configured benchmark connector source..."
  if [[ "$APPLY" -eq 1 ]]; then
    bash -lc "${sync_cmd[*]} --apply"
  else
    echo "+ ${sync_cmd[*]} --apply"
  fi
fi

if [[ -z "$SOURCE_DIR" || ! -d "$SOURCE_DIR" ]]; then
  echo "Source directory not found after synchronization: $SOURCE_DIR" >&2
  exit 1
fi

if [[ -z "$DOCKERFILE" || ! -f "$DOCKERFILE" ]]; then
  echo "Dockerfile not found: $DOCKERFILE" >&2
  exit 1
fi

if [[ ! -x "$SOURCE_DIR/gradlew" ]]; then
  if [[ -f "$SOURCE_DIR/gradlew" ]]; then
    run_cmd "chmod +x \"$SOURCE_DIR/gradlew\""
  else
    echo "Gradle wrapper not found: $SOURCE_DIR/gradlew" >&2
    exit 1
  fi
fi

FULL_IMAGE="$IMAGE_NAME:$IMAGE_TAG"
ABSOLUTE_CONNECTOR_JAR="$SOURCE_DIR/$CONNECTOR_JAR"
ABSOLUTE_CONNECTOR_RUNTIME_DIR="$SOURCE_DIR/$CONNECTOR_RUNTIME_DIR"
GRADLE_WRAPPER_JAR="$SOURCE_DIR/gradle/wrapper/gradle-wrapper.jar"
GRADLE_USER_HOME="$SOURCE_DIR/.gradle-user-home"

echo "Source dir:        $SOURCE_DIR"
echo "Dockerfile:        $DOCKERFILE"
echo "Gradle task:       $GRADLE_TASK"
echo "Connector jar:     $CONNECTOR_JAR"
echo "Image:             $FULL_IMAGE"
echo "Cluster runtime:   $CLUSTER_RUNTIME"
if [[ "$CLUSTER_RUNTIME" == "minikube" ]]; then
  echo "Minikube profile:  $MINIKUBE_PROFILE"
else
  echo "K3s import command:$K3S_IMAGE_IMPORT_COMMAND"
fi

connector_jar_rebuild_reason() {
  local jar_path="$1"
  if [[ ! -f "$jar_path" ]]; then
    echo "connector jar is missing"
    return 0
  fi

  local inputs=(
    "$SOURCE_DIR/settings.gradle.kts"
    "$SOURCE_DIR/gradle/libs.versions.toml"
    "$ABSOLUTE_CONNECTOR_RUNTIME_DIR/build.gradle.kts"
  )

  if [[ -d "$ABSOLUTE_CONNECTOR_RUNTIME_DIR/src" ]]; then
    while IFS= read -r input_path; do
      inputs+=("$input_path")
    done < <(find "$ABSOLUTE_CONNECTOR_RUNTIME_DIR/src" -type f | sort)
  fi

  for input_path in "${inputs[@]}"; do
    if [[ ! -e "$input_path" ]]; then
      continue
    fi
    if [[ "$input_path" -nt "$jar_path" ]]; then
      echo "source changed: ${input_path#$SOURCE_DIR/}"
      return 0
    fi
  done

  return 1
}

REBUILD_REASON=""
if [[ "$FORCE_BUILD" -eq 1 ]]; then
  REBUILD_REASON="force build requested"
else
  REBUILD_REASON="$(connector_jar_rebuild_reason "$ABSOLUTE_CONNECTOR_JAR" || true)"
fi

if [[ -f "$ABSOLUTE_CONNECTOR_JAR" && -z "$REBUILD_REASON" ]]; then
  echo "Reusing existing connector jar: $ABSOLUTE_CONNECTOR_JAR"
else
  if [[ -n "$REBUILD_REASON" ]]; then
    echo "Connector jar is outdated and will be rebuilt: $REBUILD_REASON"
  fi
  if [[ ! -f "$GRADLE_WRAPPER_JAR" ]]; then
    echo "Gradle wrapper jar not found: $GRADLE_WRAPPER_JAR" >&2
    exit 1
  fi

  run_cmd "mkdir -p \"$GRADLE_USER_HOME\""
  run_cmd "cd \"$SOURCE_DIR\" && GRADLE_USER_HOME=\"$GRADLE_USER_HOME\" java -classpath \"$GRADLE_WRAPPER_JAR\" org.gradle.wrapper.GradleWrapperMain --no-daemon -Dorg.gradle.workers.max=1 \"$GRADLE_TASK\" -x test"
fi

if [[ ! -f "$ABSOLUTE_CONNECTOR_JAR" ]]; then
  echo "Connector jar not found after preparation: $ABSOLUTE_CONNECTOR_JAR" >&2
  exit 1
fi

DOCKER_BUILD_CONTEXT="$SOURCE_DIR"
DOCKER_BUILD_JAR="$CONNECTOR_JAR"
if [[ "$APPLY" -eq 1 ]]; then
  DOCKER_BUILD_CONTEXT="$(mktemp -d)"
  cleanup_build_context() {
    rm -rf "$DOCKER_BUILD_CONTEXT"
  }
  trap cleanup_build_context EXIT
  cp "$ABSOLUTE_CONNECTOR_JAR" "$DOCKER_BUILD_CONTEXT/connector.jar"
  DOCKER_BUILD_JAR="connector.jar"
fi

run_cmd "docker build -f \"$DOCKERFILE\" --build-arg CONNECTOR_JAR=\"$DOCKER_BUILD_JAR\" -t \"$FULL_IMAGE\" \"$DOCKER_BUILD_CONTEXT\""

if [[ "$SKIP_MINIKUBE_LOAD" -eq 0 ]]; then
  load_image_into_runtime "$FULL_IMAGE"
fi

echo
echo "Suggested deployment overrides:"
echo "  PIONERA_EDC_CONNECTOR_IMAGE_NAME=$IMAGE_NAME"
echo "  PIONERA_EDC_CONNECTOR_IMAGE_TAG=$IMAGE_TAG"
