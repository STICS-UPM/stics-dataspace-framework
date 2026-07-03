#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${WORK_DIR:-/tmp/inesdata_seed}"
NAMESPACE="${NAMESPACE:-demo}"
COMPONENTS_NAMESPACE="${COMPONENTS_NAMESPACE:-components}"
COMMON_SERVICES_NAMESPACE="${COMMON_SERVICES_NAMESPACE:-common-srvs}"
COMMON_KUBECONFIG="${COMMON_KUBECONFIG:-${AI_MODEL_HUB_COMMON_KUBECONFIG:-${K3S_KUBECONFIG_COMMON:-${KUBECONFIG:-}}}}"
COMMON_POSTGRES_POD="${COMMON_POSTGRES_POD:-common-srvs-postgresql-0}"
COUNT="${COUNT:-8}"
CONNECTORS_CSV="${CONNECTORS_CSV:-conn-citycouncil-demo,conn-company-demo}"
ADAPTER="${ADAPTER:-inesdata}"
CREDENTIALS_DIR="${CREDENTIALS_DIR:-$ROOT_DIR/inesdata-testing/deployments/DEV/demo}"
KEYCLOAK_TOKEN_URL="${KEYCLOAK_TOKEN_URL:-}"
CONNECTOR_K8S_NAMESPACES="${CONNECTOR_K8S_NAMESPACES:-}"
CONNECTOR_KUBECONFIGS="${CONNECTOR_KUBECONFIGS:-}"
CONNECTOR_PROTOCOL_URLS="${CONNECTOR_PROTOCOL_URLS:-}"
DEPLOYER_CONFIG_FILE="${DEPLOYER_CONFIG_FILE:-$ROOT_DIR/deployers/inesdata/deployer.config}"
MODEL_VOCABULARY_ID="${MODEL_VOCABULARY_ID:-JS_DAIMO_Model}"
MODEL_VOCABULARY_NAME="${MODEL_VOCABULARY_NAME:-DAIMO Model Metadata}"
MODEL_VOCABULARY_CATEGORY="${MODEL_VOCABULARY_CATEGORY:-machineLearning}"
MODEL_VOCABULARY_SCHEMA_FILE="${MODEL_VOCABULARY_SCHEMA_FILE:-}"
DATASET_VOCABULARY_ID="${DATASET_VOCABULARY_ID:-JS_DAIMO_Dataset}"
DATASET_VOCABULARY_NAME="${DATASET_VOCABULARY_NAME:-DAIMO Dataset Metadata}"
DATASET_VOCABULARY_CATEGORY="${DATASET_VOCABULARY_CATEGORY:-dataset}"
DATASET_VOCABULARY_SCHEMA_FILE="${DATASET_VOCABULARY_SCHEMA_FILE:-}"
DAIMO_NS="https://w3id.org/pionera/daimo#"
DCT_NS="http://purl.org/dc/terms/"
DCAT_NS="http://www.w3.org/ns/dcat#"
MODEL_FILE="$WORK_DIR/LGBM_Classifier_1.pkl"
SEED_SCOPE="${SEED_SCOPE:-models}"
USE_CASES_SOURCE_DIR="${USE_CASES_SOURCE_DIR:-${AI_MODEL_HUB_USE_CASE_MODEL_SERVER_SOURCE_DIR:-${AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR:-$ROOT_DIR/adapters/inesdata/sources/AIModelHub-Use-Cases}}}"
USE_CASE_MODEL_ASSET_JSON_DIR="${USE_CASE_MODEL_ASSET_JSON_DIR:-$ROOT_DIR/use_cases/use_case_models}"
USE_CASE_DATASET_ASSET_JSON_DIR="${USE_CASE_DATASET_ASSET_JSON_DIR:-$ROOT_DIR/use_cases/use_case_datasets}"
MOBILITY_SEGMENTS_DATASET_FILE="${MOBILITY_SEGMENTS_DATASET_FILE:-$USE_CASES_SOURCE_DIR/data/mobility-datasets/segments_test.csv}"
MOBILITY_ACTUAL_TRAVEL_TIME_DATASET_ID="${MOBILITY_ACTUAL_TRAVEL_TIME_DATASET_ID:-company-mobility-actual-travel-time-test}"
MOBILITY_DELAY_DATASET_ID="${MOBILITY_DELAY_DATASET_ID:-company-mobility-delay-test}"
MOBILITY_PREVIOUS_DELAY_DATASET_ID="${MOBILITY_PREVIOUS_DELAY_DATASET_ID:-company-mobility-previous-delay-test}"
MOBILITY_BENCHMARK_SAMPLE_ROWS="${MOBILITY_BENCHMARK_SAMPLE_ROWS:-30}"
MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME="${MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME:-segments_test_sample.csv}"
MOBILITY_ACTUAL_TRAVEL_TIME_SAMPLE_DATASET_ID="${MOBILITY_ACTUAL_TRAVEL_TIME_SAMPLE_DATASET_ID:-company-mobility-actual-travel-time-sample-test}"
MOBILITY_DELAY_SAMPLE_DATASET_ID="${MOBILITY_DELAY_SAMPLE_DATASET_ID:-company-mobility-delay-sample-test}"
MOBILITY_PREVIOUS_DELAY_SAMPLE_DATASET_ID="${MOBILITY_PREVIOUS_DELAY_SAMPLE_DATASET_ID:-company-mobility-previous-delay-sample-test}"
MOBILITY_SEGMENTS_DATASET_ID="${MOBILITY_SEGMENTS_DATASET_ID:-$MOBILITY_DELAY_DATASET_ID}"
LEGACY_MOBILITY_SEGMENTS_DATASET_ID="${LEGACY_MOBILITY_SEGMENTS_DATASET_ID:-company-mobility-segments-test}"
FLARES_5W1H_DATASET_FILE="${FLARES_5W1H_DATASET_FILE:-$USE_CASES_SOURCE_DIR/data/flares-datasets/5w1h_subtarea_1_test.json}"
FLARES_5W1H_DATASET_ID="${FLARES_5W1H_DATASET_ID:-company-flares-5w1h-test}"
FLARES_RELIABILITY_DATASET_FILE="${FLARES_RELIABILITY_DATASET_FILE:-$USE_CASES_SOURCE_DIR/data/flares-datasets/5w1h_subtarea_2_test.json}"
FLARES_RELIABILITY_DATASET_ID="${FLARES_RELIABILITY_DATASET_ID:-company-flares-reliability-test}"
USE_CASE_DATASET_IDS=(
  "$MOBILITY_ACTUAL_TRAVEL_TIME_DATASET_ID"
  "$MOBILITY_DELAY_DATASET_ID"
  "$MOBILITY_PREVIOUS_DELAY_DATASET_ID"
  "$MOBILITY_ACTUAL_TRAVEL_TIME_SAMPLE_DATASET_ID"
  "$MOBILITY_DELAY_SAMPLE_DATASET_ID"
  "$MOBILITY_PREVIOUS_DELAY_SAMPLE_DATASET_ID"
  "$FLARES_5W1H_DATASET_ID"
  "$FLARES_RELIABILITY_DATASET_ID"
)
STRICT_MODE="${STRICT_MODE:-0}"
MODEL_SET="${MODEL_SET:-mock}"
INCLUDE_USE_CASE_MODELS="${INCLUDE_USE_CASE_MODELS:-0}"
SKIP_USE_CASE_MODELS="${SKIP_USE_CASE_MODELS:-0}"
SKIP_INESDATA_MODELS="${SKIP_INESDATA_MODELS:-0}"
INCLUDE_FLARES_METRIC_MODELS="${INCLUDE_FLARES_METRIC_MODELS:-${AI_MODEL_HUB_INCLUDE_FLARES_METRIC_MODELS:-0}}"
USE_CASE_PUBLICATION_MODE="${USE_CASE_PUBLICATION_MODE:-${AI_MODEL_HUB_USE_CASE_PUBLICATION_MODE:-split}}"
CHECK_USE_CASE_MODEL_SERVER_CONTRACT="${CHECK_USE_CASE_MODEL_SERVER_CONTRACT:-${AI_MODEL_HUB_CHECK_USE_CASE_MODEL_SERVER_CONTRACT:-1}}"
USE_CASE_MODEL_SERVER_BASE_URL="${USE_CASE_MODEL_SERVER_BASE_URL:-}"
COMBINED_HTTP_COUNT="${COMBINED_HTTP_COUNT:-10}"
COMBINED_INESDATA_COUNT="${COMBINED_INESDATA_COUNT:-$COUNT}"
NEGOTIATION_TIMEOUT_SECONDS="${NEGOTIATION_TIMEOUT_SECONDS:-${AI_MODEL_HUB_SEED_NEGOTIATION_TIMEOUT_SECONDS:-180}}"
NEGOTIATION_POLL_INTERVAL_SECONDS="${NEGOTIATION_POLL_INTERVAL_SECONDS:-${AI_MODEL_HUB_SEED_NEGOTIATION_POLL_INTERVAL_SECONDS:-3}}"
NEGOTIATION_STATE_REQUEST_TIMEOUT_SECONDS="${NEGOTIATION_STATE_REQUEST_TIMEOUT_SECONDS:-${AI_MODEL_HUB_SEED_NEGOTIATION_STATE_REQUEST_TIMEOUT_SECONDS:-20}}"
NEGOTIATION_PORT_FORWARD_DELAY_SECONDS="${NEGOTIATION_PORT_FORWARD_DELAY_SECONDS:-${AI_MODEL_HUB_SEED_NEGOTIATION_PORT_FORWARD_DELAY_SECONDS:-3}}"
RECONCILE_DATASET_STORAGE="${RECONCILE_DATASET_STORAGE:-${AI_MODEL_HUB_RECONCILE_DATASET_STORAGE:-1}}"
DATASET_STORAGE_REGION="${DATASET_STORAGE_REGION:-${AI_MODEL_HUB_DATASET_STORAGE_REGION:-eu-central-1}}"

usage() {
  cat <<'EOF'
Usage: seed_ml_assets_for_connectors.sh [options]

Options:
  --namespace <ns>            Dataspace namespace/name used by legacy seed defaults (default: demo)
  --components-namespace <ns> Namespace where component fixtures run, including model-server (default: components)
  --common-services-namespace <ns>
                              Namespace where PostgreSQL is deployed (default: common-srvs)
  --common-kubeconfig <path>  Kubeconfig for common services in vm-distributed
  --adapter <name>            Dataspace adapter API mode: inesdata or edc (default: inesdata)
  --count <n>                 Number of InesDataStore assets per connector (default: 8)
  --connectors <csv>          Connectors list (default: conn-citycouncil-demo,conn-company-demo)
  --credentials-dir <path>    Folder containing credentials-connector-<name>.json
  --keycloak-token-url <url>  Token endpoint. If omitted, read from deployers/inesdata/deployer.config
  --connector-k8s-namespaces <map>
                              CSV map connector=namespace for port-forward targets
  --connector-kubeconfigs <map>
                              CSV map connector=kubeconfig for vm-distributed port-forwards
  --connector-protocol-urls <map>
                              CSV map connector=protocol-url for cross-connector negotiations
  --model-vocabulary-id <id>  Model vocabulary ID used in assetData (default: JS_DAIMO_Model)
  --model-vocabulary-name <n> Model vocabulary display name
  --model-vocabulary-category <cat>
                              Model vocabulary category (default: machineLearning)
  --model-vocabulary-schema <path>
                              Model JSON schema file. Default auto-detects daimo_model.schema.json
  --dataset-vocabulary-id <id>
                              Dataset vocabulary ID used in assetData (default: JS_DAIMO_Dataset)
  --dataset-vocabulary-name <n>
                              Dataset vocabulary display name
  --dataset-vocabulary-category <cat>
                              Dataset vocabulary category (default: dataset)
  --dataset-vocabulary-schema <path>
                              Dataset JSON schema file. Default auto-detects daimo_dataset.schema.json
  --vocabulary-id/name/category/schema
                              Legacy aliases applied to both DAIMO vocabularies
  --seed-scope <scope>        What to seed: vocabularies, models, datasets or all (default: models)
  --model-set <mode>          mock, use-cases or combined (default: mock)
  --include-use-case-models   Also seed FLARES/Mobility HttpData assets
  --skip-use-case-models      Skip FLARES/Mobility HttpData assets in use-cases/combined modes
  --skip-inesdata-models      Skip stored InesDataStore model placeholder assets
  --include-flares-metric-models
                              Also seed FLARES /metrics endpoints as separate model assets
  --skip-use-case-model-server-contract-check
                              Do not verify expected use-case routes before Step 10 seeding
  --use-case-publication-mode <mode>
                              How to place use-case models: mirrored, split or provider-only
                              (default: split, matching AIModelHub)
  --use-case-model-server-base-url <url>
                              Base URL for the real use-case model server
  --combined-http-count <n>   Mock HttpData assets kept in combined mode (default: 10)
  --combined-inesdata-count <n>
                              InesDataStore assets kept in combined mode (default: --count)
  --negotiation-timeout-seconds <n>
                              Max seconds to wait for each negotiation state (default: 180)
  --negotiation-poll-interval-seconds <n>
                              Seconds between negotiation state polls (default: 3)
  --negotiation-state-request-timeout-seconds <n>
                              Max seconds for each negotiation state request (default: 20)
  --negotiation-port-forward-delay-seconds <n>
                              Seconds to wait after opening each negotiation port-forward (default: 3)
  --skip-dataset-storage-reconcile
                              Skip post-Step 9 reconciliation of official uploaded benchmark datasets
  --strict                    Fail if any connector fails (default: disabled)
  -h, --help                  Show this help

Notes:
  - Connector passwords are always read from credentials files at runtime.
  - The DAIMO model and dataset vocabularies are created/updated first in each connector.
  - INESData file assets use Management API upload-chunk + finalize-upload.
  - EDC mode only creates standard EDC HttpData assets and policies/contracts.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)
      NAMESPACE="${2:-}"
      shift 2
      ;;
    --components-namespace)
      COMPONENTS_NAMESPACE="${2:-}"
      shift 2
      ;;
    --common-services-namespace)
      COMMON_SERVICES_NAMESPACE="${2:-}"
      shift 2
      ;;
    --common-kubeconfig)
      COMMON_KUBECONFIG="${2:-}"
      shift 2
      ;;
    --adapter)
      ADAPTER="${2:-}"
      shift 2
      ;;
    --count)
      COUNT="${2:-}"
      shift 2
      ;;
    --connectors)
      CONNECTORS_CSV="${2:-}"
      shift 2
      ;;
    --credentials-dir)
      CREDENTIALS_DIR="${2:-}"
      shift 2
      ;;
    --keycloak-token-url)
      KEYCLOAK_TOKEN_URL="${2:-}"
      shift 2
      ;;
    --connector-k8s-namespaces)
      CONNECTOR_K8S_NAMESPACES="${2:-}"
      shift 2
      ;;
    --connector-kubeconfigs)
      CONNECTOR_KUBECONFIGS="${2:-}"
      shift 2
      ;;
    --connector-protocol-urls)
      CONNECTOR_PROTOCOL_URLS="${2:-}"
      shift 2
      ;;
    --model-vocabulary-id)
      MODEL_VOCABULARY_ID="${2:-}"
      shift 2
      ;;
    --model-vocabulary-name)
      MODEL_VOCABULARY_NAME="${2:-}"
      shift 2
      ;;
    --model-vocabulary-category)
      MODEL_VOCABULARY_CATEGORY="${2:-}"
      shift 2
      ;;
    --model-vocabulary-schema)
      MODEL_VOCABULARY_SCHEMA_FILE="${2:-}"
      shift 2
      ;;
    --dataset-vocabulary-id)
      DATASET_VOCABULARY_ID="${2:-}"
      shift 2
      ;;
    --dataset-vocabulary-name)
      DATASET_VOCABULARY_NAME="${2:-}"
      shift 2
      ;;
    --dataset-vocabulary-category)
      DATASET_VOCABULARY_CATEGORY="${2:-}"
      shift 2
      ;;
    --dataset-vocabulary-schema)
      DATASET_VOCABULARY_SCHEMA_FILE="${2:-}"
      shift 2
      ;;
    --vocabulary-id)
      MODEL_VOCABULARY_ID="${2:-}"
      DATASET_VOCABULARY_ID="${2:-}"
      shift 2
      ;;
    --vocabulary-name)
      MODEL_VOCABULARY_NAME="${2:-}"
      DATASET_VOCABULARY_NAME="${2:-}"
      shift 2
      ;;
    --vocabulary-category)
      MODEL_VOCABULARY_CATEGORY="${2:-}"
      DATASET_VOCABULARY_CATEGORY="${2:-}"
      shift 2
      ;;
    --vocabulary-schema)
      MODEL_VOCABULARY_SCHEMA_FILE="${2:-}"
      DATASET_VOCABULARY_SCHEMA_FILE="${2:-}"
      shift 2
      ;;
    --seed-scope)
      SEED_SCOPE="${2:-}"
      shift 2
      ;;
    --model-set)
      MODEL_SET="${2:-}"
      shift 2
      ;;
    --include-use-case-models)
      INCLUDE_USE_CASE_MODELS=1
      shift
      ;;
    --skip-use-case-models)
      SKIP_USE_CASE_MODELS=1
      shift
      ;;
    --skip-inesdata-models)
      SKIP_INESDATA_MODELS=1
      shift
      ;;
    --include-flares-metric-models)
      INCLUDE_FLARES_METRIC_MODELS=1
      shift
      ;;
    --skip-use-case-model-server-contract-check)
      CHECK_USE_CASE_MODEL_SERVER_CONTRACT=0
      shift
      ;;
    --use-case-publication-mode)
      USE_CASE_PUBLICATION_MODE="${2:-}"
      shift 2
      ;;
    --use-case-model-server-base-url)
      USE_CASE_MODEL_SERVER_BASE_URL="${2:-}"
      shift 2
      ;;
    --combined-http-count)
      COMBINED_HTTP_COUNT="${2:-}"
      shift 2
      ;;
    --combined-inesdata-count)
      COMBINED_INESDATA_COUNT="${2:-}"
      shift 2
      ;;
    --negotiation-timeout-seconds)
      NEGOTIATION_TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --negotiation-poll-interval-seconds)
      NEGOTIATION_POLL_INTERVAL_SECONDS="${2:-}"
      shift 2
      ;;
    --negotiation-state-request-timeout-seconds)
      NEGOTIATION_STATE_REQUEST_TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --negotiation-port-forward-delay-seconds)
      NEGOTIATION_PORT_FORWARD_DELAY_SECONDS="${2:-}"
      shift 2
      ;;
    --skip-dataset-storage-reconcile)
      RECONCILE_DATASET_STORAGE=0
      shift
      ;;
    --strict)
      STRICT_MODE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

mkdir -p "$WORK_DIR"

if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || [[ "$COUNT" -lt 1 ]]; then
  echo "Invalid --count value: $COUNT" >&2
  exit 1
fi

positive_integer_or_default() {
  local value="$1"
  local default="$2"
  if [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$default"
  fi
}

expand_home_path() {
  local value="$1"
  case "$value" in
    "~") printf '%s' "$HOME" ;;
    "~/"*) printf '%s/%s' "$HOME" "${value#~/}" ;;
    *) printf '%s' "$value" ;;
  esac
}

