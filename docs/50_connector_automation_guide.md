# STICS Connector Automation Guide

How to publish and consume data in the STICS data space from an external system (Python), using the
connector **Management API**.

| | |
|---|---|
| Audience | Developers automating asset publication / consumption against a STICS connector |
| Reference client | [`docs/examples/stics_connector_client.py`](examples/stics_connector_client.py) (Python 3.9+, only needs `requests`) |
| Postman | `validation/core/collections/postman/07_stics_connector_toolbox.json` + `00_environment_toolbox.json` |
| Status | Every behaviour described here was verified against the running connectors (October 2026) |

---

## 1. Concepts in one minute

A connector exposes data through four linked objects. To **publish**, you create them in this order:

```
Asset ──────────────┐
(what is shared)    │
                    ├──►  Contract definition  ──►  appears in the catalogue
Policy ─────────────┘     (which assets, under
(the terms)               which policies)
```

| Object | Purpose | Visible to consumers? |
|---|---|---|
| **Asset** | Metadata + the *data address* that tells the connector where the data lives | No, not by itself |
| **Policy** | ODRL rules (the terms of use) | No |
| **Contract definition** | Selects assets and attaches an *access policy* and a *contract policy* | **Yes**: this is what puts an asset in the catalogue |

An asset without a contract definition is **never shown in any catalogue**. This is the most common reason for
"I published it but I cannot see it".

To **consume**, a consumer connector does: *catalogue → contract negotiation → transfer → download*
(section 9).

## 2. Connectors and endpoints

| Participant id | Management API base URL | DSP (protocol) URL |
|---|---|---|
| `contest-stics` | `https://con-test.stics.linkeddata.es/management` | `https://con-test.stics.linkeddata.es/protocol` |
| `conlab-stics` | `https://con-lab.stics.linkeddata.es/management` | `https://con-lab.stics.linkeddata.es/protocol` |
| `connector-stics` | `https://stics.bavenir.eu/management` | `https://stics.bavenir.eu/protocol` |
| `connector-bavenir` | `https://connector-bavenir.stics.bavenir.eu/management` | `https://connector-bavenir.stics.bavenir.eu/protocol` |
| `contest-bavenir` | `https://con-test.stics.bavenir.eu/management` | `https://con-test.stics.bavenir.eu/protocol` |

Other useful URLs, all relative to the connector base (`https://<host>`):

| Path | Use |
|---|---|
| `/api/check/health` | Health of the connector (`isSystemHealthy`, per-component results). Public. |
| `/connector-interface/` | Web interface (Assets, Catalog, Contracts...). Login via Keycloak. |

Shared services: Keycloak `https://auth.dev.linkeddata.es` (realm `stics`), S3 storage
`https://minio.dev.linkeddata.es` (region `eu-central-1`, path-style).

## 3. Authentication

The Management API is protected with OAuth2 bearer tokens issued by Keycloak.

* Realm: `stics`, client: `dataspace-users`, grant: `password`.
* You need a Keycloak **service user** for your connector (for example `user-connector-bavenir`). Ask STICS for
  one dedicated to your automation instead of sharing a person's account. The connector accepts the roles
  `connector-user`, `connector-management` and `connector-admin`; our service users carry `connector-user` plus a
  role named after the connector.
* Access tokens last **5 minutes**; the refresh token lasts 30 minutes. The reference client refreshes
  automatically.

```bash
TOKEN=$(curl -sk -X POST https://auth.dev.linkeddata.es/realms/stics/protocol/openid-connect/token \
  -d grant_type=password -d client_id=dataspace-users -d username="$KC_USER" \
  --data-urlencode "password=$KC_PASSWORD" | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" https://stics.bavenir.eu/management/v3/assets/request \
  -H 'Content-Type: application/json' -d '{"@context":{"@vocab":"https://w3id.org/edc/v0.0.1/ns/"}}'
```

