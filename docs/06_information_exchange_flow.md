# 06. Flujo de Intercambio de Información

## Objetivo

Este documento explica de forma didáctica qué valida hoy el core API del dataspace en el framework, por qué existe cada colección de Postman/Newman y cómo puede reproducirse manualmente en Postman.

La idea es que sirva para tres cosas a la vez:

- explicar de forma clara el intercambio básico de datos en un espacio de datos
- dejar claro qué está validando realmente `validation/core`
- permitir reconstruir y revisar manualmente en Postman las pruebas core del framework

## Qué valida hoy el core del dataspace

El core API del framework valida seis bloques:

1. autenticación y salud básica del entorno
2. CRUD técnico del Management API
3. preparación del proveedor
4. descubrimiento desde el consumidor
5. negociación del contrato
6. inicio de la transferencia real de INESData y validación del destino de almacenamiento

En el repositorio, estas pruebas viven en:

- [01_environment_health.json](../validation/core/collections/01_environment_health.json)
- [02_connector_management_api.json](../validation/core/collections/02_connector_management_api.json)
- [03_provider_setup.json](../validation/core/collections/03_provider_setup.json)
- [04_consumer_catalog.json](../validation/core/collections/04_consumer_catalog.json)
- [05_consumer_negotiation.json](../validation/core/collections/05_consumer_negotiation.json)
- [06_consumer_transfer.json](../validation/core/collections/06_consumer_transfer.json)

La lógica de validación está en:

- [common_tests.js](../validation/shared/api/common_tests.js)
- [management_tests.js](../validation/core/tests/management_tests.js)
- [provider_tests.js](../validation/core/tests/provider_tests.js)
- [catalog_tests.js](../validation/core/tests/catalog_tests.js)
- [negotiation_tests.js](../validation/core/tests/negotiation_tests.js)
- [transfer_tests.js](../validation/core/tests/transfer_tests.js)

## Cómo encaja esto con EDC e INESData

INESData se apoya en la arquitectura de EDC, así que conviene entender cuatro piezas básicas antes de leer el detalle de las colecciones:

- `provider`
  - es el participante que publica un recurso y lo ofrece al resto
- `consumer`
  - es el participante que descubre la oferta, negocia un contrato y solicita la transferencia
- `Management API`
  - es la API administrativa que se usa para crear assets, policies, contract definitions, lanzar negociaciones y consultar estados
- `protocol API`
  - es la superficie DSP que permite exponer catálogo e interoperar entre participantes

El flujo EDC clásico sigue esta idea:

1. el proveedor publica un asset negociable
2. el consumidor descubre esa oferta en catálogo
3. el consumidor negocia un contrato sobre esa oferta
4. el consumidor inicia una transferencia basada en el acuerdo obtenido

En INESData, la parte diferencial está en el último paso:

- el framework no valida como camino principal un `HttpData-PULL` genérico
- valida el flujo real de INESData, que usa `AmazonS3-PUSH`
- el runtime resuelve un `dataDestination` hacia el bucket del consumidor
- el framework comprueba ese destino y, cuando puede, añade una verificación posterior en MinIO

Dicho de forma sencilla:

- `03` publica
- `04` descubre
- `05` negocia
- `06` transfiere hacia almacenamiento

## Mapa rápido

| Colección | Qué valida | Por qué existe | Cómo probarla en Postman | Para qué sirve dentro del flujo |
| --- | --- | --- | --- | --- |
| `01_environment_health.json` | login y checks básicos de APIs y DSP | detectar rápido si el entorno responde antes del flujo E2E | importar la colección y ejecutar los requests de login y health con un environment válido | evitar diagnosticar como fallo de negocio un problema de infraestructura o autenticación |
| `02_connector_management_api.json` | CRUD técnico de assets, policies y contract definitions | comprobar que el Management API del proveedor crea, lista y elimina recursos correctamente | ejecutar la colección completa con el JWT del proveedor | validar la base técnica del conector antes del flujo funcional |
| `03_provider_setup.json` | preparación del recurso ofertable | sin asset, policy y contract definition no hay nada que negociar | ejecutar provider login y después las requests de creación/listado | dejar un recurso publicable en el proveedor |
| `04_consumer_catalog.json` | descubrimiento del recurso por el consumidor | comprobar que lo publicado por el proveedor aparece en catálogo | ejecutar consumer login y la request de catálogo federado | demostrar visibilidad entre conectores |
| `05_consumer_negotiation.json` | negociación del contrato | sin acuerdo contractual no se puede transferir | lanzar negociación y consultar estado | obtener `agreementId` |
| `06_consumer_transfer.json` | transferencia INESData hacia almacenamiento destino | comprobar que el consumidor inicia la transferencia real que usa el portal de INESData y que el runtime resuelve el bucket destino correcto | lanzar la transferencia custom, consultar estado y validar el `dataDestination` del proceso | obtener `transferId` y comprobar que el proceso apunta al bucket del consumidor |

Cuando estas colecciones se ejecutan desde el framework con `experiment_dir`, existe además un post-check técnico adicional:

- se captura una instantánea previa del bucket del consumidor
- después de `06_consumer_transfer.json` se consulta MinIO otra vez
- el framework compara si han aparecido objetos nuevos o modificados tras el inicio de la transferencia
- el resultado se guarda en `experiments/<id>/storage_checks/<provider>__<consumer>.json`

