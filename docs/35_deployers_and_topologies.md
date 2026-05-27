# Deployers y Topologías

## Topologías Soportadas

El framework usa estos nombres canónicos:

```text
local
vm-single
vm-distributed
```

El menú puede mostrar alias más amigables:

```text
local  máquina local
vm1    una máquina virtual
vm3    tres máquinas virtuales
```

## Comportamiento Actual

`local` es la topología por defecto y la ruta soportada para despliegue normal.

`vm-single` y `vm-distributed` ya forman parte del contexto del deployer y de
la planificación de `hosts`. `vm-single` dispone de ejecución real para la ruta
base del dataspace. `vm-distributed` debe alinearse con la rama `main` antes de
considerarse una ruta operativa cerrada: no debe introducir namespaces propios
ni convenciones distintas a las que usan `local` y `vm-single`.

Esta protección evita ejecutar suposiciones locales contra un entorno VM allí donde la topología todavía no está cerrada.

## Convención de Nombres

Para variables de entorno exportadas por el usuario, la convención pública del
framework es `PIONERA_*`.

Ejemplos:

```text
PIONERA_VM_EXTERNAL_IP
PIONERA_VM_COMMON_IP
PIONERA_VM_PROVIDER_IP
PIONERA_VM_CONSUMER_IP
PIONERA_INGRESS_EXTERNAL_IP
```

En cambio, `deployer.config` conserva claves internas sin prefijo, por ejemplo
`VM_EXTERNAL_IP` o `INGRESS_EXTERNAL_IP`. Esto no significa que el usuario deba
exportar esas variables legacy: el loader convierte automáticamente los
overrides `PIONERA_*` a las claves internas de configuración.

### Nombres Públicos y Recursos SQL

Los nombres públicos de dataspace, namespaces, hostnames y realms de Keycloak
deben mantenerse en minúsculas. Pueden usar guiones cuando el recurso lo
permite; por ejemplo, `pionera-edc` es un nombre válido para un dataspace EDC y
su realm de Keycloak.

Los recursos SQL derivados del dataspace no usan guiones. El framework
normaliza internamente `-` a `_` al generar nombres de bases de datos y roles de
PostgreSQL. Por ejemplo, el dataspace `pionera-edc` genera:

```text
pionera_edc_rs
pionera_edc_rsusr
pionera_edc_wp
pionera_edc_wpusr
```

Estos nombres SQL deben derivarse de `DS_1_NAME`. No deben editarse
manualmente en los artefactos generados de despliegue.

## Capas de Configuración

La configuración compartida de infraestructura se resuelve ahora por capas:

```text
deployers/infrastructure/deployer.config
deployers/infrastructure/topologies/local.config
deployers/infrastructure/topologies/vm-single.config
deployers/infrastructure/topologies/vm-distributed.config
```

Regla práctica:

- `deployers/infrastructure/deployer.config` debe contener la base común y
  estable
- `deployers/infrastructure/topologies/*.config` debe contener solo overrides
  dependientes de la topología activa
- las variables `PIONERA_*` siguen teniendo prioridad máxima

El bootstrap crea automáticamente los `.config` locales desde sus
`.config.example` cuando aún no existen y no sobrescribe ficheros locales ya
ajustados. Los `.config.example` son las plantillas versionables; los `.config`
locales no deben subirse al repositorio.

Durante la migración, el framework sigue tolerando claves de topología en la
base común para no romper entornos existentes. Aun así, la CLI ya emite
warnings cuando detecta ese drift y te indica el overlay correcto, por ejemplo
`deployers/infrastructure/topologies/local.config` o
`deployers/infrastructure/topologies/vm-single.config`.

Los `deployer.config` de los adapters (`inesdata`, `edc`) siguen siendo
independientes de esta capa y conservan la identidad del dataspace, conectores,
componentes y flags propias de cada adapter.

## Namespaces Canónicos

El estado actual de `main` usa el perfil `role-aligned` para INESData. Todas las
topologías deben resolver los mismos roles de namespace:

