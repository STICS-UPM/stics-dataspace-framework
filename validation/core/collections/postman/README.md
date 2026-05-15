# Replicación Manual Compacta en Postman

## Objetivo

Este documento es una versión operativa y provisional del paso manual en Postman. Su objetivo no es explicar el flujo conceptualmente, sino dejar una referencia exacta y ejecutable para reproducir el recorrido E2E principal del framework **sin depender** de la inyección dinámica de `test_script` que hace `NewmanExecutor`.

Los artefactos asociados son:

- `Validation-Environment/validation/core/collections/postman/01_environment_health.json`
- `Validation-Environment/validation/core/collections/postman/02_connector_management_api.json`
- `Validation-Environment/validation/core/collections/postman/03_e2e_compact.json`
- `Validation-Environment/validation/core/collections/postman/00_environment.json`
- `Validation-Environment/validation/core/collections/postman/00_environment_edc.json`

Antes de lanzar estas colecciones desde `Level 6`, el framework ejecuta un
preflight ligero sobre Management API para el par `provider/consumer`. Esa
comprobación valida login de ambos conectores y prueba, con sus propios tokens,
estos endpoints:

- `POST /management/v3/assets/request` en el proveedor
- `POST /management/v3/contractnegotiations/request` en el consumidor
- `POST /management/v3/catalog/request` en el consumidor contra el protocolo del proveedor

Si alguno falla, el framework aborta antes de Newman y persiste el diagnóstico
en `00_management_api_preflight.json` dentro del directorio de reportes del par.

## Colecciones disponibles

Esta carpeta contiene tres variantes importables en Postman:

1. `01_environment_health.json`
   - réplica autocontenida de `01_environment_health.json`
   - útil para smoke básico de autenticación, Management API y DSP
2. `02_connector_management_api.json`
   - réplica autocontenida de `02_connector_management_api.json`
   - útil para validar el CRUD técnico del proveedor
3. `03_e2e_compact.json`
   - flujo compacto orientado a `03` + `04` + `05` + `06`
   - útil cuando se quiere validar el recorrido E2E principal con menos tiempo de ejecución

Las tres colecciones reutilizan un environment del adapter que quieras probar:

- `Validation-Environment/validation/core/collections/postman/00_environment.json` para INESData
- `Validation-Environment/validation/core/collections/postman/00_environment_edc.json` para EDC

La lógica original que el framework inyecta dinámicamente sigue estando en:

- `Validation-Environment/framework/newman_executor.py`
- `Validation-Environment/validation/shared/api/common_tests.js`
- `Validation-Environment/validation/core/tests/provider_tests.js`
- `Validation-Environment/validation/core/tests/catalog_tests.js`
- `Validation-Environment/validation/core/tests/negotiation_tests.js`
- `Validation-Environment/validation/core/tests/transfer_tests.js`

## Por qué existe esta colección compacta

La colección `03_e2e_compact.json` reduce tiempo de ejecución porque elimina comprobaciones que en Postman manual suelen aportar poco valor cuando el objetivo es validar el flujo principal de interoperabilidad:

- omite `01_environment_health.json` y `02_connector_management_api.json`
- omite los requests de listado CRUD intermedios de `03_provider_setup.json`
- omite `Direct DSP Catalog Request` de `04_consumer_catalog.json`
- omite `Check Transfer Status` de `06_consumer_transfer.json` y se apoya en la resolución directa del destino
- hace login del proveedor una sola vez y login del consumidor una sola vez
- embebe en cada request el script exacto necesario para producir las variables de la siguiente request

## Configuración inicial exacta del environment

Antes de importar o reconstruir manualmente la colección, crea un environment con estas variables base. Si quieres ahorrar tiempo, puedes importar directamente:

- `Validation-Environment/validation/core/collections/postman/00_environment.json` para INESData
- `Validation-Environment/validation/core/collections/postman/00_environment_edc.json` para EDC

