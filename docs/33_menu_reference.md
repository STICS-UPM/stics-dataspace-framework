# Referencia del Menú

El menú guiado se abre con:

```bash
python3 main.py menu
```

El menú está en inglés para alinearse con nombres de comandos, código y artefactos técnicos. Esta guía explica cuándo usar cada opción.

## Encabezado

El menú ya no muestra por defecto un bloque con el adapter activo o la lista de
adapters disponibles. La idea es reducir carga cognitiva en la ruta normal de
uso.

Si una acción depende del adapter, el framework:

- usa el adapter que hayas preseleccionado con `S`;
- o lo pide en ese momento si todavía no se ha elegido uno.

Cuando abres el framework con `python3 main.py`, el selector inicial muestra una
sección `Other actions` con la misma opción `G - Validate target` que aparece
después en `[Operations]`. Esa entrada sirve para validar targets externos sin
elegir una topología PIONERA. La topología por defecto aparece marcada como
`current`; `Back` solo aparece en submenús a los que ya has entrado.

## Full Deployment

`0 - Run All Levels (1-6) sequentially`

Usa esta opción para un despliegue completo desde cero o para reconstruir todo el entorno en orden. Ejecuta preparación de cluster, servicios comunes, dataspace, conectores, componentes y validación.

## Individual Levels

`1 - Level 1: Setup Cluster`

Prepara el cluster base. En `local`, esta ruta usa Minikube.

`2 - Level 2: Deploy Common Services`

Despliega o actualiza servicios comunes como Keycloak, MinIO, PostgreSQL y Vault.

`3 - Level 3: Deploy Dataspace`

Despliega el runtime base del dataspace y el registration service. Al terminar
correctamente, el siguiente paso normal es ejecutar `Level 4` para desplegar o
actualizar los conectores del adapter activo.

`4 - Level 4: Deploy Connectors`

Despliega los conectores del adapter activo. En `inesdata`, despliega conectores INESData. En `edc`, despliega conectores EDC.

En topología `local`, `inesdata` prepara automáticamente las imágenes locales de
`inesdata-connector` e `inesdata-connector-interface` antes de crear los
conectores, siempre que las fuentes existan bajo `adapters/inesdata/sources/`.
Este comportamiento puede desactivarse con `INESDATA_LOCAL_IMAGES_MODE=disabled`
o hacerse estricto con `INESDATA_LOCAL_IMAGES_MODE=required`.

`5 - Level 5: Deploy Components`

Despliega componentes opcionales configurados, como Ontology Hub o AI Model Hub cuando correspondan al adapter y configuración activos.

`6 - Level 6: Run Validation Tests`

Ejecuta la validación integral del adapter activo. Puede incluir limpieza previa, Newman, checks de almacenamiento, Playwright, componentes y métricas según el perfil de validación.

En topología `local`, esta opción espera que los hostnames publicados por
Ingress estén accesibles. Mantén `minikube tunnel` abierto y responde la
contraseña en esa terminal si aparece el prompt de sudo. Para conectores ya
desplegados, ejecuta `Level 6` desde el mismo checkout que ejecutó `Level 4`,
porque ahí se generan las credenciales locales usadas por la validación.

Antes de lanzar Playwright, `Level 6` también hace un preflight HTTP real del
portal del adapter:

- `inesdata`: comprueba Keycloak, los servicios `*-interface` y la ruta pública
  `http://<connector>.../inesdata-connector-interface/`;
- `edc`: comprueba Keycloak, dashboard, proxy y rutas públicas de management.

Si ese preflight falla, el nivel termina con una causa clara y persiste el
diagnóstico del adapter en `experiments/`.

## Operations

`S - Select adapter`

Permite dejar preseleccionado el adapter para la sesión actual del menú. Es un
atajo opcional: si no lo usas, el framework te preguntará el adapter cuando una
operación de `Level 3` a `Level 6` realmente lo necesite.

`T - Select topology`

Permite cambiar la topología activa para la sesión actual del menú. No escribe
ningún valor en `deployer.config`: solo cambia el contexto interactivo entre
`local`, `vm-single` y `vm-distributed` hasta que salgas del menú.

`P - Preview deployment plan`

Muestra un plan de despliegue sin modificar el entorno. Úsalo antes de ejecutar cambios destructivos o cuando quieras revisar dataspace, conectores, componentes, namespaces y hosts esperados. Si la operación necesita adapter y aún no se ha elegido uno, el menú lo pide en ese momento.

