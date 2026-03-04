# Filtering Extension (Consumer-Side)

This document describes the server-side filtering extension used to query catalogs and apply Daimo-style facets. It runs inside the consumer connector and exposes a single API endpoint.

---

## 1) Endpoint

```text
POST /api/filter/catalog
```

Example:
```bash
curl -X POST "http://localhost:29191/api/filter/catalog?profile=daimo&task=text-classification" \
  -H 'Content-Type: application/json' \
  -d @./resources/requests/fetch-catalog.json -s | jq
```

## 2) Required request body

The body must include `counterPartyAddress` and `protocol`.

Example body:
```json
{
  "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
  "counterPartyAddress": "http://localhost:19194/protocol",
  "protocol": "dataspace-protocol-http"
}
```

If either field is missing, the API returns:
```json
{"error":"Invalid catalog request"}
```

## 3) What the extension does

1. Accepts a catalog request body
2. Calls consumer management API `/v3/catalog/request`
3. Extracts datasets from the catalog
4. Applies server-side filters and sorting
5. Returns a catalog with only matching datasets

## 4) Daimo profile filters

Use `profile=daimo` to enable Daimo-style params.

| Query param | Mapped field |
| --- | --- |
| `task` | `daimo:pipeline_tag` |
| `license` | `daimo:license` |
| `tag` | `daimo:tags` |
| `library` | `daimo:library_name` |
| `dataset` | `daimo:datasets` |
| `language` | `daimo:language` |
| `base_model` | `daimo:base_model` |

Example:
```text
?profile=daimo&task=text-classification
```

Multi-value OR:
```text
?profile=daimo&task=text-classification,feature-extraction
```

## 5) Generic filters

Use one or more `filter=` parameters for any field:

```text
?filter=properties.daimo:license=MIT,Apache-2.0
?filter=properties.daimo:tags~demo
?filter=https://pionera.ai/edc/daimo#metrics.accuracy>=0.90
```

Operators:
- `=` equals (case-insensitive)
- `~` contains (case-insensitive)
- `>`, `>=`, `<`, `<=` numeric ranges

Multiple `filter=` parameters are ANDed.
Comma-separated values are ORed.

## 6) Search query

```text
?q=embedding
```

Search is applied to:
- `name`
- `id`
- `daimo:tags`
- `daimo:pipeline_tag`
- `daimo:base_model`
- `daimo:library_name`

## 7) Sorting

```text
?sort=name
?sort=license&order=desc
?sort=metrics.accuracy&order=desc
```

Strings are compared case-insensitively. Numbers are compared as doubles.

## 8) JSON-LD expansion note

Catalog outputs may expand `daimo:` keys into full IRIs:
- `daimo:pipeline_tag` becomes `https://pionera.ai/edc/daimo#pipeline_tag`

The filter handles both compact and expanded forms.

## 9) Files

- `connector/src/main/java/com/pionera/assetfilter/filter/AssetFilterExtension.java`
- `connector/src/main/java/com/pionera/assetfilter/filter/AssetFilterController.java`

## 10) Common failures

Empty catalog:
- Provider not running
- Assets not created
- Policy/contract definition missing

Invalid catalog request:
- `counterPartyAddress` or `protocol` missing from request body