if [[ -n "$COMMON_KUBECONFIG" ]]; then
  COMMON_KUBECONFIG="$(expand_home_path "$COMMON_KUBECONFIG")"
fi

NEGOTIATION_TIMEOUT_SECONDS="$(positive_integer_or_default "$NEGOTIATION_TIMEOUT_SECONDS" 180)"
NEGOTIATION_POLL_INTERVAL_SECONDS="$(positive_integer_or_default "$NEGOTIATION_POLL_INTERVAL_SECONDS" 3)"
NEGOTIATION_STATE_REQUEST_TIMEOUT_SECONDS="$(positive_integer_or_default "$NEGOTIATION_STATE_REQUEST_TIMEOUT_SECONDS" 20)"
NEGOTIATION_PORT_FORWARD_DELAY_SECONDS="$(positive_integer_or_default "$NEGOTIATION_PORT_FORWARD_DELAY_SECONDS" 3)"

MODEL_SET="$(echo "$MODEL_SET" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
USE_CASE_PUBLICATION_MODE="$(echo "$USE_CASE_PUBLICATION_MODE" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
ADAPTER="$(echo "$ADAPTER" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
case "$ADAPTER" in
  ""|"inesdata") ADAPTER="inesdata" ;;
  "edc") ;;
  *)
    echo "Invalid --adapter value: $ADAPTER. Expected inesdata or edc." >&2
    exit 1
    ;;
esac
if [[ "$ADAPTER" == "edc" ]]; then
  SKIP_INESDATA_MODELS=1
fi
case "$MODEL_SET" in
  ""|"fixture"|"deterministic") MODEL_SET="mock" ;;
  "real"|"usecases") MODEL_SET="use-cases" ;;
esac
if [[ "$MODEL_SET" != "mock" && "$MODEL_SET" != "use-cases" && "$MODEL_SET" != "combined" ]]; then
  echo "Invalid --model-set value: $MODEL_SET. Expected mock, use-cases or combined." >&2
  exit 1
fi
case "$USE_CASE_PUBLICATION_MODE" in
  ""|"mirror") USE_CASE_PUBLICATION_MODE="mirrored" ;;
  "owner-split"|"participant-split") USE_CASE_PUBLICATION_MODE="split" ;;
  "provider") USE_CASE_PUBLICATION_MODE="provider-only" ;;
esac
if [[ "$USE_CASE_PUBLICATION_MODE" != "mirrored" && "$USE_CASE_PUBLICATION_MODE" != "split" && "$USE_CASE_PUBLICATION_MODE" != "provider-only" ]]; then
  echo "Invalid --use-case-publication-mode value: $USE_CASE_PUBLICATION_MODE. Expected mirrored, split or provider-only." >&2
  exit 1
fi
if [[ "$INCLUDE_USE_CASE_MODELS" == "1" && "$MODEL_SET" == "mock" ]]; then
  MODEL_SET="use-cases"
fi
if [[ "$MODEL_SET" == "use-cases" || "$MODEL_SET" == "combined" ]]; then
  # The minimal AIModelHub Step 10 registers FLARES metric endpoints together
  # with FLARES/Mobility prediction endpoints.
  INCLUDE_FLARES_METRIC_MODELS=1
fi
SEED_SCOPE="$(echo "$SEED_SCOPE" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
case "$SEED_SCOPE" in
  vocabularies|models|datasets|all) ;;
  *)
    echo "Invalid --seed-scope value: $SEED_SCOPE. Expected vocabularies, models, datasets or all." >&2
    exit 1
    ;;
esac
if [[ "$SEED_SCOPE" == "models" || "$SEED_SCOPE" == "all" ]]; then
  if ! [[ "$COMBINED_HTTP_COUNT" =~ ^[0-9]+$ ]]; then
    echo "Invalid --combined-http-count value: $COMBINED_HTTP_COUNT" >&2
    exit 1
  fi
  if ! [[ "$COMBINED_INESDATA_COUNT" =~ ^[0-9]+$ ]]; then
    echo "Invalid --combined-inesdata-count value: $COMBINED_INESDATA_COUNT" >&2
    exit 1
  fi
fi

resolve_schema_file() {
  local target_var="$1"
  shift
  local configured="${!target_var}"
  if [[ -n "$configured" ]]; then
    if [[ -f "$configured" ]]; then
      return 0
    fi
    echo "Vocabulary schema file not found: $configured" >&2
    return 1
  fi

  local candidate
  for candidate in "$@"; do
    if [[ -f "$candidate" ]]; then
      printf -v "$target_var" '%s' "$candidate"
      return 0
    fi
  done

  echo "Could not find vocabulary schema file for $target_var." >&2
  return 1
}

if [[ -z "$KEYCLOAK_TOKEN_URL" ]]; then
  cfg_file="$DEPLOYER_CONFIG_FILE"
  if [[ ! -f "$cfg_file" ]]; then
    echo "Missing deployer config: $cfg_file" >&2
    exit 1
  fi

  kc_base="$(sed -n 's/^KC_URL=//p' "$cfg_file" | tail -n1)"
  if [[ -z "$kc_base" ]]; then
    kc_base="$(sed -n 's/^KC_INTERNAL_URL=//p' "$cfg_file" | tail -n1)"
  fi
  if [[ -z "$kc_base" ]]; then
    echo "Could not resolve KC_URL/KC_INTERNAL_URL from $cfg_file" >&2
    exit 1
  fi
  if [[ "$kc_base" != http* ]]; then
    kc_base="http://$kc_base"
  fi
  KEYCLOAK_TOKEN_URL="$kc_base/realms/$NAMESPACE/protocol/openid-connect/token"
fi

if ! resolve_schema_file MODEL_VOCABULARY_SCHEMA_FILE \
  "$ROOT_DIR/daimo_model.schema.json" \
  "$ROOT_DIR/adapters/inesdata/sources/AIModelHub/daimo_model.schema.json" \
  "$ROOT_DIR/JS_Metada_Daimo.schema.json" \
  "$ROOT_DIR/JS_Metadata_Daimo.schema.json" \
  "$ROOT_DIR/JS_Metadata_Daimo.schema.JSON"; then
  exit 1
fi

if ! resolve_schema_file DATASET_VOCABULARY_SCHEMA_FILE \
  "$ROOT_DIR/daimo_dataset.schema.json" \
  "$ROOT_DIR/adapters/inesdata/sources/AIModelHub/daimo_dataset.schema.json" \
  "$ROOT_DIR/JS_Metada_Daimo.schema.json" \
  "$ROOT_DIR/JS_Metadata_Daimo.schema.json" \
  "$ROOT_DIR/JS_Metadata_Daimo.schema.JSON"; then
  exit 1
fi

echo "Using model vocabulary schema: $MODEL_VOCABULARY_SCHEMA_FILE"
echo "Using model vocabulary id: $MODEL_VOCABULARY_ID"
echo "Using dataset vocabulary schema: $DATASET_VOCABULARY_SCHEMA_FILE"
echo "Using dataset vocabulary id: $DATASET_VOCABULARY_ID"
echo "Using seed scope: $SEED_SCOPE"
echo "Using use-case publication mode: $USE_CASE_PUBLICATION_MODE"

printf 'placeholder-model-bytes-%s\n' "$(date -u +%s)" > "$MODEL_FILE"

request_retry() {
  local out_file="$1"
  shift

  local code attempt
  for attempt in 1 2 3; do
    code="$(curl -s --max-time 45 -o "$out_file" -w '%{http_code}' "$@")"
    if [[ "$code" == "200" ]]; then
      echo "$code"
      return 0
    fi
    if [[ "$code" != "504" && "$code" != "000" ]]; then
      echo "$code"
      return 1
    fi
    sleep 2
  done

  echo "$code"
  return 1
}

allocate_local_port() {
  python3 -c 'import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()' 2>/dev/null || printf '%s\n' "19193"
}

schema_as_json_string() {
  local schema_file="$1"
  tr -d '\n' < "$schema_file" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

upsert_v3_asset() {
  local connector="$1"
  local asset_id="$2"
  local json_file="$3"
  local token="$4"
  local mgmt_url="$5"
  local asset_label="$6"
  local out_file="$WORK_DIR/${connector}_${asset_id}.create.out"
  local update_out_file="$WORK_DIR/${connector}_${asset_id}.update.out"
  local code update_code

  code="$(curl -s --max-time 30 -o "$out_file" -w '%{http_code}' \
    -X POST "$mgmt_url/v3/assets" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    --data-binary "@$json_file")" || true

  if [[ "$code" == "200" || "$code" == "204" ]]; then
    echo "[$connector] ${asset_label} asset $asset_id created (HTTP $code)"
    return 0
  fi

  if [[ "$code" == "409" ]]; then
    update_code="$(curl -s --max-time 30 -o "$update_out_file" -w '%{http_code}' \
      -X PUT "$mgmt_url/v3/assets" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$json_file")" || true

    if [[ "$update_code" == "200" || "$update_code" == "204" ]]; then
      echo "[$connector] ${asset_label} asset $asset_id updated (HTTP $update_code)"
      return 0
    fi

    echo "[$connector] ${asset_label} asset $asset_id update FAILED (HTTP ${update_code:-NA})" >&2
    cat "$update_out_file" >&2 2>/dev/null || true
    return 1
  fi

  echo "[$connector] ${asset_label} asset $asset_id FAILED (HTTP ${code:-NA})" >&2
  cat "$out_file" >&2 2>/dev/null || true
  return 1
}

delete_v3_asset_if_exists() {
  local connector="$1"
  local asset_id="$2"
  local token="$3"
  local mgmt_url="$4"
  local asset_label="$5"
  local out_file="$WORK_DIR/${connector}_${asset_id}.delete.out"
  local code

  code="$(curl -s --max-time 30 -o "$out_file" -w '%{http_code}' \
    -X DELETE "$mgmt_url/v3/assets/$asset_id" \
    -H "Authorization: Bearer $token")" || true

  if [[ "$code" == "200" || "$code" == "204" ]]; then
    echo "[$connector] ${asset_label} asset $asset_id deleted before reload (HTTP $code)"
    return 0
  fi

  if [[ "$code" == "404" ]]; then
    return 0
  fi

  if [[ "$code" == "409" ]]; then
    echo "[$connector] ${asset_label} asset $asset_id cannot be deleted because it is already referenced; keeping existing asset to avoid duplicates" >&2
    return 2
  fi

  echo "[$connector] ${asset_label} asset $asset_id delete FAILED (HTTP ${code:-NA})" >&2
  cat "$out_file" >&2 2>/dev/null || true
  return 1
}

delete_v3_resource_if_exists() {
  local connector="$1"
  local resource_path="$2"
  local resource_id="$3"
  local token="$4"
  local mgmt_url="$5"
  local resource_label="$6"
  local out_file="$WORK_DIR/${connector}_${resource_id}.delete.out"
  local code

  code="$(curl -s --max-time 30 -o "$out_file" -w '%{http_code}' \
    -X DELETE "$mgmt_url/$resource_path/$resource_id" \
    -H "Authorization: Bearer $token")" || true

  if [[ "$code" == "200" || "$code" == "204" ]]; then
    echo "[$connector] ${resource_label} $resource_id deleted (HTTP $code)"
    return 0
  fi

  if [[ "$code" == "404" ]]; then
    return 0
  fi

  echo "[$connector] ${resource_label} $resource_id delete skipped/failed (HTTP ${code:-NA})" >&2
  cat "$out_file" >&2 2>/dev/null || true
  return 1
}

retire_legacy_mobility_segments_dataset_asset() {
  local connector="$1" token="$2" mgmt_url="$3"
  local legacy_id="$LEGACY_MOBILITY_SEGMENTS_DATASET_ID"

  if [[ -z "$legacy_id" || "$legacy_id" == "$MOBILITY_ACTUAL_TRAVEL_TIME_DATASET_ID" || "$legacy_id" == "$MOBILITY_DELAY_DATASET_ID" || "$legacy_id" == "$MOBILITY_PREVIOUS_DELAY_DATASET_ID" ]]; then
    return 0
  fi

  delete_v3_resource_if_exists "$connector" "v3/contractdefinitions" "contract-seed-${legacy_id}" "$token" "$mgmt_url" "legacy Mobility dataset contract" || true
  delete_v3_resource_if_exists "$connector" "v3/policydefinitions" "policy-seed-${legacy_id}" "$token" "$mgmt_url" "legacy Mobility dataset policy" || true
  delete_v3_asset_if_exists "$connector" "$legacy_id" "$token" "$mgmt_url" "legacy Mobility dataset" || true
}

input_schema_fields_json_from_features_json() {
  local features_json="$1"
  python3 - "$features_json" <<'PY'
import json
import sys

features = json.loads(sys.argv[1])
fields = []
properties = {}
required = []
for feature in features:
    if not isinstance(feature, dict) or not feature.get("name"):
        continue
    name = str(feature["name"])
    field_type = str(feature.get("type") or "string")
    field = {
        "name": name,
        "type": field_type,
        "nullable": bool(feature.get("nullable", False)),
    }
    if feature.get("description") not in (None, ""):
        field["description"] = str(feature["description"])
    if feature.get("minValue") not in (None, ""):
        field["minValue"] = feature["minValue"]
    if feature.get("maxValue") not in (None, ""):
        field["maxValue"] = feature["maxValue"]
    fields.append(field)

    property_schema = {"type": field_type}
    if feature.get("description") not in (None, ""):
        property_schema["description"] = str(feature["description"])
    if feature.get("minValue") not in (None, ""):
        property_schema["minimum"] = feature["minValue"]
    if feature.get("maxValue") not in (None, ""):
        property_schema["maximum"] = feature["maxValue"]
    properties[name] = property_schema
    if not bool(feature.get("nullable", False)):
        required.append(name)

json_schema = {
    "type": "object",
    "properties": properties,
}
if required:
    json_schema["required"] = required

print(json.dumps({
    "fields": fields,
    "jsonSchema": json.dumps(json_schema, indent=2),
}, separators=(",", ":")))
PY
}

write_use_case_asset_json_from_fixture() {
  local fixture_file="$1"
  local output_file="$2"
  local model_base_url="${3:-}"
  local endpoint="${4:-}"

  python3 - "$fixture_file" "$output_file" "$model_base_url" "$endpoint" <<'PY'
import json
import sys

fixture_file, output_file, model_base_url, endpoint = sys.argv[1:5]
with open(fixture_file, encoding="utf-8") as handle:
    payload = json.load(handle)

if model_base_url and endpoint:
    data_address = payload.setdefault("dataAddress", {})
    data_address["baseUrl"] = model_base_url.rstrip("/") + endpoint

with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY
}

get_json_value() {
  local file="$1"
  local block="$2"
  local key="$3"
  sed -n "/\"$block\"[[:space:]]*:[[:space:]]*{/,/}/p" "$file" \
    | sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" \
    | head -n1
}

connector_short_name() {
  local connector="$1"
  connector="${connector#conn-}"
  connector="${connector%-$NAMESPACE}"
  printf '%s' "$connector"
}

lookup_connector_map() {
  local map_csv="$1"
  local connector="$2"
  local fallback="$3"
  local connector_short
  connector_short="$(connector_short_name "$connector")"

  local old_ifs="$IFS"
  local entry key value
  IFS=','
  for entry in $map_csv; do
    IFS="$old_ifs"
    entry="$(printf '%s' "$entry" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [[ -z "$entry" ]] && continue
    if [[ "$entry" == *"="* ]]; then
      key="${entry%%=*}"
      value="${entry#*=}"
    elif [[ "$entry" == *":"* ]]; then
      key="${entry%%:*}"
      value="${entry#*:}"
    else
      IFS=','
      continue
    fi
    key="$(printf '%s' "$key" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    value="$(printf '%s' "$value" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    if [[ "$key" == "$connector" || "$key" == "$connector_short" ]]; then
      printf '%s' "$value"
      IFS="$old_ifs"
      return 0
    fi
    IFS=','
  done
  IFS="$old_ifs"
  printf '%s' "$fallback"
}

extract_token_field() {
  local response="$1"
  local field="$2"
  printf '%s' "$response" \
    | sed -n "s/.*\"$field\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" \
    | head -n1
}

request_connector_token() {
  local username="$1"
  local password="$2"
  local connector="$3"
  local creds_label="$4"
  local response token err

  response="$(curl -s -X POST "$KEYCLOAK_TOKEN_URL" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=dataspace-users' \
    --data-urlencode "username=$username" \
    --data-urlencode "password=$password")"

  token="$(extract_token_field "$response" "access_token")"
  if [[ -n "$token" ]]; then
    printf '%s' "$token"
    return 0
  fi

  err="$(extract_token_field "$response" "error_description")"
  if [[ -z "$err" ]]; then
    err="$(extract_token_field "$response" "error")"
  fi
  [[ -z "$err" ]] && err="unknown token error"
  echo "[$connector] token request failed using $creds_label: $err" >&2
  return 1
}

ensure_vocabulary() {
  local connector="$1"
  local token="$2"
  local mgmt_url="$3"
  local vocab_base="$4"
  local vocabulary_id="$5"
  local vocabulary_name="$6"
  local vocabulary_category="$7"
  local vocabulary_schema_file="$8"
  local schema_str payload_file create_out update_out get_out get_code post_code put_code

  schema_str="$(schema_as_json_string "$vocabulary_schema_file")"
  payload_file="$WORK_DIR/vocabulary_${connector}_${vocabulary_id}.json"

  cat > "$payload_file" <<EOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@id": "$vocabulary_id",
  "name": "$vocabulary_name",
  "connectorId": "$connector",
  "category": "$vocabulary_category",
  "jsonSchema": "$schema_str"
}
EOF

  get_out="$WORK_DIR/vocabulary_${connector}_${vocabulary_id}.get.out"
  create_out="$WORK_DIR/vocabulary_${connector}_${vocabulary_id}.create.out"
  update_out="$WORK_DIR/vocabulary_${connector}_${vocabulary_id}.update.out"

  get_code="$(curl -s -o "$get_out" -w '%{http_code}' \
    "$mgmt_url/$vocab_base/$vocabulary_id" \
    -H "Authorization: Bearer $token")"

  if [[ "$get_code" == "200" ]]; then
    put_code="$(curl -s -o "$update_out" -w '%{http_code}' \
      -X PUT "$mgmt_url/$vocab_base" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$payload_file")"
    if [[ "$put_code" == "204" || "$put_code" == "200" ]]; then
      echo "[$connector] vocabulary '$vocabulary_id' updated"
      return 0
    fi
    if [[ "$put_code" != "404" ]]; then
      echo "[$connector] failed to update vocabulary '$vocabulary_id' (HTTP $put_code)" >&2
      cat "$update_out" >&2 || true
      return 1
    fi
    echo "[$connector] vocabulary '$vocabulary_id' update returned 404; creating it"
  fi

  post_code="$(curl -s -o "$create_out" -w '%{http_code}' \
    -X POST "$mgmt_url/$vocab_base" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    --data-binary "@$payload_file")"

  if [[ "$post_code" == "200" ]]; then
    echo "[$connector] vocabulary '$vocabulary_id' created"
    return 0
  fi

  if [[ "$post_code" == "409" ]]; then
    put_code="$(curl -s -o "$update_out" -w '%{http_code}' \
      -X PUT "$mgmt_url/$vocab_base" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$payload_file")"
    if [[ "$put_code" == "204" || "$put_code" == "200" ]]; then
      echo "[$connector] vocabulary '$vocabulary_id' updated after conflict"
      return 0
    fi
    echo "[$connector] vocabulary conflict but update failed (HTTP $put_code)" >&2
    cat "$update_out" >&2 || true
    return 1
  fi

  echo "[$connector] failed to create vocabulary '$vocabulary_id' (HTTP $post_code)" >&2
  cat "$create_out" >&2 || true
  return 1
}

