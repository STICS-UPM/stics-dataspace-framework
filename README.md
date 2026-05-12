# Validation-Environment

Validation-Environment es un framework para crear entornos reproducibles de
validación de espacios de datos PIONERA. Se utiliza para desplegar dataspaces,
validar conectores, ejecutar pruebas funcionales, recoger métricas y generar
evidencias experimentales de forma trazable.

El punto de entrada principal es `main.py`. El framework está organizado para
trabajar con distintos adapters y topologías sin duplicar la lógica común de
validación.

## Funcionalidades Principales

- desplegar un dataspace por niveles;
- seleccionar el adapter de conectores: `inesdata` o `edc`;
- preparar servicios comunes como Keycloak, MinIO, PostgreSQL y Vault;
- desplegar conectores provider/consumer;
- desplegar componentes opcionales como `ontology-hub` y `ai-model-hub` cuando el adapter lo soporte;
- sincronizar entradas de `hosts` de forma planificada e idempotente;
- ejecutar validaciones API con Newman;
- ejecutar validaciones UI con Playwright;
- comprobar transferencias y almacenamiento en MinIO;
- recoger métricas de control plane y benchmarks Kafka opcionales;
- persistir resultados en `experiments/`;
- producir reportes y artefactos de validación.

## Adapters

| Adapter | Uso |
| --- | --- |
| `inesdata` | Despliegue y validación con conectores INESData y su portal. |
| `edc` | Despliegue y validación con conectores EDC genéricos y dashboard EDC. |

Cada adapter tiene su propio deployer:

```text
deployers/inesdata/
deployers/edc/
```

Los artefactos compartidos viven en:

```text
deployers/shared/
deployers/infrastructure/
```

## Topologías

El framework reconoce tres topologías canónicas:

```text
local
vm-single
vm-distributed
```

`local` es la ruta de despliegue normal y usa Minikube. `vm-single` ya dispone
de ejecución real para la ruta base del dataspace en `inesdata` y `edc`, y usa
el mismo modelo `role-aligned` de namespaces. `vm-distributed` sigue formando
parte del contexto del deployer y de la planificación de hosts, pero todavía
permanece como topología planificada.

## Inicio Rápido

1. Clona el repositorio:

```bash
git clone --branch refactor/new-framework --single-branch https://github.com/ProyectoPIONERA/Validation-Environment.git
cd Validation-Environment
```

2. Prepara dependencias del framework:

```bash
node --version
npm --version
java -version
bash scripts/bootstrap_framework.sh
```

En Linux/WSL, este comando instala también las dependencias del sistema que
Playwright necesita para arrancar los navegadores. Si el entorno no permite
instalar paquetes del sistema, usa `--without-system-deps`.

`npm` es obligatorio porque las validaciones usan Newman y Playwright, también
en topología `vm-single`. Java 17+ es obligatorio para construir las imágenes
locales de conectores EDC/INESData que después se cargan en Minikube. En una VM
Ubuntu nueva, el bootstrap intenta instalar Node.js con `npm` y OpenJDK 17
automáticamente mediante `apt-get` cuando faltan. Si usas `--without-system-deps`
o tu entorno no permite instalar paquetes del sistema, instálalos antes del
bootstrap:

```bash
sudo apt-get update
sudo apt-get install -y nodejs npm openjdk-17-jdk
```

El bootstrap también crea automáticamente los ficheros locales
`deployer.config` a partir de sus `.example` cuando aún no existen. No los
sobrescribe si ya estaban creados.

3. Activa el entorno Python raíz:

```bash
source .venv/bin/activate
```

4. Para una ejecución local básica no tienes que crear configuración
manualmente. Revisa los ficheros generados solo si necesitas ajustar
credenciales, dominios, dataspaces o componentes:

```text
deployers/infrastructure/deployer.config
deployers/inesdata/deployer.config
deployers/edc/deployer.config
```