**TLS note.** `auth.dev.linkeddata.es` and the `*.bavenir.eu` connectors use certificates issued by an internal CA
(`pionera-internal-ingress`). Either load that CA (`verify="/path/ca-bundle.pem"` in Python) or, for tests only,
disable verification (`-k` in curl, `verify_tls=False` in the client). `con-test` / `con-lab` use public CAs.

Python:

```python
from stics_connector_client import Connector

c = Connector("https://connector-bavenir.stics.bavenir.eu/management",
              username="user-connector-bavenir", password=os.environ["KC_PASSWORD"],
              verify_tls="/path/to/ca-bundle.pem")      # or False for tests
```

## 4. Publishing workflow at a glance

| Step | API call | Python |
|---|---|---|
| 1. Create the asset | `POST /v3/assets` (or the upload flow, 5.4) | `create_http_asset`, `create_s3_asset`, `upload_file_asset` |
| 2. Create the policy | `POST /v3/policydefinitions` | `create_allow_all_policy` |
| 3. Create the contract definition | `POST /v3/contractdefinitions` | `create_contract_definition` |
| 4. Verify | `POST /federatedcatalog/request` | `wait_until_in_federated_catalog` |

Minimal complete example:

```python
c.upload_file_asset("parcels-2026", "parcels.csv",
                    name="Parcels 2026", description="Cadastral parcels, 2026 edition",
                    keywords=["cadastre", "parcels"])
c.create_allow_all_policy("allow-all", exists_ok=True)
c.create_contract_definition("parcels-2026-cd", "allow-all", "allow-all", asset_ids=["parcels-2026"])
print(c.wait_until_in_federated_catalog("parcels-2026"))   # up to ~2.5 minutes, see 7
```

## 5. Assets

All requests: `Content-Type: application/json`, `Authorization: Bearer <token>`. Success is **HTTP 200**
(creation returns `{"@id": ..., "createdAt": ...}`).

### 5.1 Mandatory metadata

The connector rejects an asset (HTTP 400) unless **all six** of these are present and non-blank:

| Property | Example |
|---|---|
| `name` | `"Parcels 2026"` |
| `version` | `"1.0.0"` |
| `assetType` | `"dataset"` |
| `shortDescription` | `"Cadastral parcels"` |
| `dcterms:description` | `"Cadastral parcels, 2026 edition"` |
| `dcat:keyword` | `["cadastre", "parcels"]` (array) |

`contenttype` is optional but recommended (`text/csv`, `application/json`, `text/turtle`...).

The error body lists what is missing, for example
`mandatory field 'http://www.w3.org/ns/dcat#keyword' is missing or it is blank`
(`ConnectorError.messages` in the client).

Any other property is accepted and stored, including **DCAT / custom-ontology metadata and nested objects**
(`dcat:contactPoint`, `dcat:distribution`, `citser:*` ...). All of it is returned to consumers in the catalogue.
Prefixed keys must be declared in the `@context` of the request.

```json
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/",
               "dcterms": "http://purl.org/dc/terms/", "dcat": "http://www.w3.org/ns/dcat#"},
  "@id": "my-asset",
  "properties": {
    "name": "My asset", "version": "1.0.0", "assetType": "dataset", "contenttype": "text/csv",
    "shortDescription": "Short text",
    "dcterms:description": "Long text",
    "dcat:keyword": ["a", "b"]
  },
  "dataAddress": { "...": "see 5.2 - 5.4" }
}
```

### 5.2 Data address: HTTP endpoint (`HttpData`)

The connector fetches the data from an HTTP(S) URL when a consumer requests it.

```json
"dataAddress": {
  "type": "HttpData", "name": "my-asset",
  "baseUrl": "https://example.org/api/data",
  "proxyPath": "true"
}
```

`name` and `baseUrl` are required. Optional (standard EDC `HttpData` properties, accepted by the connector):
`method`, `proxyPath`, `proxyQueryParams`, `proxyBody`, `contentType`, and `header:<Name>` entries to send fixed
headers upstream.

