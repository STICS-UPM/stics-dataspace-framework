# Commands Reference (Asset Filter Template)

This is the full, step-by-step workflow in the same style as the Samples tutorials. Each step includes what it does, the command, and a sample output or troubleshooting note.

---

## Prereqs

- Java 17+
- `jq`
- Ports free: 19193, 19194, 19291 (provider) and 29191, 29193, 29194 (consumer)
- If Gradle needs a local cache: use `GRADLE_USER_HOME=./.gradle`

## 0) Build

```bash
./gradlew :connector:build
./gradlew :provider-proxy-data-plane:build
./gradlew :final-connector:build
```

If Checkstyle fails, see **Troubleshooting**.

## 1) Run provider and consumer

Provider:
```bash
java -Dedc.fs.config=./resources/configuration/provider-configuration.properties \
  -jar ./provider-proxy-data-plane/build/libs/connector.jar

```

Consumer:
```bash
java -Dedc.fs.config=./resources/configuration/consumer-configuration.properties \
  -jar ./connector/build/libs/connector.jar
```


Provider-final:
```bash
java -Dedc.fs.config=./resources/configuration/provider-configuration.properties \
  -jar ./final-connector/build/libs/connector.jar

```

Consumer-final:
```bash
java -Dedc.fs.config=./resources/configuration/consumer-configuration.properties \
  -jar ./final-connector/build/libs/connector.jar
```

Expected log excerpt:
```text
INFO ... Booting EDC runtime
INFO ... Runtime ... ready
```

## 2) Create assets (provider)

### AI model assets
```bash
curl -d @./resources/requests/ai-models/create-asset-ai-classification.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/assets -s | jq

curl -d @./resources/requests/ai-models/create-asset-ai-regression.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/assets -s | jq

curl -d @./resources/requests/ai-models/create-asset-ai-embedding.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/assets -s | jq
```

### Mock inference asset
```bash
curl -d @./resources/requests/create-asset-infer-mock.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/assets -s | jq
```

Sample output:
```json
{
  "@type": "IdResponse",
  "@id": "model-iris-multiclass-v1"
}
```

## 3) Create policy + contract definition (provider)

These make all assets accessible (empty selector), so the consumer can negotiate a contract for any asset.

```bash
curl -d @./resources/requests/create-policy.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/policydefinitions -s | jq

curl -d @./resources/requests/create-contract-definition.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/contractdefinitions -s | jq
```

Sample output:
```json
{
  "@type": "IdResponse",
  "@id": "1",
  "createdAt": 1700000000000
}
```

## 4) Fetch catalog (consumer, sanity check)

```bash
curl -X POST "http://localhost:29193/management/v3/catalog/request" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

Sample output (trimmed):
```json
{
  "@type": "dcat:Catalog",
  "dcat:dataset": [
    { "@id": "model-iris-multiclass-v1", "name": "Iris Multiclass Classifier v1" },
    { "@id": "model-text-embedding-v3", "name": "Text Embedding Model v3" }
  ]
}
```

If `dcat:dataset` is empty, ensure:
- provider is running
- policy + contract definition exist
- assets were created

Important:
- `catalog/request` shows counterparty offers (external view), not your own local assets.

### 4.1) List local assets (provider)

```bash
curl -X POST "http://localhost:19193/management/v3/assets/request" \
  -H 'Content-Type: application/json' \
  -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"},"filterExpression":[]}' -s | jq
```

Use `29193` instead of `19193` to list local assets on consumer.

## 5) Negotiate contract (consumer)

From the catalog output, copy the contract offer id at:
`dcat:dataset.odrl:hasPolicy.@id`

Update `resources/requests/negotiate-contract.json`:
1. Replace the policy `@id` with the copied offer id.
2. Replace `assigner`/`target` if you changed connector IDs or asset ids.

Then run:
```bash
curl -d @./resources/requests/negotiate-contract.json \
  -X POST -H 'content-type: application/json' http://localhost:29193/management/v3/contractnegotiations \
  -s | jq
```

Sample output:
```json
{
  "@type": "IdResponse",
  "@id": "<negotiation-id>"
}
```

### 5.1) Wait for agreement (optional but recommended)

Poll until it reaches `FINALIZED`:
```bash
curl -X GET "http://localhost:29193/management/v3/contractnegotiations/<negotiation-id>" -s | jq
```

When finalized, the agreement id is at:
`contractAgreementId` (or `edc:contractAgreementId` depending on output).

## 6) Filter catalog (extension)

This calls the consumer filter extension at `/api/filter/catalog` and applies server‑side filters.

Daimo profile + task filter:
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?profile=daimo&task=text-classification" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

Multi‑value filter:
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?profile=daimo&task=text-classification,feature-extraction" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

Generic filter (no profile):
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?filter=properties.daimo:license=MIT,Apache-2.0" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

## 7) Inference (extension)

### Start mock inference server (separate terminal)
```bash
python3 ./tools/mock-inference-server.py
```

### Call inference by asset id
The extension will resolve contract agreement + transfer + EDR automatically.
```bash
curl -X POST "http://localhost:29191/api/infer" \
  -H "Content-Type: application/json" \
  -d @./resources/requests/infer-example.json -s | jq
```

Sample output:
```json
{
  "model": "mock-inference-v1",
  "task": "echo",
  "input": { "inputs": "Hello from Pionera" },
  "result": { "label": "OK", "score": 1.0 }
}
```

## 8) UI

```bash
cd ./ui/ml-browser-app
npm install
npm start
```

Open: `http://localhost:4200`

If the UI fails to load models, see **Troubleshooting**.

## Troubleshooting

**Checkstyle header warnings**
- Ensure `resources/edc-checkstyle-config.xml` + `resources/suppressions.xml` exist (copied from Samples).
- Our custom Java files must include the Apache header.

**CORS errors from UI**
- In `resources/configuration/consumer-configuration.properties`, set:
  - `edc.web.rest.cors.enabled=true`
  - `edc.web.rest.cors.origins=http://localhost:4200`
- Restart consumer.

Important:
- Do not list multiple origins in a single header value. Browsers reject it.
- If you use `127.0.0.1:4200`, set that as the single allowed origin and open UI using `127.0.0.1`.

**Catalog filter says `Invalid catalog request`**
- Your request body must include `counterPartyAddress` and `protocol` in `fetch-catalog.json`.

**Policy endpoint 404**
- Use `/management/v3/policydefinitions` (not `/policies`).

**Inference returns empty or 404**
- Ensure contract negotiation finished.
- Ensure mock inference server is running.
- Asset must be an endpoint asset with `contenttype: application/json` and `daimo:inference_path`.