```ini
COMMON_SERVICES_NAMESPACE=common-srvs
DS_1_NAME=pionera
DS_1_NAMESPACE=core-control
NAMESPACE_PROFILE=role-aligned
DS_1_REGISTRATION_NAMESPACE=core-control
DS_1_PROVIDER_NAMESPACE=provider
DS_1_CONSUMER_NAMESPACE=consumer
COMPONENTS_NAMESPACE=components
```

| Namespace | Rol |
| --- | --- |
| `common-srvs` | Servicios comunes: Keycloak, MinIO, PostgreSQL y Vault |
| `core-control` | Registration-service y control plane del dataspace |
| `provider` | Grupo/ubicación de conectores usado por los flujos base de validación |
| `consumer` | Grupo/ubicación de conectores usado por los flujos base de validación |
| `components` | Componentes opcionales: Ontology Hub, AI Model Hub y Semantic Virtualization |
| `ingress-nginx` | Ingress controller del cluster |
| `kube-system` | Infraestructura Kubernetes |

Los nombres `provider` y `consumer` son convenciones del entorno de validación,
no roles funcionales rígidos. Un conector puede actuar como proveedor o consumidor
según el flujo de prueba. Para más de dos conectores, define el inventario en
`DS_1_CONNECTORS` y, si necesitas controlar su ubicación, usa
`DS_1_CONNECTOR_NAMESPACES`:

```ini
DS_1_CONNECTORS=citycouncil,company,partnera
DS_1_CONNECTOR_NAMESPACES=citycouncil:provider,company:consumer,partnera:provider
DS_1_VALIDATION_PAIRS=citycouncil>company,partnera>citycouncil
LEVEL4_CONNECTOR_RECONCILIATION_MODE=full
```

En los archivos `deployer.config.example`, estas claves aparecen vacías de forma
intencional para conservar el despliegue actual:

```ini
DS_1_CONNECTOR_NAMESPACES=
DS_1_VALIDATION_PAIRS=
```

Con esos valores vacíos, el framework usa la convención histórica: el primer
conector de `DS_1_CONNECTORS` queda asociado al grupo `provider`, el segundo al
grupo `consumer` y los conectores adicionales al namespace del dataspace. Solo
es necesario llenar estas variables cuando se quiera controlar explícitamente la
ubicación de cada conector o ejecutar pares de validación distintos al par base.

`DS_1_CONNECTOR_NAMESPACES` decide dónde se despliega cada conector.
`DS_1_VALIDATION_PAIRS` decide qué pares se usan como origen/destino en las
validaciones automatizadas. `LEVEL4_CONNECTOR_RECONCILIATION_MODE=full`
conserva el comportamiento histórico de nivel 4: reconcilia el conjunto
configurado y puede recrear conectores existentes para dejar un despliegue
limpio. Para añadir conectores sin recrear los que ya están sanos, usa
`LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive`.

Si las claves de mapeo no se definen, el framework conserva el comportamiento
histórico: primer conector como origen de validación, segundo como destino de
validación y conectores adicionales en el namespace del dataspace.

Para Semantic Virtualization, el nivel 5 sincroniza las fuentes necesarias para
la validación del componente: `morph-kgv`, `mapping-editor` y `Automap`.
`morph-kgv` se empaqueta como API runtime, `mapping-editor` se despliega cuando
la UI/editor está habilitada y `Automap` queda disponible como herramienta de
generación de mappings para trazabilidad, readiness y una línea base
determinista de nivel 6. Esa línea base no invoca LLM ni lee secretos: usa
fixtures versionados para comprobar extracción de esquema/ontología,
reutilización de una ontología gobernable por Ontology Hub, materialización RDF
controlada y métricas de evaluación.

La validación de `morph-kgv` comprueba además que el source sincronizado expone
el contrato actual del componente: instalación versionable, `run_query.py`,
`morph-kgv serve config.ini`, ejemplos `config.ini` y endpoint `/sparql`.

