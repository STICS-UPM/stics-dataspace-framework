# Medidas Reales de Kafka

En la secuencia de evolución descrita desde [07_experiment_system.md](./07_experiment_system.md), la Fase 3 distingue dos capas complementarias:

- benchmark de broker Kafka en `kafka_metrics.json`
- validación funcional Kafka transfer en `kafka_transfer_results.json`

## Alcance

Esta fase mantiene el benchmark de broker Kafka como opcional, pero hace que su resultado sea explícito y repetible desde los caminos de ejecución activos:

- `python main.py inesdata metrics --kafka`
- `python main.py inesdata run --kafka`
- `python main.py menu` -> `M - Run metrics / benchmarks`

La activación del benchmark de broker para usuarios debe hacerse desde el CLI o el menú, no desde `deployer.config`. En el menú, la pregunta `Enable standalone Kafka broker benchmark?` se refiere solo a este benchmark independiente del broker. La suite funcional avanzada `EDC+Kafka`, inspirada en el sample oficial `Transfer06KafkaBrokerTest` de EDC, queda separada del benchmark de broker y puede ejecutarse en `Level 6`, después de Newman, para los adaptadores `inesdata` y `edc`. Por defecto queda desactivada para ahorrar tiempo durante las validaciones rutinarias.

Cuando se activa en `Level 6`, la preparación del broker Kafka
arranca en segundo plano al comenzar el nivel, mientras Newman sigue en primer
plano. Esto reduce espera total sin alterar el flujo de Newman.

## Salida

Toda ejecución con Kafka habilitado debe dejar:

- `kafka_metrics.json`

Cuando se ejecuta `Level 6`, la suite Kafka transfer deja además:

- `kafka_transfer_results.json`
- `kafka_transfer/<provider>__<consumer>.json`

`kafka_metrics.json` debe contener siempre un estado de ejecución:

- `completed`
- `skipped`

`kafka_transfer_results.json` contiene una lista de resultados por par proveedor-consumidor:

- `passed`
- `failed`
- `skipped`

En consola, la suite se muestra con una salida neutral como `Kafka transfer
validation` para que el resultado no quede acoplado al nombre de un adapter. La
salida normal imprime cada par proveedor-consumidor cuando termina, usando
iconos de estado y un resumen final. El detalle incluye pasos ejecutados,
topics, mensajes producidos y consumidos, latencias y throughput. El detalle de
muestras de mensajes puede habilitarse con
`PIONERA_KAFKA_TRANSFER_LOG_MESSAGES=true`.

## Payload Completado

Cuando un broker es alcanzable, el payload incluye:

- `status`
- `topic`
- `messages_produced`
- `messages_consumed`
- `average_latency_ms`
- `p50_latency_ms`
- `p95_latency_ms`
- `p99_latency_ms`
- `throughput_messages_per_second`
- `broker_source`
- `bootstrap_servers`

## Payload Omitido

Cuando Kafka no puede alcanzarse o arrancarse, el payload sigue existiendo e incluye:

- `status=skipped`
- `reason`
- `broker_source` cuando se conozca
- `bootstrap_servers` cuando se conozcan

## Resolucion del Broker

La resolucion del broker sigue este orden:

1. variables de entorno
2. configuración Kafka del adapter
3. overrides de ejecución
4. broker Kafka gestionado por el framework dentro de Kubernetes

El modo por defecto para validaciones locales integradas es `kubernetes`. En ese
modo, el framework crea temporalmente un `Deployment` y dos `Service` en el
namespace del dataspace:

- `framework-kafka` para clientes dentro del cluster;
- `framework-kafka-external` para el acceso temporal desde el host mediante
  `kubectl port-forward`.

El dataplane de los conectores debe usar el bootstrap interno:

```text
framework-kafka.<namespace>.svc.cluster.local:9092
```

El proceso Python del framework puede usar un `port-forward` temporal hacia
`127.0.0.1:<puerto>` para crear topics, producir mensajes de prueba y consumir
el topic destino desde el host. Ese `port-forward` es un detalle de soporte de
la validación, no el endpoint funcional que deben usar los conectores.

