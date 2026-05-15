# Manual Test Samples (curl)

This is a **copy/paste-ready** set of curl commands to validate the full stack:
- provider/consumer connectors
- asset publishing
- contract + negotiation
- filtering extension
- inference extension (assetId‑based auto‑transfer)

---

## 0) Prereqs

You need two runtimes running:
- Provider (with proxy data plane)
- Consumer (with filter + inference extensions)

Optional:
- Mock inference server (for predictable output)

---

## 1) Start the Provider and Consumer

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

Mock inference server (optional):
```bash
python3 ./tools/mock-inference-server.py
```

Simple classifier server (optional):
```bash
python3 ./tools/simple-classifier-server.py
```

---

## 2) Publish AI Assets (Provider)

Daimo‑style assets:
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

Mock inference asset (endpoint‑style):
```bash
curl -d @./resources/requests/create-asset-infer-mock.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/assets -s | jq
```

Simple classifier inference asset:
```bash
curl -d @./resources/requests/create-asset-infer-simple-classifier.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/assets -s | jq
```

---

## 3) Policy + Contract Definition (Provider)

Policy definition:
```bash
curl -d @./resources/requests/create-policy.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/policydefinitions -s | jq
```

Contract definition:
```bash
curl -d @./resources/requests/create-contract-definition.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/contractdefinitions -s | jq
```

---

## 4) Catalog Fetch (Consumer)

```bash
curl -X POST "http://localhost:29193/management/v3/catalog/request" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

---

## 5) Negotiate Contract (Consumer)

From the catalog output, copy the contract offer id:
`dcat:dataset.odrl:hasPolicy.@id`

Update `resources/requests/negotiate-contract.json`:
- Replace the policy `@id` with the copied offer id

```bash
curl -X POST "http://localhost:29193/management/v3/contractnegotiations" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/negotiate-contract.json -s | jq
```

---

## 6) Filtering Extension Tests

Daimo profile (task):
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?profile=daimo&task=text-classification" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

Multi‑value (task in list):
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?profile=daimo&task=text-classification,feature-extraction" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

Generic filters:
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?filter=properties.daimo:license=MIT,Apache-2.0" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

Combined filters:
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?filter=properties.daimo:license=MIT,Apache-2.0&filter=properties.daimo:tags~demo" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

Numeric range (metrics):
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?filter=https%3A%2F%2Fpionera.ai%2Fedc%2Fdaimo%23metrics.accuracy%3E%3D0.90&filter=https%3A%2F%2Fpionera.ai%2Fedc%2Fdaimo%23metrics.accuracy%3C%3D0.95" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

Sorting:
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?sort=name" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

---

## 7) Inference Extension Tests

Asset‑based (auto‑transfer):
```bash
curl -X POST "http://localhost:29191/api/infer" \
  -H "Content-Type: application/json" \
  -d '{
    "assetId": "model-mock-infer-v1",
    "method": "POST",
    "payload": { "inputs": "Hello from Pionera" }
  }' -s | jq
```

Simple classifier example:
```bash
curl -X POST "http://localhost:29191/api/infer" \
  -H "Content-Type: application/json" \
  -d '{
    "assetId": "provider~simple-text-classifier-v1",
    "method": "POST",
    "payload": { "inputs": "This model is great but a bit slow" }
  }' -s | jq
```

Legacy (transferProcessId):
Before calling the management transfer endpoint, update:
`resources/requests/start-transfer.json` with the contract agreement id.

```bash
curl -X POST "http://localhost:29193/management/v3/transferprocesses" \
  -H "Content-Type: application/json" \
  -d @./resources/requests/start-transfer.json -s | jq

curl -X POST "http://localhost:29191/api/infer" \
  -H "Content-Type: application/json" \
  -d @./resources/requests/infer-example.json -s | jq
```

---

## 8) UI Smoke Test

- Start UI in `ui/ml-browser-app`:
  ```bash
  npm start
  ```
- Open `http://localhost:4200`
- Filters call `/api/filter/catalog`
- Execute model calls `/api/infer`

---

## 9) Reset (When Provider Restarts)

If the provider connector restarts, in‑memory data is cleared. Re‑run:
1. Asset creation
2. Policy definition
3. Contract definition
4. Contract negotiation