La resolución central vive en:

```text
deployers/shared/lib/namespaces.py
deployers/inesdata/deployer.config.example
```

La topología distribuida debe cambiar placement, direcciones y routing, pero no
debe cambiar estos nombres funcionales salvo que se introduzca una migración
explícita y compatible en el resolvedor común de namespaces.

## Arranque en Frío y Readiness

En una instalación limpia o después de reiniciar el entorno, algunos servicios
pueden requerir más tiempo para estar operativos aunque sus recursos de
Kubernetes ya existan. Esto aplica especialmente a `local` y `vm-single`, donde
imágenes locales, volúmenes persistentes, DNS interno, Vault, Keycloak, bases de
datos, conectores y componentes se inicializan en la misma máquina.

Si un nivel falla por timeout de readiness, se deben revisar los logs del
componente y del servicio dependiente antes de relanzar el nivel afectado. Una
reejecución puede completarse correctamente cuando el primer intento ya dejó
inicializados recursos persistentes o imágenes locales. Este comportamiento no
debe ocultar fallos recurrentes: si el error se reproduce tras reinicio o desde
un entorno limpio, debe tratarse como incidencia del framework, del despliegue o
del componente correspondiente.

## Local

`local` usa Minikube.

Flujo típico:

```bash
python3 main.py menu
python3 main.py inesdata hosts --topology local --dry-run
python3 main.py edc hosts --topology local --dry-run
```

Las entradas de `hosts` normalmente resuelven a `127.0.0.1` y dependen de
`minikube tunnel` para exponer Ingress en topología `local`.

Si un entorno concreto necesita una dirección distinta de loopback, puede
declararla explícitamente en:

```text
LOCAL_HOSTS_ADDRESS
LOCAL_INGRESS_EXTERNAL_IP
```

Estas claves deben vivir en:

```text
deployers/infrastructure/topologies/local.config
```

Si esas claves están vacías, el framework mantiene el modo loopback canónico.

### Dimensionamiento Local

Para una máquina local con Docker Desktop y una pila completa de validación,
declara también los recursos de Minikube en el overlay local:

```text
LOCAL_RESOURCE_PROFILE=coexistence
MINIKUBE_DRIVER=docker
MINIKUBE_CPUS=10
MINIKUBE_MEMORY=18432
MINIKUBE_PROFILE=minikube
```

Esta recomendación no sale de una regla genérica, sino de la degradación
observada durante `Level 6` en local:

- Docker Desktop mostraba `20 CPUs available` y `14.9 GB` disponibles para el
  motor.
- El contenedor `minikube` tenía un límite cgroup real de `12884901888` bytes,
  es decir `12 GiB`.
- Kubernetes veía el nodo con `20 CPU` y `15996068Ki` de memoria, unos
  `15.25 GiB`.
- Por tanto, el scheduler de Kubernetes podía razonar sobre más memoria de la
  que Docker permitía realmente al contenedor.
- El cgroup de Minikube registró `oom_kill=3` y los eventos Kubernetes
  registraron `SystemOOM`, `NodeNotReady`, reinicios de Keycloak, Ontology Hub,
  Elasticsearch, AI Model Hub, conectores y `storage-provisioner`.
- La ejecución local ya contenía servicios comunes, un dataspace INESData,
  componentes, Kafka y suites de validación Newman, Kafka y Playwright.
- Muchos pods de aplicación estaban en QoS `BestEffort`, sin requests ni
  limits, por lo que Kubernetes no podía reservar memoria de forma fiable ni
  protegerlos durante presión de memoria.

La estimación se calcula así:

- consumo estable observado tras recuperación: aproximadamente `5.1 GiB` en el
  contenedor Minikube;
- pico cgroup observado: aproximadamente `9.3 GiB`, pero ya con OOM, por lo que
  el pico real necesario era superior al margen disponible;
- límite efectivo actual: `12 GiB`, insuficiente porque produjo `SystemOOM` y
  `NodeNotReady`;
