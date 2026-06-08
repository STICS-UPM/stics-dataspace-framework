#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${WORK_DIR:-/tmp/inesdata_seed}"
NAMESPACE="${NAMESPACE:-demo}"
COMPONENTS_NAMESPACE="${COMPONENTS_NAMESPACE:-components}"
COUNT="${COUNT:-8}"
CONNECTORS_CSV="${CONNECTORS_CSV:-conn-citycouncil-demo,conn-company-demo}"
CREDENTIALS_DIR="${CREDENTIALS_DIR:-$ROOT_DIR/inesdata-testing/deployments/DEV/demo}"
KEYCLOAK_TOKEN_URL="${KEYCLOAK_TOKEN_URL:-}"
DEPLOYER_CONFIG_FILE="${DEPLOYER_CONFIG_FILE:-$ROOT_DIR/deployers/inesdata/deployer.config}"
VOCABULARY_ID="${VOCABULARY_ID:-JS_Pionera_Daimo}"
VOCABULARY_NAME="${VOCABULARY_NAME:-JS Metadata Daimo}"
VOCABULARY_CATEGORY="${VOCABULARY_CATEGORY:-machineLearning}"
VOCABULARY_SCHEMA_FILE="${VOCABULARY_SCHEMA_FILE:-}"
MODEL_FILE="$WORK_DIR/LGBM_Classifier_1.pkl"
SEED_SCOPE="${SEED_SCOPE:-models}"
USE_CASES_SOURCE_DIR="${USE_CASES_SOURCE_DIR:-${AI_MODEL_HUB_USE_CASE_MODEL_SERVER_SOURCE_DIR:-${AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR:-$ROOT_DIR/adapters/inesdata/sources/AIModelHub-Use-Cases}}}"
MOBILITY_SEGMENTS_DATASET_FILE="${MOBILITY_SEGMENTS_DATASET_FILE:-$USE_CASES_SOURCE_DIR/data/mobility-datasets/segments_test.csv}"
MOBILITY_SEGMENTS_DATASET_ID="${MOBILITY_SEGMENTS_DATASET_ID:-company-mobility-segments-test}"
FLARES_5W1H_DATASET_FILE="${FLARES_5W1H_DATASET_FILE:-$USE_CASES_SOURCE_DIR/data/flares-datasets/5w1h_subtarea_1_test.json}"
FLARES_5W1H_DATASET_ID="${FLARES_5W1H_DATASET_ID:-company-flares-5w1h-test}"
FLARES_RELIABILITY_DATASET_FILE="${FLARES_RELIABILITY_DATASET_FILE:-$USE_CASES_SOURCE_DIR/data/flares-datasets/5w1h_subtarea_2_test.json}"
FLARES_RELIABILITY_DATASET_ID="${FLARES_RELIABILITY_DATASET_ID:-company-flares-reliability-test}"
USE_CASE_DATASET_IDS=("$MOBILITY_SEGMENTS_DATASET_ID" "$FLARES_5W1H_DATASET_ID" "$FLARES_RELIABILITY_DATASET_ID")
STRICT_MODE="${STRICT_MODE:-0}"
MODEL_SET="${MODEL_SET:-mock}"
INCLUDE_USE_CASE_MODELS="${INCLUDE_USE_CASE_MODELS:-0}"
SKIP_USE_CASE_MODELS="${SKIP_USE_CASE_MODELS:-0}"
SKIP_INESDATA_MODELS="${SKIP_INESDATA_MODELS:-0}"
USE_CASE_MODEL_SERVER_BASE_URL="${USE_CASE_MODEL_SERVER_BASE_URL:-}"
COMBINED_HTTP_COUNT="${COMBINED_HTTP_COUNT:-10}"
COMBINED_INESDATA_COUNT="${COMBINED_INESDATA_COUNT:-$COUNT}"

