# Developer Guide: Filtering and Inference Extensions

This guide explains how to integrate and operate the custom extensions from a software developer perspective.

Scope:
- `AssetFilterExtension` (`/api/filter/catalog`)
- `InferenceExtension` (`/api/infer`)

Related source files:
- `connector/src/main/java/com/pionera/assetfilter/filter/AssetFilterExtension.java`
- `connector/src/main/java/com/pionera/assetfilter/filter/AssetFilterController.java`
- `connector/src/main/java/com/pionera/assetfilter/infer/InferenceExtension.java`
- `connector/src/main/java/com/pionera/assetfilter/infer/InferenceController.java`

## 1) Runtime and Activation Model

Both extensions are regular EDC `ServiceExtension`s and are activated through Java service loader registration:

- `connector/src/main/resources/META-INF/services/org.eclipse.edc.spi.system.ServiceExtension`

At runtime boot:
1. EDC discovers the extension classes from service loader metadata.
2. EDC injects dependencies (`WebService`, `TypeManager`, `Monitor`).
3. Each extension registers a JAX-RS resource into API context `web.http.path` (default `/api`).

Effective endpoints in this project:
- `POST http://localhost:29191/api/filter/catalog`
- `POST http://localhost:29191/api/infer`

## 2) Configuration Keys

### 2.1 Shared (used by both)

From `resources/configuration/consumer-configuration.properties`:
- `edc.hostname` (optional; defaults to `localhost` in code)
- `web.http.management.port` (default `29193`)
- `web.http.management.path` (default `/management`)

These build the management base URL used for internal control-plane API calls.

### 2.2 Inference-specific

- `asset.infer.connector.id` (default `provider`)
- `asset.infer.counterparty.address` (default `http://localhost:19194/protocol`)
- `asset.infer.protocol` (default `dataspace-protocol-http`)
- `asset.infer.transfer.type` (default `HttpData-PULL`)

## 3) Filtering Extension (`/api/filter/catalog`)

## 3.1 Purpose

Provide a developer-friendly catalog filtering API on top of EDC `POST /management/v3/catalog/request`, adding:
- query-based filtering
- Daimo profile field mapping
- search (`q`)
- sorting (`sort`, `order`)

## 3.2 Request Contract

Method and path:
- `POST /api/filter/catalog`

Body:
- Must be a valid catalog request body with:
  - `counterPartyAddress`
  - `protocol`
- The controller accepts compact and expanded key forms:
  - `counterPartyAddress` / `protocol`
  - `edc:counterPartyAddress` / `edc:protocol`
  - full IRI equivalents

Query parameters:
- `profile=daimo` enables short Daimo facets
- `task`, `license`, `tag|tags`, `library`, `dataset`, `language`, `base_model`, `name`
- `filter=<expression>` for generic field expressions
- `q=<term>` full-text-like search over selected fields
- `sort=<field>`
- `order=asc|desc` (default `asc`)

## 3.3 Filter Expression Syntax

`filter=<key><op><value>`

Operators:
- `=`, `==` exact (case-insensitive for strings)
- `~` contains
- `>`, `>=`, `<`, `<=` numeric comparison

Examples:
- `filter=properties.daimo:license=MIT,Apache-2.0`
- `filter=properties.daimo:tags~demo`
- `filter=https://pionera.ai/edc/daimo#metrics.accuracy>=0.90`

Semantics:
- Multiple `filter=` params are ANDed.
- Comma-separated values are ORed.

## 3.4 Daimo Profile Mapping

When `profile=daimo`, short keys map to metadata fields:
- `task -> daimo:pipeline_tag`
- `license -> daimo:license`
- `tag|tags -> daimo:tags`
- `library -> daimo:library_name`
- `dataset -> daimo:datasets`
- `language -> daimo:language`
- `base_model -> daimo:base_model`
- `name -> name`

## 3.5 Internal Flow

1. Validate request body and required catalog fields.
2. Call:
   - `POST {managementBaseUrl}/v3/catalog/request`
3. Extract datasets from `dcat:dataset` (also supports `dataset` / `datasets`).
4. Apply filter conditions.
5. Apply sorting.
6. Return catalog payload with filtered datasets.

## 3.6 Response Behavior

Success:
- `200 OK` with catalog JSON (dataset list potentially reduced/reordered).

Errors:
- `400 {"error":"Invalid catalog request"}` if body missing/invalid required fields
- `502 {"error":"Failed to fetch catalog"}` if downstream management call fails
- `500 {"error":"Catalog filter failed"}` on unhandled errors

## 3.7 Call Examples

Simple Daimo filter:

```bash
curl -X POST "http://localhost:29191/api/filter/catalog?profile=daimo&task=text-classification" \
  -H "Content-Type: application/json" \
  -d @resources/requests/fetch-catalog.json
```

Combined generic filters + sorting:

```bash
curl -X POST "http://localhost:29191/api/filter/catalog?filter=properties.daimo:license=MIT&filter=properties.daimo:tags~demo&sort=name&order=asc" \
  -H "Content-Type: application/json" \
  -d @resources/requests/fetch-catalog.json
```

## 4) Inference Extension (`/api/infer`)

## 4.1 Purpose

Provide one endpoint for model execution that can:
- use direct EDR info if provided,
- or resolve agreement/transfer/EDR automatically from asset or contract info,
- then invoke the target HTTP endpoint and return raw backend output.

## 4.2 Request Contract

Method and path:
- `POST /api/infer`

Recommended request:

```json
{
  "assetId": "model-mock-infer-v1",
  "method": "POST",
  "path": "/infer",
  "headers": { "Content-Type": "application/json" },
  "payload": { "inputs": "Hello from Pionera" }
}
```

Accepted input variants:
- Endpoint/EDR mode: `endpoint` + `authorization` (+ optional `authHeader`)
- Transfer mode: `transferProcessId` (or `transferId`)
- Contract mode: `contractId` (or `contractAgreementId` / `agreementId`)
- Asset mode: `assetId` (or `id`)

Optional transport fields:
- `method` (default `POST`)
- `path` (default empty)
- `headers` object
- `payload` (aliases: `body`, `input`)

## 4.3 Resolution Strategy (Priority Order)

1. If `endpoint` and `authorization` provided -> use directly.
2. Else if `transferProcessId` provided -> poll EDR API.
3. Else if `contractId` provided -> start transfer, then poll EDR.
4. Else if `assetId` provided:
   - Try local-owner shortcut:
     - `GET /management/v3/assets/{assetId}` and inspect data address
     - If `HttpData` + `baseUrl` exists -> call directly (no transfer)
   - Otherwise query agreements, select best match, start transfer, poll EDR.
5. If none resolve -> return `400`.

## 4.4 Internal Control-Plane Calls

Depending on request type, controller may call:
- `GET {managementBaseUrl}/v3/assets/{id}`
- `POST {managementBaseUrl}/v3/contractagreements/request`
- `POST {managementBaseUrl}/v3/transferprocesses`
- `GET {managementBaseUrl}/v3/edrs/{transferProcessId}/dataaddress`

EDR polling defaults:
- attempts: `10`
- delay: `500ms`

## 4.5 Execution and Proxying

After endpoint resolution:
1. Build target URL from resolved endpoint + requested `path`.
2. Forward method/headers/payload to target URL.
3. Return upstream status code and body.
4. Preserve `Content-Type` from upstream when available.

## 4.6 Response Behavior

Success:
- Returns upstream status/body from the model/backend service.

Client errors:
- `400 {"error":"Missing request body"}`
- `400 {"error":"No contract agreement found for assetId"}`
- `400 {"error":"Missing assetId/transferProcessId/contractId or endpoint/authorization"}`
- `400 {"error":"EDR is missing endpoint (asset is not an HTTP endpoint)"}`

Server error:
- `500 {"error":"Inference failed"}`

## 4.7 Call Examples

Asset-based execution:

```bash
curl -X POST "http://localhost:29191/api/infer" \
  -H "Content-Type: application/json" \
  -d @resources/requests/infer-example.json
```

Direct EDR mode:

```bash
curl -X POST "http://localhost:29191/api/infer" \
  -H "Content-Type: application/json" \
  -d '{
    "endpoint":"http://localhost:19291/public",
    "authorization":"<EDR_TOKEN>",
    "method":"POST",
    "path":"/infer",
    "payload":{"inputs":"Hello"}
  }'
```

## 5) Integration Checklist for Developers

1. Build and run provider and consumer runtimes.
2. Create provider assets.
3. Create policy + contract definition on provider.
4. Negotiate contract from consumer for external assets.
5. Use `/api/filter/catalog` for filtered discovery.
6. Use `/api/infer` for execution.

Operational notes:
- For local assets on same connector, inference may skip transfer if a local `HttpData` base URL is available.
- For remote assets, agreement and transfer/EDR are required.
- Ensure `counterPartyAddress` and `protocol` are present in filter request body.

## 6) Production-Hardening Notes

Current implementation is correct for development/integration, but production users should add:
- stronger request schema validation
- resilient retry/backoff and timeout configuration
- OAuth/OIDC-managed APIs (not mock IAM)
- external vault and key rotation
- persistent distributed stores for stateful components