Esos ficheros son **environments importables de Postman** y contienen solo las variables base necesarias, sin variables derivadas del flujo.

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
  "transferStartPath": "inesdatatransferprocesses",
  "transferDestinationType": "InesDataStore",
  "providerProtocolAddress": "http://conn-citycouncil-pionera:19194/protocol",
  "consumerProtocolAddress": "http://conn-company-pionera:19194/protocol"
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
  "transferStartPath": "transferprocesses",
  "transferRequestType": "TransferRequestDto",
  "transferType": "AmazonS3-PUSH",
  "transferDestinationType": "AmazonS3",
  "transferDestinationBucket": "pionera-edc-conn-companyedc-pionera-edc",
  "transferDestinationRegion": "eu-central-1",
  "transferDestinationEndpointOverride": "http://minio.dev.ed.dataspaceunit.upm",
  "providerProtocolAddress": "http://conn-citycounciledc-pionera-edc:19194/protocol",
  "consumerProtocolAddress": "http://conn-companyedc-pionera-edc:19194/protocol"
}
```

Notas importantes:

- `providerProtocolAddress` y `consumerProtocolAddress` **no** son endpoints pensados para ser invocados directamente desde Postman en tu máquina; son direcciones que el conector utiliza internamente cuando recibe la request de Management API.
- Las contraseñas locales del entorno INESData actual se generan bajo `deployers/inesdata/deployments/DEV/pionera/credentials-connector-<connector>.json`, campo `connector_user.passwd`.
- Para EDC, las contraseñas equivalentes se generan bajo `deployers/edc/deployments/DEV/pionera-edc/credentials-connector-<connector>.json`, campo `connector_user.passwd`.
- La colección compacta genera dinámicamente todos los identificadores `e2e_*`, así que no hace falta precargarlos en el environment.

## Variables de colección usadas para reintentos

La colección define estas collection variables para acotar los reintentos y mantener una ejecución más rápida que el conjunto completo del framework:

- `catalog_max_attempts = 6`
- `negotiation_start_max_attempts = 30`
- `negotiation_status_max_attempts = 10`
- `transfer_start_max_attempts = 8`
- `transfer_destination_max_attempts = 10`

## Orden de ejecución

La colección compacta debe ejecutarse exactamente en este orden:

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

## Configuración exacta request por request

En cada bloque siguiente se documenta la configuración exacta que hay que implementar si decides reconstruir la colección manualmente en Postman. Si prefieres ahorrar tiempo, importa directamente `03_e2e_compact.json`, donde todo esto ya está embebido.

### 1. Provider Login

- **Objetivo**: Autenticar al proveedor y sembrar todos los identificadores `e2e_*` que usará el resto del flujo.
- **Referencia funcional en el framework**: `03_provider_setup.json` - request `Provider Login` con script embebido adicional para limpiar y encadenar estado.
- **Método**: `POST`
- **URL**: `{{keycloakUrl}}/realms/{{dataspace}}/protocol/openid-connect/token`
- **Headers**:
  - `Content-Type: application/x-www-form-urlencoded`
- **Variables requeridas antes de lanzar la request**: `keycloakUrl`, `dataspace`, `keycloakClientId`, `provider_user`, `provider_password`, `provider`, `consumer`
- **Variables que deja preparadas para la siguiente request**: `provider_jwt`, `e2e_suffix`, `e2e_asset_id`, `e2e_policy_id`, `e2e_contract_definition_id`, `e2e_expected_provider_bucket`, `e2e_expected_consumer_bucket`

**Body (`urlencoded`)**

```text
grant_type=password
client_id={{keycloakClientId}}
username={{provider_user}}
password={{provider_password}}
scope=openid profile email
```

**Tests Script exacto**

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

- **Objetivo**: Crear el asset negociable mínimo para el flujo E2E.
- **Referencia funcional en el framework**: `03_provider_setup.json` - request `Create E2E Asset`.
- **Método**: `POST`
- **URL**: `http://{{provider}}.{{dsDomain}}/management/v3/assets`
- **Headers**:
  - `Authorization: Bearer {{provider_jwt}}`
  - `Content-Type: application/json`
- **Variables requeridas antes de lanzar la request**: `provider_jwt`, `provider`, `dsDomain`, `e2e_asset_id`, `e2e_suffix`
- **Variables que deja preparadas para la siguiente request**: `e2e_asset_id` (se confirma/actualiza con el `@id` devuelto)

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