- margen mínimo adicional para control plane, probes, Kafka, navegador
  Playwright, JVMs y cachés: `3-4 GiB`;
- margen adicional si en la misma topología local se mantienen `inesdata` y
  `edc` instalados, con dos dataspaces y sus conectores: `2-4 GiB`;
- rango estable resultante para el cluster local completo: `16-18 GiB`;
- punto recomendado si el host lo permite: `18 GiB` para Minikube y `10 CPU`.

Reglas prácticas:

- no configures `MINIKUBE_MEMORY` por encima de la memoria que Docker Desktop
  puede asignar al motor;
- deja al menos `4-6 GiB` fuera de Minikube para WSL, Docker Desktop, VS Code,
  navegador y el proceso Python/Node de las pruebas;
- si Docker Desktop permanece en torno a `14.9 GB`, el modo local completo con
  `inesdata`, `edc`, componentes y `Level 6` no es reproducible de forma
  estable; en ese caso usa un adapter cada vez o ejecuta la validación completa
  en `vm-single`;
- `8 CPU / 12288 MB` queda como perfil mínimo de desarrollo o smoke test, no
  como baseline estable para `Level 6` completo con ambos adapters;
- `10 CPU / 16384 MB` es el mínimo razonable para una validación local más
  exigente si Docker Desktop dispone de al menos `20 GB`;
- `10 CPU / 18432 MB` es el baseline recomendado cuando se pretende validar
  localmente la coexistencia de `inesdata` y `edc`;
- `Level 1` consulta la memoria real expuesta por Docker Desktop y avisa si el
  entorno queda en perfil de un solo adapter;
- `Level 3/4/5` bloquean la instalación o ampliación del segundo adapter local
  cuando ya existe otro adapter activo y la capacidad efectiva es inferior al
  baseline de coexistencia; en modo interactivo ofrecen un cambio controlado de
  adapter que borra únicamente los namespaces y artefactos runtime gestionados
  del adapter anterior, preservando `common-srvs`, y exige confirmación exacta
  antes de ejecutar la limpieza;
- en ejecución no interactiva, el cambio local de adapter se considera
  destructivo y requiere `PIONERA_LOCAL_ADAPTER_SWITCH_CONFIRM` con el valor
  `SWITCH TO EDC` o `SWITCH TO INESDATA`;
- `Level 6` en modo estable evalúa la capacidad local antes de ejecutar las
  suites; si detecta `inesdata` y `edc` conviviendo con menos de `18432 MB`
  efectivos, bloquea la validación para evitar resultados contaminados por
  `NodeNotReady`;
- no conviene interpretar `401`, `500` o crashes funcionales de la aplicación
  como un problema de CPU por defecto, pero sí deben considerarse contaminados
  si el postflight de `Level 6` registra OOM, `NodeNotReady` o reinicios nuevos.

Si se cambia `MINIKUBE_CPUS` o `MINIKUBE_MEMORY`, hay que recrear el cluster
desde `Level 1`, porque Minikube no redimensiona de forma fiable un perfil ya
creado por el framework. Antes de hacerlo, sube primero el límite de recursos de
Docker Desktop para que el nuevo valor de Minikube tenga soporte real.

Para reproducibilidad, `Level 6` en topología `local` resuelve
`--validation-mode auto` como `stable`. Este modo conserva las mismas suites y
aserciones, pero reduce el solapamiento entre Newman, Kafka, Playwright y
componentes. Si necesitas priorizar velocidad en local, usa
`--validation-mode fast` o `PIONERA_VALIDATION_MODE=fast`.

Como parte de ese modo estable, `Level 6` valida la salud del runtime local con
`kubectl` antes de lanzar las suites y vuelve a tomar una muestra al final. Los
artefactos `local_stability_preflight.json` y
`local_stability_postflight.json` ayudan a separar fallos de aplicación de
reinicios de pods o eventos `NodeNotReady`.