Antes de dar el broker por listo, el framework valida tanto el listener interno
del cluster como el listener externo usado por el `port-forward`.

Cuando interesa una variante local más estable sin salir de Kubernetes, puede
activarse explícitamente:

```bash
PIONERA_KAFKA_PROVISIONER=kubernetes-split-kraft
```

Esa variante separa `controller` y `broker` dentro del namespace Kafka y sigue
siendo opt-in. No sustituye automáticamente al provisionador `kubernetes`
histórico.

## Configuración del Broker

El broker Kafka puede configurarse con:

- `KAFKA_PROVISIONER`, con valor por defecto `kubernetes`;
- `KAFKA_K8S_NAMESPACE`, por defecto el namespace del dataspace;
- `KAFKA_K8S_SERVICE_NAME`, por defecto `framework-kafka`;
- `KAFKA_K8S_LOCAL_PORT`, por defecto `39092`;
- `KAFKA_MINIKUBE_PROFILE`, por defecto `minikube`;
- `container_env_file`
- `container_env`
- `KAFKA_EDC_STARTUP_GRACE_SECONDS` cuando la transferencia Kafka necesita unos segundos extra para estabilizar el dataplane antes de empezar a producir mensajes de medida. El valor por defecto actual es `60` segundos y la suite usa mensajes sonda antes de empezar a medir latencias reales.
- `KAFKA_EDC_PRE_RUN_SETTLE_SECONDS` cuando interesa dejar una pequeña ventana de asentamiento tras limpiar transferencias y recursos Kafka EDC anteriores. El valor por defecto actual es `10` segundos y ayuda a reducir flakes cuando el dataplane todavía está cerrando consumidores o productores viejos.
- `KAFKA_EDC_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS` cuando el runtime EDC necesita unos segundos para que el acuerdo contractual ya finalizado sea visible en proveedor y consumidor antes de iniciar `Kafka-PUSH`. El valor por defecto actual es `30` segundos y evita carreras transitorias con errores `404 Not found` al arrancar la transferencia.
- `KAFKA_EDC_MESSAGE_SAMPLE_LIMIT`, por defecto `5`, para limitar cuántos IDs de mensajes quedan como muestra en los artefactos y pueden imprimirse en consola cuando se habilita el modo verbose.

La suite funcional Kafka de `Level 6` es opt-in. Para ejecutarla junto con el
resto de pruebas, usa:

```bash
PIONERA_LEVEL6_RUN_KAFKA=true
```

En una ejecución interactiva de `Level 6`, el framework pregunta
`Run Kafka validation suites too?` como primera acción visible para activar
esta suite. La variable anterior queda como mecanismo explícito para
automatización, CI o ejecuciones no interactivas.

Para asegurar que Kafka se omite temporalmente aunque exista una configuración
previa de ejecución, usa:

```bash
PIONERA_LEVEL6_SKIP_KAFKA=true
```

Con esa variable, el framework no prepara el broker Kafka ni ejecuta la suite
`EDC+Kafka`, y deja `kafka_transfer_results.json` con estado `skipped`. Para
volver a ejecutar Kafka, elimina la variable o asígnala a `false`, y define
`PIONERA_LEVEL6_RUN_KAFKA=true`. La suite Kafka sigue formando parte del alcance
final de `Level 6`, pero no bloquea las iteraciones rápidas por defecto.

El modo `docker` sigue disponible para desarrollo avanzado mediante
`KAFKA_PROVISIONER=docker`, pero no es el default de `Level 6`. En local, usar
Docker como broker externo puede dejar al dataplane apuntando a
`host.minikube.internal:<puerto>` y provocar que la transferencia quede en
`STARTED` sin mover mensajes si ese puerto no es alcanzable desde los pods.

Para `Level 6` completo en `local`, la validación sigue dependiendo de
hostnames públicos funcionales para Keycloak y los conectores. El broker Kafka
puede apoyarse en `port-forward` internos del framework, pero eso no convierte
el flujo completo en válido si la capa pública local no está disponible.

