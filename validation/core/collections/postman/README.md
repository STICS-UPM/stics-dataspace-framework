# Compact Manual Replication in Postman

## Goal

This document is an operational, provisional version of the manual Postman step. Its goal is not to explain the flow conceptually, but to leave an exact, runnable reference to reproduce the framework's main E2E path **without depending** on the dynamic `test_script` injection performed by `NewmanExecutor`.

The associated artifacts are:

- `Validation-Environment/validation/core/collections/postman/01_environment_health.json`
- `Validation-Environment/validation/core/collections/postman/02_connector_management_api.json`
- `Validation-Environment/validation/core/collections/postman/03_e2e_compact.json`
- `Validation-Environment/validation/core/collections/postman/00_environment.json`
- `Validation-Environment/validation/core/collections/postman/00_environment_edc.json`

Before launching these collections from `Level 6`, the framework runs a
lightweight Management API preflight for the `provider/consumer` pair. That
check validates the login of both connectors and tests, with their own tokens,
these endpoints:

- `POST /management/v3/assets/request` on the provider
- `POST /management/v3/contractnegotiations/request` on the consumer
- `POST /management/v3/catalog/request` on the consumer against the provider's protocol

If any of them fails, the framework aborts before Newman and persists the
diagnostics in `00_management_api_preflight.json` inside the pair's report
directory.

## Available collections

This folder contains three variants that can be imported into Postman:

1. `01_environment_health.json`
   - self-contained replica of `01_environment_health.json`
   - useful for a basic smoke test of authentication, Management API, and DSP
2. `02_connector_management_api.json`
   - self-contained replica of `02_connector_management_api.json`
   - useful to validate the provider's technical CRUD
3. `03_e2e_compact.json`
   - compact flow covering `03` + `04` + `05` + `06`
   - useful when you want to validate the main E2E path with less execution time

The three collections reuse an environment for the adapter you want to test:

- `Validation-Environment/validation/core/collections/postman/00_environment.json` for INESData
- `Validation-Environment/validation/core/collections/postman/00_environment_edc.json` for EDC

The versioned environments are parameterized with the deployment's base
variables. INESData uses `pionera` by default with the
`core-control`/`provider`/`consumer` namespaces, and EDC uses `pionera-edc`
with `edc-control`/`edc-provider`/`edc-consumer`. If your local
`deployer.config` uses other values, duplicate the environment in Postman and
adjust those variables without modifying the collections.

The original logic that the framework injects dynamically still lives in:

- `Validation-Environment/framework/newman_executor.py`
- `Validation-Environment/validation/shared/api/common_tests.js`
- `Validation-Environment/validation/core/tests/provider_tests.js`
- `Validation-Environment/validation/core/tests/catalog_tests.js`
- `Validation-Environment/validation/core/tests/negotiation_tests.js`
- `Validation-Environment/validation/core/tests/transfer_tests.js`

## Why this compact collection exists

The `03_e2e_compact.json` collection reduces execution time because it removes checks that usually add little value in manual Postman runs when the goal is to validate the main interoperability flow:

- it skips `01_environment_health.json` and `02_connector_management_api.json`
- it skips the intermediate CRUD listing requests of `03_provider_setup.json`
- it skips `Direct DSP Catalog Request` from `04_consumer_catalog.json`
- it skips `Check Transfer Status` from `06_consumer_transfer.json` and relies on resolving the destination directly
- it logs in the provider only once and the consumer only once
- it embeds in each request the exact script needed to produce the variables of the next request

## Exact initial environment configuration

Before importing or manually rebuilding the collection, create an environment with these base variables. To save time, you can import directly:

- `Validation-Environment/validation/core/collections/postman/00_environment.json` for INESData
- `Validation-Environment/validation/core/collections/postman/00_environment_edc.json` for EDC

Those files are **importable Postman environments** and contain only the necessary base variables, without variables derived from the flow.

### Environment INESData

```json
{
  "provider": "conn-citycouncil-pionera",
  "consumer": "conn-company-pionera",
  "provider_user": "user-conn-citycouncil-pionera",
  "provider_password": "<copiar localmente>",
  "consumer_user": "user-conn-company-pionera",
  "consumer_password": "<copiar localmente>",
  "dsDomain": "dev.ds.dataspaceunit.upm",
  "dataspace": "pionera",
  "keycloakUrl": "http://auth.dev.ed.dataspaceunit.upm",
  "keycloakClientId": "dataspace-users",
  "adapter": "inesdata",
  "registrationNamespace": "core-control",
  "providerNamespace": "provider",
  "consumerNamespace": "consumer",
  "protocolPort": "19194",
  "protocolPath": "/protocol",
  "providerProtocolAddressOverride": "",
  "consumerProtocolAddressOverride": "",
  "transferStartPath": "inesdatatransferprocesses",
  "transferDestinationType": "InesDataStore",
  "providerProtocolAddress": "",
  "consumerProtocolAddress": ""
}
```

### Environment EDC

