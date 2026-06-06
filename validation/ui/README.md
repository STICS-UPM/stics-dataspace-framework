# Validación UI con Playwright

Esta carpeta contiene la capa UI de validación con Playwright.

Actualmente existen dos modos:

- `inesdata`: suite estable heredada del portal INESData
- `edc`: suite del dashboard EDC con autenticación `oidc-bff`, flujos core y
  validaciones de integración de componentes

La suite `inesdata` sigue siendo la referencia principal y actualmente cubre:

- `01 login readiness`
- `03 provider setup` con creación de asset y subida de fichero
- `03b provider policy creation`
- `03c provider contract definition creation`
- `04 consumer catalog` con listado y detalle
- `05 consumer negotiation`
- `06 consumer transfer`

## Estructura

- `adapters/inesdata/specs/`: specs principales de la UI INESData.
- `adapters/inesdata/components/`: page objects propios de la UI INESData.
- `adapters/edc/specs/`: specs principales del dashboard EDC.
- `adapters/edc/components/`: page objects propios del dashboard EDC.
- `shared/components/`: page objects compartidos entre adapters, como Keycloak y MinIO.
- `shared/fixtures/`: resolución de runtime, autenticación y evidencias.
- `tests/`: referencias legacy; la ejecución activa se hace desde `adapters/<adapter>/specs/`.
- `test_cases.yaml`: catálogo técnico para checks `support` y `ops`.
- `../projects/inesdata/integration/test_cases.yaml`: catálogo canónico de los flujos de integración INESData `DS-UI-*`.
- `reporting.py`: agregador que transforma el `results.json` de Playwright en un reporte enriquecido para `Level 6`.
- `playwright.inesdata.config.ts`: configuración de ejecución y reporters.
- `playwright.edc.config.ts`: configuración separada para la suite del dashboard EDC.
- `playwright.ops.config.ts`: configuración separada para suites opcionales de operaciones.

## Preparación

1. Copia `.env.example` a `.env`.
2. Elige uno de estos modos de runtime:
   - `single-portal`: ajusta `PORTAL_BASE_URL`, `PORTAL_USER` y `PORTAL_PASSWORD`
   - `connector-aware`: ajusta `UI_PORTAL_CONNECTOR` o `UI_PORTAL_ROLE`, y para flujos de dataspace `UI_PROVIDER_CONNECTOR` y `UI_CONSUMER_CONNECTOR`
3. Si vas a ejecutar la suite `edc`, define al menos:
   - `UI_ADAPTER=edc`
   - `UI_DATASPACE=<dataspace edc>`
   - opcionalmente `UI_PROVIDER_CONNECTOR` y `UI_CONSUMER_CONNECTOR`
4. Opcional: cambia `PORTAL_TEST_FILE_MB` o `PORTAL_TEST_OBJECT_PREFIX`.

## Instalacion

```bash
cd validation/ui
npm install
npx playwright install
```

## Ejecucion

Suite INESData completa:

```bash
cd validation/ui
npm run test:e2e
```

Suite estable de `inesdata`:

```bash
cd validation/ui
npm run test:inesdata
```

Suite de `edc`:

```bash
cd validation/ui
UI_ADAPTER=edc \
UI_DATASPACE=demoedc \
UI_PROVIDER_CONNECTOR=conn-citycounciledc-demoedc \
UI_CONSUMER_CONNECTOR=conn-companyedc-demoedc \
npm run test:edc
```

La suite actual de `edc` cubre:

- `01 login readiness`
- `02 navigation smoke`
- `03 consumer negotiation`
- `03 provider setup`
- `03b provider policy creation`
- `03c provider contract definition creation`
- `04 consumer catalog`
- `04 consumer transfer`
- `05 consumer transfer storage` con validación del objeto transferido en MinIO
- `05 e2e transfer flow`
- `06b MinIO bucket visibility`
- `07 semantic virtualization HttpData`
- `08 ontology hub read-only`
- `09 AI Model Hub HttpData`
- `10 AI Model Observer route availability`
- `11 AI Model Browser`
- `12 AI Model Execution`
- `13 AI Model Benchmarking`
- `14 AI Model Hub DAIMO metadata`
- `15 AI Model External Execution`
- `16 AI Model Observer participant summary`

Las pruebas `10` y `16` de EDC son comprobaciones explícitas de paridad para
`AI Model Observer`. Por defecto no se ejecutan porque el dashboard EDC actual
no expone esa ruta. Si se habilita `UI_EDC_MODEL_OBSERVER_DEMO=1`, fallan con
un mensaje directo hasta que exista una integración real del Observer en EDC.