ensure_daimo_vocabularies() {
  local connector="$1"
  local token="$2"
  local mgmt_url="$3"
  local vocab_base="$4"

  ensure_vocabulary \
    "$connector" "$token" "$mgmt_url" "$vocab_base" \
    "$MODEL_VOCABULARY_ID" "$MODEL_VOCABULARY_NAME" \
    "$MODEL_VOCABULARY_CATEGORY" "$MODEL_VOCABULARY_SCHEMA_FILE" || return 1

  ensure_vocabulary \
    "$connector" "$token" "$mgmt_url" "$vocab_base" \
    "$DATASET_VOCABULARY_ID" "$DATASET_VOCABULARY_NAME" \
    "$DATASET_VOCABULARY_CATEGORY" "$DATASET_VOCABULARY_SCHEMA_FILE" || return 1
}

# =============================================================================
# MODEL DEFINITIONS — 25 HttpData models served by model-server
# =============================================================================

MODEL_SERVER_BASE="${MODEL_SERVER_BASE:-${AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL:-${MODEL_SERVER_CONNECTOR_BASE_URL:-${AI_MODEL_HUB_MODEL_SERVER_BASE_URL:-http://model-server.${COMPONENTS_NAMESPACE}.svc.cluster.local:8080}}}}"
MODEL_SERVER_BASE="${MODEL_SERVER_BASE%/}"
if [[ -z "$USE_CASE_MODEL_SERVER_BASE_URL" ]]; then
  USE_CASE_MODEL_SERVER_BASE_URL="$MODEL_SERVER_BASE"
fi
USE_CASE_MODEL_SERVER_BASE_URL="${USE_CASE_MODEL_SERVER_BASE_URL%/}"

MODEL_SLUGS=(
  chest-xray pneumonia covid19 lung-nodule tuberculosis
  ecommerce-sentiment twitter-sentiment product-review customer-feedback social-media-sentiment
  bmi body-fat bmr ideal-weight health-risk
  iris-classifier flower-classifier plant-identifier botanical-classifier flora-recognition
  fraud-transaction credit-card-fraud payment-anomaly risk-scorer fraud-classifier
)

MODEL_TITLES=(
  "Chest X-Ray Classifier" "Pneumonia Detector" "COVID-19 Screener" "Lung Nodule Detector" "Tuberculosis Classifier"
  "E-commerce Sentiment" "Twitter Sentiment" "Product Review Classifier" "Customer Feedback Analyzer" "Social Media Sentiment"
  "BMI Calculator" "Body Fat Estimator" "BMR Calculator" "Ideal Weight Predictor" "Health Risk Assessor"
  "Iris Classifier" "Flower Type Classifier" "Plant Species Identifier" "Botanical Classifier" "Flora Recognition"
  "Fraud Detector" "Credit Card Fraud" "Payment Anomaly Detector" "Risk Scorer" "Financial Fraud Classifier"
)

MODEL_ENDPOINTS=(
  /api/v1/vision/chest-xray /api/v1/vision/pneumonia /api/v1/vision/covid19 /api/v1/vision/lung-nodule /api/v1/vision/tuberculosis
  /api/v1/nlp/ecommerce-sentiment /api/v1/nlp/twitter-sentiment /api/v1/nlp/product-review /api/v1/nlp/customer-feedback /api/v1/nlp/social-media
  /api/v1/health/bmi /api/v1/health/body-fat /api/v1/health/bmr /api/v1/health/ideal-weight /api/v1/health/risk-assessment
  /api/v1/classification/iris /api/v1/classification/flower /api/v1/classification/plant /api/v1/classification/botanical /api/v1/classification/flora
  /api/v1/fraud/transaction /api/v1/fraud/credit-card /api/v1/fraud/anomaly /api/v1/fraud/risk-scorer /api/v1/fraud/classifier
)

MODEL_DESCRIPTIONS=(
  "Classifies chest X-ray images for pathology detection"
  "Detects pneumonia patterns in medical imaging"
  "Screens medical images for COVID-19 indicators"
  "Identifies lung nodules and assesses malignancy risk"
  "Classifies tuberculosis indicators from chest radiographs"
  "Analyzes e-commerce product reviews for sentiment"
  "Performs sentiment analysis on Twitter posts"
  "Classifies product reviews by sentiment polarity"
  "Analyzes customer feedback for satisfaction scoring"
  "Monitors social media posts for sentiment trends"
  "Calculates Body Mass Index from weight and height"
  "Estimates body fat percentage from anthropometric data"
  "Computes Basal Metabolic Rate for nutrition planning"
  "Predicts ideal weight range based on height and frame"
  "Assesses overall health risk from biometric inputs"
  "Classifies Iris flower species from petal/sepal measurements"
  "Identifies flower types from morphological features"
  "Identifies plant species from botanical measurements"
  "Classifies botanical specimens by taxonomic family"
  "Recognizes flora categories from measurement data"
  "Detects fraudulent transactions in real time"
  "Identifies credit card fraud patterns"
  "Detects payment anomalies and unusual patterns"
  "Scores transaction risk for compliance review"
  "Classifies financial fraud by type and severity"
)

# Group index (0-based) for each model — determines input schema and metadata
MODEL_GROUPS=(0 0 0 0 0  1 1 1 1 1  2 2 2 2 2  3 3 3 3 3  4 4 4 4 4)

GROUP_TASKS=("Computer vision" "Natural Language Processing" "Tabular" "Tabular" "Predictive event")
GROUP_SUBTASKS=("Image Classification" "Text classification" "Other" "Other" "Other")
GROUP_ALGORITHMS=("Convolutional Neural Network" "Transformer" "Linear Regression" "Random Forest" "Gradient Boosting")
GROUP_FRAMEWORKS=("TensorFlow" "Custom" "scikit-learn" "scikit-learn" "XGBoost")
GROUP_LIBRARIES=("Keras" "Transformers" "scikit-learn" "scikit-learn" "XGBoost")

USE_CASE_MODEL_SLUGS=(
  flares-5w1h-albert
  flares-reliability-albert
  flares-5w1h-bert
  flares-reliability-bert
  flares-5w1h-distilbert
  flares-reliability-distilbert
  mobility-lightgbm-actual-travel-time
  mobility-randomforest-actual-travel-time
  mobility-catboost-actual-travel-time
  mobility-lightgbm-delay
  mobility-randomforest-delay
  mobility-catboost-delay
  mobility-lightgbm-previous-delay
  mobility-randomforest-previous-delay
  mobility-catboost-previous-delay
)

USE_CASE_MODEL_TITLES=(
  "FLARES 5W1H ALBERT"
  "FLARES Reliability ALBERT"
  "FLARES 5W1H BERT"
  "FLARES Reliability BERT"
  "FLARES 5W1H DistilBERT"
  "FLARES Reliability DistilBERT"
  "Mobility LightGBM Actual Travel Time"
  "Mobility Random Forest Actual Travel Time"
  "Mobility CatBoost Actual Travel Time"
  "Mobility LightGBM Delay"
  "Mobility Random Forest Delay"
  "Mobility CatBoost Delay"
  "Mobility LightGBM Previous Delay"
  "Mobility Random Forest Previous Delay"
  "Mobility CatBoost Previous Delay"
)

USE_CASE_MODEL_ENDPOINTS=(
  /flares/dccuchile-albert-base-spanish-5w1h
  /flares/dccuchile-albert-base-spanish-reliability
  /flares/dccuchile-bert-base-spanish-wwm-uncased-5w1h
  /flares/dccuchile-bert-base-spanish-wwm-uncased-reliability
  /flares/dccuchile-distilbert-base-spanish-uncased-5w1h
  /flares/dccuchile-distilbert-base-spanish-uncased-reliability
  /mobility/lightgbm_actual_travel_time
  /mobility/randomforest_actual_travel_time
  /mobility/catboost_actual_travel_time
  /mobility/lightgbm_delay
  /mobility/randomforest_delay
  /mobility/catboost_delay
  /mobility/lightgbm_previous_delay
  /mobility/randomforest_previous_delay
  /mobility/catboost_previous_delay
)

FLARES_METRIC_MODEL_SLUGS=(
  flares-5w1h-albert-metrics
  flares-reliability-albert-metrics
  flares-5w1h-bert-metrics
  flares-reliability-bert-metrics
  flares-5w1h-distilbert-metrics
  flares-reliability-distilbert-metrics
)

FLARES_METRIC_MODEL_TITLES=(
  "FLARES 5W1H ALBERT Metrics"
  "FLARES Reliability ALBERT Metrics"
  "FLARES 5W1H BERT Metrics"
  "FLARES Reliability BERT Metrics"
  "FLARES 5W1H DistilBERT Metrics"
  "FLARES Reliability DistilBERT Metrics"
)

FLARES_METRIC_MODEL_ENDPOINTS=(
  /flares/dccuchile-albert-base-spanish-5w1h/metrics
  /flares/dccuchile-albert-base-spanish-reliability/metrics
  /flares/dccuchile-bert-base-spanish-wwm-uncased-5w1h/metrics
  /flares/dccuchile-bert-base-spanish-wwm-uncased-reliability/metrics
  /flares/dccuchile-distilbert-base-spanish-uncased-5w1h/metrics
  /flares/dccuchile-distilbert-base-spanish-uncased-reliability/metrics
)

FLARES_METRIC_MODEL_DESCRIPTIONS=(
  "Computes FLARES 5W1H span metrics from native validation rows"
  "Computes FLARES reliability classification metrics from native validation rows"
  "Computes FLARES 5W1H span metrics from native validation rows"
  "Computes FLARES reliability classification metrics from native validation rows"
  "Computes FLARES 5W1H span metrics from native validation rows"
  "Computes FLARES reliability classification metrics from native validation rows"
)

USE_CASE_MODEL_DESCRIPTIONS=(
  "Extracts 5W1H spans from Spanish text using a fine-tuned ALBERT token classifier"
  "Classifies reliability for extracted FLARES spans using a fine-tuned ALBERT sequence classifier"
  "Extracts 5W1H spans from Spanish text using a fine-tuned BERT token classifier"
  "Classifies reliability for extracted FLARES spans using a fine-tuned BERT sequence classifier"
  "Extracts 5W1H spans from Spanish text using a fine-tuned DistilBERT token classifier"
  "Classifies reliability for extracted FLARES spans using a fine-tuned DistilBERT sequence classifier"
  "Predicts actual travel time for public transport segments using LightGBM"
  "Predicts actual travel time for public transport segments using Random Forest"
  "Predicts actual travel time for public transport segments using CatBoost"
  "Predicts segment delay for public transport trips using LightGBM"
  "Predicts segment delay for public transport trips using Random Forest"
  "Predicts segment delay for public transport trips using CatBoost"
  "Predicts previous segment delay for public transport trips using LightGBM"
  "Predicts previous segment delay for public transport trips using Random Forest"
  "Predicts previous segment delay for public transport trips using CatBoost"
)

USE_CASE_MODEL_TASKS=(
  "Natural Language Processing"
  "Natural Language Processing"
  "Natural Language Processing"
  "Natural Language Processing"
  "Natural Language Processing"
  "Natural Language Processing"
  "Tabular"
  "Tabular"
  "Tabular"
  "Tabular"
  "Tabular"
  "Tabular"
  "Tabular"
  "Tabular"
  "Tabular"
)

USE_CASE_MODEL_SUBTASKS=(
  "token-classification"
  "text-classification"
  "token-classification"
  "text-classification"
  "token-classification"
  "text-classification"
  "tabular-regression"
  "tabular-regression"
  "tabular-regression"
  "tabular-regression"
  "tabular-regression"
  "tabular-regression"
  "tabular-regression"
  "tabular-regression"
  "tabular-regression"
)

USE_CASE_MODEL_TASK_TYPES=(
  "classification"
  "classification"
  "classification"
  "classification"
  "classification"
  "classification"
  "regression"
  "regression"
  "regression"
  "regression"
  "regression"
  "regression"
  "regression"
  "regression"
  "regression"
)

USE_CASE_MODEL_MODALITIES=(
  '["text"]'
  '["text"]'
  '["text"]'
  '["text"]'
  '["text"]'
  '["text"]'
  '["tabular"]'
  '["tabular"]'
  '["tabular"]'
  '["tabular"]'
  '["tabular"]'
  '["tabular"]'
  '["tabular"]'
  '["tabular"]'
  '["tabular"]'
)

USE_CASE_MODEL_SUBTASK_DESCRIPTIONS=(
  "FLARES 5W1H span extraction"
  "FLARES reliability classification"
  "FLARES 5W1H span extraction"
  "FLARES reliability classification"
  "FLARES 5W1H span extraction"
  "FLARES reliability classification"
  "Public transport actual travel time prediction"
  "Public transport actual travel time prediction"
  "Public transport actual travel time prediction"
  "Public transport segment delay prediction"
  "Public transport segment delay prediction"
  "Public transport segment delay prediction"
  "Public transport previous delay prediction"
  "Public transport previous delay prediction"
  "Public transport previous delay prediction"
)

USE_CASE_MODEL_LIBRARIES=(
  "Transformers"
  "Transformers"
  "Transformers"
  "Transformers"
  "Transformers"
  "Transformers"
  "LightGBM"
  "scikit-learn"
  "CatBoost"
  "LightGBM"
  "scikit-learn"
  "CatBoost"
  "LightGBM"
  "scikit-learn"
  "CatBoost"
)

CITY_USE_CASE_MODEL_SLUGS=(
  flares-5w1h-albert
  flares-reliability-albert
  flares-5w1h-distilbert
  flares-reliability-distilbert
  mobility-lightgbm-actual-travel-time
  mobility-randomforest-actual-travel-time
)

COMPANY_USE_CASE_MODEL_SLUGS=(
  flares-5w1h-bert
  flares-reliability-bert
  mobility-catboost-actual-travel-time
  mobility-lightgbm-delay
  mobility-randomforest-delay
  mobility-catboost-delay
  mobility-lightgbm-previous-delay
  mobility-randomforest-previous-delay
  mobility-catboost-previous-delay
)

CITY_FLARES_METRIC_MODEL_SLUGS=(
  flares-5w1h-albert-metrics
  flares-reliability-albert-metrics
  flares-5w1h-distilbert-metrics
  flares-reliability-distilbert-metrics
)

COMPANY_FLARES_METRIC_MODEL_SLUGS=(
  flares-5w1h-bert-metrics
  flares-reliability-bert-metrics
)

# Per-connector group context — appended to title for differentiation
CITY_GROUP_CTX=("Municipal Health" "City Services" "Citizens Wellness" "City Botanical" "City Treasury")
COMPANY_GROUP_CTX=("Corporate Health" "Corp Analytics" "Employee Wellness" "AgriTech Lab" "Corp Finance")

connector_tag() {
  case "$1" in
    *citycouncil*) echo "city" ;;
    *company*)     echo "company" ;;
    *)
      # Topologies that do not use the demo connector names (e.g. vm-distributed
      # conn-org2/org3-pionera) carry their provider/consumer role in the
      # --connector-k8s-namespaces map. Map that role onto the demo tags so the
      # role-keyed model/dataset placement (city=provider, company=consumer)
      # still works: the consumer must receive the FLARES/mobility datasets.
      local _role
      _role="$(lookup_connector_map "$CONNECTOR_K8S_NAMESPACES" "$1" "")"
      case "$_role" in
        provider) echo "city" ;;
        consumer) echo "company" ;;
        *)
          connector_short_name "$1" \
            | tr -c '[:alnum:]' '_' \
            | sed 's/^_*//; s/_*$//; s/__*/_/g' \
            | cut -c1-32
          ;;
      esac
      ;;
  esac
}

group_context() {
  local tag="$1" group="$2"
  case "$tag" in
    city)    echo "${CITY_GROUP_CTX[$group]}" ;;
    company) echo "${COMPANY_GROUP_CTX[$group]}" ;;
    *)       echo "Group $group" ;;
  esac
}

use_case_model_owner_tag() {
  local slug="$1"
  case "$slug" in
    flares-5w1h-albert|flares-reliability-albert|flares-5w1h-distilbert|flares-reliability-distilbert|\
    flares-5w1h-albert-metrics|flares-reliability-albert-metrics|flares-5w1h-distilbert-metrics|flares-reliability-distilbert-metrics|\
    flares-dccuchile-albert-*|flares-dccuchile-distilbert-*|\
    mobility-lightgbm-actual-travel-time|mobility-randomforest-actual-travel-time)
      echo "city"
      ;;
    flares-5w1h-bert|flares-reliability-bert|flares-5w1h-bert-metrics|flares-reliability-bert-metrics|\
    flares-dccuchile-bert-base-*|\
    mobility-catboost-actual-travel-time|mobility-lightgbm-delay|mobility-randomforest-delay|mobility-catboost-delay|\
    mobility-lightgbm-previous-delay|mobility-randomforest-previous-delay|mobility-catboost-previous-delay)
      echo "company"
      ;;
    *)
      echo "both"
      ;;
  esac
}

should_publish_model_for_tag() {
  local tag="$1"
  local slug="$2"
  local owner
  owner="$(use_case_model_owner_tag "$slug")"
  case "$USE_CASE_PUBLICATION_MODE" in
    mirrored)
      return 0
      ;;
    provider-only)
      [[ "$owner" == "both" || "$tag" == "city" ]]
      ;;
    split)
      [[ "$owner" == "both" || "$owner" == "$tag" ]]
      ;;
    *)
      return 1
      ;;
  esac
}

input_features_json() {
  local group="$1"
  case "$group" in
    0) cat <<'GRP0'
[{"name":"image_url","type":"string","description":"URL of the medical image","nullable":false},{"name":"image_size","type":"string","description":"Image dimensions e.g. 512x512","nullable":false}]
GRP0
      ;;
    1) cat <<'GRP1'
[{"name":"text","type":"string","description":"Text to analyze for sentiment","nullable":false}]
GRP1
      ;;
    2) cat <<'GRP2'
[{"name":"weight_kg","type":"number","description":"Weight in kilograms","nullable":false,"minValue":1,"maxValue":300},{"name":"height_m","type":"number","description":"Height in meters","nullable":false,"minValue":0.5,"maxValue":2.5}]
GRP2
      ;;
    3) cat <<'GRP3'
[{"name":"sepal_length","type":"number","description":"Sepal length in cm","nullable":false},{"name":"sepal_width","type":"number","description":"Sepal width in cm","nullable":false},{"name":"petal_length","type":"number","description":"Petal length in cm","nullable":false},{"name":"petal_width","type":"number","description":"Petal width in cm","nullable":false}]
GRP3
      ;;
    4) cat <<'GRP4'