```json
{
  "provider": "conn-citycounciledc-pionera-edc",
  "consumer": "conn-companyedc-pionera-edc",
  "provider_user": "user-conn-citycounciledc-pionera-edc",
  "provider_password": "<copiar localmente>",
  "consumer_user": "user-conn-companyedc-pionera-edc",
  "consumer_password": "<copiar localmente>",
  "dsDomain": "dev.ds.dataspaceunit.upm",
  "dataspace": "pionera-edc",
  "keycloakUrl": "http://auth.dev.ed.dataspaceunit.upm",
  "keycloakClientId": "dataspace-users",
  "adapter": "edc",
  "registrationNamespace": "edc-control",
  "providerNamespace": "edc-provider",
  "consumerNamespace": "edc-consumer",
  "protocolPort": "19194",
  "protocolPath": "/protocol",
  "providerProtocolAddressOverride": "",
  "consumerProtocolAddressOverride": "",
  "transferStartPath": "transferprocesses",
  "transferRequestType": "TransferRequestDto",
  "transferType": "AmazonS3-PUSH",
  "transferDestinationType": "AmazonS3",
  "transferDestinationBucket": "pionera-edc-conn-companyedc-pionera-edc",
  "transferDestinationRegion": "eu-central-1",
  "transferDestinationEndpointOverride": "http://minio.dev.ed.dataspaceunit.upm",
  "providerProtocolAddress": "",
  "consumerProtocolAddress": ""
}
```

Important notes:

- `providerProtocolAddress` and `consumerProtocolAddress` are resolved automatically when the compact collection starts, from `provider`, `consumer`, `providerNamespace`, `consumerNamespace`, `protocolPort`, and `protocolPath`. Only use `providerProtocolAddressOverride` or `consumerProtocolAddressOverride` if you need to force a different internal path.
- The local passwords of the current INESData environment are generated under `deployers/inesdata/deployments/DEV/pionera/credentials-connector-<connector>.json`, field `connector_user.passwd`.
- For EDC, the equivalent passwords are generated under `deployers/edc/deployments/DEV/pionera-edc/credentials-connector-<connector>.json`, field `connector_user.passwd`.
- The compact collection dynamically generates all the `e2e_*` identifiers, so there is no need to preload them in the environment.

## Collection variables used for retries

The collection defines these collection variables to bound the retries and keep the run faster than the framework's full set:

- `catalog_max_attempts = 6`
- `negotiation_start_max_attempts = 30`
- `negotiation_status_max_attempts = 10`
- `transfer_start_max_attempts = 8`
- `transfer_destination_max_attempts = 10`

## Execution order

The compact collection must be run exactly in this order:

1. `Provider Login`
2. `Create E2E Asset`
3. `Create E2E Policy`
4. `Create E2E Contract Definition`
5. `Consumer Login`
6. `Request Federated Catalog (Management API)`
7. `Start Contract Negotiation`
8. `Check Negotiation Status`
9. `Start Transfer Process`
10. `Resolve Current Transfer Destination`

## Exact configuration, request by request

Each of the following blocks documents the exact configuration to implement if you decide to rebuild the collection manually in Postman. To save time, import `03_e2e_compact.json` directly, where all of this is already embedded.

### 1. Provider Login

- **Goal**: Authenticate the provider and seed all the `e2e_*` identifiers the rest of the flow will use.
- **Functional reference in the framework**: `03_provider_setup.json` - request `Provider Login` with an additional embedded script to clean and chain state.
- **Method**: `POST`
- **URL**: `{{keycloakUrl}}/realms/{{dataspace}}/protocol/openid-connect/token`
- **Headers**:
  - `Content-Type: application/x-www-form-urlencoded`
- **Variables required before sending the request**: `keycloakUrl`, `dataspace`, `keycloakClientId`, `provider_user`, `provider_password`, `provider`, `consumer`
- **Variables it leaves ready for the next request**: `provider_jwt`, `e2e_suffix`, `e2e_asset_id`, `e2e_policy_id`, `e2e_contract_definition_id`, `e2e_expected_provider_bucket`, `e2e_expected_consumer_bucket`

**Body (`urlencoded`)**

```text
grant_type=password
client_id={{keycloakClientId}}
username={{provider_user}}
password={{provider_password}}
scope=openid profile email
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  return;
}

pm.test("HTTP status is 200", function () {
  pm.response.to.have.status(200);
});

pm.test("Provider login returns access_token", function () {
  pm.expect(body.access_token).to.be.a("string").and.not.empty;
});

const suffix = String(Date.now());
setVar("provider_jwt", body.access_token);
setVar("e2e_suffix", suffix);
setVar("e2e_asset_id", `asset-e2e-${suffix}`);
setVar("e2e_policy_id", `policy-e2e-${suffix}`);
setVar("e2e_contract_definition_id", `contract-e2e-${suffix}`);
setVar("e2e_expected_provider_bucket", `${pm.environment.get("dataspace")}-${pm.environment.get("provider")}`);
setVar("e2e_expected_consumer_bucket", `${pm.environment.get("dataspace")}-${pm.environment.get("consumer")}`);
[
  "providerParticipantId",
  "e2e_offer_policy_id",
  "e2e_catalog_asset_id",
  "e2e_negotiation_id",
  "e2e_agreement_id",
  "e2e_transfer_id",
  "e2e_transfer_destination_bucket",
  "catalog_lookup_attempt",
  "negotiation_start_attempt",
  "negotiation_status_attempt",
  "transfer_start_attempt",
  "transfer_destination_attempt"
].forEach(function (key) {
  pm.environment.unset(key);
  pm.collectionVariables.unset(key);
});
```

### 2. Create E2E Asset

- **Goal**: Create the minimal negotiable asset for the E2E flow.
- **Functional reference in the framework**: `03_provider_setup.json` - request `Create E2E Asset`.
- **Method**: `POST`
- **URL**: `http://{{provider}}.{{dsDomain}}/management/v3/assets`
- **Headers**:
  - `Authorization: Bearer {{provider_jwt}}`
  - `Content-Type: application/json`