`H - Plan/apply hosts entries`

Planifica o aplica entradas del fichero `hosts`. Por defecto solo planifica. La
salida muestra los hostnames concretos por nivel y el motivo si el sync queda
en `Skipped`.

Si el sync automático no está habilitado, el menú interactivo también puede
ofrecer aplicar el plan en ese momento cuando detecta un fichero `hosts`
resoluble. Para aplicar cambios de forma explícita fuera del prompt interactivo,
usa `PIONERA_SYNC_HOSTS=true` y `PIONERA_HOSTS_FILE`.

En el menú interactivo, si el adapter elegido para la operación expone
hostnames públicos y vas a ejecutar niveles `3-6`, el framework verifica
primero si faltan hostnames en el fichero `hosts` local. Si faltan, muestra la
lista y pregunta si quieres reconciliar el bloque gestionado del framework
antes de continuar. Si cancelas o el sistema no permite escribir el fichero, el
nivel no se ejecuta.

Fuera del menú, la ruta equivalente y más directa para está reparación es:

```bash
python3 main.py <adapter> local-repair --topology local
```

`U - Show available access URLs`

Muestra las URLs de acceso derivadas de la configuración activa del adapter en
un formato legible. Es útil después de `Level 2`, `Level 4` o `Level 5` cuando
quieres ver rápidamente portales, dashboards, APIs, componentes o accesos
compartidos sin buscar en artefactos o ficheros de configuración.

La salida puede incluir:

- `Keycloak`
- `MinIO API`
- `MinIO Console`
- `registration-service`
- URLs de portales, conectores y componentes
- `MinIO Bucket` por conector cuando aplique

En topología `vm-single`, la salida añade una sección `Local Browser Access`
con los valores detectados automáticamente desde la VM: IP candidata de la VM,
IP de Minikube, usuario SSH, comando de túnel SSH, entradas para el fichero
`hosts` de la máquina local y URLs que puedes abrir en tu navegador local.

`G - Validate target`

Abre el flujo guiado para targets externos de validación, pensado inicialmente
para INESData productivo o entornos que el framework no despliega.
Este flujo no selecciona ni cambia el adapter activo usado por los niveles de
despliegue; se muestra como proyecto de validación externo en modo
`validation-only`.

El flujo actual incluye un runner mínimo seguro:

- permite seleccionar un target bajo `validation/targets/`;
- valida el YAML del target;
- muestra dataspaces, suites, componentes y secretos requeridos;
- no ejecuta limpieza ni borra datos;
- no ejecuta escrituras;
- no ejecuta `Levels 1-5`;
- ejecuta únicamente specs Playwright `read-only` explícitamente habilitados en
  `project_suites`;
- si solo existen plantillas `*.example.*`, termina como `skipped` sin ejecutar
  Playwright.

Úsalo para revisar que la configuración base de INESData externo está completa
o para generar evidencias Playwright read-only cuando existan specs reales.
Newman y Kafka productivos quedan fuera de esta primera fase.

`E - View experiment reports`

Abre un visor local de experimentos de validación. No requiere seleccionar
adapter porque no despliega ni ejecuta validaciones: solo lee artefactos ya
generados bajo `experiments/`.

El flujo permite:

- listar experimentos disponibles;
- abrir el último experimento o seleccionar uno anterior;
- generar un dashboard HTML propio del framework;
- abrir reportes Playwright con `npx playwright show-report`;
- ver rutas de artefactos sin imprimir JSON largos por consola.

El dashboard se sirve únicamente en `127.0.0.1` y funciona como índice del
experimento para Playwright, Newman, Kafka, componentes y postflight local
cuando esos reportes existan.

El campo `Dashboard status` resume hallazgos del visor; no sustituye el estado
de ejecución de `Level 6`.

Más detalle en [Visor de reportes de experimentos](./40_report_viewer.md).

`M - Run metrics / benchmarks`

Ejecuta métricas o benchmarks independientes sobre el adapter elegido para esa operación. El benchmark Kafka mide el broker de forma standalone y guarda resultados en `experiments/`, pero no reemplaza la validación funcional de `Level 6`. La validación Kafka E2E del dataspace se ejecuta automáticamente dentro de `Level 6` cuando el adapter es compatible.

`X - Recreate dataspace`

Destruye y recrea el dataspace seleccionado preservando servicios comunes. Requiere escribir el nombre exacto del dataspace. Invalida conectores de nivel 4 y permite recrearlos inmediatamente si se confirma.

