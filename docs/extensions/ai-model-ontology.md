# Daimo-Style AI Model Metadata Template (EDC + JSON-LD)

This document defines a practical, Daimo-style metadata schema for AI model assets in EDC. Daimo is our namespace for HF-style fields, renamed for this project. It explains the JSON-LD vocabulary, how fields are stored, how they appear in catalogs, and how they are used by the filtering extension.

---

## 1) Goal and scope

We want metadata that is:
- Consistent and filterable
- Easy to evolve
- Compatible with JSON-LD and EDC catalogs

This template targets AI model assets but is general enough for other ML assets.

## 2) JSON-LD basics (what EDC stores)

EDC assets use JSON-LD. The most important part is the `@context` section, which declares a base vocabulary and any custom prefixes.

Minimal example:
```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "daimo": "https://pionera.ai/edc/daimo#"
  },
  "@id": "model-example",
  "properties": {
    "name": "Example Model",
    "contenttype": "application/octet-stream",
    "daimo:pipeline_tag": "text-classification"
  },
  "dataAddress": {
    "type": "HttpData",
    "baseUrl": "https://example.com/model.bin",
    "proxyPath": "true"
  }
}
```

Key points:
- `@vocab` sets the default namespace for EDC fields.
- Custom prefixes like `daimo:` let you define your own fields.
- `properties` holds all custom metadata fields.

## 3) Recommended Daimo-style namespace

Use a custom namespace you control:
```text
https://pionera.ai/edc/daimo#
```

Then define fields with `daimo:` inside `properties`.

## 4) Core Daimo-style fields

These are the main facets used in AI catalogs:

| Field | Type | Example | Purpose |
| --- | --- | --- | --- |
| `daimo:pipeline_tag` | string | `text-classification` | Task category |
| `daimo:license` | string | `Apache-2.0` | License |
| `daimo:tags` | array | `["demo","multiclass"]` | Keywords |
| `daimo:library_name` | string | `pytorch` | Library/framework |
| `daimo:datasets` | array | `["iris"]` | Training dataset |
| `daimo:language` | array | `["en"]` | Language |
| `daimo:base_model` | string | `org/base-model` | Base model |

## 4b) Extended ML metadata fields (optional)

The UI mirrors ML metadata into `daimo:*` fields for completeness. These do not affect filtering unless you add filter rules for them.

| Field | Type | Example | Source |
| --- | --- | --- | --- |
| `daimo:task` | array | `["Classification"]` | ML metadata |
| `daimo:subtask` | array | `["Multi-class"]` | ML metadata |
| `daimo:algorithm` | array | `["Random Forest"]` | ML metadata |
| `daimo:library` | array | `["scikit-learn"]` | ML metadata |
| `daimo:framework` | array | `["PyTorch"]` | ML metadata |
| `daimo:software` | array | `["Python 3.10"]` | ML metadata |
| `daimo:format` | string | `onnx` | ML metadata |
| `daimo:metrics` | object | `{ "accuracy": 0.93 }` | ML metadata |
| `daimo:hyperparameters` | object | `{ "max_depth": 3 }` | ML metadata |
| `daimo:trainingData` | string | `iris` | ML metadata |
| `daimo:validationData` | string | `iris-test` | ML metadata |

## 5) Performance metadata

Optional fields for metrics and ranking:

```json
"daimo:metrics": {
  "accuracy": 0.93,
  "f1_macro": 0.91
}
```

Use numeric values if you want range filtering.

## 6) Inference endpoint assets

If the asset is an HTTP inference endpoint, include:
- `contenttype: application/json`
- `daimo:inference_path: "/infer"`

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
    "daimo:tags": ["mock","inference","demo"],
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

## 7) How fields appear in catalog output

JSON-LD can expand compact keys into full IRIs. Example:

Compact form (input):
```text
"daimo:pipeline_tag": "text-classification"
```

Expanded form (catalog output):
```text
"https://pionera.ai/edc/daimo#pipeline_tag": "text-classification"
```

Our filtering extension supports both forms.

## 8) Daimo profile mapping in filtering

When `profile=daimo`:
- `task` maps to `daimo:pipeline_tag`
- `license` maps to `daimo:license`
- `tag` maps to `daimo:tags`
- `library` maps to `daimo:library_name`
- `dataset` maps to `daimo:datasets`
- `language` maps to `daimo:language`
- `base_model` maps to `daimo:base_model`

## 9) Generic filters (any asset)

You can also filter any field directly:
```text
?filter=properties.daimo:license=MIT
?filter=properties.daimo:tags~demo
?filter=https://pionera.ai/edc/daimo#metrics.accuracy>=0.9
```

## 10) Common pitfalls

- If `contenttype` is missing, the UI may not recognize the asset.
- If metrics are strings, numeric range filters will not work.
- If `daimo:tags` is a string instead of an array, tag filters will fail.
- If `daimo:inference_path` is missing, inference defaults to `/infer`.