- **Variables required before sending the request**: `provider_jwt`, `provider`, `dsDomain`, `e2e_asset_id`, `e2e_suffix`
- **Variables it leaves ready for the next request**: `e2e_asset_id` (confirmed/updated with the returned `@id`)

**Body (`raw`)**

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#"
  },
  "@id": "{{e2e_asset_id}}",
  "@type": "Asset",
  "properties": {
    "name": "E2E Dataspace Asset {{e2e_suffix}}",
    "version": "1.0.0",
    "shortDescription": "Asset for end-to-end dataspace validation",
    "assetType": "dataset",
    "dct:description": "Asset for end-to-end dataspace validation",
    "dcat:keyword": ["validation", "e2e", "dataspace"]
  },
  "dataAddress": {
    "type": "HttpData",
    "baseUrl": "https://jsonplaceholder.typicode.com/todos",
    "name": "todos"
  }
}
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  return;
}

pm.test("HTTP status indicates resource creation", function () {
  pm.expect(pm.response.code).to.be.oneOf([200, 201]);
});

pm.test("Asset creation returns @id", function () {
  pm.expect(body["@id"] || pm.environment.get("e2e_asset_id")).to.exist;
});

if (body["@id"]) {
  setVar("e2e_asset_id", body["@id"]);
}
```

### 3. Create E2E Policy

- **Goal**: Create the policy associated with the asset.
- **Functional reference in the framework**: `03_provider_setup.json` - request `Create E2E Policy`.
- **Method**: `POST`
- **URL**: `http://{{provider}}.{{dsDomain}}/management/v3/policydefinitions`
- **Headers**:
  - `Authorization: Bearer {{provider_jwt}}`
  - `Content-Type: application/json`
- **Variables required before sending the request**: `provider_jwt`, `provider`, `dsDomain`, `e2e_policy_id`
- **Variables it leaves ready for the next request**: `e2e_policy_id` (confirmed/updated with the returned `@id`)

**Body (`raw`)**

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "odrl": "http://www.w3.org/ns/odrl/2/"
  },
  "@id": "{{e2e_policy_id}}",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "Set",
    "permission": [],
    "prohibition": [],
    "obligation": []
  }
}
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  return;
}

pm.test("HTTP status indicates resource creation", function () {
  pm.expect(pm.response.code).to.be.oneOf([200, 201]);
});

pm.test("Policy creation returns @id", function () {
  pm.expect(body["@id"] || pm.environment.get("e2e_policy_id")).to.exist;
});

if (body["@id"]) {
  setVar("e2e_policy_id", body["@id"]);
}
```

### 4. Create E2E Contract Definition

- **Goal**: Create the contract definition that links the asset and the policy.
- **Functional reference in the framework**: `03_provider_setup.json` - request `Create E2E Contract Definition`.
- **Method**: `POST`
- **URL**: `http://{{provider}}.{{dsDomain}}/management/v3/contractdefinitions`
- **Headers**:
  - `Authorization: Bearer {{provider_jwt}}`
  - `Content-Type: application/json`
- **Variables required before sending the request**: `provider_jwt`, `provider`, `dsDomain`, `e2e_contract_definition_id`, `e2e_policy_id`, `e2e_asset_id`
- **Variables it leaves ready for the next request**: `e2e_contract_definition_id` (confirmed/updated with the returned `@id`)

**Body (`raw`)**

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "@id": "{{e2e_contract_definition_id}}",
  "accessPolicyId": "{{e2e_policy_id}}",
  "contractPolicyId": "{{e2e_policy_id}}",
  "assetsSelector": [
    {
      "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
      "operator": "=",
      "operandRight": "{{e2e_asset_id}}"
    }
  ]
}
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  return;
}

pm.test("HTTP status indicates resource creation", function () {
  pm.expect(pm.response.code).to.be.oneOf([200, 201]);
});

pm.test("Contract definition creation returns @id", function () {
  pm.expect(body["@id"] || pm.environment.get("e2e_contract_definition_id")).to.exist;
});

if (body["@id"]) {
  setVar("e2e_contract_definition_id", body["@id"]);
}
```

### 5. Consumer Login

- **Goal**: Authenticate the consumer before catalog, negotiation, and transfer.
- **Functional reference in the framework**: `04_consumer_catalog.json`, `05_consumer_negotiation.json`, and `06_consumer_transfer.json` - request `Consumer Login`.
- **Method**: `POST`
- **URL**: `{{keycloakUrl}}/realms/{{dataspace}}/protocol/openid-connect/token`
- **Headers**:
  - `Content-Type: application/x-www-form-urlencoded`
- **Variables required before sending the request**: `keycloakUrl`, `dataspace`, `keycloakClientId`, `consumer_user`, `consumer_password`
- **Variables it leaves ready for the next request**: `consumer_jwt`

**Body (`urlencoded`)**

```text
grant_type=password
client_id={{keycloakClientId}}
username={{consumer_user}}
password={{consumer_password}}
scope=openid profile email
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  return;
}

pm.test("HTTP status is 200", function () {
  pm.response.to.have.status(200);
});

pm.test("Consumer login returns access_token", function () {
  pm.expect(body.access_token).to.be.a("string").and.not.empty;
});