usage() {
  cat <<'EOF'
Usage: seed_ml_assets_for_connectors.sh [options]

Options:
  --namespace <ns>            Dataspace namespace/name used by legacy seed defaults (default: demo)
  --components-namespace <ns> Namespace where component fixtures run, including model-server (default: components)
  --count <n>                 Number of InesDataStore assets per connector (default: 8)
  --connectors <csv>          Connectors list (default: conn-citycouncil-demo,conn-company-demo)
  --credentials-dir <path>    Folder containing credentials-connector-<name>.json
  --keycloak-token-url <url>  Token endpoint. If omitted, read from deployers/inesdata/deployer.config
  --vocabulary-id <id>        Vocabulary ID used in assetData (default: JS_Pionera_Daimo)
  --vocabulary-name <name>    Vocabulary display name (default: JS Metadata Daimo)
  --vocabulary-category <cat> Vocabulary category (default: machineLearning)
  --vocabulary-schema <path>  JSON schema file. Default auto-detect from project root
  --seed-scope <scope>        What to seed: models, datasets or all (default: models)
  --model-set <mode>          mock, use-cases or combined (default: mock)
  --include-use-case-models   Also seed FLARES/Mobility HttpData assets
  --skip-use-case-models      Skip FLARES/Mobility HttpData assets in use-cases/combined modes
  --skip-inesdata-models      Skip stored InesDataStore model placeholder assets
  --use-case-model-server-base-url <url>
                              Base URL for the real use-case model server
  --combined-http-count <n>   Mock HttpData assets kept in combined mode (default: 10)
  --combined-inesdata-count <n>
                              InesDataStore assets kept in combined mode (default: --count)
  --strict                    Fail if any connector fails (default: disabled)
  -h, --help                  Show this help

Notes:
  - Connector passwords are always read from credentials files at runtime.
  - The vocabulary is created/updated first in each connector.
  - Asset insertion uses Management API upload-chunk + finalize-upload with retries.
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
    --vocabulary-id)
      VOCABULARY_ID="${2:-}"
      shift 2
      ;;
    --vocabulary-name)
      VOCABULARY_NAME="${2:-}"
      shift 2
      ;;
    --vocabulary-category)
      VOCABULARY_CATEGORY="${2:-}"
      shift 2
      ;;
    --vocabulary-schema)
      VOCABULARY_SCHEMA_FILE="${2:-}"
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

MODEL_SET="$(echo "$MODEL_SET" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
case "$MODEL_SET" in
  ""|"fixture"|"deterministic") MODEL_SET="mock" ;;
  "real"|"usecases") MODEL_SET="use-cases" ;;
esac
if [[ "$MODEL_SET" != "mock" && "$MODEL_SET" != "use-cases" && "$MODEL_SET" != "combined" ]]; then
  echo "Invalid --model-set value: $MODEL_SET. Expected mock, use-cases or combined." >&2
  exit 1
fi
if [[ "$INCLUDE_USE_CASE_MODELS" == "1" && "$MODEL_SET" == "mock" ]]; then
  MODEL_SET="use-cases"
fi
SEED_SCOPE="$(echo "$SEED_SCOPE" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
case "$SEED_SCOPE" in
  models|datasets|all) ;;
  *)
    echo "Invalid --seed-scope value: $SEED_SCOPE. Expected models, datasets or all." >&2
    exit 1
    ;;
esac
if ! [[ "$COMBINED_HTTP_COUNT" =~ ^[0-9]+$ ]] || [[ "$COMBINED_HTTP_COUNT" -lt 1 ]]; then
  echo "Invalid --combined-http-count value: $COMBINED_HTTP_COUNT" >&2
  exit 1
fi
if ! [[ "$COMBINED_INESDATA_COUNT" =~ ^[0-9]+$ ]] || [[ "$COMBINED_INESDATA_COUNT" -lt 1 ]]; then
  echo "Invalid --combined-inesdata-count value: $COMBINED_INESDATA_COUNT" >&2
  exit 1
fi