```python
c.create_http_asset("my-asset", "https://example.org/api/data", name="My asset",
                    description="...", keywords=["a"], proxy_query_params=True)
```

### 5.3 Data address: file already in S3 (`AmazonS3`)

```json
"dataAddress": {
  "type": "AmazonS3", "region": "eu-central-1", "bucketName": "my-bucket", "keyName": "folder/file.ttl",
  "accessKeyId": "...", "secretAccessKey": "...", "endpointOverride": "https://minio.dev.linkeddata.es"
}
```

**All five of `region`, `bucketName`, `accessKeyId`, `secretAccessKey`, `endpointOverride` are required** by the
connector validator (HTTP 400 otherwise), plus `keyName`. Be aware that **the keys are stored in clear in the asset's
data address** and every asset breaks if the keys are rotated. Prefer 5.4 unless the file must stay where it is.

```python
c.create_s3_asset("my-asset", "my-bucket", "folder/file.ttl", access_key_id=..., secret_access_key=...,
                  name="...", description="...", keywords=["a"])
```

### 5.4 Uploading a file to the connector store ("STICS Store")

The connector can store the file itself (in its own bucket) and create the asset in one flow. This is what the
interface does when you pick **STICS Store** and attach a file. The resulting asset is an `AmazonS3` asset that
**contains no credentials**.

1. `POST /s3assets/upload-chunk` once per chunk, `multipart/form-data` with parts `json` (the asset, with
   `"dataAddress": {"type": "InesDataStore"}`, optional `"folder"`) and `file` (the chunk), and headers
   `Content-Disposition: attachment; filename="<name>"`, `Chunk-Index: <0..n-1>`, `Total-Chunks: <n>`.
2. `POST /s3assets/finalize-upload`, `multipart/form-data` with parts `fileName` and `json`.

```bash
curl -s -X POST "$M/s3assets/upload-chunk" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Disposition: attachment; filename="data.csv"' -H 'Chunk-Index: 0' -H 'Total-Chunks: 1' \
  -F 'json=@asset.json;type=application/json' -F 'file=@data.csv;type=text/csv'
curl -s -X POST "$M/s3assets/finalize-upload" -H "Authorization: Bearer $TOKEN" \
  -F 'fileName=data.csv' -F 'json=@asset.json;type=application/json'
```

```python
c.upload_file_asset("my-csv", "data.csv", name="...", description="...", keywords=["csv"])
```

Rules verified on the connectors:

* **Every chunk except the last must be at least 50 MiB** (smaller ones get HTTP 500). A file under 50 MiB is a
  single chunk. A 115 MB file uploads as 50 + 50 + 15 MB in a few seconds. The client enforces this.
* Send chunks **in order and sequentially**; the connector keeps the upload state in memory per file name.
* The **file name is the storage key** (with `folder/` in front if given). Uploading the same name again overwrites.
* **Deleting the asset does not delete the stored file**; remove it from the bucket yourself if needed.

### 5.5 List, read, filter, update, delete

| Action | Call | Python |
|---|---|---|
| Read one | `GET /v3/assets/{id}` | `get_asset(id)` |
| List / filter | `POST /v3/assets/request` with a query | `list_assets([criteria])` |
| Count | `POST /pagination/count?type=asset` | `count_assets()` |
| Update | `PUT /v3/assets` with the **complete** asset body | `update_asset(payload)` |
| Delete | `DELETE /v3/assets/{id}` (204) | `delete_asset(id)` |

Query body: `{"@context": {...}, "offset": 0, "limit": 50, "filterExpression": [ {"operandLeft": "...",
"operator": "=", "operandRight": "..."} ]}`. Short property names (`id`, `name`, `assetType`) refer to the connector
namespace; use full IRIs for DCAT/DCTERMS properties (`http://www.w3.org/ns/dcat#keyword`).

Filtering notes (verified): `=` works for `id` and plain properties; for list-valued properties such as keywords
use `contains` or `like` (`"%value%"`), `=` and `in` return nothing in *asset listings*.