5. Abre el menú guiado:

```bash
python3 main.py menu
```

También puedes ejecutar `python3 main.py` en una terminal interactiva; antes de
mostrar el menú, el framework preguntará la topología activa. Si ya sabes la
topología, pásala explícitamente con `--topology` para entrar directo.

El menú guiado es la entrada recomendada para usuarios que quieran ejecutar los
niveles de despliegue sin memorizar comandos.

## Configuración

La configuración común de infraestructura vive en:

```text
deployers/infrastructure/deployer.config
```

La configuración específica de cada adapter vive en:

```text
deployers/inesdata/deployer.config
deployers/edc/deployer.config
```

Usa los ficheros `.example` como plantilla cuando existan:

```text
deployers/infrastructure/deployer.config.example
deployers/inesdata/deployer.config.example
```

La variable `PUBLIC_HOSTNAME` en `deployers/infrastructure/deployer.config` controla
el hostname público del entorno. Cuando está configurada, `bootstrap.py` la usa
automáticamente para establecer el `frontendUrl` de Keycloak, lo que asegura que
los tokens JWT contengan el issuer correcto para acceso externo vía HTTPS:

```text
PUBLIC_HOSTNAME=<your-public-hostname>
```

También puedes sobreescribir valores con variables `PIONERA_*`, por ejemplo:

```bash
PIONERA_DS_1_NAME=demo \
PIONERA_DS_1_NAMESPACE=demo \
PIONERA_DS_1_CONNECTORS=citycouncil,company \
python3 main.py inesdata hosts --topology local --dry-run
```

### Inicio Rápido Para `vm-single` En Una VM

Si vas a ejecutar el framework dentro de una VM Ubuntu y tu objetivo es
`vm-single`, empieza ajustando la base común y el overlay de topología con una
separación explícita:

```bash
cd ~/Validation-Environment
cp deployers/infrastructure/deployer.config.example deployers/infrastructure/deployer.config
cp deployers/infrastructure/topologies/vm-single.config.example \
  deployers/infrastructure/topologies/vm-single.config
nano deployers/infrastructure/deployer.config
nano deployers/infrastructure/topologies/vm-single.config
```

Si el fichero local ya existe, omite el `cp` y edítalo directamente. Para el
overlay `vm-single`, el bloque mínimo esperado es:

```ini
VM_EXTERNAL_IP=192.0.2.10
INGRESS_EXTERNAL_IP=192.0.2.10
```

Notas prácticas:

- usa una IP real de tu VM o del ingress publicado por tu cluster; aquí se usa
  `192.0.2.10` solo como ejemplo documental;
- si entras por el menú con `--topology vm-single` y faltan las claves
  `VM_EXTERNAL_IP`/`INGRESS_EXTERNAL_IP` en
  `deployers/infrastructure/topologies/vm-single.config`,
  el framework puede detectar una dirección candidata con `hostname -I` o
  `minikube ip` y ofrecer escribirla automáticamente;
- si mantienes claves de topología dentro de
  `deployers/infrastructure/deployer.config`, el CLI ya avisa con un warning de
  migración y te indica el overlay correcto;
- después de guardar el fichero, puedes comprobar los valores activos con:

```bash
grep -E '^(VM_EXTERNAL_IP|INGRESS_EXTERNAL_IP)=' \
  deployers/infrastructure/topologies/vm-single.config
```

- antes de arrancar `Level 1`, obtén la IP principal de la VM con:

```bash
hostname -I
```

- usa esa IP de la VM solo como valor provisional inicial en
  `VM_EXTERNAL_IP` e `INGRESS_EXTERNAL_IP`;
- en `vm-single`, `Level 1` recrea el cluster Minikube gestionado por el
  framework en la VM para asegurar una configuración reproducible;
- después de `Level 1`, obtén la IP real del cluster recreado con:

```bash
minikube ip
```

- comprueba los hostnames públicos ya publicados por ingress con:

```bash
kubectl get ingress -A
```

- regla práctica:
  - en la mayoría de instalaciones con Minikube `docker`, el valor final bueno
    será `minikube ip`;
  - usa la IP de la VM como valor final solo si has publicado el ingress
    explícitamente sobre esa IP o a través de un proxy externo que termina allí;
- si `minikube ip` es distinto del valor provisional, actualiza esas claves en
    `deployers/infrastructure/topologies/vm-single.config` o exporta los overrides
    `PIONERA_VM_EXTERNAL_IP` y `PIONERA_INGRESS_EXTERNAL_IP` antes de `Levels 3-6`;
- para `vm-single`, entra directamente por:

```bash
python3 main.py menu --topology vm-single
```

## Hosts Locales

El framework puede planificar o aplicar entradas en el fichero `hosts` del
sistema. Por defecto, la operación solo planifica.

En topología `local`, el camino canónico sigue siendo resolver los hostnames
públicos hacia `127.0.0.1` y mantener `minikube tunnel` activo. Si un entorno
necesita una dirección distinta de loopback, puede declararla explícitamente en
`LOCAL_HOSTS_ADDRESS` y `LOCAL_INGRESS_EXTERNAL_IP` dentro de
`deployers/infrastructure/topologies/local.config`.

Para despliegues locales completos con WSL + Docker, una configuración
prudente de Minikube en ese mismo overlay es:

```ini
PG_HOST=localhost
VT_URL=http://localhost:8200
LOCAL_HOSTS_ADDRESS=
LOCAL_INGRESS_EXTERNAL_IP=
LOCAL_RESOURCE_PROFILE=single-adapter
MINIKUBE_DRIVER=docker
MINIKUBE_CPUS=10
MINIKUBE_MEMORY=14336
MINIKUBE_PROFILE=minikube
```

Regla práctica:

- `10 CPU / 14336 MB` es el punto de partida recomendado para validar un
  adapter local cada vez;
- no configures `MINIKUBE_MEMORY` por encima de la memoria disponible en Docker
  Desktop;
- para mantener `inesdata` y `edc` coexistiendo en local, usa el baseline
  documentado de `10 CPU / 18432 MB` y
  `LOCAL_RESOURCE_PROFILE=coexistence` si Docker Desktop tiene margen
  suficiente;
- si Docker Desktop no alcanza ese baseline, `Level 1` avisa que el entorno
  queda en modo de un adapter local y `Level 3/4/5` bloquean la instalación del
  segundo adapter mientras el primero siga activo; si la ejecución es
  interactiva, el framework muestra un plan de cambio y puede eliminar, tras
  confirmación exacta, solo los recursos locales del adapter anterior;
- en ejecución no interactiva, el cambio de adapter debe autorizarse de forma
  explícita con `PIONERA_LOCAL_ADAPTER_SWITCH_CONFIRM="SWITCH TO EDC"` o
  `PIONERA_LOCAL_ADAPTER_SWITCH_CONFIRM="SWITCH TO INESDATA"`, según el adapter
  destino;
- si `Level 6` detecta ambos adapters en local con memoria efectiva inferior a
  ese baseline, bloquea la validación antes de contaminar resultados con
  `NodeNotReady`;
- errores como `401`, `500` o crashes internos de una aplicación siguen
  apuntando primero a bugs funcionales o de integración, no a falta de CPU.

Planificación:

```bash
python3 main.py inesdata hosts --topology local --dry-run
python3 main.py edc hosts --topology local --dry-run
python3 main.py inesdata local-repair --topology local
python3 main.py inesdata local-repair --topology local --recover-connectors
```

Aplicación explícita:

```bash
PIONERA_SYNC_HOSTS=true \
PIONERA_HOSTS_FILE=/etc/hosts \
python3 main.py edc hosts --topology local
```

En WSL, el fichero `hosts` de Windows suele estar en:

```text
/mnt/c/Windows/System32/drivers/etc/hosts
```

La sincronización es idempotente: si una entrada ya existe, el framework la
omite en lugar de duplicarla.

En el menú interactivo, cuando el adapter activo expone hostnames públicos, los
niveles `3-6` hacen una comprobación previa en topología `local`. Si faltan
entradas, el framework muestra cuáles son y pregunta si quieres aplicar solo las
entradas ausentes antes de continuar.

Para `Level 6` en topología `local`, la validación completa sigue dependiendo de
hostnames públicos accesibles por Ingress. Mantén `minikube tunnel` activo y
asegúrate de que `hosts` resuelve correctamente Keycloak, MinIO,
`registration-service` y los conectores. Los mecanismos internos de
`port-forward` que el framework puede usar en validaciones Kafka concretas no
sustituyen ese requisito del flujo completo.

## Coexistencia de Adapters

Los adapters pueden compartir los servicios comunes desplegados en
`common-srvs` (`Keycloak`, `MinIO`, `PostgreSQL`, `Vault`), pero cada dataspace
debe tener un nombre y namespace propios.

Por ejemplo, es válido desplegar:

```text
inesdata -> DS_1_NAME=demo, DS_1_NAMESPACE=demo
edc      -> DS_1_NAME=demoedc, DS_1_NAMESPACE=demoedc
```

No se debe reutilizar el mismo `DS_1_NAME` o `DS_1_NAMESPACE` para dos adapters
distintos en el mismo cluster local, porque eso puede provocar colisiones de
namespace, registration-service, bases de datos, usuarios y artefactos
generados. Los conectores pueden tener nombres similares siempre que el
dataspace resultante produzca hostnames distintos.

## Menú y Niveles

El menú se abre con:

```bash
python3 main.py menu
```

Niveles disponibles:

| Nivel | Acción |
| --- | --- |
| `1` | Setup Cluster |
| `2` | Deploy Common Services |
| `3` | Deploy Dataspace |
| `4` | Deploy Connectors |
| `5` | Deploy Components |
| `6` | Run Validation Tests |

La opción `0` ejecuta los niveles `1` a `6` de forma secuencial.

Opciones operativas del menú:

| Opción | Uso |
| --- | --- |
| `S` | Preseleccionar adapter para la sesión actual del menú. |
| `P` | Previsualizar el plan de despliegue. |
| `H` | Planificar o aplicar entradas de `hosts`, mostrando hostnames concretos y el motivo si el sync queda omitido. |
| `U` | Mostrar URLs de acceso derivadas de la configuración activa. |
| `M` | Ejecutar métricas o benchmarks independientes. |
| `X` | Recrear el dataspace seleccionado. |
| `B/D/R/C/L` | Accesos de desarrollo: bootstrap, doctor, recovery, cleanup e imágenes locales. |
| `I/O/A` | Validaciones UI de INESData, Ontology Hub y AI Model Hub. |
| `?` | Mostrar ayuda. |
| `Q` | Salir. |

Al seleccionar `edc`, el menú recuerda revisar `H` antes de ejecutar niveles que
dependen de hostnames públicos.

La opción `U` muestra las URLs de acceso en formato legible y puede incluir
endpoints compartidos como `Keycloak`, `MinIO API`, `MinIO Console`,
`registration-service`, URLs de conectores/componentes y el `bucket` MinIO de
cada conector cuando aplique.

Si no preseleccionas adapter con `S`, el menú lo pedirá automáticamente cuando
una operación de `Level 3` a `Level 6` lo necesite.

La referencia completa está en [docs/menu-reference.md](./docs/menu-reference.md).

## Validación Local y Acceso Público

En topología `local`, el framework intenta comportarse de forma coherente con un
entorno más parecido a producción:

- navegador, Playwright y validación completa de `Level 6` usan hostnames
  públicos vía Ingress;