resolve_vocabulary_schema_file() {
  if [[ -n "$VOCABULARY_SCHEMA_FILE" ]]; then
    if [[ -f "$VOCABULARY_SCHEMA_FILE" ]]; then
      return 0
    fi
    echo "Vocabulary schema file not found: $VOCABULARY_SCHEMA_FILE" >&2
    return 1
  fi

  local candidates=(
    "$ROOT_DIR/JS_Metada_Daimo.schema.json"
    "$ROOT_DIR/JS_Metadata_Daimo.schema.json"
    "$ROOT_DIR/JS_Metadata_Daimo.schema.JSON"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      VOCABULARY_SCHEMA_FILE="$candidate"
      return 0
    fi
  done

  echo "Could not find vocabulary schema file in project root." >&2
  echo "Expected one of: JS_Metada_Daimo.schema.json or JS_Metadata_Daimo.schema.json" >&2
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

if ! resolve_vocabulary_schema_file; then
  exit 1
fi

echo "Using vocabulary schema: $VOCABULARY_SCHEMA_FILE"
echo "Using vocabulary id: $VOCABULARY_ID"
echo "Using seed scope: $SEED_SCOPE"

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

schema_as_json_string() {
  local schema_file="$1"
  tr -d '\n' < "$schema_file" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

get_json_value() {
  local file="$1"
  local block="$2"
  local key="$3"
  sed -n "/\"$block\"[[:space:]]*:[[:space:]]*{/,/}/p" "$file" \
    | sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" \
    | head -n1
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
  local schema_str payload_file create_out update_out get_out get_code post_code put_code

  schema_str="$(schema_as_json_string "$VOCABULARY_SCHEMA_FILE")"
  payload_file="$WORK_DIR/vocabulary_${connector}.json"

  cat > "$payload_file" <<EOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@id": "$VOCABULARY_ID",
  "name": "$VOCABULARY_NAME",
  "connectorId": "$connector",
  "category": "$VOCABULARY_CATEGORY",
  "jsonSchema": "$schema_str"
}
EOF

  get_out="$WORK_DIR/vocabulary_${connector}.get.out"
  create_out="$WORK_DIR/vocabulary_${connector}.create.out"
  update_out="$WORK_DIR/vocabulary_${connector}.update.out"

  get_code="$(curl -s -o "$get_out" -w '%{http_code}' \
    "$mgmt_url/$vocab_base/$VOCABULARY_ID" \
    -H "Authorization: Bearer $token")"

  if [[ "$get_code" == "200" ]]; then
    put_code="$(curl -s -o "$update_out" -w '%{http_code}' \
      -X PUT "$mgmt_url/$vocab_base" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$payload_file")"
    if [[ "$put_code" == "204" || "$put_code" == "200" ]]; then
      echo "[$connector] vocabulary '$VOCABULARY_ID' updated"
      return 0
    fi
    echo "[$connector] failed to update vocabulary '$VOCABULARY_ID' (HTTP $put_code)" >&2
    cat "$update_out" >&2 || true
    return 1
  fi

  post_code="$(curl -s -o "$create_out" -w '%{http_code}' \
    -X POST "$mgmt_url/$vocab_base" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    --data-binary "@$payload_file")"

  if [[ "$post_code" == "200" ]]; then
    echo "[$connector] vocabulary '$VOCABULARY_ID' created"
    return 0
  fi

  if [[ "$post_code" == "409" ]]; then
    put_code="$(curl -s -o "$update_out" -w '%{http_code}' \
      -X PUT "$mgmt_url/$vocab_base" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data-binary "@$payload_file")"
    if [[ "$put_code" == "204" || "$put_code" == "200" ]]; then
      echo "[$connector] vocabulary '$VOCABULARY_ID' updated after conflict"
      return 0
    fi
    echo "[$connector] vocabulary conflict but update failed (HTTP $put_code)" >&2
    cat "$update_out" >&2 || true
    return 1
  fi

  echo "[$connector] failed to create vocabulary '$VOCABULARY_ID' (HTTP $post_code)" >&2
  cat "$create_out" >&2 || true
  return 1
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

# Per-connector group context — appended to title for differentiation
CITY_GROUP_CTX=("Municipal Health" "City Services" "Citizens Wellness" "City Botanical" "City Treasury")
COMPANY_GROUP_CTX=("Corporate Health" "Corp Analytics" "Employee Wellness" "AgriTech Lab" "Corp Finance")

connector_tag() {
  case "$1" in
    *citycouncil*) echo "city" ;;
    *company*)     echo "company" ;;
    *)             echo "${1//-/_}" | cut -c1-8 ;;
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
    local input_feat input_ex
    input_feat="$(input_features_json "$group" | tr -d '\n')"
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
    "daimo": "https://w3id.org/daimo/ns#",
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
      "${VOCABULARY_ID}": {
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

  models_code="$(curl -s --max-time 45 -o "$models_response" -w '%{http_code}' \
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

seed_use_case_http_data_assets() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag created=0 specs_file
  tag="$(connector_tag "$connector")"
  specs_file="$WORK_DIR/use_case_model_specs.tsv"

  if ! discover_use_case_model_specs "$specs_file"; then
    return 1
  fi

  while IFS=$'\t' read -r slug title endpoint desc task subtask algo fw library; do
    [[ -z "$slug" ]] && continue
    local asset_id="${tag}-${slug}"
    local asset_title="${title} - ${tag}"
    local json_file="$WORK_DIR/${connector}_${asset_id}.json"
    local escaped_title escaped_desc escaped_task escaped_subtask escaped_algo escaped_fw escaped_library
    escaped_title="$(json_escape "$asset_title")"
    escaped_desc="$(json_escape "$desc")"
    escaped_task="$(json_escape "$task")"
    escaped_subtask="$(json_escape "$subtask")"
    escaped_algo="$(json_escape "$algo")"
    escaped_fw="$(json_escape "$fw")"
    escaped_library="$(json_escape "$library")"

    cat > "$json_file" <<ASSET_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/daimo/ns#",
    "mls": "http://www.w3.org/ns/mls#"
  },
  "@id": "${asset_id}",
  "properties": {
    "name": "${escaped_title}",
    "version": "1.0.0",
    "contenttype": "application/json",
    "assetType": "machineLearning",
    "shortDescription": "${escaped_desc}",
    "dct:description": "${escaped_desc}",
    "dcterms:description": "${escaped_desc}",
    "dcat:keyword": ["machine-learning","use-case","real-model","${tag}"],
    "assetData": {
      "${VOCABULARY_ID}": {
        "dct:title": "${escaped_title}",
        "dcterms:title": "${escaped_title}",
        "dct:description": "${escaped_desc}",
        "dcterms:description": "${escaped_desc}",
        "daimo:task": "${escaped_task}",
        "daimo:subtask": "${escaped_subtask}",
        "daimo:algorithm": "${escaped_algo}",
        "daimo:framework": "${escaped_fw}",
        "daimo:library": "${escaped_library}",
        "dct:language": ["English","Spanish"],
        "dcterms:language": ["English","Spanish"],
        "dct:license": "apache-2.0",
        "dcterms:license": "apache-2.0",
        "daimo:input_features": [{"name":"records","type":"array","description":"Batch input accepted by the deployed use-case model endpoint","nullable":false}],
        "daimo:input_example": "[{}]",
        "mls:ModelEvaluation": [{"metric":"validated_deployment","value":1.0}]
      }
    }
  },
  "dataAddress": {
    "type": "HttpData",
    "name": "${asset_id}",
    "baseUrl": "${USE_CASE_MODEL_SERVER_BASE_URL}${endpoint}",
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
      echo "[$connector] use-case HttpData asset $asset_id created (HTTP $code)"
    else
      echo "[$connector] use-case HttpData asset $asset_id FAILED (HTTP ${code:-NA})" >&2
      cat "$out_file" >&2 2>/dev/null || true
      return 1
    fi
  done < "$specs_file"

  echo "[$connector] use-case HttpData assets created: $created"
  return 0
}