Ese post-check no sustituye a la colección `06`, pero añade una evidencia más fuerte de que el dato ha aterrizado realmente en almacenamiento.

## Qué significa que una ejecución haya pasado completamente

Cuando una ejecución completa de `validation/core` termina correctamente, la interpretación práctica debería ser esta:

- `01` y `02` han confirmado que autenticación, health checks y CRUD técnico básico del proveedor responden como se esperaba
- `03` ha dejado un asset publicable junto con su policy y su contract definition
- `04` ha demostrado que el consumidor puede descubrir la oferta del proveedor; idealmente con `200` en catálogo federado, aunque algunas respuestas auxiliares del entorno siguen siendo toleradas solo en los checks diagnósticos indicados más abajo
- `05` ha llegado a un punto útil de negociación, es decir, el framework ha obtenido `e2e_agreement_id`
- `06` ha iniciado la transferencia real de INESData, ha resuelto un `dataDestination` correcto para el bucket del consumidor y, si además el post-check está activo, ha observado evidencia nueva en MinIO

Conviene recordar dos matices importantes:

- en `05`, estados como `AGREED` o `VERIFIED` pueden aparecer como estados intermedios reconocidos antes de que el acuerdo quede plenamente materializado
- en `06`, el estado `STARTED` ya puede ser suficiente para validar el destino resuelto del flujo `AmazonS3-PUSH`, aunque la evidencia más fuerte sigue siendo que el post-check detecte objetos nuevos o modificados en el bucket del consumidor

## Cómo reproducirlo manualmente en Postman

## Paso 1. Importar las colecciones

Importa en Postman las seis colecciones de `validation/core/collections`.

No hace falta copiar a mano los scripts de tests del repositorio: las colecciones ya los llevan incorporados para uso con Postman y Newman. Este documento explica su significado y cómo interpretarlos.

## Paso 2. Crear el environment

Puedes partir de un environment como este, ajustando credenciales y dominios a tu despliegue real:

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
  "providerProtocolAddress": "http://conn-citycouncil-pionera.provider.svc.cluster.local:19194/protocol",
  "consumerProtocolAddress": "http://conn-company-pionera.consumer.svc.cluster.local:19194/protocol"
}
```

## Paso 3. Obtener las credenciales

En el entorno local actual, las contraseñas locales se generan en:

- `deployers/inesdata/deployments/DEV/pionera/credentials-connector-conn-citycouncil-pionera.json`
- `deployers/inesdata/deployments/DEV/pionera/credentials-connector-conn-company-pionera.json`

El campo que interesa es:

- `connector_user.passwd`

## Paso 4. Ejecutar en orden

Para reproducir el flujo principal en Postman, el orden recomendado es:

1. `03_provider_setup.json`
2. `04_consumer_catalog.json`
3. `05_consumer_negotiation.json`
4. `06_consumer_transfer.json`

Y para checks técnicos complementarios:

1. `01_environment_health.json`
2. `02_connector_management_api.json`

## Paso 5. Reconstruir manualmente las colecciones en Postman

Si lo que necesitas es una **guía operativa exacta** con los scripts embebidos request por request y una versión compacta del flujo para reducir tiempo de ejecución, usa como referencia principal:

- [validation/core/collections/postman/README.md](../validation/core/collections/postman/README.md)
- [validation/core/collections/postman/01_environment_health.json](../validation/core/collections/postman/01_environment_health.json)
- [validation/core/collections/postman/02_connector_management_api.json](../validation/core/collections/postman/02_connector_management_api.json)
- [validation/core/collections/postman/03_e2e_compact.json](../validation/core/collections/postman/03_e2e_compact.json)
- [validation/core/collections/postman/00_environment.json](../validation/core/collections/postman/00_environment.json)

La forma más rápida de replicar el framework es importar directamente los JSON de [validation/core/collections](../validation/core/collections/). Aun así, para reconstrucción manual o revisión detallada, puede ser útil crear las colecciones a mano y entender qué contiene cada una.

La propuesta mínima y fiel al framework actual es esta:

1. crear una colección por bloque funcional:
   - `01 Environment Health`
   - `02 Connector Management CRUD`
   - `03 Provider Setup`
   - `04 Consumer Catalog Discovery`
   - `05 Consumer Contract Negotiation`
   - `06 Consumer Transfer`
2. crear dentro de cada colección las requests exactamente en el orden que usa el framework
3. usar el environment base indicado arriba
4. guardar las variables derivadas en el environment o en collection variables
5. si quieres comportamiento muy parecido a Newman, ejecutar la colección con un pequeño delay entre requests

### Estructura mínima de la colección `01 Environment Health`

Esta colección funciona como smoke operativo del entorno. Su objetivo no es crear estado de negocio, sino comprobar que autenticación, Management API y DSP están accesibles antes de entrar en el flujo funcional principal.

Requests que debes crear:

1. `Provider Login`
2. `Consumer Login`
3. `Provider Management API Health`
4. `Consumer Management API Health`
5. `Provider DSP Catalog Endpoint`
6. `Consumer DSP Catalog Endpoint`

Requests de login:

- usan exactamente el mismo endpoint y body que en `03` y `04`
- solo guardan `provider_jwt` y `consumer_jwt`
- no generan ids `e2e_*` ni `crud_*`

Body de referencia para `Provider Management API Health` y `Consumer Management API Health`:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "offset": 0,
  "limit": 1,
  "filterExpression": []
}
```