[{"name":"amount","type":"number","description":"Transaction amount","nullable":false,"minValue":0},{"name":"merchant_category","type":"string","description":"Merchant category code","nullable":false},{"name":"location","type":"string","description":"Transaction location","nullable":false},{"name":"timestamp","type":"string","description":"Transaction timestamp ISO 8601","nullable":false}]
GRP4
      ;;
  esac
}

input_example_json() {
  local group="$1"
  case "$group" in
    0) echo '{\"image_url\":\"https://example.com/xray.png\",\"image_size\":\"512x512\"}' ;;
    1) echo '{\"text\":\"This product is excellent and very useful\"}' ;;
    2) echo '{\"weight_kg\":70.0,\"height_m\":1.75}' ;;
    3) echo '{\"sepal_length\":5.1,\"sepal_width\":3.5,\"petal_length\":1.4,\"petal_width\":0.2}' ;;
    4) echo '{\"amount\":150.00,\"merchant_category\":\"retail\",\"location\":\"domestic\",\"timestamp\":\"2024-01-15T10:30:00Z\"}' ;;
  esac
}

use_case_input_features_json() {
  local slug="$1"
  case "$slug" in
    flares-5w1h-*)
      cat <<'FLARES_5W1H_FEATURES'
[{"name":"Id","type":"integer","description":"Input text identifier","nullable":false},{"name":"Text","type":"string","description":"Spanish text to analyze","nullable":false}]
FLARES_5W1H_FEATURES
      ;;
    flares-reliability-*)
      cat <<'FLARES_REL_FEATURES'
[{"name":"Id","type":"integer","description":"Input text identifier","nullable":false},{"name":"Text","type":"string","description":"Original Spanish text","nullable":false},{"name":"Tag_Start","type":"integer","description":"Span start character offset","nullable":false},{"name":"Tag_End","type":"integer","description":"Span end character offset","nullable":false},{"name":"5W1H_Label","type":"string","description":"5W1H span label","nullable":false},{"name":"Tag_Text","type":"string","description":"Extracted span text","nullable":false}]
FLARES_REL_FEATURES
      ;;
    mobility-lightgbm-previous-delay|mobility-randomforest-previous-delay|mobility-catboost-previous-delay)
      cat <<'MOBILITY_PREV_FEATURES'
[{"name":"trip_id","type":"string","description":"GTFS trip identifier","nullable":false},{"name":"from_stop_id","type":"string","description":"Origin stop identifier","nullable":false},{"name":"to_stop_id","type":"string","description":"Destination stop identifier","nullable":false},{"name":"route_id","type":"string","description":"GTFS route identifier","nullable":false},{"name":"scheduled_travel_time","type":"number","description":"Scheduled segment travel time in seconds","nullable":false},{"name":"shape_distance","type":"number","description":"Segment distance in meters","nullable":false},{"name":"is_peak","type":"integer","description":"Peak-hour indicator","nullable":false,"minValue":0,"maxValue":1},{"name":"hour_sin","type":"number","description":"Cyclic hour sine encoding","nullable":false},{"name":"hour_cos","type":"number","description":"Cyclic hour cosine encoding","nullable":false},{"name":"weekday_sin","type":"number","description":"Cyclic weekday sine encoding","nullable":false},{"name":"weekday_cos","type":"number","description":"Cyclic weekday cosine encoding","nullable":false}]
MOBILITY_PREV_FEATURES
      ;;
    *)
      cat <<'MOBILITY_FEATURES'
[{"name":"trip_id","type":"string","description":"GTFS trip identifier","nullable":false},{"name":"from_stop_id","type":"string","description":"Origin stop identifier","nullable":false},{"name":"to_stop_id","type":"string","description":"Destination stop identifier","nullable":false},{"name":"route_id","type":"string","description":"GTFS route identifier","nullable":false},{"name":"scheduled_travel_time","type":"number","description":"Scheduled segment travel time in seconds","nullable":false},{"name":"shape_distance","type":"number","description":"Segment distance in meters","nullable":false},{"name":"is_peak","type":"integer","description":"Peak-hour indicator","nullable":false,"minValue":0,"maxValue":1},{"name":"hour_sin","type":"number","description":"Cyclic hour sine encoding","nullable":false},{"name":"hour_cos","type":"number","description":"Cyclic hour cosine encoding","nullable":false},{"name":"weekday_sin","type":"number","description":"Cyclic weekday sine encoding","nullable":false},{"name":"weekday_cos","type":"number","description":"Cyclic weekday cosine encoding","nullable":false},{"name":"previous_delay_ratio","type":"number","description":"Previous delay divided by scheduled travel time","nullable":false},{"name":"previous_delay_delta","type":"number","description":"Previous delay delta in seconds","nullable":false}]
MOBILITY_FEATURES
      ;;
  esac
}

use_case_input_columns_json() {
  local slug="$1"
  case "$slug" in
    flares-5w1h-*) echo '["Id","Text"]' ;;
    flares-reliability-*) echo '["Id","Text","Tag_Start","Tag_End","5W1H_Label","Tag_Text"]' ;;
    mobility-lightgbm-previous-delay|mobility-randomforest-previous-delay|mobility-catboost-previous-delay)
      echo '["trip_id","from_stop_id","to_stop_id","route_id","scheduled_travel_time","shape_distance","is_peak","hour_sin","hour_cos","weekday_sin","weekday_cos"]'
      ;;
    *)
      echo '["trip_id","from_stop_id","to_stop_id","route_id","scheduled_travel_time","shape_distance","is_peak","hour_sin","hour_cos","weekday_sin","weekday_cos","previous_delay_ratio","previous_delay_delta"]'
      ;;
  esac
}

use_case_label_column() {
  local slug="$1"
  case "$slug" in
    flares-5w1h-*) echo "Tags" ;;
    flares-reliability-*) echo "Reliability_Label" ;;
    mobility-*-actual-travel-time) echo "actual_travel_time" ;;
    mobility-*-previous-delay) echo "previous_delay" ;;
    mobility-*-delay) echo "delay" ;;
    *) echo "label" ;;
  esac
}

use_case_input_example_json() {
  local slug="$1"
  case "$slug" in
    flares-5w1h-*)
      echo '[{\"Id\":840,\"Text\":\"El comité de medicamentos humanos espera concluir el análisis en marzo.\"}]'
      ;;
    flares-reliability-*)
      echo '[{\"Id\":840,\"Text\":\"El comité de medicamentos humanos espera concluir el análisis en marzo.\",\"Tag_Start\":0,\"Tag_End\":35,\"5W1H_Label\":\"WHO\",\"Tag_Text\":\"El comité de medicamentos humanos\"}]'
      ;;
    mobility-lightgbm-previous-delay|mobility-randomforest-previous-delay|mobility-catboost-previous-delay)
      echo '[{\"trip_id\":\"L13_1_05:45_LxI\",\"from_stop_id\":\"7716\",\"to_stop_id\":\"19219\",\"route_id\":\"13\",\"scheduled_travel_time\":120,\"shape_distance\":681.1956848810403,\"is_peak\":0,\"hour_sin\":0.7071067811865475,\"hour_cos\":0.7071067811865476,\"weekday_sin\":0.9749279121818236,\"weekday_cos\":-0.22252093395631434}]'
      ;;
    *)
      echo '[{\"trip_id\":\"L13_1_05:45_LxI\",\"from_stop_id\":\"7716\",\"to_stop_id\":\"19219\",\"route_id\":\"13\",\"scheduled_travel_time\":120,\"shape_distance\":681.1956848810403,\"is_peak\":0,\"hour_sin\":0.7071067811865475,\"hour_cos\":0.7071067811865476,\"weekday_sin\":0.9749279121818236,\"weekday_cos\":-0.22252093395631434,\"previous_delay_ratio\":0.2499999979166667,\"previous_delay_delta\":0.0}]'
      ;;
  esac
}

use_case_supported_metrics_json() {
  local slug="$1"
  case "$slug" in
    mobility-*) echo '["RMSE","MAE","MSE","R2"]' ;;
    flares-reliability-*) echo '["Accuracy","Precision","Recall","F1"]' ;;
    *) echo '["Precision","Recall","F1"]' ;;
  esac
}

flares_metric_input_features_json() {
  local slug="$1"
  case "$slug" in
    flares-5w1h-*-metrics)
      cat <<'FLARES_5W1H_METRIC_FEATURES'
[{"name":"Id","type":"integer","description":"Input text identifier","nullable":false},{"name":"Text","type":"string","description":"Spanish text to analyze","nullable":false},{"name":"Tags","type":"array","description":"Gold 5W1H span annotations","nullable":false}]
FLARES_5W1H_METRIC_FEATURES
      ;;
    *)
      cat <<'FLARES_RELIABILITY_METRIC_FEATURES'
[{"name":"Id","type":"integer","description":"Input text identifier","nullable":false},{"name":"Text","type":"string","description":"Original Spanish text","nullable":false},{"name":"5W1H_Label","type":"string","description":"5W1H span label","nullable":false},{"name":"Tag_Text","type":"string","description":"Extracted span text","nullable":false},{"name":"Tag_Start","type":"integer","description":"Span start character offset","nullable":false},{"name":"Tag_End","type":"integer","description":"Span end character offset","nullable":false},{"name":"Reliability_Label","type":"string","description":"Gold reliability label","nullable":false}]
FLARES_RELIABILITY_METRIC_FEATURES
      ;;
  esac
}

flares_metric_input_columns_json() {
  local slug="$1"
  case "$slug" in
    flares-5w1h-*-metrics)
      echo '["Id","Text"]'
      ;;
    *)
      echo '["Id","Text","5W1H_Label","Tag_Text","Tag_Start","Tag_End"]'
      ;;
  esac
}

flares_metric_label_column() {
  local slug="$1"
  case "$slug" in
    flares-5w1h-*-metrics)
      echo "Tags"
      ;;
    *)
      echo "Reliability_Label"
      ;;
  esac
}

flares_metric_input_example_json() {
  local slug="$1"
  case "$slug" in
    flares-5w1h-*-metrics)
      echo '{\"Id\":875,\"Text\":\"Ya en 1988, un grupo de biologos zarparon para recoger organismos marinos.\",\"Tags\":[{\"Tag_Start\":3,\"Tag_End\":10,\"5W1H_Label\":\"WHEN\",\"Tag_Text\":\"en 1988\"}]}'
      ;;
    *)
      echo '{\"Id\":6831,\"Text\":\"Lo Pais no deja de sorprendernos.\",\"5W1H_Label\":\"WHAT\",\"Tag_Text\":\"su explicacion\",\"Tag_Start\":42,\"Tag_End\":56,\"Reliability_Label\":\"no confiable\"}'
      ;;
  esac
}

# =============================================================================
# SEED 25 HttpData ASSETS
# =============================================================================

seed_http_data_assets() {
  local connector="$1" token="$2" mgmt_url="$3"
  local max_assets="${4:-${#MODEL_SLUGS[@]}}"
  local tag created=0 attempted=0
  tag="$(connector_tag "$connector")"

  for idx in "${!MODEL_SLUGS[@]}"; do
    if [[ "$idx" -ge "$max_assets" ]]; then
      break
    fi
    attempted=$((attempted + 1))
    local slug="${MODEL_SLUGS[$idx]}"
    local title="${MODEL_TITLES[$idx]}"
    local endpoint="${MODEL_ENDPOINTS[$idx]}"
    local desc="${MODEL_DESCRIPTIONS[$idx]}"
    local group="${MODEL_GROUPS[$idx]}"
    local ctx
    ctx="$(group_context "$tag" "$group")"

    local asset_id="${tag}-${slug}"
    local asset_title="${title} - ${ctx}"
    local task="${GROUP_TASKS[$group]}"
    local subtask="${GROUP_SUBTASKS[$group]}"
    local algo="${GROUP_ALGORITHMS[$group]}"
    local fw="${GROUP_FRAMEWORKS[$group]}"
    local library="${GROUP_LIBRARIES[$group]}"
    local input_feat input_schema input_ex
    input_feat="$(input_features_json "$group" | tr -d '\n')"
    input_schema="$(input_schema_fields_json_from_features_json "$input_feat")"
    input_ex="$(input_example_json "$group")"

    local auc recall f1
    auc="$(awk -v n="$idx" 'BEGIN{printf "%.2f", 0.84 + (n*0.003)}')"
    recall="$(awk -v n="$idx" 'BEGIN{printf "%.2f", 0.72 + (n*0.004)}')"
    f1="$(awk -v n="$idx" 'BEGIN{printf "%.2f", 0.70 + (n*0.004)}')"

    local json_file="$WORK_DIR/${connector}_${asset_id}.json"
    cat > "$json_file" <<ASSET_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/pionera/daimo#",
    "mls": "http://www.w3.org/ns/mls#"
  },
  "@id": "${asset_id}",
  "properties": {
    "name": "${asset_title}",
    "version": "1.0.$((idx + 1))",
    "contenttype": "application/json",
    "assetType": "machineLearning",
    "shortDescription": "${desc}",
    "dct:description": "${desc} Deployed as HTTP endpoint for ${connector}.",
    "dcterms:description": "${desc} Deployed as HTTP endpoint for ${connector}.",
    "dcat:keyword": ["machine-learning","http-model","${slug}","${tag}"],
    "assetData": {
      "${MODEL_VOCABULARY_ID}": {
        "dct:title": "${asset_title}",
        "dcterms:title": "${asset_title}",
        "dct:description": "${desc}",
        "dcterms:description": "${desc}",
        "daimo:task": "${task}",
        "daimo:subtask": "${subtask}",
        "daimo:algorithm": "${algo}",
        "daimo:framework": "${fw}",
        "daimo:library": "${library}",
        "dct:language": ["English","Spanish"],
        "dcterms:language": ["English","Spanish"],
        "dct:license": "apache-2.0",
        "dcterms:license": "apache-2.0",
        "daimo:inputSchema": ${input_schema},
        "daimo:input_features": ${input_feat},
        "daimo:input_example": "${input_ex}",
        "mls:ModelEvaluation": [
          {"metric":"AUC","value":${auc}},
          {"metric":"Recall","value":${recall}},
          {"metric":"F1","value":${f1}}
        ]
      }
    }
  },
  "dataAddress": {
    "type": "HttpData",
    "name": "${asset_id}",
    "baseUrl": "${MODEL_SERVER_BASE}${endpoint}",
    "proxyMethod": "true",
    "proxyBody": "true",
    "method": "POST",
    "contentType": "application/json"
  }
}
ASSET_EOF

    local out_file="$WORK_DIR/${connector}_${asset_id}.create.out"
    local code
    code="$(curl -s --max-time 30 -o "$out_file" -w '%{http_code}' \
      -X POST "$mgmt_url/v3/assets" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$json_file")" || true

    if [[ "$code" == "200" || "$code" == "204" || "$code" == "409" ]]; then
      created=$((created + 1))
      echo "[$connector] HttpData asset $asset_id created (HTTP $code)"
    else
      echo "[$connector] HttpData asset $asset_id FAILED (HTTP ${code:-NA})" >&2
      cat "$out_file" >&2 2>/dev/null || true
      return 1
    fi
  done

  echo "[$connector] HttpData assets created: $created/$attempted"
  return 0
}

discover_use_case_model_specs() {
  local output_file="$1"
  local models_response="$WORK_DIR/use_case_models.response.json"
  local models_code

  # Follow redirects (-L): the connector-facing base URL is intentionally http
  # (avoids cert validation for connector data transfers), but the external
  # Apache proxy 301-redirects http->https. This is a read-only discovery GET,
  # so following the redirect is safe and keeps the asset baseUrl unchanged.
  models_code="$(curl -sL --max-time 45 -o "$models_response" -w '%{http_code}' \
    "$USE_CASE_MODEL_SERVER_BASE_URL/models")" || true
  if [[ "$models_code" != "200" ]]; then
    echo "Use-case model-server discovery failed at $USE_CASE_MODEL_SERVER_BASE_URL/models (HTTP ${models_code:-NA})" >&2
    cat "$models_response" >&2 2>/dev/null || true
    return 1
  fi

  set +e
  python3 - "$models_response" > "$output_file" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)

def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", str(value).strip().lower())
    return value.strip("-") or "model"

rows = []
for model_name in payload.get("flares") or []:
    slug = f"flares-{slugify(model_name)}"
    endpoint = f"/flares/{model_name}"
    subtask = "5W1H extraction" if "5w1h" in str(model_name).lower() else "text reliability classification"
    rows.append(
        [
            slug,
            f"FLARES model {model_name}",
            endpoint,
            f"Real FLARES model exposed by the AI Model Hub use-case server: {model_name}.",
            "Natural Language Processing",
            subtask,
            "Transformer",
            "PyTorch",
            "Transformers",
        ]
    )

for model_name in payload.get("mobility") or []:
    slug = f"mobility-{slugify(model_name)}"
    endpoint = f"/mobility/{model_name}"
    rows.append(
        [
            slug,
            f"Mobility model {model_name}",
            endpoint,
            f"Real GTFS mobility prediction model exposed by the AI Model Hub use-case server: {model_name}.",
            "Time series regression",
            "Public transport travel-time prediction",
            "Supervised regression",
            "scikit-learn",
            "joblib",
        ]
    )

if not rows:
    sys.exit(2)

for row in rows:
    print("\t".join(item.replace("\t", " ") for item in row))
PY
  local py_status=$?
  set -e
  if [[ "$py_status" -eq 2 ]]; then
    echo "Use-case model-server returned no models at $USE_CASE_MODEL_SERVER_BASE_URL/models" >&2
    return 1
  fi
  if [[ "$py_status" -ne 0 ]]; then
    echo "Use-case model-server discovery response could not be parsed" >&2
    return 1
  fi
}

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1])[1:-1])' "$1"
}

validate_use_case_model_server_contract() {
  if [[ "$CHECK_USE_CASE_MODEL_SERVER_CONTRACT" != "1" ]]; then
    return 0
  fi
  if [[ "$SEED_SCOPE" != "models" && "$SEED_SCOPE" != "all" ]]; then
    return 0
  fi
  if [[ "$MODEL_SET" != "use-cases" && "$MODEL_SET" != "combined" ]]; then
    return 0
  fi
  if [[ "$SKIP_USE_CASE_MODELS" == "1" ]]; then
    return 0
  fi
  if [[ -z "$USE_CASE_MODEL_SERVER_BASE_URL" ]]; then
    echo "Use-case model-server base URL is required for AIModelHub Step 10 contract validation" >&2
    return 1
  fi

  local base_url="${USE_CASE_MODEL_SERVER_BASE_URL%/}"
  local openapi_response="$WORK_DIR/use_case_openapi.response.json"
  local expected_paths="$WORK_DIR/use_case_expected_paths.txt"
  local code endpoint

  code="$(curl -sL --max-time 45 -o "$openapi_response" -w '%{http_code}' \
    "$base_url/openapi.json")" || true
  if [[ "$code" != "200" ]]; then
    echo "Use-case model-server contract validation failed at $base_url/openapi.json (HTTP ${code:-NA})" >&2
    cat "$openapi_response" >&2 2>/dev/null || true
    return 1
  fi

  : > "$expected_paths"
  for endpoint in "${USE_CASE_MODEL_ENDPOINTS[@]}"; do
    printf '%s\n' "$endpoint" >> "$expected_paths"
  done
  if [[ "$INCLUDE_FLARES_METRIC_MODELS" == "1" ]]; then
    for endpoint in "${FLARES_METRIC_MODEL_ENDPOINTS[@]}"; do
      printf '%s\n' "$endpoint" >> "$expected_paths"
    done
  fi

  set +e
  python3 - "$openapi_response" "$expected_paths" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    expected = [line.strip() for line in handle if line.strip()]

paths = set((payload.get("paths") or {}).keys())
missing = [path for path in expected if path not in paths]
if missing:
    print("Use-case model-server is missing expected AIModelHub routes:", file=sys.stderr)
    for path in missing:
        print(f"  - {path}", file=sys.stderr)
    sys.exit(1)

print(f"Use-case model-server contract OK: {len(expected)} expected routes available")
PY
  local py_status=$?
  set -e
  return "$py_status"
}