setVar("consumer_jwt", body.access_token);
```

### 6. Request Federated Catalog (Management API)

- **Goal**: Ask the consumer's Management API for the provider's federated catalog and extract the negotiable offer.
- **Functional reference in the framework**: `04_consumer_catalog.json` - request `Request Federated Catalog (Management API)`.
- **Method**: `POST`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/catalog/request`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
  - `Content-Type: application/json`
- **Variables required before sending the request**: `consumer_jwt`, `consumer`, `dsDomain`, `providerProtocolAddress`, `provider`, `e2e_asset_id`
- **Variables it leaves ready for the next request**: `providerParticipantId`, `e2e_offer_policy_id`, `e2e_catalog_asset_id`, `catalog_lookup_attempt` (only while retrying)

**Body (`raw`)**

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "@type": "CatalogRequest",
  "counterPartyAddress": "{{providerProtocolAddress}}",
  "counterPartyId": "{{provider}}",
  "protocol": "dataspace-protocol-http",
  "querySpec": {
    "offset": 0,
    "limit": 100,
    "filterExpression": []
  }
}
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

function getVar(key, fallback) {
  return pm.collectionVariables.get(key) || pm.environment.get(key) || fallback;
}

function setNext(name) {
  if (pm.execution && typeof pm.execution.setNextRequest === "function") {
    pm.execution.setNextRequest(name);
  } else if (typeof postman !== "undefined" && typeof postman.setNextRequest === "function") {
    postman.setNextRequest(name);
  }
}

function scheduleRetry() {
  const maxAttempts = parseInt(getVar("catalog_max_attempts", "6"), 10);
  const attempt = parseInt(getVar("catalog_lookup_attempt", "0"), 10) + 1;
  if (attempt < maxAttempts) {
    setVar("catalog_lookup_attempt", String(attempt));
    pm.test(`Catalog lookup pending (${attempt}/${maxAttempts})`, function () {
      pm.expect(true).to.equal(true);
    });
    setNext(pm.info.requestName);
    return true;
  }
  pm.environment.unset("catalog_lookup_attempt");
  pm.collectionVariables.unset("catalog_lookup_attempt");
  return false;
}

if (pm.response.code !== 200) {
  pm.test("Federated catalog request returns 200", function () {
    pm.expect.fail(`Expected HTTP 200, got ${pm.response.code}. Body: ${pm.response.text()}`);
  });
  setNext(null);
  return;
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  setNext(null);
  return;
}

const catalog = Array.isArray(body) ? body[0] : body;
pm.test("Catalog response contains dcat:dataset", function () {
  pm.expect(catalog).to.have.property("dcat:dataset");
});

let datasets = catalog["dcat:dataset"];
if (!Array.isArray(datasets)) {
  datasets = datasets ? [datasets] : [];
}

const expectedAssetId = getVar("e2e_asset_id", "");
const dataset = datasets.find(function (item) {
  return item && JSON.stringify(item).includes(expectedAssetId);
});

if (!dataset) {
  if (!scheduleRetry()) {
    pm.test("Catalog contains the E2E asset", function () {
      pm.expect.fail(`Asset ${expectedAssetId} did not appear in the federated catalog after retries`);
    });
    setNext(null);
  }
  return;
}

pm.environment.unset("catalog_lookup_attempt");
pm.collectionVariables.unset("catalog_lookup_attempt");

let policy = dataset["odrl:hasPolicy"];
if (Array.isArray(policy)) {
  policy = policy[0];
}

pm.test("Catalog contains the E2E asset", function () {
  pm.expect(JSON.stringify(dataset)).to.include(expectedAssetId);
});
pm.test("Catalog dataset exposes @id", function () {
  pm.expect(dataset["@id"] || expectedAssetId).to.exist;
});
pm.test("Catalog dataset exposes a policy", function () {
  pm.expect(policy).to.exist;
  pm.expect(policy["@id"]).to.exist;
});

setVar("providerParticipantId", catalog["dspace:participantId"] || getVar("provider", ""));
setVar("e2e_offer_policy_id", policy["@id"]);
setVar("e2e_catalog_asset_id", dataset["@id"] || expectedAssetId);
```

### 7. Start Contract Negotiation

- **Goal**: Start the contract negotiation with the offer found in the catalog.
- **Functional reference in the framework**: `05_consumer_negotiation.json` - request `Start Contract Negotiation`.
- **Method**: `POST`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/contractnegotiations`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
  - `Content-Type: application/json`
- **Variables required before sending the request**: `consumer_jwt`, `consumer`, `dsDomain`, `providerProtocolAddress`, `providerParticipantId`, `e2e_offer_policy_id`, `e2e_catalog_asset_id`
- **Variables it leaves ready for the next request**: `e2e_negotiation_id`, `negotiation_start_attempt` (only while retrying)

**Body (`raw`)**

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "@type": "ContractRequest",
  "counterPartyAddress": "{{providerProtocolAddress}}",
  "protocol": "dataspace-protocol-http",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "odrl:Offer",
    "@id": "{{e2e_offer_policy_id}}",
    "assigner": "{{providerParticipantId}}",
    "target": "{{e2e_catalog_asset_id}}",
    "permission": [],
    "prohibition": [],
    "obligation": []
  }
}
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

function getVar(key, fallback) {
  return pm.collectionVariables.get(key) || pm.environment.get(key) || fallback;
}

function setNext(name) {
  if (pm.execution && typeof pm.execution.setNextRequest === "function") {
    pm.execution.setNextRequest(name);
  } else if (typeof postman !== "undefined" && typeof postman.setNextRequest === "function") {
    postman.setNextRequest(name);
  }
}

