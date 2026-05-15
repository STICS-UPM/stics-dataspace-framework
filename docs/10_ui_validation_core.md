# Validación UI Core

La Fase 4 incorpora una capa de validación UI con Playwright alineada con los flujos ya cubiertos por Newman. La suite UI no introduce lógica de negocio nueva: refleja lo que el `connector-interface` ya expone para un usuario real.

## Alcance

La cobertura UI actual se divide en tres grupos:

- `adapters/inesdata/specs`: flujos funcionales estables del portal INESData.
- `adapters/edc/specs`: flujos funcionales estables del dashboard EDC.
- `extended`: flujo E2E largo para validación visual y regresión ampliada.
- `ops`: comprobaciones visuales opcionales de operación.

Los specs activos viven bajo:

- `validation/ui/adapters/inesdata/specs/`
- `validation/ui/adapters/edc/specs/`
- `validation/ui/ops/`

Y reutilizan page objects y fixtures en:

- `validation/ui/adapters/inesdata/components/`
- `validation/ui/adapters/edc/components/`
- `validation/ui/shared/components/`
- `validation/ui/shared/`

## Flujos Core

La suite INESData cubre actualmente:

- `01 login readiness`
- `03 provider setup`
- `03b provider policy creation`
- `03c provider contract definition creation`
- `04 consumer catalog`
- `05 consumer negotiation`
- `06 consumer transfer`

## Mapeo UI -> API

### 01 login readiness

- Paginas:
  - login de Keycloak
  - shell principal del conector
- Acciones UI:
  - abrir el portal del conector
  - autenticarse con credenciales del conector
  - esperar a que cargue el shell y aparezca `Log out`
- Llamadas API activadas:
  - flujo de autenticación Keycloak
  - bootstrap inicial de rutas protegidas
- Resultado esperado:
  - shell autenticado cargado
  - sin página de gateway `403`
  - sin banners visibles de error del servidor
- Alineacion API:
  - prerrequisito de `01_environment_health`

### 03 provider setup

- Paginas:
  - `/assets/create`
- Acciones UI:
  - rellenar el formulario del asset
  - elegir `InesDataStore`
  - subir un fichero
  - enviar el formulario
- Llamadas API activadas:
  - subida por chunks mediante `/s3assets/upload-chunk`
  - creacion del asset en el backend del conector
- Resultado esperado:
  - snackbar `Asset created successfully`
  - sin respuestas HTTP `>= 400` en `upload-chunk`
- Alineacion API:
  - `03_provider_setup` en su parte de asset y carga de fichero

### 03b provider policy creation

- Paginas:
  - `/policies/create`
  - listado de policies
- Acciones UI:
  - abrir la pantalla de creacion de policies
  - definir el `policyId`
  - anadir la restriccion de `participantId`
  - enviar el formulario
- Llamadas API activadas:
  - creacion de policy en el backend del conector
  - refresco del listado de policies
- Resultado esperado:
  - notificación visible de creacion correcta
  - la policy aparece en el listado
- Alineacion API:
  - `03_provider_setup` en su parte de policy

### 03c provider contract definition creation

- Paginas:
  - `/assets/create`
  - `/policies/create`
  - `/contract-definitions/create`
- Acciones UI:
  - crear un asset previo
  - crear una policy previa
  - abrir la pantalla de contract definitions
  - seleccionar la policy de acceso
  - seleccionar la policy contractual
  - asociar el asset
  - enviar el formulario
- Llamadas API activadas:
  - creacion de asset
  - creacion de policy
  - creacion de contract definition
- Resultado esperado:
  - el asset previo se crea correctamente
  - la policy previa se crea correctamente
  - la contract definition aparece en el listado
- Alineacion API:
  - `03_provider_setup` en su parte de contract definition

### 04 consumer catalog

- Paginas:
  - `/catalog`
  - detalle del dataset
- Acciones UI:
  - abrir el catálogo
  - abrir el detalle de una oferta disponible
- Llamadas API activadas:
  - consulta del catálogo federado
  - carga del detalle del dataset
- Resultado esperado:
  - el catálogo abre sin `403` ni errores visibles del servidor
  - el detalle es visible cuando existe una oferta
- Alineacion API:
  - `04_consumer_catalog`

### 05 consumer negotiation

- Paginas:
  - `/catalog`
  - detalle de dataset
  - pestana `Contract Offers`
- Acciones UI:
  - preparar un asset publicable para el provider
  - abrir el catálogo como consumer
  - localizar el asset
  - abrir el detalle
  - abrir la pestana de ofertas
  - lanzar la negociación