seed_use_case_http_data_assets() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag created=0 asset_ids_file
  tag="$(connector_tag "$connector")"
  asset_ids_file="$WORK_DIR/${connector}_use_case_model_asset_ids.txt"

  local base_url="${USE_CASE_MODEL_SERVER_BASE_URL%/}"
  local expected="${#USE_CASE_MODEL_SLUGS[@]}"
  case "$tag" in
    city) expected="${#CITY_USE_CASE_MODEL_SLUGS[@]}" ;;
    company) expected="${#COMPANY_USE_CASE_MODEL_SLUGS[@]}" ;;
  esac

  : > "$asset_ids_file"

  for idx in "${!USE_CASE_MODEL_SLUGS[@]}"; do
    local slug="${USE_CASE_MODEL_SLUGS[$idx]}"
    if ! should_publish_model_for_tag "$tag" "$slug"; then
      continue
    fi

    local title="${USE_CASE_MODEL_TITLES[$idx]}"
    local endpoint="${USE_CASE_MODEL_ENDPOINTS[$idx]}"
    local desc="${USE_CASE_MODEL_DESCRIPTIONS[$idx]}"
    local task="${USE_CASE_MODEL_TASKS[$idx]}"
    local subtask="${USE_CASE_MODEL_SUBTASKS[$idx]}"
    local task_type="${USE_CASE_MODEL_TASK_TYPES[$idx]}"
    local modality="${USE_CASE_MODEL_MODALITIES[$idx]}"
    local subtask_description="${USE_CASE_MODEL_SUBTASK_DESCRIPTIONS[$idx]}"
    local library="${USE_CASE_MODEL_LIBRARIES[$idx]}"
    local input_feat input_schema input_ex supported_metrics
    input_feat="$(use_case_input_features_json "$slug" | tr -d '\n')"
    input_schema="$(input_schema_fields_json_from_features_json "$input_feat")"
    input_ex="$(use_case_input_example_json "$slug")"
    supported_metrics="$(use_case_supported_metrics_json "$slug")"

    local asset_id="${tag}-${slug}"
    local asset_title="${title} - PIONERA Use Case"
    local json_file="$WORK_DIR/${connector}_${asset_id}.json"
    local fixture_file="$USE_CASE_MODEL_ASSET_JSON_DIR/${asset_id}.json"

    if [[ -f "$fixture_file" ]]; then
      write_use_case_asset_json_from_fixture "$fixture_file" "$json_file" "$base_url" "$endpoint"
    else
    cat > "$json_file" <<ASSET_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/pionera/daimo#",
    "mls": "http://www.w3.org/ns/mls#"
  },
  "@id": "${asset_id}",
  "properties": {
    "name": "${asset_title}",
    "version": "2.0.$((idx + 1))",
    "contenttype": "application/json",
    "assetType": "machineLearning",
    "shortDescription": "${desc}",
    "dct:description": "${desc}. Served by the FLARES/Mobility FastAPI use-case server.",
    "dcterms:description": "${desc}. Served by the FLARES/Mobility FastAPI use-case server.",
    "dcat:keyword": ["machine-learning","http-model","pionera-use-case","flares","mobility","${slug}","${tag}"],
    "assetData": {
      "${MODEL_VOCABULARY_ID}": {
        "daimo:modality": ${modality},
        "daimo:taskType": "${task_type}",
        "daimo:taskCategory": "${task}",
        "daimo:subtask": "${subtask}",
        "daimo:subtaskDescription": "${subtask_description}",
        "daimo:endpointBehavior": "prediction",
        "daimo:requestShape": "batch",
        "dct:description": "${desc}. Served by the FLARES/Mobility FastAPI use-case server.",
        "daimo:libraryName": "${library}",
        "dct:language": ["Spanish"],
        "dct:license": "apache-2.0",
        "daimo:inputSchema": ${input_schema},
        "daimo:inputExample": "${input_ex}",
        "daimo:metrics": ${supported_metrics}
      }
    }
  },
  "dataAddress": {
    "type": "HttpData",
    "name": "${asset_id}",
    "baseUrl": "${base_url}${endpoint}",
    "proxyMethod": "true",
    "proxyBody": "true",
    "method": "POST",
    "contentType": "application/json"
  }
}
ASSET_EOF
    fi

    printf '%s\n' "$asset_id" >> "$asset_ids_file"
    if upsert_v3_asset "$connector" "$asset_id" "$json_file" "$token" "$mgmt_url" "Use-case HttpData"; then
      created=$((created + 1))
    else
      return 1
    fi
  done

  echo "[$connector] use-case HttpData assets created: $created/$expected"
  return 0
}

seed_flares_metric_http_data_assets() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag created=0 asset_ids_file
  tag="$(connector_tag "$connector")"
  asset_ids_file="$WORK_DIR/${connector}_use_case_model_asset_ids.txt"
  local base_url="${USE_CASE_MODEL_SERVER_BASE_URL%/}"

  for idx in "${!FLARES_METRIC_MODEL_SLUGS[@]}"; do
    local slug="${FLARES_METRIC_MODEL_SLUGS[$idx]}"
    if ! should_publish_model_for_tag "$tag" "$slug"; then
      continue
    fi
    local title="${FLARES_METRIC_MODEL_TITLES[$idx]}"
    local endpoint="${FLARES_METRIC_MODEL_ENDPOINTS[$idx]}"
    local desc="${FLARES_METRIC_MODEL_DESCRIPTIONS[$idx]}"
    local input_feat input_schema input_ex task subtask task_type modality subtask_description supported_metrics
    input_feat="$(flares_metric_input_features_json "$slug" | tr -d '\n')"
    input_schema="$(input_schema_fields_json_from_features_json "$input_feat")"
    input_ex="$(flares_metric_input_example_json "$slug")"
    if [[ "$slug" == flares-5w1h-*-metrics ]]; then
      task="Natural Language Processing"
      subtask="token-classification"
      subtask_description="FLARES 5W1H span extraction metrics"
      supported_metrics='["Precision","Recall","F1"]'
    else
      task="Natural Language Processing"
      subtask="text-classification"
      subtask_description="FLARES reliability classification metrics"
      supported_metrics='["Accuracy","Precision","Recall","F1"]'
    fi
    task_type="classification"
    modality='["text"]'

    local asset_id="${tag}-${slug}"
    local asset_title="${title} - PIONERA Use Case"
    local json_file="$WORK_DIR/${connector}_${asset_id}.json"
    local fixture_file="$USE_CASE_MODEL_ASSET_JSON_DIR/${asset_id}.json"

    if [[ -f "$fixture_file" ]]; then
      write_use_case_asset_json_from_fixture "$fixture_file" "$json_file" "$base_url" "$endpoint"
    else
    cat > "$json_file" <<ASSET_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/pionera/daimo#",
    "mls": "http://www.w3.org/ns/mls#"
  },
  "@id": "${asset_id}",
  "properties": {
    "name": "${asset_title}",
    "version": "2.1.$((idx + 1))",
    "contenttype": "application/json",
    "assetType": "machineLearning",
    "shortDescription": "${desc}",
    "dct:description": "${desc}. Served by the FLARES FastAPI metric endpoint.",
    "dcterms:description": "${desc}. Served by the FLARES FastAPI metric endpoint.",
    "dcat:keyword": ["machine-learning","metric-model","http-model","pionera-use-case","flares","${slug}","${tag}"],
    "assetData": {
      "${MODEL_VOCABULARY_ID}": {
        "daimo:modality": ${modality},
        "daimo:taskType": "${task_type}",
        "daimo:taskCategory": "${task}",
        "daimo:subtask": "${subtask}",
        "daimo:subtaskDescription": "${subtask_description}",
        "daimo:endpointBehavior": "metric",
        "daimo:requestShape": "batch",
        "dct:description": "${desc}. Served by the FLARES FastAPI metric endpoint.",
        "daimo:libraryName": "Transformers",
        "dct:language": ["Spanish"],
        "dct:license": "apache-2.0",
        "daimo:inputSchema": ${input_schema},
        "daimo:inputExample": "${input_ex}",
        "daimo:metrics": ${supported_metrics}
      }
    }
  },
  "dataAddress": {
    "type": "HttpData",
    "name": "${asset_id}",
    "baseUrl": "${base_url}${endpoint}",
    "proxyMethod": "true",
    "proxyBody": "true",
    "method": "POST",
    "contentType": "application/json"
  }
}
ASSET_EOF
    fi

    if upsert_v3_asset "$connector" "$asset_id" "$json_file" "$token" "$mgmt_url" "FLARES metric HttpData"; then
      created=$((created + 1))
      printf '%s\n' "$asset_id" >> "$asset_ids_file"
    else
      return 1
    fi
  done

  echo "[$connector] FLARES metric HttpData assets created: $created/${#FLARES_METRIC_MODEL_SLUGS[@]}"
  return 0
}

# =============================================================================
# SEED N InesDataStore ASSETS (upload-chunk + finalize)
# =============================================================================

seed_inesdata_store_assets() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag created=0
  tag="$(connector_tag "$connector")"

  local stamp
  stamp="$(date -u +%Y%m%d%H%M%S)"

  for idx in $(seq 1 "$COUNT"); do
    local id="${tag}-lgbm-$(printf '%02d' "$idx")"
    local title="LGBM ${connector} Model $(printf '%02d' "$idx")"
    local auc recall f1
    auc="$(awk -v n="$idx" 'BEGIN{printf "%.2f", 0.84 + (n*0.01)}')"
    recall="$(awk -v n="$idx" 'BEGIN{printf "%.2f", 0.72 + (n*0.01)}')"
    f1="$(awk -v n="$idx" 'BEGIN{printf "%.2f", 0.70 + (n*0.01)}')"
    local json_file="$WORK_DIR/${connector}_${id}.json"

    cat > "$json_file" <<INES_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/pionera/daimo#",
    "mls": "http://www.w3.org/ns/mls#"
  },
  "@id": "${id}",
  "properties": {
    "name": "${title}",
    "version": "1.0.${idx}",
    "contenttype": "application/octet-stream",
    "assetType": "machineLearning",
    "shortDescription": "Seeded LightGBM model ${idx} for ${connector}.",
    "dct:description": "Binary classifier for default probability estimation.",
    "dcterms:description": "Binary classifier for default probability estimation.",
    "dcat:byteSize": 5242880,
    "dcterms:format": "pkl",
    "dcat:keyword": ["machine-learning","lightgbm","inesdata","${tag}"],
    "assetData": {
      "${MODEL_VOCABULARY_ID}": {
        "dct:title": "${title}",
        "dcterms:title": "${title}",
        "dct:description": "Binary classifier for default probability estimation.",
        "dcterms:description": "Binary classifier for default probability estimation.",
        "daimo:task": "Tabular",
        "daimo:subtask": "Calculate default probability",
        "daimo:algorithm": "Gradient Boosting Decision Trees",
        "daimo:framework": "LightGBM",
        "daimo:library": "LightGBM",
        "dct:language": ["English","Spanish"],
        "dcterms:language": ["English","Spanish"],
        "dct:license": "apache-2.0",
        "dcterms:license": "apache-2.0",
        "daimo:input_features": [
          {"name":"age","type":"integer","description":"Applicant age in years","nullable":false,"minValue":18,"maxValue":99},
          {"name":"annual_income","type":"number","description":"Annual income in EUR","nullable":false,"minValue":0,"maxValue":1000000},
          {"name":"debt_ratio","type":"number","description":"Debt to income ratio","nullable":false,"minValue":0,"maxValue":2},
          {"name":"late_payments_12m","type":"integer","description":"Late payments in last 12 months","nullable":false,"minValue":0,"maxValue":24}
        ],
        "daimo:input_example": "{\"age\":41,\"annual_income\":52000,\"debt_ratio\":0.36,\"late_payments_12m\":1}",
        "mls:ModelEvaluation": [
          {"metric":"AUC","value":${auc}},
          {"metric":"Recall","value":${recall}},
          {"metric":"F1","value":${f1}}
        ]
      }
    }
  },
  "dataAddress": {"type":"InesDataStore","folder":"ml-seeded-assets"}
}
INES_EOF

    local up_code fin_code
    up_code="$(request_retry "$WORK_DIR/${connector}_${id}.upload.out" \
      -X POST "$mgmt_url/s3assets/upload-chunk" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Disposition: attachment; filename="LGBM_Classifier_1.pkl"' \
      -H 'Chunk-Index: 0' \
      -H 'Total-Chunks: 1' \
      -F "json=@$json_file;type=application/json" \
      -F "file=@$MODEL_FILE;type=application/octet-stream")" || true

    fin_code="$(request_retry "$WORK_DIR/${connector}_${id}.finalize.out" \
      -X POST "$mgmt_url/s3assets/finalize-upload" \
      -H "Authorization: Bearer $token" \
      -F "json=@$json_file;type=application/json" \
      -F 'fileName=LGBM_Classifier_1.pkl')" || true

    if [[ "$fin_code" == "200" || "$fin_code" == "409" ]] && [[ "$up_code" == "200" || "$up_code" == "000" || "$up_code" == "409" ]]; then
      created=$((created + 1))
      echo "[$connector] InesDataStore asset $id upload=$up_code finalize=$fin_code"
    else
      echo "[$connector] InesDataStore asset $id upload=${up_code:-NA} finalize=${fin_code:-NA}" >&2
      cat "$WORK_DIR/${connector}_${id}.finalize.out" >&2 || true
      return 1
    fi
  done

  echo "[$connector] InesDataStore assets created: $created/$COUNT"
  return 0
}

# =============================================================================
# CREATE POLICY + CONTRACT DEFINITION (allow-all, covers all assets)
# =============================================================================

create_policy_and_contract() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag
  tag="$(connector_tag "$connector")"

  local policy_id="policy-seed-${tag}"
  local contract_id="contract-seed-${tag}"

  # Create allow-all policy
  local policy_file="$WORK_DIR/${connector}_policy.json"
  cat > "$policy_file" <<PEOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "odrl": "http://www.w3.org/ns/odrl/2/"
  },
  "@id": "${policy_id}",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "Set",
    "permission": [],
    "prohibition": [],
    "obligation": []
  }
}
PEOF

  local policy_out="$WORK_DIR/${connector}_policy.out"
  local policy_code
  policy_code="$(curl -s --max-time 30 -o "$policy_out" -w '%{http_code}' \
    -X POST "$mgmt_url/v3/policydefinitions" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    --data-binary "@$policy_file")" || true

  if [[ "$policy_code" == "200" || "$policy_code" == "204" || "$policy_code" == "409" ]]; then
    echo "[$connector] policy '$policy_id' created (HTTP $policy_code)"
  else
    echo "[$connector] policy creation failed (HTTP ${policy_code:-NA})" >&2
    cat "$policy_out" >&2 2>/dev/null || true
    return 1
  fi

  # Create contract definition covering all machineLearning assets
  local contract_file="$WORK_DIR/${connector}_contract.json"
  cat > "$contract_file" <<CEOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@id": "${contract_id}",
  "accessPolicyId": "${policy_id}",
  "contractPolicyId": "${policy_id}",
  "assetsSelector": [
    {
      "operandLeft": "https://w3id.org/edc/v0.0.1/ns/assetType",
      "operator": "=",
      "operandRight": "machineLearning"
    }
  ]
}
CEOF

  local contract_out="$WORK_DIR/${connector}_contract.out"
  local contract_code
  contract_code="$(curl -s --max-time 30 -o "$contract_out" -w '%{http_code}' \
    -X POST "$mgmt_url/v3/contractdefinitions" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    --data-binary "@$contract_file")" || true

  if [[ "$contract_code" == "200" || "$contract_code" == "204" || "$contract_code" == "409" ]]; then
    echo "[$connector] contract '$contract_id' created (HTTP $contract_code)"
  else
    echo "[$connector] contract creation failed (HTTP ${contract_code:-NA})" >&2
    cat "$contract_out" >&2 2>/dev/null || true
    return 1
  fi

  return 0
}

create_use_case_model_policies_and_contracts() {
  local connector="$1" token="$2" mgmt_url="$3"
  local asset_ids_file="$WORK_DIR/${connector}_use_case_model_asset_ids.txt"

  if [[ ! -s "$asset_ids_file" ]]; then
    echo "[$connector] no use-case model asset ids found for narrow contracts: $asset_ids_file" >&2
    return 1
  fi

  local created=0
  while IFS= read -r asset_id; do
    [[ -z "$asset_id" ]] && continue
    local policy_id="policy-seed-${asset_id}"
    local contract_id="contract-seed-${asset_id}"
    local policy_file="$WORK_DIR/${connector}_${asset_id}_model_policy.json"
    local policy_out="$WORK_DIR/${connector}_${asset_id}_model_policy.out"
    local policy_code
    local contract_file="$WORK_DIR/${connector}_${asset_id}_model_contract.json"
    local contract_out="$WORK_DIR/${connector}_${asset_id}_model_contract.out"
    local contract_code

    cat > "$policy_file" <<PEOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "odrl": "http://www.w3.org/ns/odrl/2/"
  },
  "@id": "${policy_id}",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "Set",
    "permission": [],
    "prohibition": [],
    "obligation": []
  }
}
PEOF

    policy_code="$(curl -s --max-time 30 -o "$policy_out" -w '%{http_code}' \
      -X POST "$mgmt_url/v3/policydefinitions" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$policy_file")" || true

    if [[ "$policy_code" == "200" || "$policy_code" == "204" || "$policy_code" == "409" ]]; then
      echo "[$connector] model policy '$policy_id' created (HTTP $policy_code)"
    else
      echo "[$connector] model policy creation failed for $asset_id (HTTP ${policy_code:-NA})" >&2
      cat "$policy_out" >&2 2>/dev/null || true
      return 1
    fi

    cat > "$contract_file" <<CEOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@id": "${contract_id}",
  "accessPolicyId": "${policy_id}",
  "contractPolicyId": "${policy_id}",
  "assetsSelector": [
    {
      "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
      "operator": "=",
      "operandRight": "${asset_id}"
    }
  ]
}
CEOF

    contract_code="$(curl -s --max-time 30 -o "$contract_out" -w '%{http_code}' \
      -X POST "$mgmt_url/v3/contractdefinitions" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$contract_file")" || true

    if [[ "$contract_code" == "200" || "$contract_code" == "204" || "$contract_code" == "409" ]]; then
      created=$((created + 1))
      echo "[$connector] model contract '$contract_id' created (HTTP $contract_code)"
    else
      echo "[$connector] model contract creation failed for $asset_id (HTTP ${contract_code:-NA})" >&2
      cat "$contract_out" >&2 2>/dev/null || true
      return 1
    fi
  done < "$asset_ids_file"

  echo "[$connector] model contracts created: $created"
  return 0
}

