# 47. Evidencia de Interoperabilidad EDC — STICS (Provider ↔ Consumer)

## Qué demuestra este documento

Este documento deja constancia, con comandos ejecutables, de que los dos
conectores EDC del proyecto STICS —desplegados manualmente vía Docker Compose
(ver [12_local_validation_environment.md](./12_local_validation_environment.md)
y el histórico del proyecto)— interoperan correctamente dentro del dataspace
real: autenticación OAuth2 contra Keycloak, publicación de catálogo DSP,
negociación de contrato y **ambos** tipos de transferencia soportados por el
conector (`HttpData-PULL` y `HttpData-PUSH`).

Ejecutado y verificado el 2026-07-02 contra el entorno real `vm-distributed`
del dataspace `stics`:

| Rol | Identidad (participant id) | VM | URL pública |
| --- | --- | --- | --- |
| Provider | `connector-stics` | `178.105.249.140` | `https://stics.bavenir.eu` |
| Consumer | `conlab-stics` | `192.168.122.239` | `https://con-lab.stics.linkeddata.es` |

Los assets/políticas/definiciones de contrato creados durante estas pruebas
se han dejado intencionadamente en el provider como evidencia — no son datos
de producción, son artefactos de prueba (`stics-interop-*`, `stics-push-*`).

## Requisitos previos

- `curl` y `jq` instalados.
- Credenciales de gestión (`connector_user`) de cada conector. Estas **no**
  están en este documento porque son secretas; se obtienen de:

  ```text
  deployers/edc/deployments/DEV/vm-distributed/stics/connectors/<connector-name>/credentials.json
  ```

  Campo `connector_user.user` / `connector_user.passwd`, para
  `connector-stics` (provider) y `conlab-stics` (consumer).

## 1. Variables de entorno

```bash
export KEYCLOAK_TOKEN_URL="https://auth.dev.linkeddata.es/realms/stics/protocol/openid-connect/token"

export PROVIDER_MGMT="https://stics.bavenir.eu/management"
export PROVIDER_DSP="https://stics.bavenir.eu/protocol"
export PROVIDER_PARTICIPANT_ID="connector-stics"
export PROVIDER_USER="user-connector-stics"          # ver credentials.json
export PROVIDER_PASSWORD="<copiar de credentials.json>"

export CONSUMER_MGMT="https://con-lab.stics.linkeddata.es/management"
export CONSUMER_PARTICIPANT_ID="conlab-stics"
export CONSUMER_USER="user-conlab-stics"              # ver credentials.json
export CONSUMER_PASSWORD="<copiar de credentials.json>"

# sufijo único para no chocar con ejecuciones anteriores
export RUN_ID=$(date +%s)
```

Nota: todos los ejemplos usan `curl -k` porque el dataspace usa un CA interno
autofirmado (`pionera-internal-ingress-tls`), no porque el TLS esté mal
configurado.

## 2. Obtener tokens de gestión (Keycloak, grant `password`, client `dataspace-users`)

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

## 3. Provider: crear Asset + Policy + ContractDefinition

El validador de asset de INESData exige más campos que el ejemplo estándar de
Eclipse EDC: `version`, `shortDescription`, `description`, `assetType`, y
además `dcterms:description` / `dcat:keyword` con sus prefijos declarados en
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

Cada llamada debe devolver `200` con un `IdResponse`.

## 4. Consumer: consultar el catálogo del provider y extraer la oferta

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

Si `OFFER_ID` sale vacío, esperar unos segundos: el catálogo se rellena por
el crawler periódico del registration-service (cada
`edc.catalog.cache.execution.period.seconds`, 60s en este entorno) y puede no
haber corrido aún tras crear el asset.

## 5. Consumer: negociar el contrato

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

# Poll hasta FINALIZED (normalmente 2-6s)
until [ "$(curl -sk -H "Authorization: Bearer $CONSUMER_TOKEN" \
  "$CONSUMER_MGMT/v3/contractnegotiations/$NEGOTIATION_ID" | jq -r '.state')" = "FINALIZED" ]; do
  sleep 2
done

CONTRACT_AGREEMENT_ID=$(curl -sk -H "Authorization: Bearer $CONSUMER_TOKEN" \
  "$CONSUMER_MGMT/v3/contractnegotiations/$NEGOTIATION_ID" | jq -r '.contractAgreementId')
echo "Contract agreement id: $CONTRACT_AGREEMENT_ID"
```

## 6a. Transferencia `HttpData-PULL`

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

# Poll hasta STARTED/COMPLETED
until curl -sk -H "Authorization: Bearer $CONSUMER_TOKEN" \
  "$CONSUMER_MGMT/v3/transferprocesses/$TRANSFER_ID" | jq -e '.state == "STARTED" or .state == "COMPLETED"' >/dev/null; do
  sleep 2
done

# Obtener el EDR (Endpoint Data Reference) y tirar del dato real
EDR=$(curl -sk -H "Authorization: Bearer $CONSUMER_TOKEN" \
  "$CONSUMER_MGMT/v3/edrs/$TRANSFER_ID/dataaddress")
ENDPOINT=$(echo "$EDR" | jq -r '.endpoint')
AUTH=$(echo "$EDR" | jq -r '.authorization')

curl -sk "$ENDPOINT" -H "Authorization: $AUTH"
```

**Resultado esperado** (dato real tirado a través del data-plane del
provider): un JSON del tipo `{"userId":1,"id":1,"title":"...","completed":false}`.

## 6b. Transferencia `HttpData-PUSH`

Requiere un asset/policy/contract-definition nuevos (repetir pasos 3-5 con un
`RUN_ID` distinto), y un destino HTTP público donde el provider pueda hacer
`POST` directamente. En esta prueba se usó un receptor simple
(`http.server` de Python) expuesto como una ruta adicional del propio
Ingress del consumer.

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

**Verificación real (2026-07-02)**: el receptor de prueba registró un
`POST /push-sink` con `X-Real-IP: 178.105.249.140` (la IP real del provider)
y `User-Agent: okhttp/4.12.0` (el cliente HTTP del propio conector),
entregando el cuerpo JSON real — confirma que el *data-plane* del provider
empuja directamente al destino indicado por el consumer, sin pasar por un
EDR firmado.

## Resultados obtenidos en la ejecución de referencia

| Paso | Resultado |
| --- | --- |
| Token provider/consumer | `200`, JWT válido |
| Create asset/policy/contract-definition | `200` en los tres |
| Fetch catalog | `200`, asset presente |
| Negotiate contract | `200` → `AGREED` → `FINALIZED` |
| Transfer `HttpData-PULL` | `STARTED`, EDR `200`, dato real `200` |
| Transfer `HttpData-PUSH` | `COMPLETED`, POST real recibido con IP del provider |

## Ficheros Postman equivalentes

Para quien prefiera Postman a `curl`, hay una colección autocontenida y su
entorno en:

```text
validation/core/collections/postman/04_stics_edc_interop.json
validation/core/collections/postman/00_environment_stics.json
```

Importar ambos en Postman, seleccionar el entorno `00 Environment - STICS EDC
Interop`, rellenar `provider_password` / `consumer_password` (marcados como
`<copiar localmente>`, provienen de los `credentials.json` mencionados
arriba) y ejecutar la colección en orden con "Run collection".
