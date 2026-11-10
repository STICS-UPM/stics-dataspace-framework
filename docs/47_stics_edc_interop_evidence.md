# 47. EDC Interoperability Evidence — STICS (Provider ↔ Consumer)

## What this document proves

This document records, with runnable commands, that the two EDC connectors of
the STICS project (deployed manually with Docker Compose; see
[12_local_validation_environment.md](./12_local_validation_environment.md)
and the project history) interoperate correctly inside the real dataspace:
OAuth2 authentication against Keycloak, DSP catalog publication, contract
negotiation, and **both** transfer types supported by the connector
(`HttpData-PULL` and `HttpData-PUSH`).

Run and verified on 2026-07-02 against the real `vm-distributed` environment
of the `stics` dataspace:

| Role | Identity (participant id) | VM | Public URL |
| --- | --- | --- | --- |
| Provider | `connector-stics` | `178.105.249.140` | `https://stics.bavenir.eu` |
| Consumer | `conlab-stics` | `192.168.122.239` | `https://con-lab.stics.linkeddata.es` |

The assets, policies, and contract definitions created during these tests
were intentionally left on the provider as evidence. They are not production
data; they are test artifacts (`stics-interop-*`, `stics-push-*`).

## Prerequisites

- `curl` and `jq` installed.
- Management credentials (`connector_user`) for each connector. They are
  **not** in this document because they are secret; get them from:

  ```text
  deployers/edc/deployments/DEV/vm-distributed/stics/connectors/<connector-name>/credentials.json
  ```

  Fields `connector_user.user` / `connector_user.passwd`, for
  `connector-stics` (provider) and `conlab-stics` (consumer).

## 1. Environment variables

```bash
export KEYCLOAK_TOKEN_URL="https://auth.dev.linkeddata.es/realms/stics/protocol/openid-connect/token"

export PROVIDER_MGMT="https://stics.bavenir.eu/management"
export PROVIDER_DSP="https://stics.bavenir.eu/protocol"
export PROVIDER_PARTICIPANT_ID="connector-stics"
export PROVIDER_USER="user-connector-stics"          # see credentials.json
export PROVIDER_PASSWORD="<copy from credentials.json>"

export CONSUMER_MGMT="https://con-lab.stics.linkeddata.es/management"
export CONSUMER_PARTICIPANT_ID="conlab-stics"
export CONSUMER_USER="user-conlab-stics"              # see credentials.json
export CONSUMER_PASSWORD="<copy from credentials.json>"

# unique suffix to avoid clashing with previous runs
export RUN_ID=$(date +%s)
```

Note: every example uses `curl -k` because the dataspace uses an internal
self-signed CA (`pionera-internal-ingress-tls`), not because TLS is
misconfigured.

## 2. Get management tokens (Keycloak, `password` grant, `dataspace-users` client)

```bash
PROVIDER_TOKEN=$(curl -sk -X POST "$KEYCLOAK_TOKEN_URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=dataspace-users" \
  -d "username=$PROVIDER_USER" \
  -d "password=$PROVIDER_PASSWORD" \
  -d "scope=openid profile email" | jq -r '.access_token')

CONSUMER_TOKEN=$(curl -sk -X POST "$KEYCLOAK_TOKEN_URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=dataspace-users" \
  -d "username=$CONSUMER_USER" \
  -d "password=$CONSUMER_PASSWORD" \
  -d "scope=openid profile email" | jq -r '.access_token')

echo "provider token length: ${#PROVIDER_TOKEN}"
echo "consumer token length: ${#CONSUMER_TOKEN}"
```

## 3. Provider: create Asset + Policy + ContractDefinition

The INESData asset validator requires more fields than the standard Eclipse
EDC example: `version`, `shortDescription`, `description`, `assetType`, plus
`dcterms:description` / `dcat:keyword` with their prefixes declared in
`@context`.

