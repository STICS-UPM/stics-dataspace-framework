#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.kafka.yml"
DEFAULT_MESSAGE_COUNT=10
DEFAULT_POLL_TIMEOUT=20
DEFAULT_COMMAND="metrics"
DEFAULT_ADAPTER="inesdata"
DEFAULT_BROKER="localhost:9092"
DEFAULT_BURN_IN=60
DEFAULT_MAX_RETRIES=3
DEFAULT_RETRY_BACKOFF=15

COMMAND="$DEFAULT_COMMAND"
ADAPTER="$DEFAULT_ADAPTER"
MESSAGE_COUNT="$DEFAULT_MESSAGE_COUNT"
POLL_TIMEOUT="$DEFAULT_POLL_TIMEOUT"
BOOTSTRAP_SERVERS="$DEFAULT_BROKER"
BURN_IN_SECONDS="$DEFAULT_BURN_IN"
MAX_RETRIES="$DEFAULT_MAX_RETRIES"
RETRY_BACKOFF_SECONDS="$DEFAULT_RETRY_BACKOFF"
KEEP_BROKER=0
PREPARE_ONLY=0
TEARDOWN_ONLY=0
QUIET=0
TOPIC_STRATEGY="EXPERIMENT_TOPIC"
TOPIC_NAME=""
REUSE_BROKER_ON_RETRY=1

usage() {
  cat <<'EOF'
Usage: scripts/run_kafka_benchmark.sh [options]

Automates a reproducible external Kafka benchmark for PIONERA.

Options:
  --command <metrics|run>      Framework command to run (default: metrics)
  --adapter <name>             Adapter name (default: inesdata)
  --messages <count>           Number of Kafka messages to produce (default: 10)
  --poll-timeout <seconds>     Kafka poll timeout in seconds (default: 20)
  --bootstrap <host:port>      External Kafka bootstrap server (default: localhost:9092)
  --burn-in <seconds>          Seconds to observe broker stability before benchmark (default: 60)
  --max-retries <count>        Retry transient infrastructure failures (default: 3)
  --retry-backoff <seconds>    Base backoff between retries (default: 15)
  --topic-strategy <name>      Kafka topic strategy: EXPERIMENT_TOPIC or STATIC_TOPIC (default: EXPERIMENT_TOPIC)
  --topic-name <name>          Topic name when using STATIC_TOPIC
  --no-reuse-broker-on-retry   Force a clean broker restart on each retry
  --keep-broker                Keep kafka-local running after the benchmark
  --prepare-only               Start broker and stop before running the framework
  --teardown-only              Stop and remove kafka-local, then exit
  --quiet                      Reduce status output
  -h, --help                   Show this help
EOF
}

log() {
  if [[ "$QUIET" -eq 0 ]]; then
    echo "$@"
  fi
}

warn() {
  echo "[WARNING] $*" >&2
}

fail() {
  echo "[ERROR] $*" >&2
  exit 1
}

have_docker_compose() {
  docker compose version >/dev/null 2>&1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --command)
      COMMAND="$2"; shift 2 ;;
    --adapter)
      ADAPTER="$2"; shift 2 ;;
    --messages)
      MESSAGE_COUNT="$2"; shift 2 ;;
    --poll-timeout)
      POLL_TIMEOUT="$2"; shift 2 ;;
    --bootstrap)
      BOOTSTRAP_SERVERS="$2"; shift 2 ;;
    --burn-in)
      BURN_IN_SECONDS="$2"; shift 2 ;;
    --max-retries)
      MAX_RETRIES="$2"; shift 2 ;;
    --retry-backoff)
      RETRY_BACKOFF_SECONDS="$2"; shift 2 ;;
    --topic-strategy)
      TOPIC_STRATEGY="$2"; shift 2 ;;
    --topic-name)
      TOPIC_NAME="$2"; shift 2 ;;
    --no-reuse-broker-on-retry)
      REUSE_BROKER_ON_RETRY=0; shift ;;
    --keep-broker)
      KEEP_BROKER=1; shift ;;
    --prepare-only)
      PREPARE_ONLY=1; shift ;;
    --teardown-only)
      TEARDOWN_ONLY=1; shift ;;
    --quiet)
      QUIET=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      fail "Unknown option: $1" ;;
  esac
done

[[ "$COMMAND" =~ ^(metrics|run)$ ]] || fail "--command must be 'metrics' or 'run'"
[[ "$MESSAGE_COUNT" =~ ^[0-9]+$ ]] || fail "--messages must be numeric"
[[ "$POLL_TIMEOUT" =~ ^[0-9]+$ ]] || fail "--poll-timeout must be numeric"
[[ "$BURN_IN_SECONDS" =~ ^[0-9]+$ ]] || fail "--burn-in must be numeric"
[[ "$MAX_RETRIES" =~ ^[0-9]+$ ]] || fail "--max-retries must be numeric"
[[ "$RETRY_BACKOFF_SECONDS" =~ ^[0-9]+$ ]] || fail "--retry-backoff must be numeric"
[[ "$TOPIC_STRATEGY" =~ ^(EXPERIMENT_TOPIC|STATIC_TOPIC)$ ]] || fail "--topic-strategy must be EXPERIMENT_TOPIC or STATIC_TOPIC"
if [[ "$TOPIC_STRATEGY" == "STATIC_TOPIC" && -z "$TOPIC_NAME" ]]; then
  fail "--topic-name is required when --topic-strategy STATIC_TOPIC is used"
