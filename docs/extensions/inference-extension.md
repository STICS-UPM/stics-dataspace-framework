# Inference Extension (Consumer-Side)

This document explains the inference extension: inputs, internal flow, error cases, and testing.

---

## 1) Goal

Provide a consumer-side API that lets the UI call a model endpoint using only an `assetId` and a payload. The extension handles transfer + EDR resolution internally.

Flow summary:
1. Filter catalog to find an asset
2. Negotiate a contract (one-time)
3. Call `/api/infer` with `assetId` and `payload`

## 2) Endpoint

```text
POST /api/infer
```

Default URL:
```text
http://localhost:29191/api/infer
```

## 3) Default transfer config

Configured in `resources/configuration/consumer-configuration.properties`:
- `asset.infer.protocol=dataspace-protocol-http`
- `asset.infer.transfer.type=HttpData-PULL`
- `asset.infer.connector.id` (optional fallback)
- `asset.infer.counterparty.address` (optional fallback)

These values are fallback defaults. The runtime now first tries to resolve `connectorId` and
`counterPartyAddress` dynamically from the selected asset's finalized agreement/negotiation.

## 4) Request format (recommended)

```json
{
  "assetId": "model-mock-infer-v1",
  "method": "POST",
  "path": "/infer",
  "headers": {
    "Content-Type": "application/json"
  },
  "payload": {
    "inputs": "Hello from Pionera"
  }
}
```

Notes:
- `assetId` is required.
- `path` is optional. If omitted, the UI uses `daimo:inference_path` or falls back to `/infer`.
- The extension does not negotiate. You must already have a contract agreement.
- For direct API callers (not the UI), include `path` or ensure the asset has `daimo:inference_path`. Otherwise the request hits the base URL.

## 5) Internal steps (what the extension does)

1. Parses request JSON
2. Resolves an EDR:
   - If `endpoint` + `authorization` are provided, uses them
   - Else, if `assetId` is provided:
     - if asset is local on the active connector, it executes directly against local data address
     - if asset is external, it looks up a matching contract agreement and starts a transfer
     - when transfer parameters are not provided in the request, it derives them from agreement + negotiation metadata
   - Else, if `contractId` is provided, it starts a transfer directly
   - Else, if `transferProcessId` is provided, it waits for the EDR
3. Sends a request to the provider proxy endpoint with method + headers + payload
4. Returns the raw response

Agreement lookup:
```text
POST {managementBaseUrl}/v3/contractagreements/request
```

EDR lookup:
```text
GET {managementBaseUrl}/v3/edrs/{transferProcessId}/dataaddress
```

## 6) Error cases

No agreement found:
```json
{"error":"No contract agreement found for assetId"}
```

Missing required fields:
```json
{"error":"Missing assetId/transferProcessId/contractId or endpoint/authorization"}
```

Non-endpoint asset:
```json
{"error":"EDR is missing endpoint (asset is not an HTTP endpoint)"}
```

## 7) Direct EDR mode (optional)

```json
{
  "endpoint": "http://localhost:19291/public",
  "authorization": "EDR_TOKEN_HERE",
  "method": "POST",
  "path": "/infer",
  "payload": { "inputs": "Hello" }
}
```

## 8) Files

- `connector/src/main/java/com/pionera/assetfilter/infer/InferenceExtension.java`
- `connector/src/main/java/com/pionera/assetfilter/infer/InferenceController.java`
- `resources/requests/infer-example.json`
- `resources/requests/create-asset-infer-mock.json`
- `tools/mock-inference-server.py`

## 9) Local mock inference test

Start server:
```bash
python3 ./tools/mock-inference-server.py
```

Create asset:
```bash
curl -d @./resources/requests/create-asset-infer-mock.json \
  -H 'content-type: application/json' \
  http://localhost:19193/management/v3/assets -s | jq
```

Call inference:
```bash
curl -X POST "http://localhost:29191/api/infer" \
  -H "Content-Type: application/json" \
  -d @./resources/requests/infer-example.json -s | jq
```

Expected output:
```json
{
  "model": "mock-inference-v1",
  "task": "echo",
  "input": { "inputs": "Hello from Pionera" },
  "result": { "label": "OK", "score": 1.0 }
}
```