- la comunicación interna entre conectores usa nombres internos de Kubernetes;
- `port-forward` queda reservado como mecanismo local de soporte o diagnóstico.

Esto significa que `Level 6` completo no debe considerarse correcto si solo
funciona mediante `port-forward`. Primero deben estar operativos `hosts`,
Ingress y `minikube tunnel`.

## Prerrequisitos

Para ejecución local, el framework espera:

| Bloque | Herramientas principales |
| --- | --- |
| Base local | Python 3.10+, Git, Docker |
| Kubernetes local | Minikube, Helm, `kubectl` |
| Validación | Node.js, `npm`, Newman, Playwright |
| Builds de conectores | Java 17+ / OpenJDK 17 |
| Operación | cliente PostgreSQL `psql`, permisos para `hosts` cuando aplique |

Verificación rápida:

```bash
python3 --version
git --version
docker --version
minikube version
helm version
kubectl version --client=true
psql --version
node --version
npm --version
npx newman -v
```

El bootstrap del framework prepara `.venv`, dependencias Python, dependencias
Node.js, navegadores Playwright y, en Linux/WSL, las dependencias del sistema
necesarias para ejecutar esos navegadores:

```bash
bash scripts/bootstrap_framework.sh
```

El bootstrap requiere Python `3.10+`. Si `python3` apunta a una versión más
antigua pero la máquina ya tiene otra versión compatible instalada, el script
intentará usar automáticamente `python3.10`, `python3.11`, `python3.12` o
`python3.13`. También puede forzarse explícitamente:

```bash
PIONERA_PYTHON_BIN=python3.11 bash scripts/bootstrap_framework.sh
```

Si un entorno no permite instalar paquetes del sistema desde el bootstrap, se
puede usar `bash scripts/bootstrap_framework.sh --without-system-deps`.

## Minikube Tunnel

En despliegues locales puede ser necesario mantener `minikube tunnel` abierto en
otra terminal:

```bash
minikube tunnel
```

Cuando `minikube tunnel` solicite contraseña, puede que la consola no muestre un
indicador visible. Introduce la contraseña y pulsa `Enter`.

Los accesos funcionales locales deben ejercitar los hostnames publicados por
Ingress. El framework puede usar `port-forward` como apoyo interno para
diagnósticos o clientes host-side, pero no debe sustituir los endpoints de
navegador o API. El fallback de `port-forward` para conectores está desactivado
por defecto y solo debe habilitarse temporalmente con
`PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK=true`.

PostgreSQL es una excepción operativa interna: el servicio PostgreSQL del
cluster sigue usando el puerto `5432`. En topología `local`, el framework
intenta usar `PG_PORT=5432` como puerto local preferente para `psql` y Python.
Si ese puerto local está ocupado por un `kubectl port-forward` antiguo del
framework, lo libera y lo recrea como
`127.0.0.1:5432 -> common-srvs-postgresql:5432`. Si el puerto pertenece a
Windows, WSL u otro proyecto, el framework no mata ese proceso: falla con un
diagnóstico para que el usuario libere el puerto manualmente.

`Level 6` comprueba esos hostnames antes de ejecutar la limpieza y las suites de
validación. Si vas a validar conectores ya desplegados, ejecuta `Level 6` desde
el mismo checkout que ejecutó `Level 4`, porque las credenciales locales
generadas para Keycloak, MinIO y conectores viven bajo
`deployers/<adapter>/deployments/`.

## Acceso Externo (entorno VM/PIONERA)

En entornos desplegados en VM, los conectores y servicios pueden requerir un
proxy externo para quedar accesibles desde fuera de la máquina host. El
framework ya soporta `PUBLIC_HOSTNAME` para ajustar el `frontendUrl` de
Keycloak, y además incluye un script operativo para preparar el acceso público
vía nginx en la VM:

```bash
cd deployers/inesdata/scripts
bash setup-nginx-proxy.sh [cluster_ip] [vm_ip] [public_hostname] [internal_domain]
```