fi
(( MAX_RETRIES >= 1 )) || fail "--max-retries must be >= 1"

cd "$REPO_ROOT"

find_python() {
  if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    echo "$VIRTUAL_ENV/bin/python"
    return 0
  fi
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    echo "$REPO_ROOT/.venv/bin/python"
    return 0
  fi
  if [[ -x "$REPO_ROOT/deployers/inesdata/.venv/bin/python" ]]; then
    echo "$REPO_ROOT/deployers/inesdata/.venv/bin/python"
    return 0
  fi
  command -v python3 >/dev/null 2>&1 && { command -v python3; return 0; }
  command -v python >/dev/null 2>&1 && { command -v python; return 0; }
  return 1
}

PYTHON_BIN="$(find_python)" || fail "No Python interpreter found. Activate a venv first."

ensure_framework_requirements() {
  local requirements_file="$REPO_ROOT/requirements.txt"
  [[ -f "$requirements_file" ]] || fail "Missing framework requirements file: $requirements_file"

  log "Ensuring framework Python dependencies are installed in: $PYTHON_BIN"
  "$PYTHON_BIN" -m pip install -r "$requirements_file" >/dev/null
}

ensure_framework_requirements

ensure_newman_available() {
  local local_newman="$REPO_ROOT/node_modules/.bin/newman"

  if [[ -x "$local_newman" ]]; then
    return 0
  fi

  if command -v newman >/dev/null 2>&1; then
    return 0
  fi

  if [[ -f "$REPO_ROOT/package.json" ]]; then
    log "Ensuring local Node.js tooling is installed with npm..."
    npm install >/dev/null
  fi

  if [[ -x "$local_newman" ]] || command -v newman >/dev/null 2>&1; then
    return 0
  fi

  fail "Newman is not available. Run 'npm install' in the repo root or install it globally with 'npm install -g newman'."
}

ensure_newman_available

teardown_broker() {
  if have_docker_compose && [[ -f "$COMPOSE_FILE" ]]; then
    docker compose -f "$COMPOSE_FILE" down -v >/dev/null 2>&1 || true
  fi
  docker rm -f kafka-local >/dev/null 2>&1 || true
}

if [[ "$TEARDOWN_ONLY" -eq 1 ]]; then
  log "Stopping kafka-local..."
  teardown_broker
  exit 0
fi

start_broker() {
  if have_docker_compose && [[ -f "$COMPOSE_FILE" ]]; then
    log "Starting kafka-local with docker compose..."
    docker compose -f "$COMPOSE_FILE" up -d >/dev/null
  else
    fail "docker compose is required for this helper and was not found."
  fi
}

container_health() {
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' kafka-local 2>/dev/null || true
}

wait_for_health() {
  local deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
    local status
    status="$(container_health)"
    case "$status" in
      healthy)
        log "Kafka container is healthy."
        return 0
        ;;
      starting|running|created|restarting|"")
        sleep 5
        ;;
      exited|dead|unhealthy)
        return 1
        ;;
      *)
        sleep 5
        ;;
    esac
  done
  return 1
}

broker_has_instability() {
  local logs
  logs="$(docker logs --tail 300 kafka-local 2>&1 || true)"
  grep -Eq 'Fencing broker|Unable to send a heartbeat|Disconnecting from node .* due to request timeout|RequestTimedOutError' <<<"$logs"
}

burn_in_check() {
  log "Observing broker stability for ${BURN_IN_SECONDS}s..."
  sleep "$BURN_IN_SECONDS"
  docker ps --filter name=kafka-local | cat
  if broker_has_instability; then
    return 1
  fi
  return 0
}