Estas dos requests llaman a:

- `POST /management/v3/assets/request` del proveedor
- `POST /management/v3/assets/request` del consumidor

La idea no es todavía validar un asset concreto, sino confirmar que:

- el token sirve
- el endpoint responde
- el conector devuelve una respuesta JSON coherente

Body de referencia para `Provider DSP Catalog Endpoint` y `Consumer DSP Catalog Endpoint`:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "protocol": "dataspace-protocol-http"
}
```

Estas dos requests llaman a:

- `POST /protocol/catalog/request` del proveedor
- `POST /protocol/catalog/request` del consumidor

Qué conviene observar manualmente:

- que ambos logins devuelven `access_token`
- que los endpoints de Management API responden sin errores del conector
- que los endpoints DSP son accesibles; en una ejecución sana suelen responder `200`, aunque la validación funcional fuerte del catálogo se hace realmente en `04`

### Estructura mínima de la colección `02 Connector Management CRUD`

Esta colección reproduce el CRUD técnico del proveedor sobre los tres tipos de recursos que usa EDC en el flujo principal:

- asset
- policy
- contract definition

Requests que debes crear:

1. `Provider Login`
2. `Create CRUD Asset`
3. `List CRUD Assets`
4. `Create CRUD Policy`
5. `List CRUD Policies`
6. `Create CRUD Contract Definition`
7. `List CRUD Contract Definitions`
8. `Delete CRUD Contract Definition`
9. `Verify CRUD Contract Definition Deleted`
10. `Delete CRUD Policy`
11. `Verify CRUD Policy Deleted`
12. `Delete CRUD Asset`
13. `Verify CRUD Asset Deleted`

Script mínimo recomendado en `Provider Login` para replicar la generación de ids CRUD del framework:

```javascript
const body = pm.response.json();

pm.environment.set("provider_jwt", body.access_token);

const suffix = String(Date.now());
pm.environment.set("crud_suffix", suffix);
pm.environment.set("crud_asset_id", `asset-crud-${suffix}`);
pm.environment.set("crud_policy_id", `policy-crud-${suffix}`);
pm.environment.set("crud_contract_definition_id", `contract-crud-${suffix}`);
```

Body de referencia para `Create CRUD Asset`:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "dct": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#"
  },
  "@id": "{{crud_asset_id}}",
  "@type": "Asset",
  "properties": {
    "name": "CRUD Test Asset {{crud_suffix}}",
    "version": "1.0.0",
    "shortDescription": "CRUD validation asset",
    "assetType": "dataset",
    "dct:description": "CRUD validation asset",
    "dcat:keyword": ["validation", "crud"]
  },
  "dataAddress": {
    "type": "HttpData",
    "baseUrl": "https://jsonplaceholder.typicode.com/todos",
    "name": "todos"
  }
}
```

Body de referencia para `Create CRUD Policy`:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "odrl": "http://www.w3.org/ns/odrl/2/"
  },
  "@id": "{{crud_policy_id}}",
  "policy": {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "Set",
    "permission": [],
    "prohibition": [],
    "obligation": []
  }
}
```

Body de referencia para `Create CRUD Contract Definition`:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "@id": "{{crud_contract_definition_id}}",
  "accessPolicyId": "{{crud_policy_id}}",
  "contractPolicyId": "{{crud_policy_id}}",
  "assetsSelector": [
    {
      "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
      "operator": "=",
      "operandRight": "{{crud_asset_id}}"
    }
  ]
}
```

Body de referencia para todas las requests de listado y de verificación de borrado:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "offset": 0,
  "limit": 50,
  "filterExpression": []
}
```

Requests `DELETE`:

- `DELETE /management/v3/contractdefinitions/{{crud_contract_definition_id}}`
- `DELETE /management/v3/policydefinitions/{{crud_policy_id}}`
- `DELETE /management/v3/assets/{{crud_asset_id}}`

Qué conviene comprobar manualmente:

- que cada create devuelve `200` o `201` con `@id`
- que cada id aparece en el listado inmediatamente después de crearlo
- que cada delete devuelve `200` o `204`
- que el recurso ya no aparece en el listado posterior

### Estructura mínima de la colección `03 Provider Setup`

Requests que debes crear:

1. `Provider Login`
2. `Create E2E Asset`
3. `List E2E Assets`
4. `Create E2E Policy`
5. `List E2E Policies`
6. `Create E2E Contract Definition`
7. `List E2E Contract Definitions`

Script mínimo recomendado en `Provider Login` para replicar la generación de ids del framework:

```javascript
const body = pm.response.json();

pm.environment.set("provider_jwt", body.access_token);

const suffix = String(Date.now());
pm.environment.set("e2e_suffix", suffix);
pm.environment.set("e2e_asset_id", `asset-e2e-${suffix}`);
pm.environment.set("e2e_policy_id", `policy-e2e-${suffix}`);
pm.environment.set("e2e_contract_definition_id", `contract-e2e-${suffix}`);
```

Body de referencia para `Create E2E Asset`:

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

Body de referencia para `Create E2E Policy`:

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

Body de referencia para `Create E2E Contract Definition`:

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

### Estructura mínima de la colección `04 Consumer Catalog Discovery`

Requests que debes crear:

1. `Provider Login`
2. `Consumer Login`
3. `Request Federated Catalog (Management API)`
4. `Direct DSP Catalog Request`

Body de referencia para `Request Federated Catalog (Management API)`:

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

Script mínimo recomendado en `Request Federated Catalog (Management API)` para guardar las variables que luego usa `05`:

```javascript
const body = pm.response.json();
const catalog = Array.isArray(body) ? body[0] : body;
let datasets = catalog["dcat:dataset"];