Cuando la suite Kafka necesita recuperarse de un problema HTTP local puntual en
Keycloak o en la management API del conector, puede activarse:

```bash
PIONERA_LEVEL6_LOCAL_HTTP_PORT_FORWARD_FALLBACK=true
```

Ese fallback está limitado a la fase Kafka de `Level 6` en `local`. No debe
usarse como sustituto de Ingress, `hosts` o `minikube tunnel` para la validación
completa del nivel.

La ruta local normal no requiere declarar variables Kafka en los
`deployer.config`. El framework usa defaults reproducibles y los ficheros
`deployer.config.example` se mantienen con las claves mínimas del adapter o de
infraestructura.

Si un entorno necesita overrides persistentes o experimentales, pueden definirse
como variables de entorno `PIONERA_KAFKA_*` al entrar por `main.py`, como
variables `KAFKA_*` al ejecutar helpers específicos, o como claves
adapter-specific en el `deployer.config` del adapter correspondiente:

- `KAFKA_PROVISIONER`
- `KAFKA_BOOTSTRAP_SERVERS`
- `KAFKA_CLUSTER_BOOTSTRAP_SERVERS`
- `KAFKA_CLUSTER_ADVERTISED_HOST`
- `KAFKA_K8S_NAMESPACE`
- `KAFKA_K8S_SERVICE_NAME`
- `KAFKA_K8S_LOCAL_PORT`
- `KAFKA_MINIKUBE_PROFILE`
- `KAFKA_TOPIC_NAME`
- `KAFKA_TOPIC_STRATEGY`
- `KAFKA_SECURITY_PROTOCOL`
- `KAFKA_CONTAINER_NAME`
- `KAFKA_CONTAINER_IMAGE`
- `KAFKA_CONTAINER_ENV_FILE`

El adapter `inesdata` reutiliza esos valores tanto para `main.py --kafka` como
para `main.py menu` en `Level 6`. En EDC deben usarse solo cuando el runtime
EDC desplegado exponga soporte Kafka equivalente.

## Runtime del Conector

El framework ya deja activada en el código fuente local del conector la dependencia `data-plane-kafka`, que es la pieza EDC necesaria para un escenario de transferencia Kafka real.

Eso significa:

- el benchmark persistido sigue siendo de broker
- la imagen local del conector ya queda preparada para construir un runtime con soporte Kafka
- el validador `EDC+Kafka` puede ya ejercer un flujo completo `asset -> catálogo -> negociación -> transfer Kafka-PUSH -> consumo del topic destino`
- ese flujo se ejecuta como suite opt-in de `Level 6`, independiente del benchmark, para no mezclar latencia del broker con latencia del intercambio mediado por EDC

## Broker Autoaprovisionado

Cuando la suite `EDC+Kafka` no recibe un broker accesible y el framework lo autoaprovisiona, el broker se levanta dentro de Kubernetes con dos listeners anunciados:

- listener de host para el productor, consumidor y admin client locales
- listener de cluster para el dataplane del conector dentro de Kubernetes

Eso evita que el dataplane reciba `localhost:<puerto>` como metadato del broker, que era la causa principal de los fallos cuando la transferencia entraba en `STARTED` pero no movía mensajes reales.

Al terminar, el framework debe eliminar el `Deployment`, los `Service` y el
`port-forward` temporal asociados al broker gestionado.

Durante la ejecución secuencial de varios pares proveedor-consumidor, el
framework intenta reutilizar el broker ya preparado en lugar de destruirlo al
primer error transitorio. Esto reduce flakes en `minikube` y hace más estable la
validación integrada de `Level 6`.

## Notas

- `kafka_metrics.json` y `kafka_transfer_results.json` responden a preguntas distintas y no deben compararse directamente.
- `kafka_metrics.json` mide el broker.
- `kafka_transfer_results.json` mide el flujo Kafka transfer mediado por el conector sobre un topic fuente y un topic destino.
- Si la suite `EDC+Kafka` falla mientras el benchmark pasa, el problema suele estar en el flujo de transferencia o en el runtime del conector, no en el broker base.