seed_flares_metric_http_data_assets() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag created=0
  tag="$(connector_tag "$connector")"

  for idx in "${!FLARES_METRIC_MODEL_SLUGS[@]}"; do
    local slug="${FLARES_METRIC_MODEL_SLUGS[$idx]}"
    local title="${FLARES_METRIC_MODEL_TITLES[$idx]}"
    local endpoint="${FLARES_METRIC_MODEL_ENDPOINTS[$idx]}"
    local desc="${FLARES_METRIC_MODEL_DESCRIPTIONS[$idx]}"
    local input_columns input_feat input_ex label_column task subtask target_fields metric_evaluation supported_metrics metric_directions
    input_columns="$(flares_metric_input_columns_json "$slug")"
    input_feat="$(flares_metric_input_features_json "$slug" | tr -d '\n')"
    input_ex="$(flares_metric_input_example_json "$slug")"
    label_column="$(flares_metric_label_column "$slug")"
    if [[ "$slug" == flares-5w1h-*-metrics ]]; then
      task="Token Classification"
      subtask="5W1H span extraction"
      target_fields='["Tag_Start","Tag_End","5W1H_Label"]'
      supported_metrics='["Precision","Recall","F1"]'
      metric_directions='{"Precision":"higher","Recall":"higher","F1":"higher"}'
      metric_evaluation='[{"metric":"Precision","value":0.0},{"metric":"Recall","value":0.0},{"metric":"F1","value":0.0}]'
    else
      task="Classification"
      subtask="Reliability classification"
      target_fields='["Reliability_Label"]'
      supported_metrics='["Accuracy","Precision","Recall","F1"]'
      metric_directions='{"Accuracy":"higher","Precision":"higher","Recall":"higher","F1":"higher"}'
      metric_evaluation='[{"metric":"Accuracy","value":0.0},{"metric":"Precision","value":0.0},{"metric":"Recall","value":0.0},{"metric":"F1","value":0.0}]'
    fi

    local asset_id="${tag}-${slug}"
    local asset_title="${title} - PIONERA Use Case"
    local json_file="$WORK_DIR/${connector}_${asset_id}.json"

    cat > "$json_file" <<ASSET_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/daimo/ns#",
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
      "${VOCABULARY_ID}": {
        "dct:title": "${asset_title}",
        "dcterms:title": "${asset_title}",
        "dct:description": "${desc}",
        "dcterms:description": "${desc}",
        "daimo:task": "${task}",
        "daimo:subtask": "${subtask}",
        "daimo:algorithm": "Transformer",
        "daimo:framework": "PyTorch",
        "daimo:library": "Transformers",
        "daimo:benchmark_model_type": "metric",
        "daimo:request_shape": "batch",
        "daimo:metrics": ${supported_metrics},
        "daimo:metric_directions": ${metric_directions},
        "daimo:target_fields": ${target_fields},
        "dct:language": ["Spanish"],
        "dcterms:language": ["Spanish"],
        "dct:license": "apache-2.0",
        "dcterms:license": "apache-2.0",
        "daimo:input": ${input_columns},
        "daimo:label": "${label_column}",
        "daimo:input_features": ${input_feat},
        "daimo:input_example": "${input_ex}",
        "mls:ModelEvaluation": ${metric_evaluation}
      }
    }
  },
  "dataAddress": {
    "type": "HttpData",
    "name": "${asset_id}",
    "baseUrl": "${USE_CASE_MODEL_SERVER_BASE_URL}${endpoint}",
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
      echo "[$connector] FLARES metric HttpData asset $asset_id created (HTTP $code)"
    else
      echo "[$connector] FLARES metric HttpData asset $asset_id FAILED (HTTP ${code:-NA})" >&2
      cat "$out_file" >&2 2>/dev/null || true
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
    "daimo": "https://w3id.org/daimo/ns#",
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
      "${VOCABULARY_ID}": {
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
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@id": "${policy_id}",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "odrl:Set",
    "odrl:permission": [{"odrl:action": "USE"}],
    "odrl:prohibition": [],
    "odrl:obligation": []
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

# =============================================================================
# SEED USE-CASE BENCHMARK DATASETS (Company provider -> City Council consumer)
# =============================================================================

upload_seed_file_asset() {
  local connector="$1" token="$2" mgmt_url="$3" asset_id="$4" json_file="$5" source_file="$6" upload_filename="$7" content_type="$8" asset_label="$9"
  local up_code fin_code

  up_code="$(request_retry "$WORK_DIR/${connector}_${asset_id}.upload.out" \
    -X POST "$mgmt_url/s3assets/upload-chunk" \
    -H "Authorization: Bearer $token" \
    -H "Content-Disposition: attachment; filename=\"$upload_filename\"" \
    -H 'Chunk-Index: 0' \
    -H 'Total-Chunks: 1' \
    -F "json=@$json_file;type=application/json" \
    -F "file=@$source_file;type=$content_type")" || true

  fin_code="$(request_retry "$WORK_DIR/${connector}_${asset_id}.finalize.out" \
    -X POST "$mgmt_url/s3assets/finalize-upload" \
    -H "Authorization: Bearer $token" \
    -F "json=@$json_file;type=application/json" \
    -F "fileName=$upload_filename")" || true

  if [[ "$fin_code" == "200" || "$fin_code" == "409" ]] && [[ "$up_code" == "200" || "$up_code" == "000" || "$up_code" == "409" ]]; then
    echo "[$connector] ${asset_label} asset $asset_id upload=$up_code finalize=$fin_code"
    return 0
  fi

  echo "[$connector] ${asset_label} asset $asset_id upload=${up_code:-NA} finalize=${fin_code:-NA}" >&2
  cat "$WORK_DIR/${connector}_${asset_id}.finalize.out" >&2 2>/dev/null || true
  return 1
}

seed_mobility_segments_dataset_asset() {
  local connector="$1" token="$2" mgmt_url="$3"
  local tag dataset_filename json_file
  tag="$(connector_tag "$connector")"

  if [[ "$tag" != "company" ]]; then
    return 0
  fi

  if [[ ! -f "$MOBILITY_SEGMENTS_DATASET_FILE" ]]; then
    echo "[$connector] Mobility dataset file not found: $MOBILITY_SEGMENTS_DATASET_FILE" >&2
    return 1
  fi

  dataset_filename="$(basename "$MOBILITY_SEGMENTS_DATASET_FILE")"
  json_file="$WORK_DIR/${connector}_${MOBILITY_SEGMENTS_DATASET_ID}.json"

  cat > "$json_file" <<DATASET_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/daimo/ns#"
  },
  "@id": "${MOBILITY_SEGMENTS_DATASET_ID}",
  "properties": {
    "name": "Mobility Segments Test Dataset",
    "version": "1.0.0",
    "contenttype": "text/csv",
    "assetType": "dataset",
    "shortDescription": "Mobility benchmark validation dataset.",
    "dct:description": "CSV validation dataset for Mobility benchmark models.",
    "dcterms:description": "CSV validation dataset for Mobility benchmark models.",
    "dcterms:format": "csv",
    "dcat:keyword": ["dataset","benchmark","validation","mobility","csv"],
    "assetData": {
      "${VOCABULARY_ID}": {
        "dct:title": "Mobility Segments Test Dataset",
        "dcterms:title": "Mobility Segments Test Dataset",
        "dct:description": "CSV validation dataset for Mobility benchmark models.",
        "dcterms:description": "CSV validation dataset for Mobility benchmark models.",
        "daimo:asset_type": "dataset",
        "daimo:task": "Predictive event",
        "daimo:subtask": "Other",
        "daimo:input": [
          "trip_id",
          "journey_id",
          "from_stop_id",
          "to_stop_id",
          "departure_time",
          "arrival_time",
          "actual_travel_time",
          "scheduled_travel_time",
          "delay",
          "shape_distance",
          "route_id",
          "direction_id",
          "service_id",
          "hour",
          "weekday",
          "is_peak",
          "hour_sin",
          "hour_cos",
          "weekday_sin",
          "weekday_cos",
          "previous_delay",
          "previous_delay_ratio"
        ],
        "daimo:label": "previous_delay_delta"
      }
    }
  },
  "dataAddress": {"type":"InesDataStore"}
}
DATASET_EOF

  upload_seed_file_asset "$connector" "$token" "$mgmt_url" "$MOBILITY_SEGMENTS_DATASET_ID" "$json_file" "$MOBILITY_SEGMENTS_DATASET_FILE" "$dataset_filename" "text/csv" "Mobility dataset"
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
  local subtasks=("Other" "Text classification")
  local keywords_json=(
    '["dataset","benchmark","validation","flares","5w1h","jsonl"]'
    '["dataset","benchmark","validation","flares","reliability","jsonl"]'
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
    local keywords="${keywords_json[$idx]}"
    local input="${input_json[$idx]}"
    local label="${labels[$idx]}"
    local json_file="$WORK_DIR/${connector}_${asset_id}.json"

    if [[ ! -f "$source_file" ]]; then
      echo "[$connector] FLARES dataset file not found: $source_file" >&2
      return 1
    fi

    cat > "$json_file" <<DATASET_EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/daimo/ns#"
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
      "${VOCABULARY_ID}": {
        "dct:title": "${title}",
        "dcterms:title": "${title}",
        "dct:description": "${description}",
        "dcterms:description": "${description}",
        "daimo:asset_type": "dataset",
        "daimo:task": "Natural Language Processing",
        "daimo:subtask": "${subtask}",
        "daimo:input": ${input},
        "daimo:label": "${label}"
      }
    }
  },
  "dataAddress": {"type":"InesDataStore"}
}
DATASET_EOF

    if ! upload_seed_file_asset "$connector" "$token" "$mgmt_url" "$asset_id" "$json_file" "$source_file" "$upload_filename" "application/x-ndjson" "FLARES dataset"; then
      return 1
    fi
  done

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
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@id": "${policy_id}",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "odrl:Set",
    "odrl:permission": [{"odrl:action": "USE"}],
    "odrl:prohibition": [],
    "odrl:obligation": []
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

