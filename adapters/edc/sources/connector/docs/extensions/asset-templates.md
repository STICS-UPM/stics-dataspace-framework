# Asset Templates (Provider Assets)

This document defines the asset JSON templates we use for creating provider assets, plus what each field means.

---

## 1) Where Assets Are Created

Assets are created on the **provider** connector via:

```text
POST http://localhost:19193/management/v3/assets
```

Template files:
- `resources/requests/create-asset.json` (minimal HttpData asset)
- `resources/requests/ai-models/template-asset-ai.json` (Daimo-style model)
- `resources/requests/create-asset-infer-mock.json` (inference endpoint example)

---

## 2) EDC Metadata Rules (Official Guidance)

### 2.1 Asset Semantics
An asset is **metadata only**. It does not contain the data itself. The `dataAddress` is the pointer to the physical data location, and assets can also include `privateProperties` that are **not serialized** into DSP catalogs.

### 2.2 `@id`
The `@id` must be unique. EDC does not strictly require a UUID, but it is **strongly recommended** to use UUIDs to avoid collisions.

### 2.3 `properties` and `privateProperties`
`properties` is the **public metadata** exposed in catalogs. It is open-ended, and you can add arbitrary fields. `privateProperties` is internal and **not exposed** in DSP. EDC also defines a few well-known properties in the `edc` namespace: `id`, `description`, `version`, `name`, and `contenttype`.

### 2.4 JSON-LD Context (`@context`)
EDC uses JSON-LD. The `@context` defines namespaces for custom metadata. If you use custom keys without a custom namespace, they will be expanded under the default EDC vocabulary. EDC stores assets in **expanded form** and compacts on egress.

### 2.5 `dataAddress`
`dataAddress` is required and its schema depends on the `type` (e.g., `HttpData`, S3, File). Assets and data addresses are **schemaless** beyond basic validation. Do not store credentials inside `dataAddress` or `privateProperties`; store secrets in a vault and reference them.

### 2.6 Field Breakdown (Core Asset Fields)

| Field | Meaning | Notes |
| --- | --- | --- |
| `@context` | JSON-LD context for namespaces | Use `@vocab` for the EDC namespace and add custom prefixes for your metadata. |
| `@id` | Unique asset identifier | UUID is recommended for uniqueness. |
| `properties` | Public metadata | Open-ended; appears in DSP catalogs. |
| `privateProperties` | Internal metadata | Not serialized to DSP catalogs. |
| `dataAddress` | Pointer to actual data | Required; schema depends on `type`. |
| `dataAddress.type` | Storage type | Determines what other fields are required. |

---

## 3) Minimal HttpData Asset (Required Fields)

This is the smallest valid asset we use:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "@id": "assetId",
  "properties": {
    "name": "product description",
    "contenttype": "application/json"
  },
  "dataAddress": {
    "type": "HttpData",
    "name": "Test asset",
    "baseUrl": "https://jsonplaceholder.typicode.com/users",
    "proxyPath": "true"
  }
}
```

Required fields:
- `@id`: unique asset id.
- `properties.name`: display name.
- `properties.contenttype`: used by UI and inference to determine executability.
- `dataAddress.type`: `HttpData` in our current setup.
- `dataAddress.baseUrl`: where the data or endpoint lives.

---

## 4) Daimo-Style AI Model Asset (Recommended)

We use a Daimo-style schema for filterable model metadata:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "daimo": "https://pionera.ai/edc/daimo#"
  },
  "@id": "model-your-id",
  "properties": {
    "name": "Model Display Name",
    "contenttype": "application/octet-stream",
    "daimo:pipeline_tag": "text-classification",
    "daimo:license": "Apache-2.0",
    "daimo:tags": ["demo"],
    "daimo:library_name": "pytorch",
    "daimo:datasets": ["dataset-name"],
    "daimo:language": ["en"],
    "daimo:base_model": "org/base-model",
    "daimo:metrics": {
      "accuracy": 0.9
    }
  },
  "dataAddress": {
    "type": "HttpData",
    "baseUrl": "https://example.com/model.bin",
    "proxyPath": "true"
  }
}
```

Details for these fields are documented in:
- `docs/extensions/ai-model-ontology.md`

---

## 5) Inference Endpoint Asset

For assets that are **HTTP inference endpoints**, add:
- `contenttype: application/json`
- `daimo:inference_path: "/infer"` (or your endpoint path)

Example:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "daimo": "https://pionera.ai/edc/daimo#"
  },
  "@id": "model-mock-infer-v1",
  "properties": {
    "name": "Mock Inference Model v1",
    "contenttype": "application/json",
    "daimo:pipeline_tag": "text-classification",
    "daimo:license": "Apache-2.0",
    "daimo:tags": ["mock", "inference", "demo"],
    "daimo:library_name": "custom",
    "daimo:datasets": ["mock"],
    "daimo:language": ["en"],
    "daimo:base_model": "mock-base",
    "daimo:inference_path": "/infer"
  },
  "dataAddress": {
    "type": "HttpData",
    "baseUrl": "http://localhost:9000",
    "proxyPath": "true"
  }
}
```

Notes:
- The UI’s **Model Execution** page only lists executable assets if `contenttype` includes `application/json`, or `daimo:tags` contains `inference` or `endpoint`.

---

## 6) Data Address Notes

Currently supported in this repo:
- `HttpData` (required fields: `type`, `baseUrl`)

UI also includes S3 and DataSpacePrototypeStore options, but those **upload endpoints are not implemented** in this repo.