- Llamadas API activadas:
  - consulta del catálogo federado
  - inicio de `contractnegotiations`
  - polling de estado de negociación
- Resultado esperado:
  - el asset aparece en el catálogo del consumer
  - la negociación termina con notificación visible
  - no aparecen errores HTTP `>= 400` en las llamadas funcionales observadas
- Alineacion API:
  - `05_consumer_negotiation`

### 06 consumer transfer

- Paginas:
  - `/catalog`
  - `/contracts`
  - `/transfer-history`
- Acciones UI:
  - preparar un asset publicable para el provider
  - abrir el catálogo como consumer
  - negociar el contrato
  - abrir la vista de contratos
  - iniciar transferencia a `InesDataStore`
  - abrir el historial de transferencias
  - esperar al estado final visible
- Llamadas API activadas:
  - consulta del catálogo federado
  - `contractnegotiations`
  - `transferprocess`
  - consulta del historial de transferencias
- Resultado esperado:
  - el contrato aparece en la vista de contratos
  - la UI muestra `Transfer initiated successfully`
  - la transferencia aparece como completada en el historial
- Alineacion API:
  - `06_consumer_transfer`

## Suite Extendida

Además de los specs atómicos, existe un flujo E2E largo:

- `adapters/inesdata/specs/05-e2e-transfer-flow.spec.ts`

Este spec encadena:

- login del provider
- creación del asset desde UI
- bootstrap complementario de artefactos contractuales
- login del consumer
- catálogo
- negociación
- transferencia

Su objetivo es servir como regresion extendida y validación visual del recorrido visible de punta a punta. No sustituye a los specs atómicos `05` y `06`.

## Suite Ops Opcional

La suite `ops` contiene comprobaciones visuales separadas del flujo funcional del adapter:

- `ops/minio-bucket-visibility.spec.ts`

Esta suite valida que el navegador de buckets de MinIO Console carga correctamente para el bucket del provider y el del consumer.

Notas importantes:

- es una evidencia visual y operativa, no la fuente de verdad del flujo de intercambio
- no debe sustituir las comprobaciones técnicas de almacenamiento
- los errores de endpoints administrativos como `site-replication`, `quota` o `retention` no deben tratarse como fallo funcional del dataspace

## Evidencias

Cada ejecución Playwright genera:

- video
- trace
- screenshots en hitos funcionales
- adjuntos JSON con datos del flujo cuando aplica

Por defecto los artefactos se guardan en:

- `validation/ui/test-results`
- `validation/ui/playwright-report`
- `validation/ui/blob-report`

Cuando la ejecución se redirige desde el framework, las rutas pueden sobreescribirse por variables de entorno para quedar asociadas al experimento activo.

## Parametrizacion

La suite soporta dos modos de resolucion de runtime.

### Modo `single-portal`

Pensado para smoke simple sobre un solo conector.

Variables principales:

- `PORTAL_BASE_URL`
- `PORTAL_USER`
- `PORTAL_PASSWORD`
- `PORTAL_SKIP_LOGIN`
- `PORTAL_TEST_FILE_MB`
- `PORTAL_TEST_OBJECT_PREFIX`

### Modo `connector-aware`

Pensado para flujos reales de dataspace y suites que necesitan distinguir provider y consumer.

Variables principales:

- `UI_PORTAL_CONNECTOR`
- `UI_PORTAL_ROLE`
- `UI_DATASPACE`
- `UI_ENVIRONMENT`
- `UI_DS_DOMAIN`
- `UI_KEYCLOAK_URL`
- `UI_KEYCLOAK_CLIENT_ID`
- `UI_PROVIDER_CONNECTOR`
- `UI_CONSUMER_CONNECTOR`

Reglas practicas:

- los specs simples pueden resolverse por `PORTAL_*` o por `UI_PORTAL_CONNECTOR` / `UI_PORTAL_ROLE`
- los flujos de negociación y transferencia usan `UI_PROVIDER_CONNECTOR` y `UI_CONSUMER_CONNECTOR`
- la resolucion de credenciales y URLs parte de `deployers/<adapter>/deployer.config` cuando existe y de los `credentials-connector-*.json` generados en `deployers/<adapter>/deployments/`

## Integración con Level 6

`main.py menu` Level 6 ejecuta por defecto un subconjunto estable de smoke UI por cada conector:

- `adapters/inesdata/specs/01-login-readiness.spec.ts`
- `adapters/inesdata/specs/04-consumer-catalog.spec.ts`