seed_connector() {
  local connector="$1"
  local creds_file="$CREDENTIALS_DIR/credentials-connector-$connector.json"
  local fallback_creds_file="$ROOT_DIR/deployers/inesdata/deployments/DEV/$NAMESPACE/credentials-connector-$connector.json"
  local mgmt_url="http://127.0.0.1:19193/management"
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

  kubectl -n "$NAMESPACE" port-forward "svc/$connector" 19193:19193 >"$WORK_DIR/port_forward_$connector.log" 2>&1 &
  pf_pid=$!
  sleep 2

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

  if ! ensure_vocabulary "$connector" "$token" "$mgmt_url" "$vocab_base"; then
    cleanup_pf
    return 1
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
          if ! seed_flares_metric_http_data_assets "$connector" "$token" "$mgmt_url"; then
            cleanup_pf
            return 1
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
          if ! seed_flares_metric_http_data_assets "$connector" "$token" "$mgmt_url"; then
            cleanup_pf
            return 1
          fi
        fi
        if ! seed_http_data_assets "$connector" "$token" "$mgmt_url" "$COMBINED_HTTP_COUNT"; then
          cleanup_pf
          return 1
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
    if [[ "$SKIP_INESDATA_MODELS" != "1" ]] && ! seed_inesdata_store_assets "$connector" "$token" "$mgmt_url"; then
      COUNT="$original_count"
      cleanup_pf
      return 1
    fi
    if [[ "$SKIP_INESDATA_MODELS" == "1" ]]; then
      inesdata_count_label="0"
    fi
    COUNT="$original_count"

    # Create policy + contract definition for model assets.
    if ! create_policy_and_contract "$connector" "$token" "$mgmt_url"; then
      cleanup_pf
      return 1
    fi
  fi

  if [[ "$SEED_SCOPE" == "datasets" || "$SEED_SCOPE" == "all" ]]; then
    if ! seed_mobility_segments_dataset_asset "$connector" "$token" "$mgmt_url"; then
      cleanup_pf
      return 1
    fi

    if ! seed_flares_test_dataset_assets "$connector" "$token" "$mgmt_url"; then
      cleanup_pf
      return 1
    fi

    if ! create_company_dataset_policies_and_contracts "$connector" "$token" "$mgmt_url"; then
      cleanup_pf
      return 1
    fi
  fi

  cleanup_pf
  echo "[$connector] ${SEED_SCOPE} seeding complete: $http_assets_label + $inesdata_count_label InesDataStore"
  return 0
}

