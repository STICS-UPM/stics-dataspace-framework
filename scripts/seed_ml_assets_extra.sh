#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRED_FILE="$ROOT_DIR/inesdata-testing/deployments/DEV/demo/credentials-connector-conn-citycouncil-demo.json"
WORK_DIR="/tmp/inesdata_seed"
MODEL_FILE="$WORK_DIR/LGBM_Classifier_1.pkl"
COUNT="${1:-3}"
MGMT_URL="http://127.0.0.1:19193/management"

mkdir -p "$WORK_DIR"
USERNAME="$(sed -n '/"connector_user"/,/}/p' "$CRED_FILE" | sed -n 's/.*"user"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
PASSWORD="$(sed -n '/"connector_user"/,/}/p' "$CRED_FILE" | sed -n 's/.*"passwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
TOKEN="$(curl -s -X POST 'http://keycloak.dev.ed.dataspaceunit.upm:8080/realms/demo/protocol/openid-connect/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=password' \
  --data-urlencode 'client_id=dataspace-users' \
  --data-urlencode "username=$USERNAME" \
  --data-urlencode "password=$PASSWORD" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')"
[[ -n "$TOKEN" ]]

printf 'placeholder-model-bytes-%s\n' "$(date -u +%s)" > "$MODEL_FILE"

pf_pid=""
cleanup() {
  if [[ -n "$pf_pid" ]] && kill -0 "$pf_pid" 2>/dev/null; then
    kill "$pf_pid" >/dev/null 2>&1 || true
    wait "$pf_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

kubectl -n demo port-forward svc/conn-citycouncil-demo 19193:19193 >/tmp/inesdata_seed/port_forward_extra.log 2>&1 &
pf_pid=$!
sleep 2

request_retry() {
  local out="$1"
  shift
  local code attempt
  for attempt in 1 2 3; do
    code="$(curl -s --max-time 30 -o "$out" -w '%{http_code}' "$@")"
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

STAMP="$(date -u +%Y%m%d%H%M%S)"
created=0

for idx in $(seq 1 "$COUNT"); do
  id="$(printf 'ml-inesdatastore-seed-extra-%s-%02d' "$STAMP" "$idx")"
  json_file="$WORK_DIR/$id.json"

  cat > "$json_file" <<EOF
{
  "@context": {"@vocab":"https://w3id.org/edc/v0.0.1/ns/","dcterms":"http://purl.org/dc/terms/","dcat":"http://www.w3.org/ns/dcat#","daimo":"https://w3id.org/daimo/ns#","mls":"http://www.w3.org/ns/mls#"},
  "@id": "$id",
  "properties": {
    "name": "LGBM Credit Risk Extra $idx",
    "version": "2.1.$idx",
    "contenttype": "application/octet-stream",
    "assetType": "machineLearning",
    "shortDescription": "Seeded LightGBM extra asset $idx",
    "dcterms:description": "Extra machine learning asset seeded automatically.",
    "dcat:byteSize": 5242880,
    "dcterms:format": "pkl",
    "dcat:keyword": ["machine-learning","lightgbm","inesdata"],
    "assetData": {
      "JS_Pionera_Daimo": {
        "dcterms:title": "LGBM Credit Risk Extra $idx",
        "dcterms:description": "Binary classifier for default probability.",
        "daimo:task": "Tabular",
        "daimo:subtask": "Calculate default probability",
        "daimo:algorithm": "Gradient Boosting Decision Trees",
        "daimo:framework": "LightGBM",
        "daimo:library": "LightGBM",
        "dcterms:language": ["English"],
        "dcterms:license": "apache-2.0",
        "daimo:input_features": [{"name":"age","type":"integer","description":"Applicant age","nullable":false,"minValue":18,"maxValue":99}],
        "daimo:input_example": "{\"age\":40}",
        "mls:ModelEvaluation": [{"metric":"AUC","value":0.88}]
      }
    }
  },
  "dataAddress": {"type":"InesDataStore","folder":"ml-seeded-assets"}
}
EOF

  up_code="$(request_retry "$WORK_DIR/$id.upload.out" \
    -X POST "$MGMT_URL/s3assets/upload-chunk" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Disposition: attachment; filename="LGBM_Classifier_1.pkl"' \
    -H 'Chunk-Index: 0' \
    -H 'Total-Chunks: 1' \
    -F "json=@$json_file;type=application/json" \
    -F "file=@$MODEL_FILE;type=application/octet-stream")" || true

  fin_code="$(request_retry "$WORK_DIR/$id.finalize.out" \
    -X POST "$MGMT_URL/s3assets/finalize-upload" \
    -H "Authorization: Bearer $TOKEN" \
    -F "json=@$json_file;type=application/json" \
    -F 'fileName=LGBM_Classifier_1.pkl')" || true

  if [[ "$fin_code" == "200" && ( "$up_code" == "200" || "$up_code" == "000" ) ]]; then
    created=$((created + 1))
    echo "$id upload=${up_code} finalize=200"
  else
    echo "$id upload=${up_code:-NA} finalize=${fin_code:-NA}" >&2
    cat "$WORK_DIR/$id.finalize.out" >&2 || true
    exit 1
  fi
done

echo "created_assets=$created stamp=$STAMP"