if (!Array.isArray(datasets)) {
  datasets = [datasets];
}

const expectedAssetId = pm.environment.get("e2e_asset_id");
const dataset = datasets.find(item => item && JSON.stringify(item).includes(expectedAssetId)) || datasets[0];
let policy = dataset["odrl:hasPolicy"];

if (Array.isArray(policy)) {
  policy = policy[0];
}

pm.environment.set("providerParticipantId", catalog["dspace:participantId"] || pm.environment.get("provider"));
pm.environment.set("e2e_offer_policy_id", policy["@id"]);
pm.environment.set("e2e_catalog_asset_id", dataset["@id"] || expectedAssetId);
```

### Estructura mínima de la colección `05 Consumer Contract Negotiation`

Requests que debes crear:

1. `Consumer Login`
2. `Start Contract Negotiation`
3. `Check Negotiation Status`

Body de referencia para `Start Contract Negotiation`:

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

Body de referencia para `Check Negotiation Status`:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "offset": 0,
  "limit": 100
}
```

Script mínimo recomendado en `Check Negotiation Status` para replicar el guardado del acuerdo sin caer en negociaciones antiguas:

```javascript
const body = pm.response.json();
const negotiationId = pm.environment.get("e2e_negotiation_id");
let negotiation = body;

if (Array.isArray(body)) {
  negotiation = body.find(item => item && (item["@id"] === negotiationId || item.id === negotiationId));
}

if (negotiation && negotiation.contractAgreementId) {
  pm.environment.set("e2e_agreement_id", negotiation.contractAgreementId);
}
```

### Estructura mínima de la colección `06 Consumer Transfer`

Requests que debes crear:

1. `Consumer Login`
2. `Start Transfer Process`
3. `Check Transfer Status`
4. `Resolve Current Transfer Destination`