**Deleting**: an asset referenced by a contract agreement answers **HTTP 409** and cannot be deleted. The same
applies to a policy referenced by a contract definition or agreement. Plan for this when cleaning up test data
(delete the contract definition first, then the policy, then the asset).

## 6. Policies and contract definitions

### 6.1 Policies

A policy is an ODRL `Set`. Two are commonly used:

```json
{"@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/", "odrl": "http://www.w3.org/ns/odrl/2/"},
 "@id": "allow-all",
 "policy": {"@context": "http://www.w3.org/ns/odrl.jsonld", "@type": "Set",
            "permission": [], "prohibition": [], "obligation": []}}
```

`POST /v3/policydefinitions` (200). Also `GET /v3/policydefinitions/{id}`, `POST /v3/policydefinitions/request`,
`DELETE /v3/policydefinitions/{id}`.

> **Important.** When a consumer negotiates, the request must carry the **complete offer exactly as it
> received it in the catalogue**, not just its id (section 9.2). If only the id is sent, the provider compares the
> request with its policy and **terminates the negotiation** as soon as the policy has any rule (a permission, a
> constraint such as `ALWAYS_TRUE`...). With the complete offer, empty policies and policies with constraints
> (`ALWAYS_TRUE` as access policy and/or contract policy) all negotiate correctly.

### 6.2 Contract definitions

```json
{"@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
 "@id": "parcels-2026-cd",
 "accessPolicyId": "allow-all",
 "contractPolicyId": "allow-all",
 "assetsSelector": [{"@type": "CriterionDto", "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                     "operator": "=", "operandRight": "parcels-2026"}]}
```

`POST /v3/contractdefinitions` (200). Also `GET /v3/contractdefinitions/{id}`,
`POST /v3/contractdefinitions/request`, `DELETE /v3/contractdefinitions/{id}`.

* `accessPolicyId`: who may **see** the offer in the catalogue. `contractPolicyId`: the terms the consumer **accepts**
  when negotiating.
* The selector decides which assets are exposed. Verified selectors:

| Goal | Criterion | Python |
|---|---|---|
| One asset | `id = "x"` | `asset_ids=["x"]` |
| Several assets | `id in ["x", "y"]` | `asset_ids=["x", "y"]` |
| By property | `assetType = "dataset"`, `name = "..."`, `contenttype = "text/csv"` | `criteria=[c.criterion("assetType", "=", "dataset")]` |
| By keyword | `http://www.w3.org/ns/dcat#keyword` with `=` or `contains` | `criteria=[c.criterion("http://www.w3.org/ns/dcat#keyword", "contains", "cadastre")]` |

(`in` does **not** work for keywords.)

* An **empty selector exposes every asset** of the connector under that contract definition's policies; the client
  refuses to send one. Check `list_contract_definitions()` for definitions with `assetsSelector: []`.
* If **several contract definitions select the same asset**, the catalogue shows **one offer per contract
  definition** (the first part of an offer id, before the first `:`, is the base64 of the contract definition id).
  The consumer decides which one to accept.
* To change a contract definition or a policy, delete and recreate it.

## 7. Verifying that the asset is published