# =============================================================================
# CROSS-CONNECTOR NEGOTIATIONS (5 total, after all connectors are seeded)
# =============================================================================

negotiate_one() {
  local consumer="$1" provider="$2" asset_id="$3" label="$4"
  local creds_file="$CREDENTIALS_DIR/credentials-connector-$consumer.json"
  local fallback_creds_file="$ROOT_DIR/inesdata-deployment/deployments/DEV/$NAMESPACE/credentials-connector-$consumer.json"
  local mgmt_url="http://127.0.0.1:19193/management"
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

  # Port-forward consumer
  kubectl -n "$NAMESPACE" port-forward "svc/$consumer" 19193:19193 >"$WORK_DIR/pf_neg_$consumer.log" 2>&1 &
  pf_pid=$!
  sleep 2

  neg_cleanup() {
    if [[ -n "$pf_pid" ]] && kill -0 "$pf_pid" 2>/dev/null; then
      kill "$pf_pid" >/dev/null 2>&1 || true
      wait "$pf_pid" 2>/dev/null || true
    fi
  }

  # Step 1: Request catalog from provider
  local protocol_addr="http://${provider}:19194/protocol"
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
    "limit": 50,
    "filterExpression": []
  }
}
CAT_EOF

  local cat_code
  cat_code="$(curl -s --max-time 60 -o "$catalog_out" -w '%{http_code}' \
    -X POST "$mgmt_url/v3/catalog/request" \
    -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' \
    --data-binary "@$catalog_file")" || true

  if [[ "$cat_code" != "200" ]]; then
    neg_cleanup
    echo "[negotiate] catalog request failed for $asset_id (HTTP ${cat_code:-NA})" >&2
    return 1
  fi

  # Step 2: Extract offer_id from catalog using Python (JSON-LD structure)
  local offer_id participant_id
  read -r offer_id participant_id < <(python3 -c "
import json, sys
try:
    cat = json.load(open('$catalog_out'))
except Exception:
    print(' ')
    sys.exit(0)
datasets = cat.get('dcat:dataset', [])
if isinstance(datasets, dict):
    datasets = [datasets]
pid = cat.get('dspace:participantId', cat.get('participantId', ''))
offer = ''
for ds in datasets:
    if ds.get('@id') == '$asset_id':
        pol = ds.get('odrl:hasPolicy', {})
        if isinstance(pol, list):
            pol = pol[0] if pol else {}
        offer = pol.get('@id', '')
        break
print(offer + ' ' + pid)
" 2>/dev/null) || true

  [[ -z "$participant_id" ]] && participant_id="$provider"

  if [[ -z "$offer_id" ]]; then
    neg_cleanup
    echo "[negotiate] could not extract offer_id for $asset_id from catalog" >&2
    echo "[negotiate] catalog response:" >&2
    head -c 2000 "$catalog_out" >&2
    return 1
  fi

  echo "[negotiate] found offer_id=$offer_id for $asset_id"

  # Step 3: Initiate contract negotiation
  local neg_payload="$WORK_DIR/neg_request_${asset_id}.json"
  cat > "$neg_payload" <<NEG_EOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@type": "ContractRequest",
  "counterPartyAddress": "${protocol_addr}",
  "protocol": "dataspace-protocol-http",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "odrl:Offer",
    "@id": "${offer_id}",
    "assigner": "${participant_id}",
    "target": "${asset_id}",
    "odrl:permission": [{"odrl:action": {"@id": "USE"}}],
    "odrl:prohibition": [],
    "odrl:obligation": []
  }
}
NEG_EOF

  local neg_out="$WORK_DIR/neg_result_${asset_id}.out"
  local neg_code
  neg_code="$(curl -s --max-time 30 -o "$neg_out" -w '%{http_code}' \
    -X POST "$mgmt_url/v3/contractnegotiations" \
    -H "Authorization: Bearer $token" \
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

  # Step 4: Wait for FINALIZED (up to 60 seconds)
  local deadline=$((SECONDS + 60))
  local state=""
  while [[ $SECONDS -lt $deadline ]]; do
    sleep 3
    local state_out="$WORK_DIR/neg_state_${asset_id}.out"
    curl -s --max-time 15 -o "$state_out" \
      "$mgmt_url/v3/contractnegotiations/$neg_id" \
      -H "Authorization: Bearer $token" 2>/dev/null || true

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

  echo "[negotiate] $asset_id: timeout waiting for negotiation (last state: ${state:-unknown})" >&2
  neg_cleanup
  return 1
}

