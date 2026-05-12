#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRED_FILE="$ROOT_DIR/inesdata-testing/deployments/DEV/demo/credentials-connector-conn-citycouncil-demo.json"
WORK_DIR="/tmp/inesdata_seed"
MODEL_FILE="$WORK_DIR/LGBM_Classifier_1.pkl"
MGMT_URL="http://127.0.0.1:19193/management"
KEYCLOAK_TOKEN_URL="http://keycloak.dev.ed.dataspaceunit.upm:8080/realms/demo/protocol/openid-connect/token"

mkdir -p "$WORK_DIR"

if [[ ! -f "$CRED_FILE" ]]; then
  echo "Credentials file not found: $CRED_FILE" >&2
  exit 1
fi

USERNAME="$(sed -n '/"connector_user"/,/}/p' "$CRED_FILE" | sed -n 's/.*"user"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
PASSWORD="$(sed -n '/"connector_user"/,/}/p' "$CRED_FILE" | sed -n 's/.*"passwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"

if [[ -z "$USERNAME" || -z "$PASSWORD" ]]; then
  echo "Could not extract connector_user credentials" >&2
  exit 1
fi

TOKEN="$(curl -s -X POST "$KEYCLOAK_TOKEN_URL" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=password' \
  --data-urlencode 'client_id=dataspace-users' \
  --data-urlencode "username=$USERNAME" \
  --data-urlencode "password=$PASSWORD" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')"

if [[ -z "$TOKEN" ]]; then
  echo "Failed to obtain access token" >&2
  exit 1
fi

printf 'placeholder-model-bytes-%s\n' "$(date -u +%s)" > "$MODEL_FILE"

pf_pid=""
cleanup() {
  if [[ -n "$pf_pid" ]] && kill -0 "$pf_pid" 2>/dev/null; then
    kill "$pf_pid" >/dev/null 2>&1 || true
    wait "$pf_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

kubectl -n demo port-forward svc/conn-citycouncil-demo 19193:19193 >/tmp/inesdata_seed/port_forward.log 2>&1 &
pf_pid=$!
sleep 2

if ! curl -s -o /tmp/inesdata_seed/mgmt_probe.out -w '%{http_code}' "$MGMT_URL/v3/assets/request" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"filterExpression":[]}' | grep -Eq '200|4..'; then
  echo "Management API probe failed" >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%d%H%M%S)"
created_ids=()

request_with_retry() {
  local out_file="$1"
  shift

  local attempt code
  for attempt in 1 2 3; do
    code="$(curl -s -o "$out_file" -w '%{http_code}' "$@")"
    if [[ "$code" == "200" ]]; then
      echo "$code"
      return 0
    fi
    if [[ "$code" != "504" ]]; then
      echo "$code"
      return 1
    fi
    sleep 2
  done

  echo "$code"
  return 1
}

for i in 1 2 3 4 5 6 7 8; do
  id="$(printf 'ml-inesdatastore-seed-%s-%02d' "$STAMP" "$i")"
  title="$(printf 'LGBM Credit Risk Classifier %02d' "$i")"
  auc="$(awk -v n="$i" 'BEGIN{printf "%.2f", 0.84 + (n*0.01)}')"
  recall="$(awk -v n="$i" 'BEGIN{printf "%.2f", 0.72 + (n*0.01)}')"
  f1="$(awk -v n="$i" 'BEGIN{printf "%.2f", 0.70 + (n*0.01)}')"
  json_file="$WORK_DIR/$id.json"

  cat > "$json_file" <<EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "daimo": "https://w3id.org/daimo/ns#",
    "mls": "http://www.w3.org/ns/mls#"
  },
  "@id": "$id",
  "properties": {
    "name": "$title",
    "version": "1.0.$i",
    "contenttype": "application/octet-stream",
    "assetType": "machineLearning",
    "shortDescription": "LightGBM classifier for default-risk scoring (seeded dataset $i).",
    "dcterms:description": "Modelo LightGBM para scoring de riesgo de impago con metadatos DAIMO completos.",
    "dcat:byteSize": 5242880,
    "dcterms:format": "pkl",
    "dcat:keyword": ["machine-learning","lightgbm","risk","classification","inesdata"],
    "assetData": {
      "JS_Pionera_Daimo": {
        "dcterms:title": "$title",
        "dcterms:description": "Binary classifier for loan default probability estimation.",
        "daimo:task": "Tabular",
        "daimo:subtask": "Calculate default probability",
        "daimo:algorithm": "Gradient Boosting Decision Trees",
        "daimo:framework": "LightGBM",
        "daimo:library": "LightGBM",
        "dcterms:language": ["English","Spanish"],
        "dcterms:license": "apache-2.0",
        "daimo:input_features": [
          {"name":"age","type":"integer","description":"Applicant age in years","nullable":false,"minValue":18,"maxValue":99},
          {"name":"annual_income","type":"number","description":"Annual income in EUR","nullable":false,"minValue":0,"maxValue":1000000},
          {"name":"debt_ratio","type":"number","description":"Debt to income ratio","nullable":false,"minValue":0,"maxValue":2},
          {"name":"late_payments_12m","type":"integer","description":"Late payments in last 12 months","nullable":false,"minValue":0,"maxValue":24}
        ],
        "daimo:input_example": "{\"age\":41,\"annual_income\":52000,\"debt_ratio\":0.36,\"late_payments_12m\":1}",
        "mls:ModelEvaluation": [
          {"metric":"AUC","value":$auc},
          {"metric":"Recall","value":$recall},
          {"metric":"F1","value":$f1}
        ]
      }
    }
  },
  "dataAddress": {"type":"InesDataStore","folder":"ml-seeded-assets"}
}
EOF

  upload_out="$WORK_DIR/$id.upload.out"
  finalize_out="$WORK_DIR/$id.finalize.out"

  upload_code="$(request_with_retry "$upload_out" \
    -X POST "$MGMT_URL/s3assets/upload-chunk" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Disposition: attachment; filename="LGBM_Classifier_1.pkl"' \
    -H 'Chunk-Index: 0' \
    -H 'Total-Chunks: 1' \
    -F "json=@$json_file;type=application/json" \
    -F "file=@$MODEL_FILE;type=application/octet-stream")" || true

  finalize_code="$(request_with_retry "$finalize_out" \
    -X POST "$MGMT_URL/s3assets/finalize-upload" \
    -H "Authorization: Bearer $TOKEN" \
    -F "json=@$json_file;type=application/json" \
    -F 'fileName=LGBM_Classifier_1.pkl')" || true

  if [[ "$upload_code" == "200" && "$finalize_code" == "200" ]]; then
    created_ids+=("$id")
    echo "$id upload=200 finalize=200"
  else
    echo "$id upload=${upload_code:-NA} finalize=${finalize_code:-NA}" >&2
    echo "upload body:" >&2
    cat "$upload_out" >&2 || true
    echo "finalize body:" >&2
    cat "$finalize_out" >&2 || true
    exit 1
  fi
done

printf '%s\n' "${created_ids[@]}" > "$WORK_DIR/created_ids.txt"
echo "created_assets=${#created_ids[@]} stamp=$STAMP"