function transient(code) {
  return [401, 403, 404, 409, 423, 429, 500, 502, 503, 504].includes(code);
}

function retryOrFail() {
  const maxAttempts = parseInt(getVar("negotiation_start_max_attempts", "30"), 10);
  const attempt = parseInt(getVar("negotiation_start_attempt", "0"), 10) + 1;
  if (attempt < maxAttempts) {
    setVar("negotiation_start_attempt", String(attempt));
    pm.test(`Negotiation start pending (${attempt}/${maxAttempts})`, function () {
      pm.expect(true).to.equal(true);
    });
    setNext(pm.info.requestName);
    return true;
  }
  pm.environment.unset("negotiation_start_attempt");
  pm.collectionVariables.unset("negotiation_start_attempt");
  pm.test("Contract negotiation can be started", function () {
    pm.expect.fail(`Start Contract Negotiation kept returning HTTP ${pm.response.code}: ${pm.response.text()}`);
  });
  setNext(null);
  return false;
}

if (transient(pm.response.code)) {
  retryOrFail();
  return;
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  setNext(null);
  return;
}

pm.environment.unset("negotiation_start_attempt");
pm.collectionVariables.unset("negotiation_start_attempt");

pm.test("HTTP status indicates negotiation creation", function () {
  pm.expect(pm.response.code).to.be.oneOf([200, 201]);
});

pm.test("Negotiation start returns @id", function () {
  pm.expect(body["@id"]).to.exist;
});

setVar("e2e_negotiation_id", body["@id"]);
pm.environment.unset("e2e_agreement_id");
pm.collectionVariables.unset("e2e_agreement_id");
```

### 8. Check Negotiation Status

- **Goal**: Poll the negotiation until `contractAgreementId` is obtained.
- **Functional reference in the framework**: `05_consumer_negotiation.json` - request `Check Negotiation Status`.
- **Method**: `POST`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/contractnegotiations/request`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
  - `Content-Type: application/json`
- **Variables required before sending the request**: `consumer_jwt`, `consumer`, `dsDomain`, `e2e_negotiation_id`
- **Variables it leaves ready for the next request**: `e2e_agreement_id`, `negotiation_status_attempt` (only while retrying)

**Body (`raw`)**

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "offset": 0,
  "limit": 100
}
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

function getVar(key, fallback) {
  return pm.collectionVariables.get(key) || pm.environment.get(key) || fallback;
}

function setNext(name) {
  if (pm.execution && typeof pm.execution.setNextRequest === "function") {
    pm.execution.setNextRequest(name);
  } else if (typeof postman !== "undefined" && typeof postman.setNextRequest === "function") {
    postman.setNextRequest(name);
  }
}

function transient(code) {
  return [401, 403, 404, 429, 500, 502, 503, 504].includes(code);
}

function retryOrFail(reason) {
  const maxAttempts = parseInt(getVar("negotiation_status_max_attempts", "10"), 10);
  const attempt = parseInt(getVar("negotiation_status_attempt", "0"), 10) + 1;
  if (attempt < maxAttempts) {
    setVar("negotiation_status_attempt", String(attempt));
    pm.test(`Negotiation status pending (${attempt}/${maxAttempts})`, function () {
      pm.expect(true).to.equal(true);
    });
    if (reason) console.log(reason);
    setNext(pm.info.requestName);
    return true;
  }
  pm.environment.unset("negotiation_status_attempt");
  pm.collectionVariables.unset("negotiation_status_attempt");
  pm.test("Contract agreement becomes available", function () {
    pm.expect.fail(reason || "Negotiation did not produce contractAgreementId after retries");
  });
  setNext(null);
  return false;
}

if (transient(pm.response.code)) {
  retryOrFail(`Check Negotiation Status returned HTTP ${pm.response.code}: ${pm.response.text()}`);
  return;
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  setNext(null);
  return;
}

pm.test("HTTP status is 200", function () {
  pm.response.to.have.status(200);
});

const negotiationId = getVar("e2e_negotiation_id", "");
let negotiation = Array.isArray(body)
  ? body.find(item => item && (item["@id"] === negotiationId || item.id === negotiationId))
  : body;

if (!negotiation) {
  retryOrFail(`Negotiation ${negotiationId} is still not visible in the status list`);
  return;
}

const state = negotiation.state;
pm.test("Negotiation state is recognized", function () {
  pm.expect(state).to.be.oneOf([
    "INITIAL",
    "REQUESTED",
    "REQUESTING",
    "VERIFYING",
    "IN_PROGRESS",
    "AGREED",
    "VERIFIED",
    "FINALIZED",
    "TERMINATING",
    "TERMINATED"
  ]);
});

const agreementId = negotiation.contractAgreementId;
if ((state === "TERMINATING" || state === "TERMINATED") && !agreementId) {
  pm.test("Negotiation did not terminate", function () {
    pm.expect.fail(`Negotiation reached ${state} state before contractAgreementId${negotiation.errorDetail ? `: ${negotiation.errorDetail}` : ''}`);
  });
  setNext(null);
  return;
}

if ((state === "TERMINATING" || state === "TERMINATED") && agreementId) {
  console.log(`Negotiation reached ${state} after producing contractAgreementId; transfer validation will confirm agreement usability.`);
  if (negotiation.errorDetail) console.log("Negotiation error detail:", negotiation.errorDetail);
}

if (!agreementId) {
  retryOrFail(`Negotiation ${negotiationId} is in state ${state || 'unknown'} without contractAgreementId`);
  return;
}