# =============================================================================
# SEED USE-CASE BENCHMARK DATASETS (Company provider -> City Council consumer)
# =============================================================================

upload_seed_file_asset() {
  local connector="$1" token="$2" mgmt_url="$3" asset_id="$4" json_file="$5" source_file="$6" upload_filename="$7" content_type="$8" asset_label="$9"
  local delete_status=0 up_code fin_code

  delete_v3_asset_if_exists "$connector" "$asset_id" "$token" "$mgmt_url" "$asset_label" || delete_status=$?
  if [[ "$delete_status" -eq 1 ]]; then
    return 1
  fi
  local skip_finalize=0
  if [[ "$delete_status" -eq 2 ]]; then
    echo "[$connector] ${asset_label} asset $asset_id kept existing; refreshing S3 object only"
    skip_finalize=1
  fi

  up_code="$(request_retry "$WORK_DIR/${connector}_${asset_id}.upload.out" \
    -X POST "$mgmt_url/s3assets/upload-chunk" \
    -H "Authorization: Bearer $token" \
    -H "Content-Disposition: attachment; filename=\"$upload_filename\"" \
    -H 'Chunk-Index: 0' \
    -H 'Total-Chunks: 1' \
    -F "json=@$json_file;type=application/json" \
    -F "file=@$source_file;type=$content_type")" || true

  if [[ "$skip_finalize" -eq 1 ]]; then
    fin_code="skipped"
  else
    fin_code="$(request_retry "$WORK_DIR/${connector}_${asset_id}.finalize.out" \
      -X POST "$mgmt_url/s3assets/finalize-upload" \
      -H "Authorization: Bearer $token" \
      -F "json=@$json_file;type=application/json" \
      -F "fileName=$upload_filename")" || true
  fi

  if [[ "$fin_code" == "200" || "$fin_code" == "409" || "$fin_code" == "skipped" ]] && [[ "$up_code" == "200" || "$up_code" == "000" || "$up_code" == "409" ]]; then
    echo "[$connector] ${asset_label} asset $asset_id upload=$up_code finalize=$fin_code"
    return 0
  fi

  echo "[$connector] ${asset_label} asset $asset_id upload=${up_code:-NA} finalize=${fin_code:-NA}" >&2
  cat "$WORK_DIR/${connector}_${asset_id}.finalize.out" >&2 2>/dev/null || true
  return 1
}

seed_mobility_segments_dataset_asset() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag dataset_filename sample_dataset_file sample_rows
  tag="$(connector_tag "$connector")"

  if [[ "$tag" != "company" ]]; then
    return 0
  fi

  if [[ ! -f "$MOBILITY_SEGMENTS_DATASET_FILE" ]]; then
    echo "[$connector] Mobility dataset file not found: $MOBILITY_SEGMENTS_DATASET_FILE" >&2
    return 1
  fi

  dataset_filename="$(basename "$MOBILITY_SEGMENTS_DATASET_FILE")"
  sample_dataset_file="$WORK_DIR/$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME"
  sample_rows="$MOBILITY_BENCHMARK_SAMPLE_ROWS"
  if ! [[ "$sample_rows" =~ ^[0-9]+$ ]] || [[ "$sample_rows" -lt 1 ]]; then
    echo "[$connector] invalid MOBILITY_BENCHMARK_SAMPLE_ROWS=$sample_rows" >&2
    return 1
  fi
  head -n "$((sample_rows + 1))" "$MOBILITY_SEGMENTS_DATASET_FILE" > "$sample_dataset_file"

  retire_legacy_mobility_segments_dataset_asset "$connector" "$token" "$mgmt_url"

  local dataset_ids=(
    "$MOBILITY_ACTUAL_TRAVEL_TIME_DATASET_ID"
    "$MOBILITY_DELAY_DATASET_ID"
    "$MOBILITY_PREVIOUS_DELAY_DATASET_ID"
    "$MOBILITY_ACTUAL_TRAVEL_TIME_SAMPLE_DATASET_ID"
    "$MOBILITY_DELAY_SAMPLE_DATASET_ID"
    "$MOBILITY_PREVIOUS_DELAY_SAMPLE_DATASET_ID"
  )
  local source_files=(
    "$MOBILITY_SEGMENTS_DATASET_FILE"
    "$MOBILITY_SEGMENTS_DATASET_FILE"
    "$MOBILITY_SEGMENTS_DATASET_FILE"
    "$sample_dataset_file"
    "$sample_dataset_file"
    "$sample_dataset_file"
  )
  local upload_filenames=(
    "$dataset_filename"
    "$dataset_filename"
    "$dataset_filename"
    "$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME"
    "$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME"
    "$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME"
  )

  for idx in "${!dataset_ids[@]}"; do
    local asset_id="${dataset_ids[$idx]}"
    local json_file="$WORK_DIR/${connector}_${asset_id}.json"
    local fixture_file="$USE_CASE_DATASET_ASSET_JSON_DIR/${asset_id}.json"
    local source_file="${source_files[$idx]}"
    local upload_filename="${upload_filenames[$idx]}"

    if [[ ! -f "$fixture_file" ]]; then
      echo "[$connector] Mobility dataset fixture not found: $fixture_file" >&2
      return 1
    fi

    write_use_case_asset_json_from_fixture "$fixture_file" "$json_file"
    if ! upload_seed_file_asset "$connector" "$token" "$mgmt_url" "$asset_id" "$json_file" "$source_file" "$upload_filename" "text/csv" "Mobility dataset"; then
      return 1
    fi
  done
}

seed_flares_test_dataset_assets() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag
  tag="$(connector_tag "$connector")"

  if [[ "$tag" != "company" ]]; then
    return 0
  fi

  local dataset_ids=("$FLARES_5W1H_DATASET_ID" "$FLARES_RELIABILITY_DATASET_ID")
  local source_files=("$FLARES_5W1H_DATASET_FILE" "$FLARES_RELIABILITY_DATASET_FILE")
  local upload_filenames=("5w1h_subtarea_1_test.jsonl" "5w1h_subtarea_2_test.jsonl")
  local titles=("FLARES 5W1H Test Dataset" "FLARES Reliability Test Dataset")
  local descriptions=(
    "JSONL validation dataset for FLARES 5W1H span extraction metrics."
    "JSONL validation dataset for FLARES reliability classification metrics."
  )
  local subtasks=("token-classification" "text-classification")
  local task_types=("classification" "classification")
  local label_types=("span" "categorical")
  local keywords_json=(
    '["dataset","benchmark","validation","flares","5w1h","jsonl"]'
    '["dataset","benchmark","validation","flares","reliability","jsonl"]'
  )
  local vocabulary_keywords_json=(
    '["benchmark","validation","test","flares","span-extraction","jsonl"]'
    '["benchmark","validation","test","flares","classification","jsonl"]'
  )
  local input_json=(
    '["Id","Text"]'
    '["Id","Text","5W1H_Label","Tag_Text","Tag_Start","Tag_End"]'
  )
  local labels=("Tags" "Reliability_Label")

  for idx in "${!dataset_ids[@]}"; do
    local asset_id="${dataset_ids[$idx]}"
    local source_file="${source_files[$idx]}"
    local upload_filename="${upload_filenames[$idx]}"
    local title="${titles[$idx]}"
    local description="${descriptions[$idx]}"
    local subtask="${subtasks[$idx]}"
    local task_type="${task_types[$idx]}"
    local label_type="${label_types[$idx]}"
    local keywords="${keywords_json[$idx]}"
    local vocabulary_keywords="${vocabulary_keywords_json[$idx]}"
    local input="${input_json[$idx]}"
    local label="${labels[$idx]}"
    local json_file="$WORK_DIR/${connector}_${asset_id}.json"
    local fixture_file="$USE_CASE_DATASET_ASSET_JSON_DIR/${asset_id}.json"

    if [[ ! -f "$source_file" ]]; then
      echo "[$connector] FLARES dataset file not found: $source_file" >&2
      return 1
    fi

    if [[ -f "$fixture_file" ]]; then
      write_use_case_asset_json_from_fixture "$fixture_file" "$json_file"
    else
    cat > "$json_file" <<DATASET_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/pionera/daimo#"
  },
  "@id": "${asset_id}",
  "properties": {
    "name": "${title}",
    "version": "1.0.0",
    "contenttype": "application/x-ndjson",
    "assetType": "dataset",
    "shortDescription": "${description}",
    "dct:description": "${description}",
    "dcterms:description": "${description}",
    "dcterms:format": "jsonl",
    "fileName": "${upload_filename}",
    "dcat:keyword": ${keywords},
    "assetData": {
      "${DATASET_VOCABULARY_ID}": {
        "dct:title": "${title}",
        "dcterms:title": "${title}",
        "dct:description": "${description}",
        "dcterms:description": "${description}",
        "${DCT_NS}description": "${description}",
        "${DCT_NS}language": ["Spanish"],
        "${DCT_NS}license": "other",
        "${DCT_NS}format": "jsonl",
        "${DCAT_NS}keyword": ${vocabulary_keywords},
        "${DAIMO_NS}modality": ["text"],
        "${DAIMO_NS}taskCategory": "Natural Language Processing",
        "${DAIMO_NS}taskType": "${task_type}",
        "${DAIMO_NS}subtask": "${subtask}",
        "${DAIMO_NS}subtaskDescription": "${description}",
        "${DAIMO_NS}input": ${input},
        "${DAIMO_NS}label": "${label}",
        "${DAIMO_NS}labelType": "${label_type}",
        "${DAIMO_NS}datasetVersion": "1.0.0",
        "${DAIMO_NS}datasetRole": "benchmark",
        "${DAIMO_NS}protocol": "holdout-test-set"
      }
    }
  },
  "dataAddress": {"type":"InesDataStore"}
}
DATASET_EOF
    fi

    if ! upload_seed_file_asset "$connector" "$token" "$mgmt_url" "$asset_id" "$json_file" "$source_file" "$upload_filename" "application/x-ndjson" "FLARES dataset"; then
      return 1
    fi
  done

  return 0
}

reconcile_use_case_dataset_storage_assets() {
  local connector="$1"
  local creds_file="$2"

  if [[ "$RECONCILE_DATASET_STORAGE" != "1" ]]; then
    return 0
  fi
  if [[ "$ADAPTER" != "inesdata" ]]; then
    return 0
  fi
  if [[ "$(connector_tag "$connector")" != "company" ]]; then
    return 0
  fi

  local db_name db_user db_pass bucket
  db_name="$(get_json_value "$creds_file" database name)"
  db_user="$(get_json_value "$creds_file" database user)"
  db_pass="$(get_json_value "$creds_file" database passwd)"
  bucket="$(get_json_value "$creds_file" access_urls minio_bucket)"
  if [[ -z "$bucket" ]]; then
    bucket="$(get_json_value "$creds_file" public_access_urls minio_bucket)"
  fi

  if [[ -z "$db_name" || -z "$db_user" || -z "$db_pass" || -z "$bucket" ]]; then
    echo "[$connector] cannot reconcile AI Model Hub benchmark dataset storage: missing database or bucket metadata" >&2
    return 1
  fi

  local sql_file out_file err_file
  sql_file="$WORK_DIR/${connector}_ai_model_hub_dataset_storage_reconcile.sql"
  out_file="$WORK_DIR/${connector}_ai_model_hub_dataset_storage_reconcile.out"
  err_file="$WORK_DIR/${connector}_ai_model_hub_dataset_storage_reconcile.err"

  python3 - "$sql_file" "$bucket" "$DATASET_STORAGE_REGION" \
    "$MOBILITY_ACTUAL_TRAVEL_TIME_DATASET_ID" "segments_test.csv" \
    "$MOBILITY_DELAY_DATASET_ID" "segments_test.csv" \
    "$MOBILITY_PREVIOUS_DELAY_DATASET_ID" "segments_test.csv" \
    "$MOBILITY_ACTUAL_TRAVEL_TIME_SAMPLE_DATASET_ID" "$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME" \
    "$MOBILITY_DELAY_SAMPLE_DATASET_ID" "$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME" \
    "$MOBILITY_PREVIOUS_DELAY_SAMPLE_DATASET_ID" "$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME" \
    "$FLARES_5W1H_DATASET_ID" "5w1h_subtarea_1_test.jsonl" \
    "$FLARES_RELIABILITY_DATASET_ID" "5w1h_subtarea_2_test.jsonl" <<'PY'
import json
import sys

sql_file, bucket, region, *pairs = sys.argv[1:]
ns = "https://w3id.org/edc/v0.0.1/ns/"

lines = ["\\set ON_ERROR_STOP on", "begin;"]
asset_ids = []
for asset_id, file_name in zip(pairs[0::2], pairs[1::2]):
    asset_ids.append(asset_id)
    data_address = {
        f"{ns}type": "AmazonS3",
        f"{ns}keyName": file_name,
        f"{ns}bucketName": bucket,
        f"{ns}region": region,
    }
    private_properties = {"storageAssetFile": file_name}
    lines.append(
        "update edc_asset\n"
        f"   set data_address = '{json.dumps(data_address, separators=(',', ':'))}'::json,\n"
        f"       private_properties = '{json.dumps(private_properties, separators=(',', ':'))}'::json\n"
        f" where asset_id = '{asset_id}';"
    )
ids_sql = ",".join("'" + asset_id.replace("'", "''") + "'" for asset_id in asset_ids)
lines.append(
    "select asset_id,\n"
    "       data_address->>'https://w3id.org/edc/v0.0.1/ns/type',\n"
    "       data_address->>'https://w3id.org/edc/v0.0.1/ns/keyName',\n"
    "       private_properties->>'storageAssetFile'\n"
    "  from edc_asset\n"
    f" where asset_id in ({ids_sql})\n"
    " order by asset_id;"
)
lines.append("commit;")
with open(sql_file, "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines))
    handle.write("\n")
PY

  local kubectl_cmd=(kubectl)
  if [[ -n "$COMMON_KUBECONFIG" ]]; then
    kubectl_cmd+=(--kubeconfig "$COMMON_KUBECONFIG")
  fi

  echo "[$connector] reconciling official AI Model Hub benchmark dataset storage metadata"
  if ! "${kubectl_cmd[@]}" exec -i -n "$COMMON_SERVICES_NAMESPACE" "$COMMON_POSTGRES_POD" -- \
    env "PGPASSWORD=$db_pass" psql -U "$db_user" -d "$db_name" -At \
    < "$sql_file" > "$out_file" 2> "$err_file"; then
    echo "[$connector] benchmark dataset storage reconciliation failed" >&2
    cat "$err_file" >&2 2>/dev/null || true
    return 1
  fi

  cat "$out_file"
  local expected ok=1
  for expected in \
    "${MOBILITY_ACTUAL_TRAVEL_TIME_DATASET_ID}|AmazonS3|segments_test.csv|segments_test.csv" \
    "${MOBILITY_DELAY_DATASET_ID}|AmazonS3|segments_test.csv|segments_test.csv" \
    "${MOBILITY_PREVIOUS_DELAY_DATASET_ID}|AmazonS3|segments_test.csv|segments_test.csv" \
    "${MOBILITY_ACTUAL_TRAVEL_TIME_SAMPLE_DATASET_ID}|AmazonS3|${MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME}|${MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME}" \
    "${MOBILITY_DELAY_SAMPLE_DATASET_ID}|AmazonS3|${MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME}|${MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME}" \
    "${MOBILITY_PREVIOUS_DELAY_SAMPLE_DATASET_ID}|AmazonS3|${MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME}|${MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME}" \
    "${FLARES_5W1H_DATASET_ID}|AmazonS3|5w1h_subtarea_1_test.jsonl|5w1h_subtarea_1_test.jsonl" \
    "${FLARES_RELIABILITY_DATASET_ID}|AmazonS3|5w1h_subtarea_2_test.jsonl|5w1h_subtarea_2_test.jsonl"; do
    if ! grep -Fqx "$expected" "$out_file"; then
      ok=0
      echo "[$connector] missing reconciled dataset state: $expected" >&2
    fi
  done

  if [[ "$ok" != "1" ]]; then
    return 1
  fi

  echo "[$connector] official AI Model Hub benchmark datasets are transfer-ready"
  return 0
}

seed_use_case_dataset_http_data_assets() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag created=0
  tag="$(connector_tag "$connector")"

  retire_legacy_mobility_segments_dataset_asset "$connector" "$token" "$mgmt_url"

  local dataset_ids=(
    "$MOBILITY_ACTUAL_TRAVEL_TIME_DATASET_ID"
    "$MOBILITY_DELAY_DATASET_ID"
    "$MOBILITY_PREVIOUS_DELAY_DATASET_ID"
    "$MOBILITY_ACTUAL_TRAVEL_TIME_SAMPLE_DATASET_ID"
    "$MOBILITY_DELAY_SAMPLE_DATASET_ID"
    "$MOBILITY_PREVIOUS_DELAY_SAMPLE_DATASET_ID"
    "$FLARES_5W1H_DATASET_ID"
    "$FLARES_RELIABILITY_DATASET_ID"
  )
  local titles=(
    "Mobility actual travel time test dataset"
    "Mobility delay test dataset"
    "Mobility previous delay test dataset"
    "Mobility actual travel time sample test dataset"
    "Mobility delay sample test dataset"
    "Mobility previous delay sample test dataset"
    "FLARES 5W1H test dataset"
    "FLARES reliability test dataset"
  )
  local filenames=(
    "$(basename "$MOBILITY_SEGMENTS_DATASET_FILE")"
    "$(basename "$MOBILITY_SEGMENTS_DATASET_FILE")"
    "$(basename "$MOBILITY_SEGMENTS_DATASET_FILE")"
    "$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME"
    "$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME"
    "$MOBILITY_SEGMENTS_SAMPLE_DATASET_FILENAME"
    "$(basename "$FLARES_5W1H_DATASET_FILE")"
    "$(basename "$FLARES_RELIABILITY_DATASET_FILE")"
  )
  local content_types=(
    "text/csv"
    "text/csv"
    "text/csv"
    "text/csv"
    "text/csv"
    "text/csv"
    "application/x-ndjson"
    "application/x-ndjson"
  )
  local task_categories=(
    "Tabular"
    "Tabular"
    "Tabular"
    "Tabular"
    "Tabular"
    "Tabular"
    "Natural Language Processing"
    "Natural Language Processing"
  )
  local task_types=(
    "regression"
    "regression"
    "regression"
    "regression"
    "regression"
    "regression"
    "classification"
    "classification"
  )
  local subtasks=(
    "tabular-regression"
    "tabular-regression"
    "tabular-regression"
    "tabular-regression"
    "tabular-regression"
    "tabular-regression"
    "token-classification"
    "text-classification"
  )
  local label_types=(
    "continuous"
    "continuous"
    "continuous"
    "continuous"
    "continuous"
    "continuous"
    "span"
    "categorical"
  )
  local formats=(
    "csv"
    "csv"
    "csv"
    "csv"
    "csv"
    "csv"
    "jsonl"
    "jsonl"
  )
  local modalities_json=(
    '["tabular"]'
    '["tabular"]'
    '["tabular"]'
    '["tabular"]'
    '["tabular"]'
    '["tabular"]'
    '["text"]'
    '["text"]'
  )
  local languages_json=(
    '["Language independent"]'
    '["Language independent"]'
    '["Language independent"]'
    '["Language independent"]'
    '["Language independent"]'
    '["Language independent"]'
    '["Spanish"]'
    '["Spanish"]'
  )
  local keywords_json=(
    '["benchmark","validation","test","mobility","actual-travel-time","public-transport","regression","csv"]'
    '["benchmark","validation","test","mobility","delay","public-transport","regression","csv"]'
    '["benchmark","validation","test","mobility","previous-delay","public-transport","regression","csv"]'
    '["benchmark","validation","sample","test","mobility","actual-travel-time","public-transport","regression","csv"]'
    '["benchmark","validation","sample","test","mobility","delay","public-transport","regression","csv"]'
    '["benchmark","validation","sample","test","mobility","previous-delay","public-transport","regression","csv"]'
    '["benchmark","validation","test","flares","span-extraction","jsonl"]'
    '["benchmark","validation","test","flares","classification","jsonl"]'
  )
  local input_json=(
    '["trip_id","from_stop_id","to_stop_id","route_id","scheduled_travel_time","shape_distance","is_peak","hour_sin","hour_cos","weekday_sin","weekday_cos","previous_delay_ratio","previous_delay_delta"]'
    '["trip_id","from_stop_id","to_stop_id","route_id","scheduled_travel_time","shape_distance","is_peak","hour_sin","hour_cos","weekday_sin","weekday_cos","previous_delay_ratio","previous_delay_delta"]'
    '["trip_id","from_stop_id","to_stop_id","route_id","scheduled_travel_time","shape_distance","is_peak","hour_sin","hour_cos","weekday_sin","weekday_cos"]'
    '["trip_id","from_stop_id","to_stop_id","route_id","scheduled_travel_time","shape_distance","is_peak","hour_sin","hour_cos","weekday_sin","weekday_cos","previous_delay_ratio","previous_delay_delta"]'
    '["trip_id","from_stop_id","to_stop_id","route_id","scheduled_travel_time","shape_distance","is_peak","hour_sin","hour_cos","weekday_sin","weekday_cos","previous_delay_ratio","previous_delay_delta"]'
    '["trip_id","from_stop_id","to_stop_id","route_id","scheduled_travel_time","shape_distance","is_peak","hour_sin","hour_cos","weekday_sin","weekday_cos"]'
    '["Id","Text"]'
    '["Id","Text","5W1H_Label","Tag_Text","Tag_Start","Tag_End"]'
  )
  local labels=(
    "actual_travel_time"
    "delay"
    "previous_delay"
    "actual_travel_time"
    "delay"
    "previous_delay"
    "Tags"
    "Reliability_Label"
  )

  for idx in "${!dataset_ids[@]}"; do
    local asset_id="${dataset_ids[$idx]}"
    local title="${titles[$idx]} - ${tag}"
    local filename="${filenames[$idx]}"
    local content_type="${content_types[$idx]}"
    local task_category="${task_categories[$idx]}"
    local task_type="${task_types[$idx]}"
    local subtask="${subtasks[$idx]}"
    local label_type="${label_types[$idx]}"
    local format="${formats[$idx]}"
    local modality="${modalities_json[$idx]}"
    local language="${languages_json[$idx]}"
    local keywords="${keywords_json[$idx]}"
    local input="${input_json[$idx]}"
    local label="${labels[$idx]}"
    local endpoint="${USE_CASE_MODEL_SERVER_BASE_URL}/datasets/${filename}"
    local json_file="$WORK_DIR/${connector}_${asset_id}.json"
    local escaped_title
    escaped_title="$(json_escape "$title")"

    cat > "$json_file" <<ASSET_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/pionera/daimo#"
  },
  "@id": "${asset_id}",
  "properties": {
    "name": "${escaped_title}",
    "version": "1.0.0",
    "contenttype": "${content_type}",
    "assetType": "dataset",
    "dct:description": "Use-case benchmark dataset referenced as standard EDC HttpData.",
    "dcterms:description": "Use-case benchmark dataset referenced as standard EDC HttpData.",
    "dcat:keyword": ["dataset","benchmark","use-case","${tag}"],
    "assetData": {
      "${DATASET_VOCABULARY_ID}": {
        "dct:title": "${escaped_title}",
        "dcterms:title": "${escaped_title}",
        "${DCT_NS}description": "Use-case benchmark dataset referenced as standard EDC HttpData.",
        "${DCT_NS}language": ${language},
        "${DCT_NS}license": "other",
        "${DCT_NS}format": "${format}",
        "${DCAT_NS}keyword": ${keywords},
        "${DAIMO_NS}modality": ${modality},
        "${DAIMO_NS}taskCategory": "${task_category}",
        "${DAIMO_NS}taskType": "${task_type}",
        "${DAIMO_NS}subtask": "${subtask}",
        "${DAIMO_NS}subtaskDescription": "Use-case benchmark dataset referenced as standard EDC HttpData.",
        "${DAIMO_NS}input": ${input},
        "${DAIMO_NS}label": "${label}",
        "${DAIMO_NS}labelType": "${label_type}",
        "${DAIMO_NS}datasetVersion": "1.0.0",
        "${DAIMO_NS}datasetRole": "benchmark",
        "${DAIMO_NS}protocol": "holdout-test-set",
        "${DAIMO_NS}benchmarkDatasetSource": "${filename}"
      }
    }
  },
  "dataAddress": {
    "type": "HttpData",
    "name": "${asset_id}",
    "baseUrl": "${endpoint}",
    "proxyMethod": "true",
    "method": "GET",
    "contentType": "${content_type}"
  }
}
ASSET_EOF

    local out_file="$WORK_DIR/${connector}_${asset_id}.create.out"
    local code
    code="$(curl -s --max-time 30 -o "$out_file" -w '%{http_code}' \
      -X POST "$mgmt_url/v3/assets" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$json_file")" || true

    if [[ "$code" == "200" || "$code" == "204" || "$code" == "409" ]]; then
      created=$((created + 1))
      echo "[$connector] EDC HttpData dataset $asset_id created (HTTP $code)"
    else
      echo "[$connector] EDC HttpData dataset $asset_id FAILED (HTTP ${code:-NA})" >&2
      cat "$out_file" >&2 2>/dev/null || true
      return 1
    fi
  done

  echo "[$connector] EDC HttpData datasets created: $created/${#dataset_ids[@]}"
  return 0
}

