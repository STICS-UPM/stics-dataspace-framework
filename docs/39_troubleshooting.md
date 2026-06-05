# Troubleshooting

## Windows Llega al Bastion Pero WSL No

En topología `vm-distributed`, una terminal WSL puede no heredar correctamente
la conectividad de Windows hacia la VPN, red corporativa o red de laboratorio.
El síntoma típico es que `Test-NetConnection` funciona en PowerShell, pero en
WSL fallan la resolución DNS o la conexión TCP al bastion.

Comprueba primero desde Windows:

```powershell
Test-NetConnection <bastion-host> -Port <bastion-port>
```

Después comprueba desde WSL:

```bash
getent hosts <bastion-host>
nc -vz <bastion-host> <bastion-port>
```

Si Windows funciona y WSL falla, activa networking mirrored en
`%UserProfile%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
firewall=true
```

Reinicia WSL desde PowerShell:

```powershell
wsl --shutdown
```

Al abrir de nuevo WSL, repite `getent` y `nc` antes de probar SSH. Para
`vm-distributed`, usa una llave SSH dedicada al entorno VM; no reutilices llaves
personales ni llaves privadas compartidas. La guía completa está en
[Preparación de conectores externos](./45_external_connector_readiness.md#operación-desde-windows-y-wsl).

## Las Entradas de Hosts No Resuelven

Previsualiza las entradas esperadas:

```bash
python3 main.py edc hosts --topology local --dry-run
```

Aplica entradas solo con sincronización explícita:

```bash
PIONERA_SYNC_HOSTS=true \
PIONERA_HOSTS_FILE=/etc/hosts \
python3 main.py edc hosts --topology local
```

Si una entrada ya existe, el gestor de hosts la omite en lugar de duplicarla.

## Los Servicios Minikube No Son Accesibles

En despliegues locales, mantén esto abierto en otra terminal:

```bash
minikube tunnel
```

Verifica también:

```bash
kubectl get pods -A
kubectl get ingress -A
helm list -A
```

Si el problema aparece al lanzar `Level 6`, recuerda que la validación completa
usa hostnames públicos por defecto. Un `port-forward` puntual puede servir para
diagnóstico, pero no sustituye la necesidad de que Ingress, `hosts` y
`minikube tunnel` estén realmente operativos.

## Level 2 Muestra `failed post-install`

En instalaciones locales limpias, Helm puede dejar `common-srvs` en estado
`failed` si un hook tarda más que el timeout inicial, aunque los pods terminen
arrancando correctamente unos segundos después.

`Level 2` primero comprueba los servicios reales de `common-srvs`, configura
Vault y, si el runtime está sano pero Helm sigue en `failed`, vuelve a ejecutar
Helm con más margen para reconciliar el release a `deployed`. Si el release
sigue fallando después de ese segundo intento, entonces el nivel falla porque el
estado de Helm ya no es confiable para continuar con `Level 3`.

## Los Conectores Solo Funcionan con Port-forward

En local, el resultado correcto es que los conectores sean accesibles por su
hostname público de Ingress, por ejemplo:

```text
http://conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm/inesdata-connector-interface
http://conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm/edc-dashboard/
```

Si solo funcionan con `kubectl port-forward`, revisa primero:

- que `minikube tunnel` esté abierto;
- que las entradas de `hosts` existan para el dataspace y sus conectores;
- que el Ingress del namespace exista y tenga dirección;
- que los pods y endpoints del conector estén listos.

Comandos útiles:

```bash
python3 main.py inesdata hosts --topology local --dry-run
python3 main.py edc hosts --topology local --dry-run
kubectl get ingress -A
kubectl get endpoints -A
```

El fallback de `port-forward` para conectores está desactivado por defecto para
no ocultar problemas reales de routing. Úsalo solo como diagnóstico temporal:

```bash
PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK=true
```

## Falla la Autenticación Admin de Keycloak

Comprueba que:

- los servicios comunes están en ejecución;
- la URL admin de Keycloak resuelve;
- las credenciales en `deployers/infrastructure/deployer.config` son correctas;
- el fichero `hosts` contiene las entradas de Keycloak;
- el túnel local o ingress está disponible.

## Level 3 Falla con PostgreSQL `password authentication failed`

Si `Level 3` intenta ejecutar `psql` con una contraseña placeholder como
`CHANGE_ME`, el fichero local `deployers/infrastructure/deployer.config` no está
alineado con los secretos reales de `common-srvs`.

Antes de crear el dataspace, `Level 3` sincroniza las credenciales comunes
locales desde los secretos Kubernetes de PostgreSQL, Keycloak y MinIO. Esto
permite reutilizar servicios comunes ya desplegados desde una copia limpia del
framework sin recrear `common-srvs`.

El servicio PostgreSQL del cluster sigue usando el puerto `5432`. Si
`localhost:5432` ya está ocupado por un PostgreSQL de la máquina, el framework no
debe tratarlo como el PostgreSQL del cluster ni terminarlo automáticamente. Si el
ocupante es un `kubectl port-forward` antiguo del propio framework, lo libera y
lo recrea sobre `127.0.0.1:5432 -> common-srvs-postgresql:5432`. Si el ocupante
es externo, el nivel falla con un diagnóstico para que el usuario libere el
puerto manualmente.

## Level 3 Falla con `Timeout waiting for dataspace pods`

Si el log muestra que `registration-service` está `Running`, pero el nivel falla
porque existen conectores antiguos en `Init`, `CrashLoopBackOff` u otro estado
inestable, el problema no es el dataspace base. Esos conectores pertenecen a
`Level 4`.

`Level 3` solo debe validar los pods base del dataspace, principalmente
`registration-service`. Los conectores se despliegan, actualizan y validan en
`Level 4`, por lo que no deben bloquear la recreación de un dataspace.

Después de un `Level 3` correcto, ejecuta `Level 4` para desplegar o actualizar
los conectores del adapter activo.

## Vault Indica Token Obsoleto

Si nivel 2 o nivel 4 informa que el token de Vault no es válido para el Vault en
ejecución, significa que el estado persistente de Vault y el artefacto local
`deployers/shared/common/init-keys-vault.json` no corresponden entre sí.

No reintentes nivel 4 en bucle. Primero recupera el root token actual de Vault,
si existe, o recrea los servicios comunes de nivel 2 en entorno local para que
el framework vuelva a generar claves consistentes. Después ejecuta de nuevo
nivel 3 y nivel 4.

En topología `local`, el framework intenta prevenir este caso reconciliando de
forma automática el artefacto compartido y `deployer.config` con cualquier token
local que sea válido contra el Vault en ejecución. Si no queda ningún token
válido, `Level 4` de EDC puede hacer una reparación controlada: mueve
temporalmente el artefacto obsoleto, elimina `common-srvs`, vuelve a ejecutar
`Level 2`, vuelve a ejecutar `Level 3` y reintenta `Level 4`. El backup temporal
se elimina si la reparación termina bien y se restaura si falla.

El framework pide confirmación interactiva antes de hacerlo. En ejecución no
interactiva debe habilitarse explícitamente:

```bash
PIONERA_LEVEL4_REPAIR_COMMON_SERVICES=true python3 main.py inesdata deploy --topology local
```

No actives esta variable si quieres preservar el estado actual de
`common-srvs`; recrear servicios comunes afecta a los adapters que compartan ese
cluster local.

El framework no debe copiar tokens desde runtimes legacy del adapter ni
sobrescribir `VT_TOKEN` con un token que no haya sido validado contra el Vault en
ejecución. La fuente canónica es `deployers/shared/common/init-keys-vault.json`.

En un entorno sano no debería ser necesario recrear `common-srvs` en cada
despliegue. Si vuelve a pasar, revisa si se ejecutó el mismo cluster desde dos
copias distintas del framework, si se conservaron PVCs antiguos o si se copió
`init-keys-vault.json` desde otro entorno.

## Level 4 Falla con Keycloak 415

Si `Level 4` falla al crear conectores con un error `415` de Keycloak durante
el mapeo de roles del service account, revisa que estás usando una versión del
framework que restaura `Content-Type: application/json` después de subir el
certificado público del conector.

El síntoma típico aparece justo después de:

```text
Client certificate for <connector> synchronized
```

La corrección forma parte del bootstrap de INESData y permite recrear conectores
con certificados, scopes y roles de service account de forma reproducible.

## Kafka Transfer Queda Omitido por Imagen INESData Antigua

Si `Level 6` muestra `SKIP Kafka transfer` con razón
`kafka_dataaddress_not_supported`, Kafka no necesariamente ha fallado. Ese
resultado indica que el broker y los logins funcionaron, pero el runtime del
conector rechazó assets con `DataAddress.type=Kafka`.

Comprueba la imagen desplegada:

```bash
kubectl get deploy -n provider -o wide
kubectl get deploy -n consumer -o wide
```

En local, `Level 4` debe preparar y desplegar una imagen local de
`inesdata-connector` compatible con Kafka. Si ves una imagen remota antigua,
vuelve a ejecutar `Level 4` o fuerza el comportamiento estricto:

```bash
INESDATA_LOCAL_IMAGES_MODE=required python3 main.py inesdata deploy --topology local
```

En `vm-distributed`, no se debe asumir que la imagen remota del chart tiene el
mismo contenido que la imagen local reconstruida desde `sources/`. Si la suite
Kafka se va a ejecutar en un cierre distribuido, configura
`INESDATA_CONNECTOR_IMAGE_NAME` e `INESDATA_CONNECTOR_IMAGE_TAG` con una imagen
publicada que incluya soporte `data-plane-kafka`, o activa explícitamente la
importación remota de imágenes durante una sesión de desarrollo.

## Level 4 Falla Preparando Imágenes INESData

En topología `local`, `Level 4` recompila `inesdata-connector` e
`inesdata-connector-interface` antes de crear los conectores. Si el log falla
en `Preparing artifacts for connector` con un error de `Gradle Worker Daemon`,
el problema está en el build local previo al despliegue, no en Helm ni en
Kubernetes.

El framework ejecuta Gradle de forma conservadora por defecto:

```text
--no-daemon --no-parallel -Dorg.gradle.workers.max=1
```

Si una máquina de desarrollo tiene más recursos y se quiere acelerar el build,
puede sobreescribirse con:

```bash
GRADLE_MAX_WORKERS=2 python3 main.py menu
```

## EDC Rechaza la Imagen por Defecto

En topología `local`, Level 4 prepara automáticamente la imagen local del
conector EDC cuando no hay overrides explícitos. Para ello usa:

```text
adapters/edc/scripts/build_image.sh --apply
```

Si quieres forzar una imagen concreta, o si estás preparando una topología VM,
define overrides explícitos:

```bash
PIONERA_EDC_CONNECTOR_IMAGE_NAME=validation-environment/edc-connector \
PIONERA_EDC_CONNECTOR_IMAGE_TAG=<tag> \
python3 main.py edc deploy --topology vm-distributed
```

Esta protección evita desplegar una imagen por defecto no verificada. Si la
preparación automática falla, revisa que Docker, Minikube y el repositorio bajo
`adapters/edc/sources/connector` estén disponibles.

## EDC Level 4 Falla con Credenciales Docker en WSL

En WSL con Docker Desktop, `~/.docker/config.json` puede contener
`credsStore=desktop` o `credsStore=desktop.exe`. Si esa configuración no es
usable desde la terminal WSL, `Level 4` de EDC puede fallar durante la
preparación automática de imágenes locales con un mensaje similar a:

```text
ERROR [internal] load metadata for docker.io/library/python:3.12-alpine
error getting credentials - err: exit status 1
```

El fallo ocurre antes del despliegue Kubernetes: Docker no puede resolver las
credenciales para descargar o inspeccionar la imagen base. El framework valida
la configuración Docker de WSL antes de construir imágenes locales EDC y elimina
automáticamente esos `credsStore` problemáticos, conservando el resto del
fichero. Después, vuelve a ejecutar `Level 4` desde el mismo menú.

## Playwright EDC Recibe 503 de NGINX

Si todas las pruebas UI de EDC fallan con un error de login y la captura muestra:

```text
503 Service Temporarily Unavailable
nginx
```

significa que el navegador no llegó a Keycloak ni al dashboard. Normalmente el
ingress existe, pero los servicios `*-dashboard` o `*-dashboard-proxy` no tienen
endpoints listos.

Comprueba:

```bash
kubectl get pods -n <dataspace>
kubectl get endpoints -n <dataspace>
```

En local, Level 4 prepara automáticamente las imágenes:

```text
validation-environment/edc-dashboard:latest
validation-environment/edc-dashboard-proxy:latest
```

Level 6 comprueba la disponibilidad de esos endpoints antes de lanzar
Playwright. Si no están listos, guarda el diagnóstico en
`experiments/<experiment>/ui/edc/dashboard_readiness.json`.

## Playwright INESData Falla Antes de Abrir el Portal

Si `Level 6` falla antes de lanzar Playwright para `inesdata`, o si el mensaje
indica que el portal no está listo, el problema suele estar en la ruta pública
del conector y no en la suite en sí.

Comprueba:

```bash
kubectl get pods -n <dataspace>
kubectl get endpoints -n <dataspace>
```

Y revisa que la ruta pública responda realmente:

```text
http://conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm/inesdata-connector-interface/
```

`Level 6` valida Keycloak, los servicios `*-interface` y esa ruta pública antes
de lanzar Playwright. Si falla, guarda el diagnóstico en:

```text
experiments/<experiment>/ui/inesdata/portal_readiness.json
```

## Una Topología VM Requiere Dirección

`vm-single` necesita una dirección de VM:

```bash
PIONERA_VM_EXTERNAL_IP=192.0.2.10 \
python3 main.py inesdata hosts --topology vm-single --dry-run
```

Si no hay dirección configurada, el CLI falla con un error claro de topología.

## Playwright Falla de Forma Intermitente

Comprueba:

- que la URL objetivo resuelve desde el entorno del navegador;
- que las entradas de `hosts` existen;
- que el dashboard o portal está desplegado;
- que el modo de autenticación coincide con la suite esperada;
- que el reporte en `experiments/` contiene screenshots, trazas o detalles de error.

## Level 6 Completo Falla por Endpoints Públicos Inaccesibles

Si `Level 6` falla antes de Newman, Playwright o Kafka con un mensaje sobre
hostnames públicos inaccesibles, el framework está detectando correctamente que
la capa pública local no está lista.

Revisa:

- `minikube tunnel` activo en otra terminal;
- entradas `hosts` sincronizadas;
- Ingress con dirección y backends activos;
- resolución DNS/hosts desde la misma máquina que ejecuta el framework.

Comandos útiles:

```bash
python3 main.py edc hosts --topology local --dry-run
kubectl get ingress -A
kubectl get endpoints -A
kubectl get endpointslices -A
```

En esta situación, no conviene intentar “forzar” un `Level 6` completo mediante
`port-forward`. La decisión actual del framework es mantener `hostname` como vía
normal para validación completa en `local`, de forma coherente con un entorno
más parecido a producción.

## Kafka Autoaprovisionado No Queda Listo a Tiempo

Si `Level 6` falla en la parte Kafka con mensajes sobre `port-forward`,
`bootstrap server` o `framework-kafka`, el problema suele venir de la
estabilización del broker temporal en Kubernetes local.

Comprueba:

```bash
kubectl get pods -n <dataspace>
kubectl get events -n <dataspace>
```

El framework valida el listener interno del broker y el listener externo usado
por `port-forward` antes de lanzar la suite Kafka. Si aun así falla, revisa:

- que `minikube` no haya entrado en `NodeNotReady`;
- que `framework-kafka` y `framework-kafka-external` existan en el namespace;
- que `minikube tunnel` siga activo si el entorno local lo requiere;
- el artefacto `kafka_runtime_preparation.json` dentro del experimento.

Si el broker local integrado en Kubernetes sigue siendo inestable en `local`,
puede probarse la variante opt-in:

```bash
PIONERA_KAFKA_PROVISIONER=kubernetes-split-kraft python3 main.py inesdata validate --topology local
```

Esta variante mantiene Kafka dentro de Kubernetes, pero separa `controller` y
`broker` para reducir flakes del provisionador local.

Cuando el problema no está en el broker sino en el acceso HTTP local a Keycloak
o a las management APIs durante la suite Kafka, el framework también puede usar
un fallback HTTP opt-in:

```bash
PIONERA_LEVEL6_LOCAL_HTTP_PORT_FORWARD_FALLBACK=true
```

Ese fallback está pensado para la fase Kafka de `Level 6` en `local`. No debe
interpretarse como sustituto del acceso público requerido por la validación
completa del nivel.

## Playwright INESData y Transferencias en STARTED

Si el test E2E de transferencia crea el asset, completa la negociación e inicia
la transferencia, `STARTED` es un estado aceptado para la validación UI de
INESData. La UI valida que el transfer fue aceptado e iniciado; la evidencia
fuerte de movimiento de datos debe venir de Newman, MinIO o verificaciones de
storage separadas.

Si la suite falla aunque el historial muestre `STARTED`, o si las validaciones
de almacenamiento fallan, revisa:

- el reporte `e2e-transfer-report.json` o `consumer-transfer-report.json` dentro del experimento;
- la colección Newman `06_consumer_transfer`;
- los logs del conector consumer y provider;
- la disponibilidad de MinIO y del dataplane;
- si `minikube tunnel` pidió contraseña y no quedó realmente activo.

No conviene resolver este caso sustituyendo el hostname por `port-forward`,
porque eso puede validar una ruta distinta a la que usaría el entorno local
publicado por Ingress.

## Transferencia Falla con Assets Subidos en Folder

Si un asset creado desde la UI aparece en catálogo pero la transferencia no
encuentra el objeto en MinIO/S3, comprueba si fue subido con un valor en el
campo `Folder`.

El objeto físico y el `DataAddress` del asset deben usar la misma key. Para
uploads con folder, la key esperada es:

```text
<folder>/<file>
```

El flujo E2E `adapters/inesdata/specs/05-e2e-transfer-flow.spec.ts` cubre este caso porque crea un
asset con folder, lo publica, lo descubre desde el consumidor y ejecuta
negociación y transferencia.

## EDC+Kafka Queda en STARTED o No Consume Mensajes

Cuando Kafka se activa con `PIONERA_LEVEL6_RUN_KAFKA=true`, `Level 6` ejecuta
la validación funcional EDC+Kafka después de Newman si el adapter tiene soporte
Kafka. En local, el broker gestionado por defecto se crea dentro de Kubernetes
para que el dataplane de los conectores lo alcance por DNS de cluster:

```text
framework-kafka.<namespace>.svc.cluster.local:9092
```

El proceso Python del framework puede abrir un `port-forward` temporal a
`127.0.0.1:<puerto>` para crear topics y verificar mensajes desde el host. Ese
`port-forward` es interno a la validación y no debe usarse como endpoint del
conector.

Si ves errores contra `host.minikube.internal:<puerto>` o transferencias que
quedan en `STARTED`, comprueba que no existan overrides antiguos como:

```text
KAFKA_BOOTSTRAP_SERVERS
KAFKA_CLUSTER_BOOTSTRAP_SERVERS
```

Para la ruta local normal, usa el modo por defecto:

```text
KAFKA_PROVISIONER=kubernetes
```

Durante una ejecución puedes inspeccionar el broker temporal con:

```bash
kubectl get pods,svc -n <dataspace> -l app=framework-kafka
```

Si el broker queda `ready`, los topics se crean bien y aun así la transferencia
termina en `TERMINATED` justo después de `start_transfer`, la causa habitual ya
no es el broker sino la imagen local del conector EDC. Ese patrón indica que el
control plane aceptó la transferencia, pero el runtime desplegado no incluía el
dataplane Kafka efectivo o seguía reutilizando una `connector.jar` obsoleta.
Desde esta versión, `adapters/edc/scripts/build_image.sh` reconstruye
automáticamente la jar cuando cambian los inputs del runtime para evitar ese
desalineamiento.

En `vm-distributed`, `Level 6` ejecuta un preflight específico antes de la suite
Kafka. Si el resultado queda como `kafka_runtime_preflight_failed`, revisa el
artefacto `kafka_runtime_preflight.json` del experimento. Las causas más
habituales son:

- `KAFKA_CLUSTER_BOOTSTRAP_SERVERS` vacío.
- `KAFKA_CLUSTER_BOOTSTRAP_SERVERS` apuntando a `localhost`, a
  `host.minikube.internal` o a un DNS interno `*.svc` de Kubernetes.
- Imagen de conector no fijada y flujo de imágenes locales/importación remota
  desactivado.

Para distribuida, la dirección Kafka del `DataAddress` debe ser una ruta
alcanzable desde todas las VMs de conectores, por ejemplo un `NodePort` expuesto
por la VM de servicios comunes o un endpoint equivalente acordado para ese
entorno.

## Se Acumulan Datos de Validación

Habilita o ejecuta limpieza previa cuando las pruebas repetidas creen demasiados datos.

La limpieza debe ser adapter-aware y escribir reporte bajo la carpeta del experimento actual.