negotiate_cross_connectors() {
  local total_negotiations=$(( ${#MODEL_SLUGS[@]} * 2 ))

  echo ""
  echo "=========================================="
  echo " Cross-Connector Negotiations (${total_negotiations} total)"
  echo "=========================================="

  local city_connector="" company_connector=""
  IFS=',' read -r -a _conns <<< "$CONNECTORS_CSV"
  for c in "${_conns[@]}"; do
    c="$(echo "$c" | xargs)"
    case "$c" in
      *citycouncil*) city_connector="$c" ;;
      *company*)     company_connector="$c" ;;
    esac
  done

  if [[ -z "$city_connector" || -z "$company_connector" ]]; then
    echo "Cannot run cross-connector negotiations: need both citycouncil and company connectors" >&2
    return 1
  fi

  local neg_ok=0 neg_fail=0

  # Negotiate every provider HttpData model so consumer UIs only surface contract-ready assets.
  for slug in "${MODEL_SLUGS[@]}"; do
    local asset_id="city-${slug}"
    if negotiate_one "$company_connector" "$city_connector" "$asset_id" "company->city"; then
      neg_ok=$((neg_ok + 1))
    else
      neg_fail=$((neg_fail + 1))
    fi
  done

  for slug in "${MODEL_SLUGS[@]}"; do
    local asset_id="company-${slug}"
    if negotiate_one "$city_connector" "$company_connector" "$asset_id" "city->company"; then
      neg_ok=$((neg_ok + 1))
    else
      neg_fail=$((neg_fail + 1))
    fi
  done

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
echo "Connector seeding summary: $total_ok/${#connectors[@]} succeeded (seed-scope=$SEED_SCOPE, model-set=$MODEL_SET, InesDataStore=$COUNT each)"

if [[ "${#failed_connectors[@]}" -gt 0 ]]; then
  echo "failed_connectors=${failed_connectors[*]}" >&2
  if [[ "$STRICT_MODE" == "1" ]]; then
    exit 1
  fi
fi

# Run cross-connector model negotiations only if model assets were seeded on at least 2 connectors.
if [[ "$SEED_SCOPE" == "datasets" ]]; then
  echo "Skipping cross-connector model negotiations for dataset-only seed scope"
elif [[ "$total_ok" -ge 2 ]]; then
  if ! negotiate_cross_connectors; then
    if [[ "$STRICT_MODE" == "1" ]]; then
      echo "Cross-connector negotiations did not complete successfully in strict mode" >&2
      exit 1
    fi

    echo "Warning: cross-connector negotiations were incomplete; Step 8 finished with partial federated readiness" >&2
  fi
else
  echo "Skipping cross-connector negotiations (need at least 2 successful connectors)" >&2
fi

echo ""
echo "Seed script finished."