Ejemplo:

```bash
bash setup-nginx-proxy.sh 192.168.49.2 <vm_ip> <public_hostname> <internal_domain>
```

El script:

1. instala nginx e iptables persistentes en la VM;
2. configura reglas de redirección hacia el clúster;
3. ajusta el acceso a UIs de conectores, `/auth/` y `/s3-console/`;
4. ayuda a publicar un hostname externo coherente para browser, Keycloak y MinIO.

La arquitectura y las URLs de referencia están documentadas en
[docs/acceso_externo_conectores_pionera.md](./docs/acceso_externo_conectores_pionera.md).

## CLI Principal

Listar adapters:

```bash
python3 main.py list
```

Desplegar:

```bash
python3 main.py inesdata deploy --topology local
python3 main.py edc deploy --topology local
```

Validar:

```bash
python3 main.py inesdata validate --topology local
python3 main.py edc validate --topology local
```

Ejecutar despliegue y validación:

```bash
python3 main.py inesdata run --topology local
python3 main.py edc run --topology local
```

Previsualizar sin modificar el entorno:

```bash
python3 main.py inesdata deploy --topology local --dry-run
python3 main.py edc run --topology local --dry-run
```

Recrear un dataspace de forma controlada:

```bash
python3 main.py edc recreate-dataspace --topology local --confirm-dataspace demoedc
python3 main.py edc recreate-dataspace --topology local --confirm-dataspace demoedc --with-connectors
```

## Validación

`Level 6` ejecuta la validación integral del adapter activo. Puede incluir:

- Newman;
- validación funcional EDC+Kafka después de Newman cuando el adapter la soporta;
- Playwright;
- comprobaciones de storage/MinIO;
- validaciones de componentes;
- métricas;
- reportes en `experiments/`.

En topología `local`, `Level 6` usa por defecto el modo de orquestación
`stable`: Newman, Kafka, Playwright y componentes se coordinan con menos
solapamiento para reducir ruido de Minikube local. En `vm-single` y
`vm-distributed` el modo efectivo por defecto sigue siendo `fast`.

En ese modo estable local, el framework también comprueba la salud de Kubernetes
antes y después de la validación. Si el nodo o los pods relevantes no están
listos, espera una ventana corta y falla temprano si el entorno sigue
bloqueado. Si durante la ejecución aparecen reinicios o eventos `NodeNotReady`,
quedan registrados en `local_stability_preflight.json` y
`local_stability_postflight.json` dentro del experimento.

Para forzar el modo rápido en local:

```bash
python3 main.py inesdata validate --topology local --validation-mode fast
```

También puede declararse con `PIONERA_VALIDATION_MODE=fast`.

En el layout `role-aligned`, `Level 5` publica componentes opcionales en
`components_namespace`. `Level 6` valida esos componentes después de las suites
del dataspace. Hoy `ontology-hub` se valida por defecto cuando está
configurado, mientras que la UI PT5 de `ai-model-hub` sigue siendo opt-in con
`AI_MODEL_HUB_ENABLE_UI_VALIDATION=1`.

Colecciones Newman principales:

| Colección | Uso |
| --- | --- |
| `01_environment_health.json` | Salud básica, reachability y autenticación. |
| `02_connector_management_api.json` | CRUD aislado del Management API. |
| `03_provider_setup.json` | Preparación del escenario E2E del provider. |
| `04_consumer_catalog.json` | Descubrimiento de catálogo. |
| `05_consumer_negotiation.json` | Negociación contractual. |
| `06_consumer_transfer.json` | Transferencia y recuperación de datos. |

Playwright se resuelve por adapter:

```text
validation/ui/playwright.config.ts
validation/ui/playwright.edc.config.ts
```

La documentación de validación está en [docs/validation.md](./docs/validation.md).

## Métricas y Kafka

Ejecutar métricas:

```bash
python3 main.py inesdata metrics --topology local
python3 main.py edc metrics --topology local
```

Ejecutar métricas con benchmark standalone de broker Kafka:

```bash
python3 main.py inesdata metrics --topology local --kafka
```

Helper reproducible de Kafka:

```bash
bash scripts/run_kafka_benchmark.sh --messages 10
bash scripts/run_kafka_benchmark.sh --messages 10 --max-retries 3 --retry-backoff 15
bash scripts/run_kafka_benchmark.sh --prepare-only
bash scripts/run_kafka_benchmark.sh --teardown-only
```

El benchmark standalone puede generar `kafka_metrics.json` y mide el broker
Kafka, no el flujo E2E del dataspace. Además, `Level 6` ejecuta la validación
funcional EDC+Kafka después de Newman para adapters compatibles y puede generar
`kafka_transfer_results.json`.

En local, esa validación usa por defecto un broker Kafka temporal dentro de
Kubernetes. Los conectores acceden al broker por DNS de cluster y el proceso
Python del framework puede usar un `port-forward` temporal solo para crear
topics y verificar mensajes desde el host.

## Imágenes Locales

Durante desarrollo, usa la opción `L - Build and Deploy Local Images` del menú
para construir, cargar y redesplegar imágenes locales del adapter activo.

En topología `local`, `Level 4` de INESData prepara automáticamente
`inesdata-connector` e `inesdata-connector-interface` desde las fuentes locales
antes de crear los conectores. Esto evita validar con imágenes remotas antiguas
cuando `Level 6` ejecuta flujos como Kafka o Playwright.

La opción `L` está pensada para iteración de desarrollo y preserva datos en
redeploys INESData: reutiliza los valores existentes de Helm y no recrea
credenciales, dataspace ni servicios comunes. Si un release todavía no existe,
ejecuta primero el nivel correspondiente.

Cuando el adapter activo es `edc`, las acciones rápidas de `L` construyen y
cargan imágenes locales del conector EDC, del dashboard EDC o de ambos. Si ya
hay deployments EDC en ejecución, el framework los reinicia para que tomen la
imagen nueva sin recrear datos.

Además, `Level 4` de EDC prepara automáticamente esas imágenes locales en modo
`auto` cuando se despliega en local y no hay una imagen explícita publicada que
usar.

Si la receta corresponde a un componente de `Level 5` ya desplegado, como
`Ontology Hub` o `AI Model Hub`, el framework reinicia su deployment para que
Kubernetes use la imagen recién cargada. Si el componente aún no existe, carga
la imagen y deja el despliegue para `Level 5`.

Scripts relevantes:

```text
adapters/inesdata/scripts/sync_sources.sh
adapters/inesdata/scripts/build_images.sh
adapters/inesdata/scripts/local_build_load_deploy.sh
adapters/edc/scripts/sync_sources.sh
adapters/edc/scripts/build_image.sh
adapters/edc/scripts/sync_dashboard_sources.sh
adapters/edc/scripts/build_dashboard_image.sh
adapters/edc/scripts/build_dashboard_proxy_image.sh
```

Para EDC, las fuentes locales se gestionan bajo:

```text
adapters/edc/sources/
```

El runtime del conector EDC se sincroniza desde:

```text
https://github.com/luciamartinnunez/Connector
```

El dashboard EDC se sincroniza desde:

```text
https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard
```

## Limpieza y Doctor

El menú incluye accesos directos de desarrollo:

| Herramienta | Uso |
| --- | --- |
| `Bootstrap Framework Dependencies` | Prepara o repara dependencias. |
| `Run Framework Doctor` | Ejecuta checks del entorno local. |
| `Repair Local Access / Connectors` | Reconcila `hosts` y, si hace falta, reinicia conectores tras un reinicio local o de WSL. |
| `Cleanup Workspace` | Limpia caches y artefactos temporales. |
| `Build and Deploy Local Images` | Construye imágenes locales y reinicia componentes desplegados cuando aplica. |