create_company_dataset_policies_and_contracts() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag
  tag="$(connector_tag "$connector")"

  if [[ "$tag" != "company" ]]; then
    return 0
  fi

  for asset_id in "${USE_CASE_DATASET_IDS[@]}"; do
    local policy_id="policy-seed-${asset_id}"
    local contract_id="contract-seed-${asset_id}"
    local policy_file="$WORK_DIR/${connector}_${asset_id}_policy.json"
    local policy_out="$WORK_DIR/${connector}_${asset_id}_policy.out"
    local policy_code
    local contract_file="$WORK_DIR/${connector}_${asset_id}_contract.json"
    local contract_out="$WORK_DIR/${connector}_${asset_id}_contract.out"
    local contract_code

    cat > "$policy_file" <<PEOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "odrl": "http://www.w3.org/ns/odrl/2/"
  },
  "@id": "${policy_id}",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "Set",
    "permission": [],
    "prohibition": [],
    "obligation": []
  }
}
PEOF

    policy_code="$(curl -s --max-time 30 -o "$policy_out" -w '%{http_code}' \
      -X POST "$mgmt_url/v3/policydefinitions" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$policy_file")" || true

    if [[ "$policy_code" == "200" || "$policy_code" == "204" || "$policy_code" == "409" ]]; then
      echo "[$connector] dataset policy '$policy_id' created (HTTP $policy_code)"
    else
      echo "[$connector] dataset policy creation failed for $asset_id (HTTP ${policy_code:-NA})" >&2
      cat "$policy_out" >&2 2>/dev/null || true
      return 1
    fi

    cat > "$contract_file" <<CEOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@id": "${contract_id}",
  "accessPolicyId": "${policy_id}",
  "contractPolicyId": "${policy_id}",
  "assetsSelector": [
    {
      "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
      "operator": "=",
      "operandRight": "${asset_id}"
    }
  ]
}
CEOF

    contract_code="$(curl -s --max-time 30 -o "$contract_out" -w '%{http_code}' \
      -X POST "$mgmt_url/v3/contractdefinitions" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$contract_file")" || true

    if [[ "$contract_code" == "200" || "$contract_code" == "204" || "$contract_code" == "409" ]]; then
      echo "[$connector] dataset contract '$contract_id' created (HTTP $contract_code)"
    else
      echo "[$connector] dataset contract creation failed for $asset_id (HTTP ${contract_code:-NA})" >&2
      cat "$contract_out" >&2 2>/dev/null || true
      return 1
    fi
  done

  return 0
}

# =============================================================================
# MAIN PER-CONNECTOR FUNCTION — port-forward, vocabulary, assets, policy
# =============================================================================

connector_credentials_file() {
  local connector="$1"
  local canonical="$CREDENTIALS_DIR/connectors/$connector/credentials.json"
  local legacy="$CREDENTIALS_DIR/credentials-connector-$connector.json"

  if [[ -f "$canonical" ]]; then
    printf '%s\n' "$canonical"
    return 0
  fi
  if [[ -f "$legacy" ]]; then
    printf '%s\n' "$legacy"
    return 0
  fi

  printf '%s\n' "$legacy"
}

seed_connector() {
  local connector="$1"
  local creds_file
  creds_file="$(connector_credentials_file "$connector")"
  local fallback_creds_file="$CREDENTIALS_DIR/credentials-connector-$connector.json"
  local mgmt_port
  mgmt_port="$(allocate_local_port)"
  local mgmt_url="http://127.0.0.1:${mgmt_port}/management"
  local k8s_namespace kubeconfig
  local pf_pid=""

  if [[ ! -f "$creds_file" ]]; then
    echo "Credentials file not found for $connector: $creds_file" >&2
    return 1
  fi

  local username password token
  local vocab_base
  username="$(get_json_value "$creds_file" connector_user user)"
  password="$(get_json_value "$creds_file" connector_user passwd)"

  if [[ -z "$username" || -z "$password" ]]; then
    echo "Missing connector_user credentials in $creds_file" >&2
    return 1
  fi

  token="$(request_connector_token "$username" "$password" "$connector" "$creds_file" || true)"

  if [[ -z "$token" && -f "$fallback_creds_file" && "$fallback_creds_file" != "$creds_file" ]]; then
    username="$(get_json_value "$fallback_creds_file" connector_user user)"
    password="$(get_json_value "$fallback_creds_file" connector_user passwd)"
    if [[ -n "$username" && -n "$password" ]]; then
      token="$(request_connector_token "$username" "$password" "$connector" "$fallback_creds_file" || true)"
      if [[ -n "$token" ]]; then
        echo "[$connector] using fallback credentials file: $fallback_creds_file"
      fi
    fi
  fi

  if [[ -z "$token" ]]; then
    echo "Failed to obtain token for $connector" >&2
    return 1
  fi

  cleanup_pf() {
    if [[ -n "$pf_pid" ]] && kill -0 "$pf_pid" 2>/dev/null; then
      kill "$pf_pid" >/dev/null 2>&1 || true
      wait "$pf_pid" 2>/dev/null || true
    fi
  }

  k8s_namespace="$(lookup_connector_map "$CONNECTOR_K8S_NAMESPACES" "$connector" "$NAMESPACE")"
  kubeconfig="$(lookup_connector_map "$CONNECTOR_KUBECONFIGS" "$connector" "")"
  echo "[$connector] opening management port-forward on 127.0.0.1:${mgmt_port} -> ${connector}:19193"
  if [[ -n "$kubeconfig" ]]; then
    KUBECONFIG="$kubeconfig" kubectl -n "$k8s_namespace" port-forward "svc/$connector" "${mgmt_port}:19193" >"$WORK_DIR/port_forward_$connector.log" 2>&1 &
  else
    kubectl -n "$k8s_namespace" port-forward "svc/$connector" "${mgmt_port}:19193" >"$WORK_DIR/port_forward_$connector.log" 2>&1 &
  fi
  pf_pid=$!
  sleep 2
  if ! kill -0 "$pf_pid" 2>/dev/null; then
    echo "Management API port-forward failed for $connector" >&2
    cat "$WORK_DIR/port_forward_$connector.log" >&2 || true
    return 1
  fi

  local probe
  probe="$(curl -s -o "$WORK_DIR/${connector}.probe.out" -w '%{http_code}' "$mgmt_url/v3/assets/request" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"offset":0,"limit":1,"filterExpression":[]}' || true)"
  if [[ "$probe" != "200" && "$probe" != "400" && "$probe" != "401" && "$probe" != "403" ]]; then
    cleanup_pf
    echo "Management API probe failed for $connector: HTTP $probe" >&2
    return 1
  fi

  if [[ "$ADAPTER" == "inesdata" ]]; then
    # Vocabulary API differs by runtime
    vocab_base=""
    local vocab_probe_code
    vocab_probe_code="$(curl -s -o "$WORK_DIR/${connector}.vocab_probe.out" -w '%{http_code}' \
      -X POST "$mgmt_url/vocabularies/request" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"offset":0,"limit":1,"filterExpression":[]}')"
    if [[ "$vocab_probe_code" == "200" || "$vocab_probe_code" == "400" || "$vocab_probe_code" == "401" || "$vocab_probe_code" == "403" ]]; then
      vocab_base="vocabularies"
    else
      vocab_probe_code="$(curl -s -o "$WORK_DIR/${connector}.vocab_probe_v3.out" -w '%{http_code}' \
        -X POST "$mgmt_url/v3/vocabularies/request" \
        -H "Authorization: Bearer $token" \
        -H 'Content-Type: application/json' \
        -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"offset":0,"limit":1,"filterExpression":[]}')"
      if [[ "$vocab_probe_code" == "200" || "$vocab_probe_code" == "400" || "$vocab_probe_code" == "401" || "$vocab_probe_code" == "403" ]]; then
        vocab_base="v3/vocabularies"
      fi
    fi

    if [[ -z "$vocab_base" ]]; then
      cleanup_pf
      echo "Could not resolve vocabulary API endpoint for $connector" >&2
      return 1
    fi

    if ! ensure_daimo_vocabularies "$connector" "$token" "$mgmt_url" "$vocab_base"; then
      cleanup_pf
      return 1
    fi
  else
    echo "[$connector] skipping INESData vocabulary API setup for adapter '$ADAPTER'"
  fi

  local http_assets_label="none"
  local inesdata_count_label="0"
  if [[ "$SEED_SCOPE" == "models" || "$SEED_SCOPE" == "all" ]]; then
    http_assets_label="25 HttpData"
    case "$MODEL_SET" in
      mock)
        if ! seed_http_data_assets "$connector" "$token" "$mgmt_url"; then
          cleanup_pf
          return 1
        fi
        ;;
      use-cases)
        if [[ "$SKIP_USE_CASE_MODELS" != "1" ]]; then
          if ! seed_use_case_http_data_assets "$connector" "$token" "$mgmt_url"; then
            cleanup_pf
            return 1
          fi
          if [[ "$INCLUDE_FLARES_METRIC_MODELS" == "1" ]]; then
            if ! seed_flares_metric_http_data_assets "$connector" "$token" "$mgmt_url"; then
              cleanup_pf
              return 1
            fi
          fi
        fi
        http_assets_label="use-case HttpData"
        ;;
      combined)
        if [[ "$SKIP_USE_CASE_MODELS" != "1" ]]; then
          if ! seed_use_case_http_data_assets "$connector" "$token" "$mgmt_url"; then
            cleanup_pf
            return 1
          fi
          if [[ "$INCLUDE_FLARES_METRIC_MODELS" == "1" ]]; then
            if ! seed_flares_metric_http_data_assets "$connector" "$token" "$mgmt_url"; then
              cleanup_pf
              return 1
            fi
          fi
        fi
        if [[ "$COMBINED_HTTP_COUNT" -gt 0 ]]; then
          if ! seed_http_data_assets "$connector" "$token" "$mgmt_url" "$COMBINED_HTTP_COUNT"; then
            cleanup_pf
            return 1
          fi
        fi
        http_assets_label="use-case HttpData + $COMBINED_HTTP_COUNT mock HttpData"
        ;;
    esac

    # Seed InesDataStore assets
    local original_count="$COUNT"
    inesdata_count_label="$COUNT"
    if [[ "$MODEL_SET" == "combined" ]]; then
      COUNT="$COMBINED_INESDATA_COUNT"
      inesdata_count_label="$COMBINED_INESDATA_COUNT"
    fi
    if [[ "$SKIP_INESDATA_MODELS" != "1" && "$COUNT" -gt 0 ]] && ! seed_inesdata_store_assets "$connector" "$token" "$mgmt_url"; then
      COUNT="$original_count"
      cleanup_pf
      return 1
    fi
    if [[ "$SKIP_INESDATA_MODELS" == "1" ]]; then
      inesdata_count_label="0"
    fi
    COUNT="$original_count"

    # Use-case mode must not publish every historical machineLearning asset:
    # create one narrow contract per discovered FLARES/Mobility model.
    if [[ "$MODEL_SET" == "use-cases" && "$SKIP_USE_CASE_MODELS" != "1" ]]; then
      if ! create_use_case_model_policies_and_contracts "$connector" "$token" "$mgmt_url"; then
        cleanup_pf
        return 1
      fi
    else
      if ! create_policy_and_contract "$connector" "$token" "$mgmt_url"; then
        cleanup_pf
        return 1
      fi
    fi
  fi

  if [[ "$SEED_SCOPE" == "datasets" || "$SEED_SCOPE" == "all" ]]; then
    if [[ "$ADAPTER" == "edc" ]]; then
      if ! seed_use_case_dataset_http_data_assets "$connector" "$token" "$mgmt_url"; then
        cleanup_pf
        return 1
      fi
    else
      if ! seed_mobility_segments_dataset_asset "$connector" "$token" "$mgmt_url"; then
        cleanup_pf
        return 1
      fi

      if ! seed_flares_test_dataset_assets "$connector" "$token" "$mgmt_url"; then
        cleanup_pf
        return 1
      fi

      if ! reconcile_use_case_dataset_storage_assets "$connector" "$creds_file"; then
        cleanup_pf
        return 1
      fi
    fi

    if ! create_company_dataset_policies_and_contracts "$connector" "$token" "$mgmt_url"; then
      cleanup_pf
      return 1
    fi
  fi

  cleanup_pf
  if [[ "$SEED_SCOPE" == "vocabularies" ]]; then
    echo "[$connector] vocabulary seeding complete: $MODEL_VOCABULARY_ID + $DATASET_VOCABULARY_ID"
  else
    echo "[$connector] ${SEED_SCOPE} seeding complete: $http_assets_label + $inesdata_count_label InesDataStore"
  fi
  return 0
}

# =============================================================================
# CROSS-CONNECTOR NEGOTIATIONS (5 total, after all connectors are seeded)
# =============================================================================