El diagrama local de referencia está disponible en [Inicio rápido](./32_getting_started.md#vista-local).

## VM Single

`vm-single` representa una máquina virtual respaldada por Kubernetes. Para que
el quickstart sea reproducible, `Level 1` recrea por defecto el cluster
Minikube gestionado por el framework dentro de la VM y después ejecuta los
checks de acceso, ingress, storage y permisos.

Estado actual del framework:

- `inesdata`: `Level 1` a `Level 6` operativos, con `Level 5` compartido para componentes configurados
- `edc`: `Level 1` a `Level 6` operativos, con `Level 5` compartido para componentes configurados y guarda de extensiones del conector

La topología necesita una dirección externa, suministrada mediante una de estas variables:

```text
PIONERA_VM_EXTERNAL_IP
PIONERA_VM_SINGLE_IP
PIONERA_VM_SINGLE_ADDRESS
PIONERA_HOSTS_ADDRESS
PIONERA_INGRESS_EXTERNAL_IP
PIONERA_MINIKUBE_DRIVER
PIONERA_MINIKUBE_CPUS
PIONERA_MINIKUBE_MEMORY
PIONERA_MINIKUBE_PROFILE
```

Ejemplo:

```bash
PIONERA_VM_EXTERNAL_IP=192.0.2.10 \
python3 main.py edc hosts --topology vm-single --dry-run
```

Cómo obtener la IP correcta:

```bash
hostname -I
minikube ip
kubectl get ingress -A
```

Regla práctica:

- usa la IP de `hostname -I` solo como valor provisional inicial;
- en la mayoría de instalaciones con Minikube `docker`, el valor final bueno será `minikube ip`;
- deja la IP de la VM como valor final solo si el ingress está publicado explícitamente sobre esa IP o detrás de un proxy externo que termina allí;
- después de `Level 1`, si `minikube ip` no coincide con la IP configurada, actualiza el override de entorno `PIONERA_VM_EXTERNAL_IP` o la clave `VM_EXTERNAL_IP` dentro de `deployers/infrastructure/topologies/vm-single.config` antes de `Levels 3-6`.

Las claves persistidas de `vm-single` deben vivir en:

```text
deployers/infrastructure/topologies/vm-single.config
```

## VM Distributed

`vm-distributed` representa una topología distribuida de validación. El modelo
de configuración actual permite preparar tanto un único cluster Kubernetes lógico
con varios nodos/VM como una evolución multi-cluster basada en kubeconfigs por
rol. La interpretación base sigue siendo:

```text
common    servicios comunes
provider  conector proveedor
consumer  conector consumidor
```

Los labels esperados para los nodos son:

```text
pionera.role=common
pionera.role=provider
pionera.role=consumer
```

Esto valida placement físico por rol y comunicación entre nodos manteniendo un
único plano de control Kubernetes. Para despliegues con infraestructura externa, donde los
conectores pueden vivir en VMs o servidores distintos, el asistente del menú
también recoge kubeconfigs por rol (`common`, `provider`, `consumer`) para que la
implementación operativa de `vm-distributed` pueda evolucionar sin reabrir el
modelo de configuración.

La ejecución real actual de `vm-distributed` está habilitada para el caso
conservador de un cluster Kubernetes lógico distribuido. En ese modo,
`K3S_KUBECONFIG_COMMON` debe apuntar a un kubeconfig que permita operar los
namespaces de servicios comunes, dataspace, conectores y componentes. El nivel 5
puede usar `K3S_KUBECONFIG_COMPONENTS` si se necesita dirigir los componentes a
un contexto específico. En nivel 4, si `K3S_KUBECONFIG_PROVIDER` y
`K3S_KUBECONFIG_CONSUMER` apuntan a API servers distintos de
`K3S_KUBECONFIG_COMMON`, el framework aborta antes de desplegar conectores. Esa
protección evita mezclar el bootstrap de servicios comunes con un Helm deploy de
conectores en otro cluster mientras no esté implementado el flujo multi-cluster
completo.

### Asistente de Configuración

En el menú interactivo, la opción `W - Configure vm-distributed deployment`
prepara los ficheros locales necesarios para la topología:

```text
deployers/infrastructure/deployer.config
deployers/infrastructure/topologies/vm-distributed.config
deployers/<adapter>/deployer.config
```

El asistente pregunta por dominios, IP/DNS de VMs, kubeconfigs k3s, conectores,
ubicación de conectores y pares de validación. Si no se conoce un dato, se puede
escribir `?` en el campo para ver qué significa, cómo elegirlo y qué comandos de
Ubuntu ayudan a descubrirlo. Para el inventario de conectores, el asistente
propone una ubicación inicial alternando los grupos `provider` y `consumer`; ese
valor se puede editar antes de guardar. El asistente solo escribe `.config`
locales ignorados por Git y no ejecuta despliegues por sí mismo.

Al guardar, el asistente imprime un preflight con checklist de dominios,
direcciones, kubeconfigs, inventario de conectores, ubicación, pares de
validación, modo de reconciliación, alcance de nivel 4 y plan de hosts. Si el
checklist marca `blocked` en el alcance de nivel 4, la configuración describe un
despliegue multi-kubeconfig real y el framework lo bloquea de forma preventiva
hasta que exista soporte multi-cluster completo.

Para despliegues con conectores externos o infraestructura distribuida, revisa
[Preparación de conectores externos](./45_external_connector_readiness.md)
antes de ejecutar niveles de despliegue.

### Alineamiento Requerido con `main`

Para cerrar `vm-distributed`, la implementación debe partir de la rama remota
`main` y conservar el contrato común del framework:

- usar los namespaces canónicos descritos en este documento;
- mantener `NAMESPACE_PROFILE=role-aligned`;
- resolver `common-srvs`, `core-control`, `provider`, `consumer` y `components`
  mediante `deployers/shared/lib/namespaces.py`;
- mover workloads entre nodos con labels, `nodeSelector`, affinity o tolerations,
  no mediante nombres alternativos de namespace;
- mantener las colecciones Newman, la validación Kafka y Playwright consumiendo
  las mismas variables de adapter que `local` y `vm-single`;
- guardar los overrides propios de la topología en
  `deployers/infrastructure/topologies/vm-distributed.config`;
- usar variables públicas `PIONERA_*` para overrides de usuario.

Checklist mínimo antes de declarar la topología operativa:

1. `python3 main.py inesdata hosts --topology vm-distributed --dry-run` genera
   entradas coherentes.
2. El plan de despliegue muestra los mismos namespace roles que `local` y
   `vm-single`.
3. `Level 1` valida acceso Kubernetes, ingress, storage y permisos.
4. `Level 2` despliega `common-srvs`.
5. `Level 3` despliega `core-control`.
6. `Level 4` despliega conectores en `provider` y `consumer`.
7. `Level 5` despliega componentes en `components` cuando estén configurados.
8. `Level 6` ejecuta Newman, Kafka, Playwright y validaciones de componentes sin
   rutas especiales hardcodeadas para `vm-distributed`.

## Interpretación del Diagrama VM3

El diagrama `vm3` debe leerse como una vista conceptual.

![PIONERA distributed validation environment](<./pionera_distributed_validation_environment.png>)

En la primera implementación, `vm3` significa un único cluster Kubernetes o k3s con tres nodos respaldados por VM. Los namespaces pertenecen al cluster. Los workloads se programan sobre la VM/nodo esperado usando labels, `nodeSelector` o affinity.

La EDC Management API se considera interna u orientada a operación. Las interacciones públicas entre participantes deben ocurrir mediante los endpoints de protocolo de conector, catálogo, negociación y transferencia.

## Routing

El modelo de routing por defecto es host-based:

```text
keycloak.<domain>
minio.<domain>
registration-service-<dataspace>.<ds-domain>
conn-<connector>-<dataspace>.<ds-domain>
```

El routing path-based puede añadirse más adelante si un único dominio público se convierte en requisito estricto.