## Developer

`B - Bootstrap Framework Dependencies`

Instala o repara dependencias del framework. Úsalo en una máquina limpia o tras problemas de dependencias; en Linux/WSL también prepara las dependencias de sistema necesarias para Playwright.

`D - Run Framework Doctor`

Ejecuta checks de preparación local. Úsalo antes de desplegar o para diagnosticar fallos de entorno.

`R - Repair Local Access / Connectors`

Ejecuta una recuperación guiada del acceso local. Primero puede reconciliar el
bloque gestionado de `hosts` del framework y, después, opcionalmente reiniciar
los conectores si el cluster seguía desplegado tras reiniciar WSL o el entorno
local. Cuando el bloque de `hosts` queda listo, también verifica los endpoints
públicos mínimos que el framework espera antes de `Level 6`.

La ruta CLI equivalente es:

```bash
python3 main.py <adapter> local-repair --topology local
python3 main.py <adapter> local-repair --topology local --recover-connectors
```

`C - Cleanup Workspace`

Limpia artefactos generados, caches o salidas previas que dificultan razonar sobre el estado actual.

`L - Build and Deploy Local Images`

Construye y carga imágenes locales. Úsalo durante desarrollo cuando hayas modificado código fuente de conectores, dashboards o componentes que deban probarse en el cluster.

El submenú separa la ruta habitual de desarrollo de las recetas avanzadas:

- `Quick actions`: acciones rápidas específicas del adapter activo.
  En INESData hacen `build/load/redeploy` preservando datos: el redeploy usa
  `helm upgrade --reuse-values` sobre releases existentes y no reinstala
  releases ausentes con values base. En EDC construyen/cargan las imágenes
  locales del conector y/o dashboard, y reinician deployments EDC existentes
  para que tomen la imagen nueva sin recrear datos.
- `Advanced recipes`: recetas registradas para construir, cargar y, cuando se
  seleccione, redesplegar una fuente concreta del adapter activo.

Si el release no existe, ejecuta primero el nivel correspondiente (`Level 4`
para conectores o `Level 5` para componentes).

Para recetas registradas de componentes, como `Ontology Hub` o `AI Model Hub`,
si el deployment ya existe en el namespace del dataspace activo, el framework lo
reinicia para que tome la imagen local cargada en Minikube. Si no existe, la
opción solo prepara la imagen; después ejecuta `Level 5` para desplegar el
componente.

## UI Validation

`I - INESData Tests (Normal/Live/Debug)`

Ejecuta validaciones UI del portal INESData de forma independiente del nivel 6
completo. El submenú separa `Core` de las integraciones de componentes vistas
desde INESData:

- `Ontology Hub Integration with INESData`: ejecuta `DS-UI-OH-01`.
- `AI Model Hub Integration with INESData`: ejecuta `DS-UI-AMH-01`.
- `Semantic Virtualization Integration with INESData`: ejecuta `DS-UI-SV-01`.

`O - Ontology Hub Tests (Normal/Live/Debug)`

Ejecuta validaciones UI propias de Ontology Hub, es decir, sobre la aplicación
del componente y sus suites técnicas/funcionales, no sobre INESData.

`A - AI Model Hub Tests (Normal/Live/Debug)`

Ejecuta validaciones UI propias de AI Model Hub, no la validación de integración
desde INESData.

`V - Semantic Virtualization Tests (Normal/Live/Debug)`

Ejecuta validaciones UI/read-only del virtualizador semántico. La suite abre el
endpoint público desde Playwright, valida el documento OpenAPI y comprueba que
el endpoint de consulta responde desde el contexto del navegador. También cubre
la UI/editor del virtualizador cuando está habilitada; la validación desde INESData se
ejecuta desde `I`.

## Control

`? - Help`

Muestra ayuda resumida dentro del propio menú.

`Q - Exit`

Sale del menú.

## Topología

La topología puede seleccionarse de dos maneras:

- por CLI con `--topology`
- desde el propio menú con `T - Select topology`

Ejemplos por CLI:

```bash
python3 main.py inesdata deploy --topology local
python3 main.py edc hosts --topology vm-single --dry-run
```

Topologías canónicas:

```text
local
vm-single
vm-distributed
```

Dentro del menú, la topología activa se muestra en el encabezado y se aplica a
todas las acciones de la sesión actual hasta que la cambies con `T` o salgas
del menú.