Smoke usado por `main.py menu` Level 6:

```bash
cd validation/ui
npx playwright test \
  adapters/inesdata/specs/01-login-readiness.spec.ts \
  adapters/inesdata/specs/04-consumer-catalog.spec.ts \
  --config=playwright.inesdata.config.ts
```

Suite dataspace usada por `main.py menu` Level 6 por defecto:

```bash
cd validation/ui
npx playwright test \
  adapters/inesdata/specs/03-provider-setup.spec.ts \
  adapters/inesdata/specs/03b-provider-policy-create.spec.ts \
  adapters/inesdata/specs/03c-provider-contract-definition-create.spec.ts \
  adapters/inesdata/specs/05-consumer-negotiation.spec.ts \
  adapters/inesdata/specs/06-consumer-transfer.spec.ts \
  --config=playwright.inesdata.config.ts
```

Suite ops opcional para visibilidad de buckets en MinIO Console:

```bash
cd validation/ui
npm run test:ops
```

`Level 6` la ejecuta automáticamente cuando la suite existe en `validation/ui/ops`.

Para desactivarla explícitamente desde `main.py menu` Level 6, exporta:

```bash
export LEVEL6_RUN_UI_OPS=false
```

La opción interactiva `I > Core` también la ejecuta automáticamente al final del bloque smoke + dataspace, usando el mismo modo (`Normal`, `Live` o `Debug`).

En `Live` y `Debug`, el framework activa marcadores visuales sobre los elementos antes de `click`, `fill` y otras interacciones principales para que el recorrido sea más fácil de seguir.

Para omitir la suite dataspace desde `main.py menu` Level 6, exporta:

```bash
export LEVEL6_RUN_UI_DATASPACE=false
```

Solo provider setup:

```bash
cd validation/ui
npx playwright test adapters/inesdata/specs/03-provider-setup.spec.ts --config=playwright.inesdata.config.ts
```

Negociación y transferencia:

```bash
cd validation/ui
npx playwright test adapters/inesdata/specs/05-consumer-negotiation.spec.ts adapters/inesdata/specs/06-consumer-transfer.spec.ts --config=playwright.inesdata.config.ts
```

Modo visible:

```bash
cd validation/ui
npm run test:e2e:headed
```

Modo visible `edc`:

```bash
cd validation/ui
UI_ADAPTER=edc \
UI_DATASPACE=demoedc \
UI_PROVIDER_CONNECTOR=conn-citycounciledc-demoedc \
UI_CONSUMER_CONNECTOR=conn-companyedc-demoedc \
npm run test:edc:headed
```

Modo debug:

```bash
cd validation/ui
npm run test:e2e:debug
```

## Evidencias

Cada flujo deja:

- video
- trace
- screenshots en hitos de negocio
- adjuntos JSON con datos del flujo cuando aplica

Los tests lanzados desde `main.py validate`, Level 6 o el menú interactivo activan por defecto marcadores visuales sobre los elementos antes de las interacciones principales (`click`, `fill`, `check`, `selectOption`, subida de ficheros). Esto facilita seguir el recorrido en modo `Live` y también en los vídeos generados en modo headless.

Las ejecuciones integradas usan una pausa corta de `150` ms por marcador para optimizar el tiempo total. Los modos `Live` y `Debug` usan `350` ms para que el recorrido sea más fácil de seguir visualmente.

Si ejecutas Playwright manualmente con `npx`, puedes activarlos así:

```bash
PLAYWRIGHT_INTERACTION_MARKERS=1 npx playwright test --config=playwright.inesdata.config.ts
```

Para desactivarlos explícitamente:

```bash
PLAYWRIGHT_INTERACTION_MARKERS=0 npx playwright test --config=playwright.inesdata.config.ts
```

Para ajustar la pausa del resaltado:

```bash
PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS=500 npx playwright test --config=playwright.inesdata.config.ts
```

Por defecto los artefactos se guardan en:

- `validation/ui/test-results`
- `validation/ui/playwright-report`
- `validation/ui/blob-report`

Cuando la ejecucion llega desde `main.py menu` o desde la orquestación de Level 6, esos directorios se redirigen automaticamente a `experiments/<experiment_id>/ui/<connector>/`.
Ademas, tanto `Level 6` como la opcion interactiva `I > Core` guardan un JSON enriquecido por suite:

- `ui_core_validation.json`
- `ui_ops_validation.json`
- `ui_validation_summary.json` en la raiz del experimento
- `experiment_results.json` en la raiz del experimento

