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

`vm-single` y `vm-distributed` ya forman parte del contexto del deployer y de la planificación de `hosts`. `vm-single` ya dispone de ejecución real para la ruta base del dataspace en `inesdata` y `edc`; `vm-distributed` sigue protegido por guardas hasta que exista una ruta Kubernetes cerrada para ese perfil.

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

Durante la migración, el framework sigue tolerando claves de topología en la
base común para no romper entornos existentes. Aun así, la CLI ya emite
warnings cuando detecta ese drift y te indica el overlay correcto, por ejemplo
`deployers/infrastructure/topologies/local.config` o
`deployers/infrastructure/topologies/vm-single.config`.

Los `deployer.config` de los adapters (`inesdata`, `edc`) siguen siendo
independientes de esta capa y conservan la identidad del dataspace, conectores,
componentes y flags propias de cada adapter.

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

El diagrama local de referencia está disponible en [Inicio rápido](./getting-started.md#vista-local).

## VM Single

`vm-single` representa una máquina virtual respaldada por Kubernetes. Para que
el quickstart sea reproducible, `Level 1` recrea por defecto el cluster
Minikube gestionado por el framework dentro de la VM y después ejecuta los
checks de acceso, ingress, storage y permisos.

Estado actual del framework:

- `inesdata`: `Level 1` a `Level 6` operativos, con `Level 5` compartido para componentes configurados
- `edc`: `Level 1` a `Level 4` y `Level 6` operativos
- `edc Level 5`: pendiente de soporte real de componentes

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

`vm-distributed` representa una topología distribuida de validación. La primera interpretación recomendada es un único cluster Kubernetes lógico respaldado por tres nodos/VM:

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

Esto valida placement físico por rol y comunicación entre nodos manteniendo un único plano de control Kubernetes. Un modo multi-cluster puede añadirse en el futuro si se convierte en requisito explícito.

## Interpretación del Diagrama VM3

El diagrama `vm3` debe leerse como una vista conceptual.

![PIONERA production validation environment](<./pionera production validation environment.png>)

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