connector_protocol_address() {
  local connector="$1"
  local mapped
  mapped="$(lookup_connector_map "$CONNECTOR_PROTOCOL_URLS" "$connector" "")"
  if [[ -n "$mapped" ]]; then
    printf '%s\n' "${mapped%/}"
    return 0
  fi

  local short
  short="$(connector_short_name "$connector")"
  if [[ "$short" == org* && "$KEYCLOAK_TOKEN_URL" == https://* ]]; then
    python3 - "$KEYCLOAK_TOKEN_URL" "$short" <<'PY'
from urllib.parse import urlparse
import sys

parsed = urlparse(sys.argv[1])
short = sys.argv[2]
host = parsed.hostname or ""
parts = host.split(".")
if len(parts) > 1:
    parts[0] = short
    print(f"{parsed.scheme}://{'.'.join(parts)}/protocol")
else:
    print("")
PY
    return 0
  fi

  printf 'http://%s:19194/protocol\n' "$connector"
}

write_negotiation_model_slugs() {
  local output_file="$1"
  : > "$output_file"

  if [[ "$SEED_SCOPE" == "datasets" ]]; then
    return 0
  fi

  if [[ "$MODEL_SET" == "mock" || "$MODEL_SET" == "combined" ]]; then
    local max_assets="${#MODEL_SLUGS[@]}"
    if [[ "$MODEL_SET" == "combined" ]]; then
      max_assets="$COMBINED_HTTP_COUNT"
    fi
    local idx
    for idx in "${!MODEL_SLUGS[@]}"; do
      [[ "$idx" -ge "$max_assets" ]] && break
      printf '%s\n' "${MODEL_SLUGS[$idx]}" >> "$output_file"
    done
  fi

  if [[ "$MODEL_SET" == "use-cases" || "$MODEL_SET" == "combined" ]]; then
    if [[ "$SKIP_USE_CASE_MODELS" != "1" ]]; then
      local use_case_slug
      for use_case_slug in "${USE_CASE_MODEL_SLUGS[@]}"; do
        printf '%s\n' "$use_case_slug" >> "$output_file"
      done

      if [[ "$INCLUDE_FLARES_METRIC_MODELS" == "1" ]]; then
        local flares_slug
        for flares_slug in "${FLARES_METRIC_MODEL_SLUGS[@]}"; do
          printf '%s\n' "$flares_slug" >> "$output_file"
        done
      fi
    fi
  fi

  awk 'NF && !seen[$0]++' "$output_file" > "${output_file}.tmp"
  mv "${output_file}.tmp" "$output_file"
}

negotiate_one() {
  local consumer="$1" provider="$2" asset_id="$3" label="$4"
  local creds_file
  creds_file="$(connector_credentials_file "$consumer")"
  local fallback_creds_file="$CREDENTIALS_DIR/credentials-connector-$consumer.json"
  local mgmt_port
  mgmt_port="$(allocate_local_port)"
  local mgmt_url="http://127.0.0.1:${mgmt_port}/management"
  local pf_pid=""

  echo "[negotiate] $label: $consumer -> $provider for asset '$asset_id'"

  # Get credentials
  local username password token
  if [[ -f "$creds_file" ]]; then
    username="$(get_json_value "$creds_file" connector_user user)"
    password="$(get_json_value "$creds_file" connector_user passwd)"
  fi
  if [[ -z "$username" && -f "$fallback_creds_file" ]]; then
    username="$(get_json_value "$fallback_creds_file" connector_user user)"
    password="$(get_json_value "$fallback_creds_file" connector_user passwd)"
  fi
  if [[ -z "$username" || -z "$password" ]]; then
    echo "[negotiate] cannot resolve credentials for consumer $consumer" >&2
    return 1
  fi
  token="$(request_connector_token "$username" "$password" "$consumer" "$creds_file" || true)"
  if [[ -z "$token" ]]; then
    echo "[negotiate] token request failed for $consumer" >&2
    return 1
  fi

  local auth_header_file="$WORK_DIR/neg_auth_${consumer}.headers"
  (umask 077 && printf 'Authorization: Bearer %s\n' "$token" > "$auth_header_file")

  # Port-forward consumer. In vm-distributed each connector may live in a
  # different namespace/cluster, so reuse the same maps used during seeding.
  local consumer_namespace consumer_kubeconfig
  consumer_namespace="$(lookup_connector_map "$CONNECTOR_K8S_NAMESPACES" "$consumer" "$NAMESPACE")"
  consumer_kubeconfig="$(lookup_connector_map "$CONNECTOR_KUBECONFIGS" "$consumer" "")"
  local kubectl_cmd=(kubectl)
  if [[ -n "$consumer_kubeconfig" ]]; then
    kubectl_cmd+=(--kubeconfig "$consumer_kubeconfig")
  fi
  echo "[negotiate] opening consumer management port-forward on 127.0.0.1:${mgmt_port} -> ${consumer}:19193"
  "${kubectl_cmd[@]}" -n "$consumer_namespace" port-forward "svc/$consumer" "${mgmt_port}:19193" >"$WORK_DIR/pf_neg_$consumer.log" 2>&1 &
  pf_pid=$!
  sleep "$NEGOTIATION_PORT_FORWARD_DELAY_SECONDS"
  if ! kill -0 "$pf_pid" 2>/dev/null; then
    echo "[negotiate] consumer management port-forward failed for $consumer" >&2
    cat "$WORK_DIR/pf_neg_$consumer.log" >&2 || true
    rm -f "$auth_header_file"
    return 1
  fi

  neg_cleanup() {
    if [[ -n "$pf_pid" ]] && kill -0 "$pf_pid" 2>/dev/null; then
      kill "$pf_pid" >/dev/null 2>&1 || true
      wait "$pf_pid" 2>/dev/null || true
    fi
    rm -f "$auth_header_file"
  }

  # Step 1: Request catalog from provider
  local protocol_addr
  protocol_addr="$(connector_protocol_address "$provider")"
  local catalog_file="$WORK_DIR/neg_catalog_${asset_id}.json"
  local catalog_out="$WORK_DIR/neg_catalog_${asset_id}.out"

  cat > "$catalog_file" <<CAT_EOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@type": "CatalogRequest",
  "counterPartyAddress": "${protocol_addr}",
  "counterPartyId": "${provider}",
  "protocol": "dataspace-protocol-http",
  "querySpec": {
    "offset": 0,
    "limit": 5000,
    "filterExpression": []
  }
}
CAT_EOF

  local cat_code
  cat_code="$(curl -s --max-time 60 -o "$catalog_out" -w '%{http_code}' \
    -X POST "$mgmt_url/v3/catalog/request" \
    -H "@$auth_header_file" \
    -H 'Content-Type: application/json' \
    --data-binary "@$catalog_file")" || true

  if [[ "$cat_code" != "200" ]]; then
    neg_cleanup
    echo "[negotiate] catalog request failed for $asset_id (HTTP ${cat_code:-NA})" >&2
    return 1
  fi

  # Step 2: Extract the exact offer policy from the catalog. EDC expects the
  # negotiation request to reuse the selected offer policy, not a reconstructed
  # allow-all policy with a guessed action.
  local offer_id participant_id
  local offer_policy_file="$WORK_DIR/neg_offer_policy_${asset_id}.json"
  read -r offer_id participant_id < <(python3 - "$catalog_out" "$asset_id" "$offer_policy_file" <<'PY'
import json, sys
try:
    cat = json.load(open(sys.argv[1]))
except Exception:
    print(' ')
    sys.exit(0)
asset_id = sys.argv[2]
offer_policy_file = sys.argv[3]
datasets = cat.get('dcat:dataset', [])
if isinstance(datasets, dict):
    datasets = [datasets]
pid = cat.get('dspace:participantId', cat.get('participantId', ''))
offer = ''
for ds in datasets:
    if ds.get('@id') == asset_id:
        pol = ds.get('odrl:hasPolicy', {})
        if isinstance(pol, list):
            pol = pol[0] if pol else {}
        offer = pol.get('@id', '')
        if offer:
            with open(offer_policy_file, 'w', encoding='utf-8') as handle:
                json.dump(pol, handle)
        break
print(offer + ' ' + pid)
PY
  ) || true

  [[ -z "$participant_id" ]] && participant_id="$provider"

  if [[ -z "$offer_id" || ! -s "$offer_policy_file" ]]; then
    neg_cleanup
    echo "[negotiate] could not extract offer_id for $asset_id from catalog" >&2
    echo "[negotiate] catalog response:" >&2
    head -c 2000 "$catalog_out" >&2
    return 1
  fi

  echo "[negotiate] found offer_id=$offer_id for $asset_id"

  # Step 3: Initiate contract negotiation
  local neg_payload="$WORK_DIR/neg_request_${asset_id}.json"
  python3 - "$neg_payload" "$protocol_addr" "$offer_policy_file" "$participant_id" "$asset_id" <<'PY'
import json
import sys

out_file, counter_party_address, offer_policy_file = sys.argv[1:4]
with open(offer_policy_file, encoding="utf-8") as handle:
    policy = json.load(handle)

offer_id = str(policy.get("@id") or "")
normalized_policy = {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@id": offer_id,
    "@type": "Offer",
    "assigner": str(sys.argv[4]),
    "target": str(sys.argv[5]),
}

payload = {
    "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
    "@type": "ContractRequest",
    "counterPartyAddress": counter_party_address,
    "protocol": "dataspace-protocol-http",
    "policy": normalized_policy,
}
with open(out_file, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
  if [[ ! -s "$neg_payload" ]]; then
    neg_cleanup
    echo "[negotiate] could not build negotiation request for $asset_id" >&2
    return 1
  fi
  local neg_out="$WORK_DIR/neg_result_${asset_id}.out"
  local neg_code
  neg_code="$(curl -s --max-time 30 -o "$neg_out" -w '%{http_code}' \
    -X POST "$mgmt_url/v3/contractnegotiations" \
    -H "@$auth_header_file" \
    -H 'Content-Type: application/json' \
    --data-binary "@$neg_payload")" || true

  if [[ "$neg_code" != "200" ]]; then
    neg_cleanup
    echo "[negotiate] negotiation initiation failed for $asset_id (HTTP ${neg_code:-NA})" >&2
    cat "$neg_out" >&2 2>/dev/null || true
    return 1
  fi

  local neg_id
  neg_id="$(sed -n 's/.*"@id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$neg_out" | head -n1)" || true
  if [[ -z "$neg_id" ]]; then
    neg_id="$(sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$neg_out" | head -n1)" || true
  fi

  echo "[negotiate] negotiation started: id=$neg_id for asset=$asset_id"

  # Step 4: Wait for the consumer-side negotiation to reach a terminal success state.
  local deadline=$((SECONDS + NEGOTIATION_TIMEOUT_SECONDS))
  local state=""
  while [[ $SECONDS -lt $deadline ]]; do
    sleep "$NEGOTIATION_POLL_INTERVAL_SECONDS"
    local state_out="$WORK_DIR/neg_state_${asset_id}.out"
    curl -s --max-time "$NEGOTIATION_STATE_REQUEST_TIMEOUT_SECONDS" -o "$state_out" \
      "$mgmt_url/v3/contractnegotiations/$neg_id" \
      -H "@$auth_header_file" 2>/dev/null || true

    state="$(sed -n 's/.*"state"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$state_out" | head -n1)" || true
    [[ -z "$state" ]] && state="$(sed -n 's/.*"edc:state"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$state_out" | head -n1)" || true

    if [[ "$state" == "FINALIZED" || "$state" == "VERIFIED" ]]; then
      echo "[negotiate] $asset_id: negotiation $neg_id -> $state"
      neg_cleanup
      return 0
    fi
    if [[ "$state" == "TERMINATED" || "$state" == "ERROR" ]]; then
      echo "[negotiate] $asset_id: negotiation FAILED ($state)" >&2
      neg_cleanup
      return 1
    fi
  done

  echo "[negotiate] $asset_id: timeout after ${NEGOTIATION_TIMEOUT_SECONDS}s waiting for negotiation (last state: ${state:-unknown})" >&2
  neg_cleanup
  return 1
}

negotiate_cross_connectors() {
  local negotiation_slugs_file="$WORK_DIR/negotiation_model_slugs.tsv"
  if ! write_negotiation_model_slugs "$negotiation_slugs_file"; then
    return 1
  fi

  local total_slugs
  total_slugs="$(wc -l < "$negotiation_slugs_file" | xargs)"
  if [[ "$total_slugs" -lt 1 && "$SEED_SCOPE" != "datasets" && "$SEED_SCOPE" != "all" ]]; then
    echo "Cannot run cross-connector negotiations: no model assets were selected" >&2
    return 1
  fi

  local provider_connector="" consumer_connector="" city_connector="" company_connector=""
  IFS=',' read -r -a _conns <<< "$CONNECTORS_CSV"
  for c in "${_conns[@]}"; do
    c="$(echo "$c" | xargs)"
    [[ -z "$c" ]] && continue
    local c_tag
    c_tag="$(connector_tag "$c")"
    if [[ -z "$provider_connector" ]]; then
      provider_connector="$c"
    elif [[ -z "$consumer_connector" ]]; then
      consumer_connector="$c"
    fi
    case "$c" in
      *citycouncil*) city_connector="$c" ;;
      *company*)     company_connector="$c" ;;
    esac
    case "$c_tag" in
      city)    city_connector="${city_connector:-$c}" ;;
      company) company_connector="${company_connector:-$c}" ;;
    esac
  done

  if [[ -n "$city_connector" && -n "$company_connector" ]]; then
    provider_connector="$city_connector"
    consumer_connector="$company_connector"
  fi

  if [[ -z "$provider_connector" || -z "$consumer_connector" ]]; then
    echo "Cannot run cross-connector negotiations: need at least two connectors" >&2
    return 1
  fi

  local neg_ok=0 neg_fail=0
  local provider_tag consumer_tag slug

  provider_tag="$(connector_tag "$provider_connector")"
  consumer_tag="$(connector_tag "$consumer_connector")"
  local model_negotiations=0 dataset_negotiations=0 total_negotiations=0
  while IFS= read -r slug; do
    [[ -z "$slug" ]] && continue
    if should_publish_model_for_tag "$provider_tag" "$slug"; then
      model_negotiations=$((model_negotiations + 1))
    fi
    if should_publish_model_for_tag "$consumer_tag" "$slug"; then
      model_negotiations=$((model_negotiations + 1))
    fi
  done < "$negotiation_slugs_file"

  if [[ "$SEED_SCOPE" == "datasets" || "$SEED_SCOPE" == "all" ]]; then
    if [[ -n "$city_connector" && -n "$company_connector" ]]; then
      dataset_negotiations="${#USE_CASE_DATASET_IDS[@]}"
    else
      echo "Cannot run dataset negotiations: need city/provider and company/consumer connectors" >&2
      dataset_negotiations=1
    fi
  fi

  total_negotiations=$((model_negotiations + dataset_negotiations))

  echo ""
  echo "=========================================="
  echo " Cross-Connector Negotiations (${total_negotiations} total)"
  echo "=========================================="

  if [[ "$total_negotiations" -lt 1 ]]; then
    echo "Skipping cross-connector negotiations: no published assets were selected"
    return 0
  fi

  if [[ "$dataset_negotiations" -gt 0 && ( -z "$city_connector" || -z "$company_connector" ) ]]; then
    return 1
  fi

  if [[ "$model_negotiations" -gt 0 ]]; then
    # Negotiate only the assets published by each side so consumer UIs surface
    # contract-ready models without requiring mirrored provider/consumer assets.
    while IFS= read -r slug; do
      [[ -z "$slug" ]] && continue
      if ! should_publish_model_for_tag "$provider_tag" "$slug"; then
        continue
      fi
      local asset_id="${provider_tag}-${slug}"
      if negotiate_one "$consumer_connector" "$provider_connector" "$asset_id" "${consumer_tag}->${provider_tag}"; then
        neg_ok=$((neg_ok + 1))
      else
        neg_fail=$((neg_fail + 1))
      fi
    done < "$negotiation_slugs_file"

    while IFS= read -r slug; do
      [[ -z "$slug" ]] && continue
      if ! should_publish_model_for_tag "$consumer_tag" "$slug"; then
        continue
      fi
      local asset_id="${consumer_tag}-${slug}"
      if negotiate_one "$provider_connector" "$consumer_connector" "$asset_id" "${provider_tag}->${consumer_tag}"; then
        neg_ok=$((neg_ok + 1))
      else
        neg_fail=$((neg_fail + 1))
      fi
    done < "$negotiation_slugs_file"
  fi

  if [[ "$dataset_negotiations" -gt 0 ]]; then
    local dataset_id
    for dataset_id in "${USE_CASE_DATASET_IDS[@]}"; do
      if negotiate_one "$city_connector" "$company_connector" "$dataset_id" "city->company dataset"; then
        neg_ok=$((neg_ok + 1))
      else
        neg_fail=$((neg_fail + 1))
      fi
    done
  fi

  echo ""
  echo "Negotiations complete: $neg_ok succeeded, $neg_fail failed"

  if [[ "$neg_ok" -eq 0 ]]; then
    return 1
  fi

  if [[ "$neg_fail" -gt 0 ]]; then
    return 2
  fi

  return 0
}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if ! validate_use_case_model_server_contract; then
  exit 1
fi

IFS=',' read -r -a connectors <<< "$CONNECTORS_CSV"

total_ok=0
failed_connectors=()
for connector in "${connectors[@]}"; do
  connector="$(echo "$connector" | xargs)"
  [[ -z "$connector" ]] && continue
  echo ""
  echo "=========================================="
  echo " Seeding: $connector"
  echo "=========================================="
  if ! seed_connector "$connector"; then
    failed_connectors+=("$connector")
    echo "[$connector] warning: seeding failed, continuing with remaining connectors" >&2
    continue
  fi
  total_ok=$((total_ok + 1))
done

echo ""
if [[ "$SEED_SCOPE" == "vocabularies" ]]; then
  echo "Connector vocabulary seeding summary: $total_ok/${#connectors[@]} succeeded ($MODEL_VOCABULARY_ID + $DATASET_VOCABULARY_ID)"
else
  echo "Connector seeding summary: $total_ok/${#connectors[@]} succeeded (seed-scope=$SEED_SCOPE, model-set=$MODEL_SET, InesDataStore=$COUNT each)"
fi

if [[ "${#failed_connectors[@]}" -gt 0 ]]; then
  echo "failed_connectors=${failed_connectors[*]}" >&2
  if [[ "$STRICT_MODE" == "1" ]]; then
    exit 1
  fi
fi

# Run cross-connector negotiations only when assets/contracts were seeded.
if [[ "$SEED_SCOPE" == "vocabularies" ]]; then
  echo "Skipping cross-connector negotiations for vocabulary-only seed scope"
elif [[ "$total_ok" -ge 2 ]]; then
  if ! negotiate_cross_connectors; then
    if [[ "$STRICT_MODE" == "1" ]]; then
      echo "Cross-connector negotiations did not complete successfully in strict mode" >&2
      exit 1
    fi

    echo "Warning: cross-connector negotiations were incomplete; seeding finished with partial federated readiness" >&2
  fi
else
  echo "Skipping cross-connector negotiations (need at least 2 successful connectors)" >&2
fi

echo ""
echo "Seed script finished."