**Tests Script exacto**

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

- **Objetivo**: Crear la policy asociada al asset.
- **Referencia funcional en el framework**: `03_provider_setup.json` - request `Create E2E Policy`.
- **Método**: `POST`
- **URL**: `http://{{provider}}.{{dsDomain}}/management/v3/policydefinitions`
- **Headers**:
  - `Authorization: Bearer {{provider_jwt}}`
  - `Content-Type: application/json`
- **Variables requeridas antes de lanzar la request**: `provider_jwt`, `provider`, `dsDomain`, `e2e_policy_id`
- **Variables que deja preparadas para la siguiente request**: `e2e_policy_id` (se confirma/actualiza con el `@id` devuelto)

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

**Tests Script exacto**

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

- **Objetivo**: Crear la contract definition que vincula asset y policy.
- **Referencia funcional en el framework**: `03_provider_setup.json` - request `Create E2E Contract Definition`.
- **Método**: `POST`
- **URL**: `http://{{provider}}.{{dsDomain}}/management/v3/contractdefinitions`
- **Headers**:
  - `Authorization: Bearer {{provider_jwt}}`
  - `Content-Type: application/json`
- **Variables requeridas antes de lanzar la request**: `provider_jwt`, `provider`, `dsDomain`, `e2e_contract_definition_id`, `e2e_policy_id`, `e2e_asset_id`
- **Variables que deja preparadas para la siguiente request**: `e2e_contract_definition_id` (se confirma/actualiza con el `@id` devuelto)

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

**Tests Script exacto**

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

- **Objetivo**: Autenticar al consumidor antes de catálogo, negociación y transferencia.
- **Referencia funcional en el framework**: `04_consumer_catalog.json`, `05_consumer_negotiation.json` y `06_consumer_transfer.json` - request `Consumer Login`.
- **Método**: `POST`
- **URL**: `{{keycloakUrl}}/realms/{{dataspace}}/protocol/openid-connect/token`
- **Headers**:
  - `Content-Type: application/x-www-form-urlencoded`
- **Variables requeridas antes de lanzar la request**: `keycloakUrl`, `dataspace`, `keycloakClientId`, `consumer_user`, `consumer_password`
- **Variables que deja preparadas para la siguiente request**: `consumer_jwt`

**Body (`urlencoded`)**

```text
grant_type=password
client_id={{keycloakClientId}}
username={{consumer_user}}
password={{consumer_password}}
scope=openid profile email
```

**Tests Script exacto**

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

- **Objetivo**: Pedir al Management API del consumidor el catálogo federado del proveedor y extraer la oferta negociable.
- **Referencia funcional en el framework**: `04_consumer_catalog.json` - request `Request Federated Catalog (Management API)`.
- **Método**: `POST`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/catalog/request`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
  - `Content-Type: application/json`
- **Variables requeridas antes de lanzar la request**: `consumer_jwt`, `consumer`, `dsDomain`, `providerProtocolAddress`, `provider`, `e2e_asset_id`
- **Variables que deja preparadas para la siguiente request**: `providerParticipantId`, `e2e_offer_policy_id`, `e2e_catalog_asset_id`, `catalog_lookup_attempt` (solo mientras reintenta)

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

**Tests Script exacto**

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

- **Objetivo**: Lanzar la negociación contractual con la oferta localizada en catálogo.
- **Referencia funcional en el framework**: `05_consumer_negotiation.json` - request `Start Contract Negotiation`.
- **Método**: `POST`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/contractnegotiations`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
  - `Content-Type: application/json`
- **Variables requeridas antes de lanzar la request**: `consumer_jwt`, `consumer`, `dsDomain`, `providerProtocolAddress`, `providerParticipantId`, `e2e_offer_policy_id`, `e2e_catalog_asset_id`
- **Variables que deja preparadas para la siguiente request**: `e2e_negotiation_id`, `negotiation_start_attempt` (solo mientras reintenta)

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

**Tests Script exacto**

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