```bash
ASSET_ID="stics-interop-asset-$RUN_ID"
POLICY_ID="stics-interop-policy-$RUN_ID"
CD_ID="stics-interop-cd-$RUN_ID"

curl -sk -X POST "$PROVIDER_MGMT/v3/assets" \
  -H "Authorization: Bearer $PROVIDER_TOKEN" -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#"
  },
  "@id": "$ASSET_ID",
  "properties": {
    "name": "stics interop test asset",
    "contenttype": "application/json",
    "version": "1.0.0",
    "shortDescription": "STICS provider-consumer interoperability test asset",
    "description": "STICS provider-consumer interoperability test asset",
    "assetType": "dataset",
    "dcterms:description": "STICS provider-consumer interoperability test asset",
    "dcat:keyword": ["stics", "interop-test"]
  },
  "dataAddress": {
    "type": "HttpData",
    "name": "stics interop test asset",
    "baseUrl": "https://jsonplaceholder.typicode.com/todos/1",
    "proxyPath": "true"
  }
}
EOF

curl -sk -X POST "$PROVIDER_MGMT/v3/policydefinitions" \
  -H "Authorization: Bearer $PROVIDER_TOKEN" -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/", "odrl": "http://www.w3.org/ns/odrl/2/"},
  "@id": "$POLICY_ID",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "Set",
    "permission": [], "prohibition": [], "obligation": []
  }
}
EOF

curl -sk -X POST "$PROVIDER_MGMT/v3/contractdefinitions" \
  -H "Authorization: Bearer $PROVIDER_TOKEN" -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@id": "$CD_ID",
  "accessPolicyId": "$POLICY_ID",
  "contractPolicyId": "$POLICY_ID",
  "assetsSelector": [
    {"@type": "CriterionDto", "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id", "operator": "=", "operandRight": "$ASSET_ID"}
  ]
}
EOF
```

Each call must return `200` with an `IdResponse`.

## 4. Consumer: query the provider catalog and extract the offer

```bash
CATALOG=$(curl -sk -X POST "$CONSUMER_MGMT/v3/catalog/request" \
  -H "Authorization: Bearer $CONSUMER_TOKEN" -H "Content-Type: application/json" \
  -d "{\"@context\":{\"@vocab\":\"https://w3id.org/edc/v0.0.1/ns/\"},\"counterPartyAddress\":\"$PROVIDER_DSP\",\"protocol\":\"dataspace-protocol-http\"}")

OFFER_ID=$(echo "$CATALOG" | jq -r --arg aid "$ASSET_ID" \
  '(."dcat:dataset" // ."http://www.w3.org/ns/dcat#dataset") as $ds
   | (if ($ds | type) == "array" then $ds else [$ds] end)
   | map(select(.["@id"] == $aid)) | .[0]
   | (.["odrl:hasPolicy"] // .hasPolicy) as $offer
   | (if ($offer | type) == "array" then $offer[0] else $offer end)
   | .["@id"]')

echo "Offer id: $OFFER_ID"
```

If `OFFER_ID` is empty, wait a few seconds: the catalog is filled by the
registration-service's periodic crawler (every
`edc.catalog.cache.execution.period.seconds`, 60 s in this environment), which
may not have run yet after the asset was created.

## 5. Consumer: negotiate the contract

```bash
NEGOTIATION=$(curl -sk -X POST "$CONSUMER_MGMT/v3/contractnegotiations" \
  -H "Authorization: Bearer $CONSUMER_TOKEN" -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@type": "ContractRequest",
  "counterPartyAddress": "$PROVIDER_DSP",
  "protocol": "dataspace-protocol-http",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@id": "$OFFER_ID",
    "@type": "Offer",
    "assigner": "$PROVIDER_PARTICIPANT_ID",
    "target": "$ASSET_ID"
  }
}
EOF
)
NEGOTIATION_ID=$(echo "$NEGOTIATION" | jq -r '."@id"')
echo "Negotiation id: $NEGOTIATION_ID"

# Poll until FINALIZED (usually 2-6 s)
until [ "$(curl -sk -H "Authorization: Bearer $CONSUMER_TOKEN" \
  "$CONSUMER_MGMT/v3/contractnegotiations/$NEGOTIATION_ID" | jq -r '.state')" = "FINALIZED" ]; do
  sleep 2
done

CONTRACT_AGREEMENT_ID=$(curl -sk -H "Authorization: Bearer $CONSUMER_TOKEN" \
  "$CONSUMER_MGMT/v3/contractnegotiations/$NEGOTIATION_ID" | jq -r '.contractAgreementId')
echo "Contract agreement id: $CONTRACT_AGREEMENT_ID"
```

## 6a. `HttpData-PULL` transfer