Estos tests se consideran el mínimo estable porque:

- no introducen cambios estructurales persistentes tan agresivos como la creacion de assets
- validan autenticación, carga del shell y acceso funcional al catálogo

Los flujos `03`, `03b`, `03c`, `05` y `06` existen y pueden ejecutarse manualmente o en pipelines ampliados, pero no forman parte del smoke por defecto de `Level 6`.

Para cada conector, `Level 6` guarda evidencias en:

- `experiments/<experiment_id>/ui/<connector>/test-results`
- `experiments/<experiment_id>/ui/<connector>/playwright-report`
- `experiments/<experiment_id>/ui/<connector>/blob-report`
- `experiments/<experiment_id>/ui/<connector>/results.json`

## Integración de la Suite Ops en Level 6

`Level 6` ejecuta la suite de MinIO Console automáticamente cuando:

- existe `ops/minio-bucket-visibility.spec.ts`
- existe `playwright.ops.config.ts`

Para desactivarla explícitamente, exporta:

- `LEVEL6_RUN_UI_OPS=false`

Cuando la suite está habilitada, Level 6 lanza:

- `ops/minio-bucket-visibility.spec.ts`

Y persiste sus artefactos en:

- `experiments/<experiment_id>/ui-ops/minio-console/test-results`
- `experiments/<experiment_id>/ui-ops/minio-console/playwright-report`
- `experiments/<experiment_id>/ui-ops/minio-console/blob-report`
- `experiments/<experiment_id>/ui-ops/minio-console/results.json`

La opción interactiva `I > Core` también ejecuta esta suite automáticamente al final del bloque smoke + dataspace, respetando el mismo modo (`Normal`, `Live` o `Debug`).

Igual que `Level 6`, esa ejecución interactiva persiste ahora sus artefactos bajo `experiments/<experiment_id>/` y guarda un `experiment_results.json` agregado con `ui_results` y `ui_validation`.

El framework activa marcadores visuales sobre los elementos antes de las interacciones principales (`click`, `fill`, `check`, `selectOption`, subida de ficheros) para hacer más visible el recorrido del test. Esto aplica a las ejecuciones integradas desde `main.py validate`, Level 6 y el menú interactivo. En modo `Live` facilita seguir el navegador en tiempo real; en modo headless ayuda a interpretar los vídeos del reporte. En ejecuciones manuales con `npx`, se puede activar con `PLAYWRIGHT_INTERACTION_MARKERS=1`.

Se puede desactivar explícitamente con `PLAYWRIGHT_INTERACTION_MARKERS=0`. La duración del resaltado se ajusta con `PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS`; las ejecuciones integradas usan `150` ms por defecto para no penalizar el tiempo de validación, mientras que los modos `Live` y `Debug` mantienen `350` ms para facilitar el seguimiento visual.

Esta ejecución se registra en `experiment_results.json` como:

- `test = ui-ops-minio-console`

## Troubleshooting WSL

Si los tests UI se lanzan en modo `Live (headed)` bajo WSL y la ventana de Chromium/Chrome aparece en blanco, gris o sin contenido visible:

1. Actualizar WSL/WSLg desde Windows:

```powershell
wsl --update
wsl --shutdown
```

2. Volver a abrir la distro y repetir el test `Live`.

Este paso ha resuelto en la practica el problema de visibilidad del navegador Playwright en WSL.

Si el entorno sigue mostrando síntomas gráficos extraños después de varias modificaciones locales del framework, conviene probar también con una reinstalación limpia del workspace de `Validation-Environment` antes de seguir depurando la suite.

## Limites Conocidos

- La UI cubre el flujo visible de negociación y transferencia, pero no sustituye las validaciones técnicas de `EDR` o descarga raw.
- La comprobación del almacenamiento final sigue siendo más fiable por API o SDK que por la consola de MinIO.
- La suite `ops` es opcional y no forma parte del criterio funcional principal de aceptación del dataspace.
- La suite `extended` es útil para evidencias visuales y regresion larga, pero no debe reemplazar a los specs atómicos.

## Resumen

La Fase 4 deja una capa UI utilizable y alineada con Newman:

- smoke estable para `Level 6`
- cobertura funcional de `provider`, `catalog`, `negotiation` y `transfer`
- suite E2E extendida para escenarios largos
- suite `ops` separada para evidencia visual de MinIO Console

La validación UI queda así como complemento funcional de la validación API, no como reemplazo de los chequeos técnicos de backend.