pm.environment.unset("negotiation_status_attempt");
pm.collectionVariables.unset("negotiation_status_attempt");
setVar("e2e_agreement_id", agreementId);
pm.test("Contract agreement is available", function () {
  pm.expect(agreementId).to.be.a("string").and.not.empty;
});
```

### 9. Start Transfer Process

- **Goal**: Start the real transfer using `AmazonS3-PUSH` and the configured adapter's endpoint.
- **Functional reference in the framework**: `06_consumer_transfer.json` - request `Start Transfer Process`.
- **Method**: `POST`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/{{transferStartPath}}`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
  - `Content-Type: application/json`
- **Variables required before sending the request**: `consumer_jwt`, `consumer`, `dsDomain`, `transferStartPath`, `adapter`, `transferDestinationType`, `e2e_asset_id`, `e2e_agreement_id`, `providerProtocolAddress`
- **EDC/MinIO variables when applicable**: `transferRequestType`, `transferType`, `transferDestinationBucket`, `transferDestinationRegion`, `transferDestinationEndpointOverride`
- **Variables it leaves ready for the next request**: `e2e_transfer_id`, `e2e_transfer_request_destination`, `transfer_start_attempt` (only while retrying)

**Body (`raw`)**

```text
{{transferRequestBody}}
```

**Exact Pre-request Script**

```javascript
const agreementId = pm.collectionVariables.get("e2e_agreement_id") || pm.environment.get("e2e_agreement_id");
if (!agreementId) {
  if (pm.execution && typeof pm.execution.skipRequest === "function") {
    pm.execution.skipRequest();
  }
}

function getVar(key, fallback) {
  return pm.collectionVariables.get(key) || pm.environment.get(key) || fallback;
}

function nonEmptyVar(key) {
  const value = getVar(key, "");
  return value === undefined || value === null ? "" : String(value).trim();
}

const adapter = String(getVar("adapter", "")).trim().toLowerCase();
const provider = getVar("providerParticipantId", getVar("provider", ""));
const providerProtocolAddress = getVar("providerProtocolAddress", "");
const transferType = getVar("transferType", "AmazonS3-PUSH");
const transferDestinationType = getVar("transferDestinationType", adapter === "edc" ? "AmazonS3" : "InesDataStore");

function buildS3Destination() {
  const destination = {
    type: transferDestinationType || "AmazonS3",
    bucketName: nonEmptyVar("transferDestinationBucket"),
    region: nonEmptyVar("transferDestinationRegion") || "eu-central-1",
    keyName: nonEmptyVar("transferDestinationObjectName") || nonEmptyVar("e2e_source_object_name"),
    name: nonEmptyVar("transferDestinationObjectName") || nonEmptyVar("e2e_source_object_name"),
    endpointOverride: nonEmptyVar("transferDestinationEndpointOverride")
  };
  Object.keys(destination).forEach(key => { if (!destination[key]) delete destination[key]; });
  return destination;
}

let payload;
if (adapter === "edc") {
  payload = {
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "@type": getVar("transferRequestType", "TransferRequestDto"),
    connectorId: provider,
    counterPartyAddress: providerProtocolAddress,
    contractId: agreementId,
    protocol: "dataspace-protocol-http",
    transferType
  };
  if (transferType.toLowerCase().includes("push") && transferDestinationType.toLowerCase() !== "httpdata") {
    payload.dataDestination = buildS3Destination();
  }
} else {
  payload = {
    "@context": { "@vocab": "https://w3id.org/edc/v0.0.1/ns/" },
    "@type": getVar("transferRequestType", "TransferRequest"),
    assetId: getVar("e2e_asset_id", ""),
    contractId: agreementId,
    counterPartyAddress: providerProtocolAddress,
    protocol: "dataspace-protocol-http",
    transferType,
    dataDestination: { type: transferDestinationType || "InesDataStore" }
  };
}

if (payload.dataDestination) {
  pm.collectionVariables.set("e2e_transfer_request_destination", JSON.stringify(payload.dataDestination));
} else {
  pm.collectionVariables.unset("e2e_transfer_request_destination");
}
pm.variables.set("transferRequestBody", JSON.stringify(payload, null, 2));
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

function getVar(key, fallback) {
  return pm.collectionVariables.get(key) || pm.environment.get(key) || fallback;
}

function setNext(name) {
  if (pm.execution && typeof pm.execution.setNextRequest === "function") {
    pm.execution.setNextRequest(name);
  } else if (typeof postman !== "undefined" && typeof postman.setNextRequest === "function") {
    postman.setNextRequest(name);
  }
}

function transient(code) {
  return [401, 403, 404, 409, 423, 429, 500, 502, 503, 504].includes(code);
}

function retryOrFail() {
  const maxAttempts = parseInt(getVar("transfer_start_max_attempts", "8"), 10);
  const attempt = parseInt(getVar("transfer_start_attempt", "0"), 10) + 1;
  if (attempt < maxAttempts) {
    setVar("transfer_start_attempt", String(attempt));
    pm.test(`Transfer start pending (${attempt}/${maxAttempts})`, function () {
      pm.expect(true).to.equal(true);
    });
    setNext(pm.info.requestName);
    return true;
  }
  pm.environment.unset("transfer_start_attempt");
  pm.collectionVariables.unset("transfer_start_attempt");
  pm.test("Transfer process can be started", function () {
    pm.expect.fail(`Start Transfer Process kept returning HTTP ${pm.response.code}: ${pm.response.text()}`);
  });
  setNext(null);
  return false;
}

if (transient(pm.response.code)) {
  retryOrFail();
  return;
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  setNext(null);
  return;
}

pm.environment.unset("transfer_start_attempt");
pm.collectionVariables.unset("transfer_start_attempt");

pm.test("HTTP status indicates transfer creation", function () {
  pm.expect(pm.response.code).to.be.oneOf([200, 201]);
});

pm.test("Transfer start returns @id", function () {
  pm.expect(body["@id"]).to.exist;
});

setVar("e2e_transfer_id", body["@id"]);
```