Body de referencia para `Start Transfer Process`:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "@type": "TransferRequest",
  "assetId": "{{e2e_asset_id}}",
  "contractId": "{{e2e_agreement_id}}",
  "counterPartyAddress": "{{providerProtocolAddress}}",
  "protocol": "dataspace-protocol-http",
  "transferType": "AmazonS3-PUSH",
  "dataDestination": {
    "type": "InesDataStore"
  }
}
```

Pre-request script recomendado en `Start Transfer Process`:

```javascript
if (!pm.environment.get("e2e_agreement_id")) {
  pm.execution.skipRequest();
}
```

Body de referencia para `Check Transfer Status` y `Resolve Current Transfer Destination`:

```json
{
  "@context": {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
  },
  "offset": 0,
  "limit": 100
}
```

Qué debes comprobar en `Resolve Current Transfer Destination`:

- que el proceso encontrado corresponde a `e2e_transfer_id`
- que `transferType` es `AmazonS3-PUSH`
- que `dataDestination.type` es `AmazonS3`
- que `dataDestination.bucketName` coincide con el bucket esperado del consumidor

## Paso 6. Qué parte debes crear a mano y cuál puedes reutilizar del repositorio

Si se quiere reconstruir el flujo manualmente o revisarlo con detalle, la recomendación correcta es esta:

- si quieres exactitud 1:1 con el framework, importa las colecciones de [validation/core/collections](../validation/core/collections/)
- si quieres entenderlas o reconstruirlas manualmente, sigue las plantillas de requests y scripts de este documento
- si quieres revisar la semántica exacta de cada validación, consulta:
  - [common_tests.js](../validation/shared/api/common_tests.js)
  - [provider_tests.js](../validation/core/tests/provider_tests.js)
  - [catalog_tests.js](../validation/core/tests/catalog_tests.js)
  - [negotiation_tests.js](../validation/core/tests/negotiation_tests.js)
  - [transfer_tests.js](../validation/core/tests/transfer_tests.js)

## Cómo interpretar los resultados

Este punto es importante porque aclara por qué algunas pruebas pueden aparecer en verde aunque no todos los requests devuelvan un `200`.

## Resultado funcional, resultado tolerado y paso condicional

En el core actual hay tres tipos de resultado:

- `éxito funcional`
  - el request ha hecho exactamente lo que se esperaba para avanzar en el flujo
  - ejemplo: crear un asset, obtener un `agreementId`, resolver un `dataDestination` correcto para la transferencia

- `respuesta tolerada`
  - el request no ha devuelto el resultado ideal, pero el framework lo acepta como comportamiento técnico conocido del entorno
  - ejemplo: algunas comprobaciones auxiliares de catálogo que aceptan `400`, `401` o `502`

- `paso condicional`
  - el request solo puede validarse si existe una precondición previa
  - ejemplo: `Start Transfer Process` solo puede ejecutarse de forma útil si antes la negociación ya dejó un `agreementId`

Una prueba en verde no siempre significa que se ha alcanzado el mejor resultado funcional posible. A veces significa que:

- el request ha devuelto una respuesta aceptable para ese entorno
- el paso no podía ejecutarse todavía y por tanto se marca como no bloqueante

## Definición de estados HTTP usados en el core

| HTTP status | Significado en esta validación |
| --- | --- |
| `200 OK` | respuesta correcta normal para login, listados, health checks, polling de negociación y polling de transferencia |
| `201 Created` | respuesta válida de creación de recurso; el framework la acepta junto con `200` cuando una operación crea algo nuevo |
| `204 No Content` | respuesta válida de borrado sin cuerpo; el framework la acepta junto con `200` en deletes |
| `400 Bad Request` | en general sería error, pero en el core actual se tolera en algunas comprobaciones auxiliares de catálogo porque esas requests se usan también para diagnosticar compatibilidad del entorno |
| `401 Unauthorized` | se tolera en la request directa al DSP catalog endpoint cuando el endpoint exige autenticación; eso no se interpreta como éxito funcional del catálogo, sino como comportamiento técnico conocido |
| `502 Bad Gateway` | se tolera en la request federada de catálogo como respuesta del entorno o de routing; se considera aceptable para diagnóstico, no un éxito funcional del intercambio |

## Casos concretos donde un `400`, `401` o `502` no rompe la colección

Esto ocurre hoy en [catalog_tests.js](../validation/core/tests/catalog_tests.js):

- `Direct DSP Catalog Request`
  - acepta `200`, `400` o `401`
  - el objetivo de esta request es comprobar exposición y comportamiento técnico del endpoint, no demostrar por sí sola que el catálogo federado funciona de extremo a extremo

- `Request Federated Catalog`
  - si el status no es `200`, la validación tolera `400` o `502`
  - esto se interpreta como respuesta conocida del entorno del conector, no como éxito funcional pleno del catálogo

Conclusión práctica:

- `400`, `401` y `502` no se aceptan de forma general
- solo están tolerados en requests auxiliares concretas
- no deben usarse para afirmar que el flujo E2E principal se ha completado correctamente

## Definición de estados de negociación

En [negotiation_tests.js](../validation/core/tests/negotiation_tests.js) el framework considera válidos estos estados porque son estados conocidos del runtime:

- `INITIAL`
- `REQUESTED`
- `REQUESTING`
- `VERIFYING`
- `IN_PROGRESS`
- `AGREED`
- `VERIFIED`
- `FINALIZED`
- `TERMINATED`

Cómo interpretarlos:

| Estado | Significado práctico |
| --- | --- |
| `INITIAL` | la negociación existe, pero apenas ha comenzado |
| `REQUESTED` | la negociación ha sido solicitada |
| `REQUESTING` | el runtime está enviando o procesando la solicitud |
| `VERIFYING` | el runtime está verificando la negociación antes de materializar el acuerdo |
| `IN_PROGRESS` | la negociación sigue abierta y todavía no ha terminado |
| `AGREED` | el runtime ya ha alcanzado acuerdo lógico, aunque el `contractAgreementId` todavía puede no haberse reflejado en la respuesta actual |
| `VERIFIED` | el runtime ha verificado la negociación y puede estar a punto de materializar el acuerdo |
| `FINALIZED` | la negociación ha terminado correctamente y debería existir `contractAgreementId` |
| `TERMINATED` | la negociación ha terminado, pero no necesariamente con éxito |

Punto importante:

- que un estado sea `válido` significa que el framework lo reconoce como estado posible
- no significa que todos esos estados representen éxito funcional
- para poder avanzar realmente a transferencia, lo relevante es que aparezca `e2e_agreement_id`

## Definición de estados de transferencia

En [transfer_tests.js](../validation/core/tests/transfer_tests.js) el framework considera válidos estos estados:

- `INITIAL`
- `STARTED`
- `PROVISIONING`
- `PROVISIONED`
- `REQUESTED`
- `REQUESTED_ACK`
- `IN_PROGRESS`
- `STREAMING`
- `COMPLETED`
- `DEPROVISIONING`
- `DEPROVISIONING_REQ`
- `DEPROVISIONED`
- `ENDED`
- `FINALIZED`
- `TERMINATED`

Cómo interpretarlos:

| Estado | Significado práctico |
| --- | --- |
| `INITIAL` | la transferencia se ha creado |
| `STARTED` | en el flujo real de INESData, la transferencia ya ha arrancado y este estado puede ser suficiente para validar el destino resuelto del proceso |
| `PROVISIONING` | el runtime está preparando recursos |
| `PROVISIONED` | los recursos necesarios ya están preparados |
| `REQUESTED` | la transferencia ha sido solicitada |
| `REQUESTED_ACK` | el request ha sido reconocido |
| `IN_PROGRESS` | la transferencia está en marcha |
| `STREAMING` | el dato se está sirviendo o moviendo |
| `COMPLETED` | la transferencia ha terminado correctamente |
| `DEPROVISIONING` | se están liberando recursos |
| `DEPROVISIONING_REQ` | se ha solicitado esa liberación |
| `DEPROVISIONED` | los recursos ya se han liberado |
| `ENDED` | el proceso ha finalizado |
| `FINALIZED` | compatibilidad con runtimes o adaptadores que usan ese nombre final |
| `TERMINATED` | el proceso ha terminado, pero no necesariamente con éxito |

Punto importante:

- un estado `válido` de transferencia significa que el framework entiende la respuesta
- el éxito funcional fuerte de una transferencia se acerca más a `COMPLETED` o `FINALIZED`
- `TERMINATED` sigue siendo un estado reconocido, pero no debe interpretarse como éxito de negocio

## El flujo principal explicado paso a paso

## Fase 1. Preparar el proveedor

En esta fase el proveedor autentica su usuario y crea los tres recursos mínimos para publicar un dato:

- asset
- policy
- contract definition

Sin estos tres elementos, el consumidor no tendrá nada útil que descubrir o negociar.

### Requests de la fase

| Request | Qué hace | Inputs principales | Outputs principales | Criterio esperado |
| --- | --- | --- | --- | --- |
| `Provider Login` | obtiene el token del proveedor y genera ids únicos E2E | `keycloakUrl`, `dataspace`, `keycloakClientId`, `provider_user`, `provider_password` | `provider_jwt`, `e2e_suffix`, `e2e_asset_id`, `e2e_policy_id`, `e2e_contract_definition_id` | `200` y `access_token` presente |
| `Create E2E Asset` | crea el asset que luego se publicará | `provider`, `dsDomain`, `provider_jwt`, `e2e_asset_id`, `e2e_suffix` | `e2e_asset_id` | `200` y respuesta con `@id` |
| `List E2E Assets` | consulta exacta del asset recien creado por `@id` | `provider`, `dsDomain`, `provider_jwt`, `e2e_asset_id` | ninguna | `200` y el `asset_id` aparece en la respuesta |
| `Create E2E Policy` | crea la policy que regulará el acceso | `provider`, `dsDomain`, `provider_jwt`, `e2e_policy_id` | `e2e_policy_id` | `200` y respuesta con `@id` |
| `List E2E Policies` | comprueba que la policy existe | `provider`, `dsDomain`, `provider_jwt`, `e2e_policy_id` | ninguna | `200` y la policy aparece en el listado |
| `Create E2E Contract Definition` | une asset y policy en una oferta negociable | `provider`, `dsDomain`, `provider_jwt`, `e2e_contract_definition_id`, `e2e_policy_id`, `e2e_asset_id` | `e2e_contract_definition_id` | `200` y respuesta con `@id` |
| `List E2E Contract Definitions` | comprueba que la definición contractual existe | `provider`, `dsDomain`, `provider_jwt`, `e2e_contract_definition_id` | ninguna | `200` y la contract definition aparece en el listado |

## Fase 2. Preparar el consumidor y descubrir catálogo

En esta fase el consumidor inicia sesión y comprueba que el recurso publicado por el proveedor ya es visible desde su lado.

La idea didáctica aquí es importante:

- publicar en el proveedor no basta
- el consumidor tiene que poder descubrir la oferta
- por eso esta fase marca el paso de “dato creado” a “dato visible desde otro participante”

### Requests de la fase

| Request | Qué hace | Inputs principales | Outputs principales | Criterio esperado |
| --- | --- | --- | --- | --- |
| `Consumer Login` | obtiene el token del consumidor | `keycloakUrl`, `dataspace`, `keycloakClientId`, `consumer_user`, `consumer_password` | `consumer_jwt` | `200` y `access_token` presente |
| `Request Federated Catalog (Management API)` | pide al consumidor que consulte el catálogo del proveedor | `consumer`, `dsDomain`, `consumer_jwt`, `providerProtocolAddress`, `provider`, `e2e_asset_id` | `providerParticipantId`, `e2e_offer_policy_id`, `e2e_catalog_asset_id` | idealmente `200`; `400` o `502` se consideran respuestas toleradas del entorno en esta request auxiliar |
| `Direct DSP Catalog Request` | comprueba el endpoint DSP del proveedor de forma directa | `provider`, `dsDomain`, `provider_jwt`, `providerProtocolAddress` | ninguna | `200` ideal; `400` o `401` pueden ser respuestas toleradas del entorno |

## Fase 3. Negociar el contrato

Una vez descubierto el recurso, el consumidor solicita formalmente un contrato basado en la policy ofertada.

Esto valida que el flujo no se queda solo en “veo algo en catálogo”, sino que puede producir un acuerdo reutilizable para transferencia.

### Requests de la fase

| Request | Qué hace | Inputs principales | Outputs principales | Criterio esperado |
| --- | --- | --- | --- | --- |
| `Start Contract Negotiation` | arranca la negociación contractual | `consumer`, `dsDomain`, `consumer_jwt`, `providerProtocolAddress`, `e2e_offer_policy_id`, `providerParticipantId`, `e2e_catalog_asset_id` | `e2e_negotiation_id` | respuesta de creación con `@id` |
| `Check Negotiation Status` | consulta el estado de la negociación | `consumer`, `dsDomain`, `consumer_jwt`, `e2e_negotiation_id` | `e2e_agreement_id` si ya existe acuerdo | `200` y estado reconocido; el framework reintenta varias veces antes de fallar y el éxito fuerte se da cuando aparece `contractAgreementId` |

### Importante sobre el polling de negociación

El core actual ya no hace un único vistazo al listado de negociaciones. Ahora:

- consulta hasta `100` entradas para reducir el riesgo de que la negociación actual quede fuera de página
- reintenta la comprobación varias veces antes de declarar fallo
- en ejecución con Newman introduce una pequeña espera entre requests para dar tiempo al runtime a cambiar de estado

Si reproduces esta fase manualmente en Postman y quieres un comportamiento parecido, conviene usar el runner de colección con un pequeño delay entre requests.

## Fase 4. Iniciar la transferencia real de INESData y validar su destino

Esta fase suele generar confusión, así que conviene explicarla con precisión.

Lo que valida el core actual no es “descargar un fichero desde una URL humana”, sino el camino que usa realmente el portal del conector INESData:

1. iniciar la transferencia mediante el endpoint custom `v3/inesdatatransferprocesses`
2. comprobar que ese proceso existe y tiene un estado reconocible
3. validar que el runtime ha resuelto un `dataDestination` de tipo `AmazonS3`
4. validar que el bucket destino corresponde al bucket del consumidor

Esto es importante porque el flujo real de la interfaz de INESData:

- no usa aquí la ruta genérica `HttpData-PULL` como criterio principal del framework
- no se apoya en un `Download Data` humano como evidencia principal
- delega el destino real en el endpoint custom de INESData, que resuelve internamente el bucket S3/MinIO del consumidor

Por tanto, en el core actual el éxito funcional de `06` ya no se expresa como “he obtenido un EDR descargable”, sino como “he iniciado la transferencia correcta y el proceso apunta al almacenamiento correcto”.

### Importante sobre la descarga

En este entorno:

- no debe explicarse como si siempre se generara un link de descarga listo para usar
- la descarga directa no es el criterio principal del core API de INESData
- el camino funcional real es `AmazonS3-PUSH` hacia el bucket del consumidor

Por tanto:

- `Start Transfer Process` usa el endpoint custom de INESData
- `Check Transfer Status` y `Resolve Current Transfer Destination` se reintentan varias veces antes de fallar
- la validación fuerte aquí es que el destino resuelto del proceso sea el bucket esperado del consumidor
- cuando la ejecución se lanza desde el framework, existe además una comprobación técnica posterior sobre MinIO para detectar objetos nuevos o actualizados en ese bucket

### Requests de la fase

| Request | Qué hace | Inputs principales | Outputs principales | Criterio esperado |
| --- | --- | --- | --- | --- |
| `Start Transfer Process` | inicia el proceso real de transferencia INESData asociado al acuerdo | `consumer`, `dsDomain`, `consumer_jwt`, `providerProtocolAddress`, `e2e_agreement_id`, `e2e_asset_id` | `e2e_transfer_id` | respuesta de creación con `@id`; el request usa `AmazonS3-PUSH` y `dataDestination.type=InesDataStore` |
| `Check Transfer Status` | consulta el estado del proceso de transferencia | `consumer`, `dsDomain`, `consumer_jwt`, `e2e_transfer_id` | ninguna | `200`, estado reconocido y reintentos acotados; `STARTED` ya permite pasar a validar el destino |
| `Resolve Current Transfer Destination` | localiza el proceso actual y valida el destino resuelto por INESData | `consumer`, `dsDomain`, `consumer_jwt`, `e2e_transfer_id`, `e2e_expected_consumer_bucket` | `e2e_transfer_destination_bucket` | `200`; `transferType=AmazonS3-PUSH`, `dataDestination.type=AmazonS3` y `bucketName` igual al bucket esperado del consumidor |

Fuera de Newman, el framework puede añadir un cuarto paso técnico adicional:

| Paso técnico adicional | Qué hace | Inputs principales | Outputs principales | Criterio esperado |
| --- | --- | --- | --- | --- |
| `storage_checks/<provider>__<consumer>.json` | compara el bucket del consumidor antes y después de la transferencia | credenciales MinIO del consumidor, bucket esperado, timestamp del inicio de transferencia | evidencia de objetos nuevos o actualizados | al menos un objeto nuevo o modificado tras el inicio de la transferencia |

### Importante sobre el polling de transferencia y del destino resuelto

El comportamiento actual del core es este:

- consulta hasta `100` entradas en los listados de transferencia para reducir falsos pendientes por paginación
- reintenta varias veces antes de considerar que la transferencia o el proceso actual no han aparecido
- no espera necesariamente a `COMPLETED`: si el estado llega a `STARTED`, ya puede validar el destino resuelto por INESData
- si el proceso no resuelve un `dataDestination` de tipo `AmazonS3` con el bucket esperado, el flujo falla explícitamente
- si el proceso resuelve bien el destino pero no aparece ningún objeto nuevo o actualizado en el bucket del consumidor, el post-check de almacenamiento falla y deja esa evidencia separada en `storage_checks/`

Esto hace que los artefactos sean más honestos: el resultado ya no depende de una descarga genérica que no corresponde al flujo principal de INESData, sino de la validación del destino real de transferencia.

## Checks auxiliares y CRUD técnico

Estas colecciones no representan por sí solas el intercambio E2E principal, pero son útiles para diagnosticar el entorno y justificar que la base técnica del conector funciona.

## `01_environment_health.json`

Qué valida:

- autenticación básica del proveedor y del consumidor
- salud de Management API
- salud o exposición básica de endpoints DSP

Por qué existe:

- permite distinguir rápido si el problema es de autenticación, routing o disponibilidad, antes de entrar en el flujo de negocio
- funciona como smoke operativo del entorno; la validación funcional fuerte del intercambio empieza realmente en `03`, `04`, `05` y `06`

Requests incluidas:

| Request | Qué valida | Inputs | Outputs | Resultado esperado |
| --- | --- | --- | --- | --- |
| `Provider Login` | login del proveedor | `keycloakUrl`, `dataspace`, `keycloakClientId`, `provider_user`, `provider_password` | `provider_jwt` | `200` y token |
| `Consumer Login` | login del consumidor | `keycloakUrl`, `dataspace`, `keycloakClientId`, `consumer_user`, `consumer_password` | `consumer_jwt` | `200` y token |
| `Provider Management API Health` | salud básica del Management API del proveedor | `provider`, `dsDomain`, `provider_jwt` | ninguna | `200` |
| `Consumer Management API Health` | salud básica del Management API del consumidor | `consumer`, `dsDomain`, `consumer_jwt` | ninguna | `200` |
| `Provider DSP Catalog Endpoint` | exposición básica del catálogo DSP del proveedor | `provider`, `dsDomain`, `provider_jwt` | ninguna | `200` |
| `Consumer DSP Catalog Endpoint` | exposición básica del catálogo DSP del consumidor | `consumer`, `dsDomain`, `consumer_jwt` | ninguna | `200` |

## `02_connector_management_api.json`

Qué valida:

- CRUD técnico completo de asset, policy y contract definition sobre el proveedor

Por qué existe:

- antes de validar el flujo de intercambio, conviene saber si el Management API crea, lista y borra recursos correctamente

Requests incluidas:

| Request | Qué valida | Inputs | Outputs | Resultado esperado |
| --- | --- | --- | --- | --- |
| `Provider Login` | obtiene token y genera ids CRUD | `keycloakUrl`, `dataspace`, `keycloakClientId`, `provider_user`, `provider_password` | `provider_jwt`, `crud_suffix`, `crud_asset_id`, `crud_policy_id`, `crud_contract_definition_id` | `200` y token |
| `Create CRUD Asset` | creación de asset CRUD | `provider`, `dsDomain`, `provider_jwt`, `crud_asset_id`, `crud_suffix` | `crud_asset_id` | `200` y `@id` |
| `List CRUD Assets` | consulta exacta del asset CRUD por `@id` | `provider`, `dsDomain`, `provider_jwt`, `crud_asset_id` | ninguna | `200` y el `asset_id` aparece en la respuesta |
| `Create CRUD Policy` | creación de policy CRUD | `provider`, `dsDomain`, `provider_jwt`, `crud_policy_id` | `crud_policy_id` | `200` y `@id` |
| `List CRUD Policies` | verificación de listado | `provider`, `dsDomain`, `provider_jwt`, `crud_policy_id` | ninguna | `200` y policy visible |
| `Create CRUD Contract Definition` | creación de contract definition CRUD | `provider`, `dsDomain`, `provider_jwt`, `crud_asset_id`, `crud_policy_id`, `crud_contract_definition_id` | `crud_contract_definition_id` | `200` y `@id` |
| `List CRUD Contract Definitions` | verificación de listado | `provider`, `dsDomain`, `provider_jwt`, `crud_contract_definition_id` | ninguna | `200` y contract definition visible |
| `Delete CRUD Contract Definition` | borrado | `provider`, `dsDomain`, `provider_jwt`, `crud_contract_definition_id` | ninguna | `200` o `204` |
| `Verify CRUD Contract Definition Deleted` | comprobación de borrado | `provider`, `dsDomain`, `provider_jwt`, `crud_contract_definition_id` | ninguna | `200` y recurso ya ausente |
| `Delete CRUD Policy` | borrado | `provider`, `dsDomain`, `provider_jwt`, `crud_policy_id` | ninguna | `200` o `204` |
| `Verify CRUD Policy Deleted` | comprobación de borrado | `provider`, `dsDomain`, `provider_jwt`, `crud_policy_id` | ninguna | `200` y recurso ya ausente |
| `Delete CRUD Asset` | borrado | `provider`, `dsDomain`, `provider_jwt`, `crud_asset_id` | ninguna | `200` o `204` |
| `Verify CRUD Asset Deleted` | comprobación de borrado mediante consulta exacta por `@id` | `provider`, `dsDomain`, `provider_jwt`, `crud_asset_id` | ninguna | `200` y recurso ya ausente |

## Resumen ejecutivo de cobertura actual del core

El core API del framework cubre estas capacidades:

- autenticación básica de proveedor y consumidor
- checks de salud de Management API y DSP
- CRUD técnico del proveedor
- publicación de un recurso negociable
- descubrimiento del recurso desde el consumidor
- negociación contractual
- inicio de transferencia
- consulta de estado de transferencia
- validación del destino resuelto por INESData

## Qué NO debe afirmarse

Para evitar malentendidos, este documento no debe usarse para afirmar que:

- cualquier `400` es correcto
- cualquier estado “válido” de negociación o transferencia equivale a éxito funcional
- la descarga directa forma parte garantizada del flujo core en todos los entornos
- un `TERMINATED` equivale a transferencia exitosa

Lo correcto es decir:

- el framework distingue entre éxito funcional, respuesta tolerada y paso condicional
- el flujo principal se apoya en `03`, `04`, `05` y `06`
- `01` y `02` sirven como soporte diagnóstico y técnico
- la validación principal de `06` en INESData es el destino resuelto de la transferencia, no un `Download Data` genérico

Para profundizar en la lógica exacta de cada validación, las fuentes de verdad son:

- [common_tests.js](../validation/shared/api/common_tests.js)
- [management_tests.js](../validation/core/tests/management_tests.js)
- [provider_tests.js](../validation/core/tests/provider_tests.js)
- [catalog_tests.js](../validation/core/tests/catalog_tests.js)
- [negotiation_tests.js](../validation/core/tests/negotiation_tests.js)
- [transfer_tests.js](../validation/core/tests/transfer_tests.js)