Estos artefactos separan `support_checks`, `dataspace_cases`, `ops_checks`, `evidence_index` y `catalog_alignment` sin cambiar la ejecucion nativa de Playwright. Los `dataspace_cases` se enriquecen desde `validation/projects/inesdata/integration/test_cases.yaml`.

## Variables de entorno

- `PORTAL_BASE_URL`
- `PORTAL_USER`
- `PORTAL_PASSWORD`
- `PORTAL_MANAGEMENT_BASE_URL`
- `PORTAL_SKIP_LOGIN`
- `PORTAL_TEST_FILE_MB`
- `PORTAL_TEST_OBJECT_PREFIX`
- `UI_PORTAL_CONNECTOR`
- `UI_PORTAL_ROLE`
- `UI_ADAPTER`
- `UI_DATASPACE`
- `UI_ENVIRONMENT`
- `UI_DS_DOMAIN`
- `UI_KEYCLOAK_URL`
- `UI_KEYCLOAK_CLIENT_ID`
- `UI_PROVIDER_CONNECTOR`
- `UI_CONSUMER_CONNECTOR`
- `UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO`
- `UI_SEMANTIC_VIRTUALIZATION_CATALOG_CLEANUP`
- `UI_SEMANTIC_VIRTUALIZATION_DATA_URL`
- `UI_SEMANTIC_VIRTUALIZATION_QUERY_PATH`
- `UI_ONTOLOGY_HUB_INESDATA_DEMO`
- `UI_AI_MODEL_HUB_HTTPDATA_DEMO`
- `UI_AI_MODEL_OBSERVER_DEMO`
- `UI_AI_MODEL_HUB_CATALOG_CLEANUP`
- `UI_AI_MODEL_HUB_MODEL_URL`
- `UI_AI_MODEL_HUB_MODEL_PATH`
- `UI_AI_MODEL_HUB_MODEL_NAMESPACE`
- `UI_CATALOG_READINESS_TIMEOUT_MS`
- `UI_FEDERATED_CATALOG_READINESS_TIMEOUT_MS`
- `UI_COMPONENTS_NAMESPACE`
- `UI_INGRESS_PORT`
- `PLAYWRIGHT_DNS_HOST_MAP`
- `PLAYWRIGHT_HOST_RESOLVER_RULES`
- `PLAYWRIGHT_INGRESS_PROXY_PORT`
- `PLAYWRIGHT_TRACE`

Desde el menú del framework, `I - INESData UI Tests` ejecuta los flujos del
portal INESData y las demos de integración de componentes vistas desde
INESData. Las opciones directas `O`, `A` y `V` quedan reservadas para suites
propias de cada componente.

En nivel 6, las demos de integración INESData se habilitan por defecto porque
forman parte de las validaciones automatizadas A5.2. Las mismas variables se
mantienen para ejecuciones manuales directas con Playwright.

`UI_ONTOLOGY_HUB_INESDATA_DEMO=1` habilita una demo read-only para
`PT5-OH-16` / `DS-UI-OH-01`. La prueba abre INESData, valida la ruta
`Vocabularies` contra la API compartida del conector y la ruta `Ontologies`
contra la API pública de Ontology Hub. No crea ni elimina vocabularios, assets,
contratos ni políticas.

`UI_AI_MODEL_HUB_HTTPDATA_DEMO=1` habilita `DS-UI-AMH-01`,
`DS-UI-AMH-BROWSER-01`, `DS-UI-AMH-EXEC-01` y `DS-UI-AMH-BENCH-01`. La primera
prueba publica desde
el provider un modelo controlado como asset `HttpData`, lo descubre desde el
Catalog Browser del consumer, valida metadatos visibles del modelo, negocia el
contrato desde la UI de INESData y confirma por API que el agreement queda
registrado en el conector consumidor. La segunda prueba reutiliza una fixture
controlada como asset `machineLearning` para validar `AI Model Browser`:
búsqueda, filtros por origen y tarea, metadatos visibles y apertura del detalle
del modelo. La tercera prueba usa el servidor real
`adapters/inesdata/sources/AIModelHub-Use-Cases` para validar `AI Model
Execution`: selección del modelo, payload de ejemplo, ejecución, salida visible
e historial. La cuarta prueba usa dos endpoints comparables del mismo servidor
de casos de uso, carga un CSV pequeño de validación y comprueba ranking,
métricas y acceso a evidencia de benchmark. Estas pruebas validan el gobierno
visual, contractual, de descubrimiento especializado, ejecución y comparación
con el servidor real de modelos configurado por el framework.
`UI_AI_MODEL_HUB_MODEL_URL` permite fijar la URL completa del endpoint y
`UI_AI_MODEL_HUB_MODEL_PATH` cambia la ruta por defecto
`/api/v1/nlp/ecommerce-sentiment`. Si no se define una URL explícita, las
pruebas usan `model-server` en `UI_AI_MODEL_HUB_MODEL_NAMESPACE`, en
`UI_COMPONENTS_NAMESPACE` o, por defecto, en el namespace `components`. Level 5
despliega ese fixture automáticamente cuando `AI Model Hub` está configurado.