latest_experiment() {
  ls -1dt "$REPO_ROOT"/experiments/* 2>/dev/null | head -n 1 || true
}

print_experiment_artifacts() {
  local experiment_dir="$1"
  log "Latest experiment: $experiment_dir"
  if [[ -f "$experiment_dir/kafka_metrics.json" ]]; then
    log "--- kafka_metrics.json ---"
    cat "$experiment_dir/kafka_metrics.json"
  fi
  if [[ -f "$experiment_dir/summary.md" ]]; then
    log "--- summary.md ---"
    sed -n '1,160p' "$experiment_dir/summary.md"
  fi
  if [[ -d "$experiment_dir/graphs" ]]; then
    log "--- generated graphs ---"
    ls -1 "$experiment_dir/graphs"
  fi
}

validate_kafka_result() {
  local experiment_dir="$1"
  "$PYTHON_BIN" - "$experiment_dir" <<'PY'
import json
import math
import pathlib
import sys

experiment_dir = pathlib.Path(sys.argv[1])
metrics_path = experiment_dir / "kafka_metrics.json"
if not metrics_path.exists():
    print("missing_kafka_metrics")
    sys.exit(10)

data = json.loads(metrics_path.read_text(encoding="utf-8"))
benchmark = data.get("kafka_benchmark") or {}
status = benchmark.get("status")
if status != "completed":
    print(f"benchmark_status={status or 'missing'}")
    sys.exit(10)

produced = benchmark.get("messages_produced")
consumed = benchmark.get("messages_consumed")
if produced is None or consumed is None or produced != consumed:
    print("message_count_mismatch")
    sys.exit(10)

for key in ("average_latency_ms", "min_latency_ms", "max_latency_ms", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "throughput_messages_per_second"):
    value = benchmark.get(key)
    if value is None:
        print(f"missing_{key}")
        sys.exit(10)
    numeric = float(value)
    if math.isnan(numeric) or math.isinf(numeric) or numeric < 0:
        print(f"invalid_{key}={value}")
        sys.exit(10)

print("benchmark_valid")
PY
}

run_framework_benchmark() {
  local attempt="$1"
  local before_experiment="$2"

  export KAFKA_BOOTSTRAP_SERVERS="$BOOTSTRAP_SERVERS"
  export KAFKA_TOPIC_STRATEGY="$TOPIC_STRATEGY"
  if [[ -n "$TOPIC_NAME" ]]; then
    export KAFKA_TOPIC_NAME="$TOPIC_NAME"
  else
    unset KAFKA_TOPIC_NAME
  fi
  export KAFKA_MESSAGE_COUNT="$MESSAGE_COUNT"
  export KAFKA_POLL_TIMEOUT_SECONDS="$POLL_TIMEOUT"

  log "Running framework benchmark (attempt ${attempt}/${MAX_RETRIES}): $PYTHON_BIN main.py $ADAPTER $COMMAND --kafka"
  if ! "$PYTHON_BIN" main.py "$ADAPTER" "$COMMAND" --kafka; then
    return 20
  fi

  local after_experiment
  after_experiment="$(latest_experiment)"
  if [[ -z "$after_experiment" ]]; then
    return 21
  fi
  if [[ "$after_experiment" == "$before_experiment" ]]; then
    warn "Latest experiment directory did not change; reusing $after_experiment"
  fi

  print_experiment_artifacts "$after_experiment"

  if validate_kafka_result "$after_experiment"; then
    log "Kafka benchmark accepted on attempt ${attempt}."
    return 0
  fi

  warn "Kafka benchmark result from $after_experiment is not valid enough to accept."
  return 22
}

retry_delay() {
  local attempt="$1"
  echo $(( RETRY_BACKOFF_SECONDS * attempt ))
}

attempt=1
need_fresh_broker=1
while (( attempt <= MAX_RETRIES )); do
  before_experiment="$(latest_experiment)"
  if (( need_fresh_broker == 1 )); then
    log "Cleaning previous kafka-local container..."
    teardown_broker

    if ! start_broker; then
      warn "Failed to start kafka-local on attempt ${attempt}."
    elif ! wait_for_health; then
      docker logs --tail 200 kafka-local || true
      warn "Kafka container did not become healthy on attempt ${attempt}."
    elif ! burn_in_check; then
      docker logs --tail 300 kafka-local || true
      warn "Kafka broker showed instability during burn-in on attempt ${attempt}."
    else
      need_fresh_broker=0
    fi
  fi

  if (( need_fresh_broker == 1 )); then
    :
  elif [[ "$PREPARE_ONLY" -eq 1 ]]; then
    log "Broker ready. Stopping here because --prepare-only was requested."
    exit 0
  elif run_framework_benchmark "$attempt" "$before_experiment"; then
    if [[ "$KEEP_BROKER" -eq 0 ]]; then
      log "Stopping kafka-local..."
      teardown_broker
    else
      log "Keeping kafka-local running because --keep-broker was requested."
    fi
    exit 0
  fi

  if (( attempt == MAX_RETRIES )); then
    break
  fi

  delay="$(retry_delay "$attempt")"
  warn "Retrying benchmark after ${delay}s (attempt ${attempt}/${MAX_RETRIES} failed due to infrastructure or invalid result)."
  if (( REUSE_BROKER_ON_RETRY == 0 || need_fresh_broker == 1 )); then
    teardown_broker
    need_fresh_broker=1
  else
    log "Reusing current kafka-local broker for the next retry."
  fi
  sleep "$delay"
  attempt=$((attempt + 1))
done

teardown_broker
fail "Kafka benchmark could not be completed successfully after ${MAX_RETRIES} attempts."