El script de limpieza también puede ejecutarse manualmente:

```bash
bash scripts/clean_workspace.sh
bash scripts/clean_workspace.sh --apply
bash scripts/clean_workspace.sh --apply --include-results
```

## Experimentos y Reportes

Un experimento es una ejecución reproducible del flujo de validación y medición.
Puede incluir despliegue, validación API, validación UI, métricas, Kafka y
artefactos de componentes.

Estructura habitual:

```text
experiments/
  experiment_<timestamp>/
    metadata.json
    experiment_results.json
    aggregated_metrics.json
    kafka_metrics.json
    kafka_transfer_results.json
    summary.json
    summary.md
    graphs/
```

Los reportes Playwright quedan dentro del experimento correspondiente cuando se
ejecutan desde `Level 6`.

## Arquitectura y Estructura

| Ruta | Descripción |
| --- | --- |
| `main.py` | CLI principal y menú guiado. |
| `framework/` | Núcleo reutilizable de validación, métricas y reportes. |
| `adapters/` | Integraciones específicas por adapter. |
| `deployers/` | Deployers, configuración y artefactos de despliegue. |
| `deployers/infrastructure/` | Contratos, topologías, hosts y utilidades transversales. |
| `deployers/shared/` | Charts y artefactos reutilizables. |
| `validation/` | Suites Newman, Playwright y validaciones de componentes. |
| `tests/` | Pruebas unitarias del framework. |
| `docs/` | Documentación pública estable. |

## Tests

Pruebas focalizadas de topologías, contratos, hosts y CLI:

```bash
python3 -m unittest \
  tests.test_deployer_shared_contracts \
  tests.test_deployer_shared_topology \
  tests.test_deployer_shared_hosts_manager \
  tests.test_main_cli
```

Descubrimiento general:

```bash
python3 -m unittest discover tests
```

El descubrimiento general puede incluir suites amplias de Vault, Kafka,
Ontology, métricas o componentes que dependan del entorno local disponible.

## Documentación

La documentación pública está en [docs/](./docs/README.md).

Orden recomendado:

- [Inicio rápido](./docs/getting-started.md)
- [Referencia del menú](./docs/menu-reference.md)
- [Arquitectura](./docs/architecture.md)
- [Deployers y topologías](./docs/deployers-and-topologies.md)
- [Adapters](./docs/adapters.md)
- [Validación](./docs/validation.md)
- [Desarrollo y testing](./docs/development-and-testing.md)
- [Troubleshooting](./docs/troubleshooting.md)
- [Acceso externo a conectores (VM/PIONERA)](./docs/acceso_externo_conectores_pionera.md)

## Referencias Técnicas

- [INESData local environment](https://github.com/INESData/inesdata-local-env)
- [INESData connector management API collection](https://github.com/INESData/inesdata-local-env/blob/master/resources/operations/InesData_Connector_Management_API.postman_collection.json)
- [Eclipse EDC Management API](https://eclipse-edc.github.io/Connector/openapi/management-api/#/)
- [Eclipse EDC Kafka sample](https://github.com/eclipse-edc/Samples/tree/main/transfer/transfer-06-kafka-broker)
- [DataSpaceUnit local deployment](https://github.com/DataSpaceUnit/ds-local-deployment)

## Financiación

This work has received funding from the **PIONERA project** (Enhancing interoperability in data spaces through artificial intelligence), a project funded in the context of the call for Technological Products and Services for Data Spaces of the Ministry for Digital Transformation and Public Administration within the framework of the PRTR funded by the European Union (NextGenerationEU).

<div align="center">
  <img src="funding_label.png" alt="Logos financiación" width="900" />
</div>

---

## Licencia

Validation-Environment is available under the **[Apache License 2.0](https://github.com/ProyectoPIONERA/pionera_env/blob/main/LICENSE)**.