### 10. Resolve Current Transfer Destination

- **Goal**: Resolve the current `dataDestination` of the transfer process and check that it points to the consumer's bucket.
- **Functional reference in the framework**: `06_consumer_transfer.json` - request `Resolve Current Transfer Destination`.
- **Method**: `GET`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/transferprocesses/{{e2e_transfer_id}}`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
- **Variables required before sending the request**: `consumer_jwt`, `consumer`, `dsDomain`, `e2e_transfer_id`, `e2e_expected_consumer_bucket`
- **Variables it leaves ready for the next request**: `e2e_transfer_destination_bucket`, `transfer_destination_attempt` (only while retrying)

**Exact Pre-request Script**

```javascript
if (!(pm.collectionVariables.get("e2e_transfer_id") || pm.environment.get("e2e_transfer_id"))) {
  if (pm.execution && typeof pm.execution.skipRequest === "function") {
    pm.execution.skipRequest();
  }
}
```

**Exact Tests Script**

```javascript
function setVar(key, value) {
  pm.environment.set(key, value);
  pm.collectionVariables.set(key, value);
}

function getVar(key, fallback) {
  return pm.collectionVariables.get(key) || pm.environment.get(key) || fallback;
}

function setNext(name) {
  if (pm.execution && typeof pm.execution.setNextRequest === "function") {
    pm.execution.setNextRequest(name);
  } else if (typeof postman !== "undefined" && typeof postman.setNextRequest === "function") {
    postman.setNextRequest(name);
  }
}

function transient(code) {
  return [401, 403, 404, 429, 500, 502, 503, 504].includes(code);
}

function readField(obj, fieldName) {
  if (!obj || typeof obj !== "object") return undefined;
  const namespaced = `https://w3id.org/edc/v0.0.1/ns/${fieldName}`;
  if (Object.prototype.hasOwnProperty.call(obj, fieldName)) return obj[fieldName];
  if (Object.prototype.hasOwnProperty.call(obj, namespaced)) return obj[namespaced];
  if (obj.properties && typeof obj.properties === "object") {
    if (Object.prototype.hasOwnProperty.call(obj.properties, fieldName)) return obj.properties[fieldName];
    if (Object.prototype.hasOwnProperty.call(obj.properties, namespaced)) return obj.properties[namespaced];
  }
  return undefined;
}

function parseStoredJson(key) {
  const raw = getVar(key, "");
  if (!raw) return undefined;
  try {
    return JSON.parse(raw);
  } catch (e) {
    console.log(`Could not parse ${key}: ${e}`);
    return undefined;
  }
}

function retryOrFail(reason) {
  const maxAttempts = parseInt(getVar("transfer_destination_max_attempts", "10"), 10);
  const attempt = parseInt(getVar("transfer_destination_attempt", "0"), 10) + 1;
  if (attempt < maxAttempts) {
    setVar("transfer_destination_attempt", String(attempt));
    pm.test(`Transfer destination pending (${attempt}/${maxAttempts})`, function () {
      pm.expect(true).to.equal(true);
    });
    if (reason) console.log(reason);
    setNext(pm.info.requestName);
    return true;
  }
  pm.environment.unset("transfer_destination_attempt");
  pm.collectionVariables.unset("transfer_destination_attempt");
  pm.test("Transfer destination is resolved", function () {
    pm.expect.fail(reason || "Transfer destination did not become available after retries");
  });
  setNext(null);
  return false;
}

if (transient(pm.response.code)) {
  retryOrFail(`Resolve Current Transfer Destination returned HTTP ${pm.response.code}: ${pm.response.text()}`);
  return;
}

let body;
try {
  body = pm.response.json();
} catch (e) {
  pm.test("Response body is valid JSON", function () {
    pm.expect.fail("Response body is not valid JSON");
  });
  setNext(null);
  return;
}

pm.test("HTTP status is 200", function () {
  pm.response.to.have.status(200);
});

const transferId = getVar("e2e_transfer_id", "");
let transfer = Array.isArray(body)
  ? body.find(item => item && (item["@id"] === transferId || item.id === transferId))
  : body;

if (!transfer) {
  retryOrFail(`Transfer ${transferId} is still not visible while resolving destination`);
  return;
}

const state = readField(transfer, "state") || transfer.state;
if (state === "TERMINATED") {
  pm.test("Transfer did not terminate", function () {
    pm.expect.fail(`Transfer reached TERMINATED state${transfer.errorDetail ? `: ${transfer.errorDetail}` : ''}`);
  });
  setNext(null);
  return;
}

const adapter = String(getVar("adapter", "")).trim().toLowerCase();
const expectedTransferType = getVar("transferType", "AmazonS3-PUSH");
const requestedDestinationType = getVar("transferDestinationType", "AmazonS3");
const expectsObjectStorageDestination =
  String(expectedTransferType).toLowerCase().includes("push") &&
  String(requestedDestinationType).toLowerCase() !== "httpdata";