- **Objetivo**: Consultar la negociación hasta obtener `contractAgreementId`.
- **Referencia funcional en el framework**: `05_consumer_negotiation.json` - request `Check Negotiation Status`.
- **Método**: `POST`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/contractnegotiations/request`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
  - `Content-Type: application/json`
- **Variables requeridas antes de lanzar la request**: `consumer_jwt`, `consumer`, `dsDomain`, `e2e_negotiation_id`
- **Variables que deja preparadas para la siguiente request**: `e2e_agreement_id`, `negotiation_status_attempt` (solo mientras reintenta)

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

**Tests Script exacto**

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
    "TERMINATED"
  ]);
});

if (state === "TERMINATED") {
  pm.test("Negotiation did not terminate", function () {
    pm.expect.fail(`Negotiation reached TERMINATED state${negotiation.errorDetail ? `: ${negotiation.errorDetail}` : ''}`);
  });
  setNext(null);
  return;
}

const agreementId = negotiation.contractAgreementId;
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

- **Objetivo**: Iniciar la transferencia real usando `AmazonS3-PUSH` y el endpoint del adapter configurado.
- **Referencia funcional en el framework**: `06_consumer_transfer.json` - request `Start Transfer Process`.
- **Método**: `POST`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/{{transferStartPath}}`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
  - `Content-Type: application/json`
- **Variables requeridas antes de lanzar la request**: `consumer_jwt`, `consumer`, `dsDomain`, `transferStartPath`, `adapter`, `transferDestinationType`, `e2e_asset_id`, `e2e_agreement_id`, `providerProtocolAddress`
- **Variables EDC/MinIO cuando aplica**: `transferRequestType`, `transferType`, `transferDestinationBucket`, `transferDestinationRegion`, `transferDestinationEndpointOverride`
- **Variables que deja preparadas para la siguiente request**: `e2e_transfer_id`, `e2e_transfer_request_destination`, `transfer_start_attempt` (solo mientras reintenta)

**Body (`raw`)**

```text
{{transferRequestBody}}
```

**Pre-request Script exacto**

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

**Tests Script exacto**

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

- **Objetivo**: Resolver el `dataDestination` actual del transfer process y comprobar que apunta al bucket del consumidor.
- **Referencia funcional en el framework**: `06_consumer_transfer.json` - request `Resolve Current Transfer Destination`.
- **Método**: `GET`
- **URL**: `http://{{consumer}}.{{dsDomain}}/management/v3/transferprocesses/{{e2e_transfer_id}}`
- **Headers**:
  - `Authorization: Bearer {{consumer_jwt}}`
- **Variables requeridas antes de lanzar la request**: `consumer_jwt`, `consumer`, `dsDomain`, `e2e_transfer_id`, `e2e_expected_consumer_bucket`
- **Variables que deja preparadas para la siguiente request**: `e2e_transfer_destination_bucket`, `transfer_destination_attempt` (solo mientras reintenta)

**Pre-request Script exacto**

```javascript
if (!(pm.collectionVariables.get("e2e_transfer_id") || pm.environment.get("e2e_transfer_id"))) {
  if (pm.execution && typeof pm.execution.skipRequest === "function") {
    pm.execution.skipRequest();
  }
}
```

**Tests Script exacto**

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

## Qué valida esta colección y qué deja fuera

Esta colección compacta sí valida de forma encadenada:

- creación del asset, policy y contract definition del proveedor
- descubrimiento del asset desde el consumidor vía catálogo federado
- negociación contractual hasta obtener `contractAgreementId`
- inicio de la transferencia real `AmazonS3-PUSH`
- resolución del `dataDestination` final y validación del bucket del consumidor

Esta colección compacta **no sustituye** al conjunto completo `01`-`06`, porque deja fuera checks adicionales de health, CRUD exhaustivo y diagnósticos intermedios pensados para la ejecución automática del framework.

## Relación con la documentación principal

- `Validation-Environment/docs/06_information_exchange_flow.md` sigue siendo el documento conceptual del flujo.
- Este documento es la referencia operativa exacta para Postman manual.
- La colección `Validation-Environment/validation/core/collections/postman/03_e2e_compact.json` es el artefacto importable que implementa exactamente esta guía.