`UI_AI_MODEL_OBSERVER_DEMO=1` habilita `DS-UI-AMH-OBS-01` / `MH-OBS-01`: abre
`AI Model Observer` desde INESData y valida la navegación visual hacia
`Asset timeline`, `Agreement evidence`, `Benchmark evidence` y
`Participant summary`. La prueba es read-only, usa IDs controlados, genera
capturas/JSON y se marca como `skipped` si la UI del Observer aún no está
integrada en el build local.

En EDC, `UI_ONTOLOGY_HUB_EDC_DEMO=1` habilita la validación read-only de
`Ontology Hub` desde el dashboard EDC. `UI_AI_MODEL_HUB_HTTPDATA_DEMO=1`
habilita las validaciones equivalentes de `AI Model Hub` sobre `ML Assets`,
`Model Execution`, `Model Benchmarking`, metadatos DAIMO y ejecución externa
tras negociación. `UI_EDC_MODEL_OBSERVER_DEMO=1` exige explícitamente la
paridad de `AI Model Observer` en EDC y falla mientras esa ruta no exista.

`UI_SEMANTIC_VIRTUALIZATION_CATALOG_CLEANUP=1` activa una limpieza segura previa
solo para artefactos de validación con prefijos `qa-ui-*` y `asset-e2e-*` en el
provider. Es útil cuando ejecuciones anteriores saturan la primera página del
Catalog Browser e impiden mostrar el asset temporal de la demo.

`UI_CATALOG_READINESS_TIMEOUT_MS` permite ajustar el tiempo máximo de espera
para que un asset temporal aparezca en el catálogo del consumidor. El alias
`UI_FEDERATED_CATALOG_READINESS_TIMEOUT_MS` se mantiene para los flujos que usan
el catálogo federado de INESData. Por defecto se espera hasta 180 segundos para
absorber la estabilización inicial del catálogo en despliegues recién creados.

`UI_AI_MODEL_HUB_CATALOG_CLEANUP=1` aplica la misma idea solo sobre artefactos
de validación con prefijos `qa-ui-*`, `asset-e2e-*`, `policy-ui-*` y
`contract-ui-*`. No elimina datasets funcionales con nombres estables, por
ejemplo `dataset-flares-subtask2`.

`PLAYWRIGHT_DNS_HOST_MAP` permite resolver hosts de ingress solo dentro del
proceso Node de Playwright, sin editar `/etc/hosts`. Su formato es
`host=ip,host=ip`. Para Chromium se puede usar en paralelo
`PLAYWRIGHT_HOST_RESOLVER_RULES`, por ejemplo `MAP host 192.168.49.2`. Esto es
útil para suites de integración habilitadas por Level 6, como
`UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO=1`.

Cuando la IP de ingress de minikube no sea alcanzable desde la VM, se puede
usar `kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller
8088:80` y ejecutar la suite con `UI_INGRESS_PORT=8088`. Si la UI redirige a
hosts sin puerto, `PLAYWRIGHT_INGRESS_PROXY_PORT=8088` activa un puente de rutas
en el navegador que conserva el `Host` original y usa el port-forward local.

`PLAYWRIGHT_TRACE` mantiene el comportamiento historico `on` por defecto y
permite desactivar trazas con `PLAYWRIGHT_TRACE=off` cuando se quiera generar
evidencia visual con menos riesgo de incluir cabeceras sensibles.
- `PLAYWRIGHT_OUTPUT_DIR`
- `PLAYWRIGHT_HTML_REPORT_DIR`
- `PLAYWRIGHT_BLOB_REPORT_DIR`
- `PLAYWRIGHT_JSON_REPORT_FILE`
- `LEVEL6_RUN_UI_OPS`
- `LEVEL6_RUN_UI_DATASPACE`
- `UI_MINIO_CONSOLE_URL`
- `UI_MINIO_PROVIDER_BUCKET`
- `UI_MINIO_CONSUMER_BUCKET`
- `UI_MINIO_PROVIDER_EXPECT_OBJECT`
- `UI_MINIO_CONSUMER_EXPECT_OBJECT`