```bash
TRANSFER=$(curl -sk -X POST "$CONSUMER_MGMT/v3/transferprocesses" \
  -H "Authorization: Bearer $CONSUMER_TOKEN" -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@type": "TransferRequestDto",
  "connectorId": "$PROVIDER_PARTICIPANT_ID",
  "counterPartyAddress": "$PROVIDER_DSP",
  "contractId": "$CONTRACT_AGREEMENT_ID",
  "protocol": "dataspace-protocol-http",
  "transferType": "HttpData-PULL"
}
EOF
)
TRANSFER_ID=$(echo "$TRANSFER" | jq -r '."@id"')
echo "Transfer id: $TRANSFER_ID"

# Poll until STARTED/COMPLETED
until curl -sk -H "Authorization: Bearer $CONSUMER_TOKEN" \
  "$CONSUMER_MGMT/v3/transferprocesses/$TRANSFER_ID" | jq -e '.state == "STARTED" or .state == "COMPLETED"' >/dev/null; do
  sleep 2
done

# Get the EDR (Endpoint Data Reference) and pull the real data
EDR=$(curl -sk -H "Authorization: Bearer $CONSUMER_TOKEN" \
  "$CONSUMER_MGMT/v3/edrs/$TRANSFER_ID/dataaddress")
ENDPOINT=$(echo "$EDR" | jq -r '.endpoint')
AUTH=$(echo "$EDR" | jq -r '.authorization')

curl -sk "$ENDPOINT" -H "Authorization: $AUTH"
```

**Expected result** (real data pulled through the provider's data plane): a
JSON such as `{"userId":1,"id":1,"title":"...","completed":false}`.

## 6b. `HttpData-PUSH` transfer

Requires a new asset, policy, and contract definition (repeat steps 3-5 with a
different `RUN_ID`), and a public HTTP destination the provider can `POST` to
directly. This test used a simple receiver (Python `http.server`) exposed as
an additional path on the consumer's own Ingress.

```bash
export PUSH_SINK_URL="https://con-lab.stics.linkeddata.es/push-sink"

TRANSFER_PUSH=$(curl -sk -X POST "$CONSUMER_MGMT/v3/transferprocesses" \
  -H "Authorization: Bearer $CONSUMER_TOKEN" -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
  "@type": "TransferRequestDto",
  "connectorId": "$PROVIDER_PARTICIPANT_ID",
  "counterPartyAddress": "$PROVIDER_DSP",
  "contractId": "$CONTRACT_AGREEMENT_ID",
  "protocol": "dataspace-protocol-http",
  "transferType": "HttpData-PUSH",
  "dataDestination": {
    "type": "HttpData",
    "baseUrl": "$PUSH_SINK_URL"
  }
}
EOF
)
TRANSFER_PUSH_ID=$(echo "$TRANSFER_PUSH" | jq -r '."@id"')

until curl -sk -H "Authorization: Bearer $CONSUMER_TOKEN" \
  "$CONSUMER_MGMT/v3/transferprocesses/$TRANSFER_PUSH_ID" | jq -e '.state == "COMPLETED"' >/dev/null; do
  sleep 2
done
echo "PUSH transfer COMPLETED"
```

**Real verification (2026-07-02)**: the test receiver logged a
`POST /push-sink` with `X-Real-IP: 178.105.249.140` (the provider's real IP)
and `User-Agent: okhttp/4.12.0` (the connector's own HTTP client), delivering
the real JSON body. This confirms that the provider's *data plane* pushes
directly to the destination given by the consumer, without going through a
signed EDR.

## Results of the reference run

| Step | Result |
| --- | --- |
| Provider/consumer token | `200`, valid JWT |
| Create asset/policy/contract-definition | `200` for all three |
| Fetch catalog | `200`, asset present |
| Negotiate contract | `200` → `AGREED` → `FINALIZED` |
| Transfer `HttpData-PULL` | `STARTED`, EDR `200`, real data `200` |
| Transfer `HttpData-PUSH` | `COMPLETED`, real POST received from the provider's IP |

## Equivalent Postman files

If you prefer Postman to `curl`, there is a self-contained collection and its
environment in:

```text
validation/core/collections/postman/04_stics_edc_interop.json
validation/core/collections/postman/00_environment_stics.json
```

Import both into Postman, select the `00 Environment - STICS EDC Interop`
environment, fill in `provider_password` / `consumer_password` (placeholder
values; they come from the `credentials.json` files mentioned above), and run
the collection in order with "Run collection".