if (adapter === "edc" && !expectsObjectStorageDestination) {
  pm.environment.unset("transfer_destination_attempt");
  pm.collectionVariables.unset("transfer_destination_attempt");
  pm.test("EDC transfer state is queryable through the standard management API", function () {
    pm.expect(state).to.be.a("string").and.not.empty;
  });
  return;
}

const dataDestination =
  readField(transfer, "dataDestination") ||
  transfer.dataDestination ||
  transfer["https://w3id.org/edc/v0.0.1/ns/dataDestination"] ||
  (adapter === "edc" ? parseStoredJson("e2e_transfer_request_destination") : undefined);

if (!dataDestination) {
  retryOrFail(`Transfer ${transferId} is visible but does not expose dataDestination yet`);
  return;
}

pm.environment.unset("transfer_destination_attempt");
pm.collectionVariables.unset("transfer_destination_attempt");

const transferAssetId = readField(transfer, "assetId") || transfer.assetId;
const expectedAssetId = getVar("e2e_asset_id", "");
const transferType = readField(transfer, "transferType") || transfer.transferType;
const destinationType = readField(dataDestination, "type");
const bucketName = readField(dataDestination, "bucketName");
const endpointOverride = readField(dataDestination, "endpointOverride");
const expectedBucket = getVar("e2e_expected_consumer_bucket", "");
const expectedResolvedDestinationType =
  String(requestedDestinationType).toLowerCase() === "inesdatastore" ? "AmazonS3" : requestedDestinationType;

pm.test("Transfer still references the negotiated asset", function () {
  pm.expect(transferAssetId).to.equal(expectedAssetId);
});

pm.test("Transfer uses the transfer type expected by the adapter", function () {
  pm.expect(transferType).to.equal(expectedTransferType);
});

pm.test("Resolved destination type is object storage", function () {
  pm.expect(destinationType).to.equal(expectedResolvedDestinationType);
});

pm.test("Resolved destination bucket matches consumer bucket", function () {
  pm.expect(bucketName).to.equal(expectedBucket);
});

pm.test("Resolved destination exposes endpointOverride", function () {
  pm.expect(endpointOverride).to.be.a("string").and.not.empty;
});

setVar("e2e_transfer_destination_bucket", bucketName);
```

## What this collection validates and what it leaves out

This compact collection does validate, in a chained way:

- creation of the provider's asset, policy, and contract definition
- discovery of the asset from the consumer through the federated catalog
- contract negotiation until `contractAgreementId` is obtained
- start of the real `AmazonS3-PUSH` transfer
- resolution of the final `dataDestination` and validation of the consumer's bucket

This compact collection **does not replace** the full `01`-`06` set, because it leaves out additional health checks, exhaustive CRUD, and intermediate diagnostics meant for the framework's automatic run.

## Relationship with the main documentation

- `Validation-Environment/docs/06_information_exchange_flow.md` (ES) is still the conceptual document of the flow.
- This document is the exact operational reference for manual Postman runs.
- The `Validation-Environment/validation/core/collections/postman/03_e2e_compact.json` collection is the importable artifact that implements exactly this guide.

## STICS evidence: real provider/consumer interoperability (PULL + PUSH)

Besides the framework's generic collections, this folder contains a
collection **specific to the STICS project**, self-contained and already
verified against the real `vm-distributed` environment:

- `04_stics_edc_interop.json` — complete flow: login of both connectors,
  creation of asset/policy/contract-definition on the provider, DSP catalog,
  contract negotiation, and **both** transfer types (`HttpData-PULL` with a
  real data pull through the EDR, and `HttpData-PUSH` with real delivery to
  the consumer's sink).
- `00_environment_stics.json` — environment with the real public URLs
  (`stics.bavenir.eu` for the provider, `con-lab.stics.linkeddata.es` for the
  consumer). Fill in `provider_password`/`consumer_password` locally (they
  come from `credentials.json` and are not versioned).

Unlike `03_e2e_compact.json` (generic, derives hostnames from the framework's
`{{connector}}.{{dsDomain}}` convention), this collection directly uses the
real public hostnames of the STICS project, because the
`connector-stics`/`conlab-stics` connectors run outside Kubernetes with
Docker Compose and don't follow that convention.

Narrative documentation with the same steps in `curl` (no Postman needed): [docs/47_stics_edc_interop_evidence.md](../../../../docs/47_stics_edc_interop_evidence.md).

## Evidence: PULL transfer with `connector-bavenir`

- `05_connector_bavenir_pull_transfer.json` — complete `HttpData-PULL` flow
  with `connector-bavenir` (the connector set up in the hands-on session with
  bavenir, see
  [docs/49_bavenir_hands_on_session_guide.md](../../../../docs/49_bavenir_hands_on_session_guide.md))
  as **provider** and `connector-stics` as **consumer**: login of both,
  creation of asset/policy/contract-definition on `connector-bavenir`, DSP
  catalog, negotiation, transfer, and a real data pull through
  `connector-bavenir`'s public data plane.
- `00_environment_connector_bavenir.json` — same variable keys as
  `00_environment_stics.json`, pointing to
  `connector-bavenir.stics.bavenir.eu` (provider) and `stics.bavenir.eu`
  (consumer, `connector-stics`). Fill in `provider_password` (from
  `connector-bavenir`'s `credentials.json`) and `consumer_password` (from
  `connector-stics`'s `credentials.json`) locally before running.