1. **Federated catalogue** (what the interface's *Catalog* page reads):
   `POST {management}/federatedcatalog/request` returns one catalogue per known participant, each with its
   datasets. It is a **cache refreshed about every 60 seconds**, so a new offer can take up to ~1 minute
   (`wait_until_in_federated_catalog`). The same endpoint on any connector shows offers from all participants.
2. **Directly from a consumer**: `POST {consumer-management}/v3/catalog/request` with the provider's DSP URL (9.1).
   Immediate, no cache.
3. **Interface**: `https://<host>/connector-interface/` → *Catalog*. If it stays empty after a configuration
   change, force-reload the page (Ctrl+Shift+R) so the browser drops its cached configuration.

If an asset does not show up: there is no contract definition selecting it, the selector or policies are wrong, or
the 60-second cache has not refreshed yet.

## 8. Metadata in the catalogue

Consumers receive the asset properties as a DCAT dataset: EDC re-compacts the prefixes it knows (`dcat:`, `dct:`,
`odrl:`); other namespaces (for example `citser:`) appear as full IRIs. Nested objects and arrays are preserved.
`@type` changes from `Asset` to `dcat:Dataset`. The data address is **never** disclosed.

## 9. Consuming data (consumer side)

The same client works against the *consumer's* Management API.

```python
consumer = Connector("https://stics.bavenir.eu/management", "user-connector-stics", PASSWORD)
response = consumer.pull_asset(provider_dsp="https://connector-bavenir.stics.bavenir.eu/protocol",
                               provider_id="connector-bavenir", asset_id="parcels-2026")
print(response.text)
```

`pull_asset` chains the four steps below; each is also available separately.

| Step | API | Python |
|---|---|---|
| 9.1 Catalogue | `POST /v3/catalog/request` `{counterPartyAddress, counterPartyId, protocol: "dataspace-protocol-http"}` | `request_catalog(dsp, provider_id)`, `find_offers(...)` |
| 9.2 Negotiate | `POST /v3/contractnegotiations` with the **complete offer** (9.5); poll `GET /v3/contractnegotiations/{id}` until `FINALIZED` | `find_offer(...)`, `negotiate(...)`, `wait_for_agreement(...)` |
| 9.3 Transfer | `POST /v3/transferprocesses` with `transferType: "HttpData-PULL"` (or `HttpData-PUSH` + `dataDestination`); poll until `STARTED`/`COMPLETED` | `start_transfer(...)`, `wait_for_transfer(...)` |
| 9.4 Download | `GET /v3/edrs/{transferId}/dataaddress` gives `endpoint` + `authorization`; then `GET <endpoint>` with header `Authorization: <authorization>` | `get_edr(...)`, `download(edr)` |

States: negotiation `REQUESTED → AGREED → VERIFIED → FINALIZED`; transfer `REQUESTED → STARTED → COMPLETED`.
`TERMINATED` is final (the response may contain `errorDetail`). The agreement and negotiation records stay in both
connectors permanently.

PUSH sends the data to a URL you provide (`push_destination_url`); that URL must be reachable from the provider.

### 9.5 The negotiation request must carry the complete offer

Take the offer object from the catalogue (`dcat:dataset` → `odrl:hasPolicy`), add `odrl:assigner` (the provider's
participant id) and `odrl:target` (the asset id), and send it as `policy`. The `@context` of the request must declare
the prefixes the offer uses, `edc` and `odrl`:

```json
{
  "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/", "edc": "https://w3id.org/edc/v0.0.1/ns/",
               "odrl": "http://www.w3.org/ns/odrl/2/"},
  "@type": "ContractRequest",
  "counterPartyAddress": "https://connector-bavenir.stics.bavenir.eu/protocol",
  "protocol": "dataspace-protocol-http",
  "policy": {
    "@id": "<offer @id copied from the catalogue>",
    "@type": "odrl:Offer",
    "odrl:permission": {"odrl:action": {"@id": "USE"}},
    "odrl:prohibition": [], "odrl:obligation": [],
    "odrl:assigner": {"@id": "connector-bavenir"},
    "odrl:target": {"@id": "my-asset"}
  }
}
```

This is what the connector interface does when you press *Negotiate*. The Python client does it in `negotiate()`. Two
failure modes seen in practice: sending only `@id`/`assigner`/`target` makes the negotiation end `TERMINATED` for
any policy with rules; and omitting the `edc` prefix from the context makes the connector answer HTTP 400 for offers
that contain `edc:` identifiers (such as `edc:ALWAYS_TRUE`).

## 10. Errors

| HTTP | Meaning | What to do |
|---|---|---|
| 400 | Validation failed (body lists each message) | Fix the missing/invalid fields (5.1, 5.3) |
| 401 | Missing/expired token, or wrong credentials | Request a new token; check the user and its roles |
| 403 | Authenticated but not allowed (or blocked by a firewall) | Check the user's roles |
| 404 | Object not found | Check the id |
| 409 | Already exists, or still referenced | Use `exists_ok`, or remove dependants first (5.5). The interface only shows a generic error when deleting a policy that a contract definition still uses |
| 500 | Server error. Seen when a non-final upload chunk is under 50 MiB | Check the request against section 5.4 |
| Negotiation `TERMINATED` | The request did not carry the complete offer | See 9.5 |
| 503 on `/api/check/health` | A component is unhealthy | Read `componentResults`; "Vault is sealed" means the secret store must be unsealed |

`ConnectorError` in the client carries `status`, `body` and `messages`.

## 11. Recommended practice for an automation

* Use a **dedicated Keycloak service user**; keep its password in a secret store, never in code.
* Make publication **idempotent**: `exists_ok=True` on creates; to change an asset use `update_asset`; use
  deterministic ids (for example derived from your dataset id).
* Create in order **asset → policy → contract definition**; delete in reverse. Handle 409 on deletes.
* Poll `/api/check/health` before a batch and alert on failures. A connector whose Vault token expired boots
  with errors until it is renewed.
* Do not run uploads of the same file name in parallel.
* When negotiating, always send the complete offer (9.5) and, if an asset shows several offers, choose one explicitly.
* Reuse one `Connector` instance (it caches and refreshes the token).
* Keep the keys of 5.3 out of assets when you can; prefer 5.4.

## 12. Appendix: endpoint cheat sheet

Base: `{management}` = connector `…/management`.

| Area | Method and path |
|---|---|
| Assets | `POST /v3/assets` · `GET /v3/assets/{id}` · `PUT /v3/assets` · `DELETE /v3/assets/{id}` · `POST /v3/assets/request` · `POST /pagination/count?type=asset` |
| Upload | `POST /s3assets/upload-chunk` · `POST /s3assets/finalize-upload` |
| Policies | `POST /v3/policydefinitions` · `GET/DELETE /v3/policydefinitions/{id}` · `POST /v3/policydefinitions/request` |
| Contract definitions | `POST /v3/contractdefinitions` · `GET/DELETE /v3/contractdefinitions/{id}` · `POST /v3/contractdefinitions/request` |
| Federated catalogue | `POST /federatedcatalog/request` · `POST /pagination/count?type=federatedCatalog` |
| Catalogue (consumer) | `POST /v3/catalog/request` |
| Negotiations | `POST /v3/contractnegotiations` · `GET /v3/contractnegotiations/{id}` · `POST /v3/contractnegotiations/request` · `POST /v3/contractnegotiations/{id}/terminate` |
| Agreements | `GET /v3/contractagreements/{id}` · `POST /v3/contractagreements/request` |
| Transfers | `POST /v3/transferprocesses` · `GET /v3/transferprocesses/{id}` · `POST /v3/transferprocesses/request` · `POST /v3/transferprocesses/{id}/terminate` |
| EDR | `GET /v3/edrs/{transferId}/dataaddress` · `POST /v3/edrs/request` |

A ready-made Postman collection that exercises all of the above (with automatic login and an end-to-end
folder order) is provided in `validation/core/collections/postman/07_stics_connector_toolbox.json`.

## 13. Known issues at the time of writing

* `con-test.stics.bavenir.eu` currently serves an **expired firewall certificate** (a Fortinet default
  certificate that expired on 6 October 2026); clients that validate TLS cannot reach it.
* The Helio adapter data endpoint (`helio-adapter.stics.linkeddata.es/api/citser_knowledge_graph/data`) returned
  HTTP 500 (`Provided clazz 'SIoTRxBuilder' is not a loaded component`) on 16 October 2026, which affects assets that
  point at it.
