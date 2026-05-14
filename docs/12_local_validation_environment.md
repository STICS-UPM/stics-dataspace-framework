# 12. Entorno Local de Validación

El entorno local concentra el dataspace en un único cluster `Minikube`. Sirve
como baseline reproducible para desarrollo, validación API, validación UI,
componentes y experimentos.

![PIONERA local validation environment](<./pionera_local_validation_environment.png>)

## Capas

| Capa | Elementos |
| --- | --- |
| Infraestructura | `Minikube`, `ingress`, `minikube tunnel` |
| Servicios comunes | PostgreSQL, Keycloak, MinIO, Vault |
| Dataspace | `registration-service`, public portal INESData cuando aplica |
| Conectores | Provider y consumer del adapter activo |
| Componentes | `ontology-hub`, `ai-model-hub` cuando están habilitados |
| Validación | Newman, Playwright, validaciones de componentes, métricas |

## Presupuesto de Recursos

El entorno local no debe dimensionarse solo por el consumo en reposo. `Level 6`
mantiene desplegados servicios comunes, dataspace, conectores, componentes,
Kafka y runners Newman/Playwright, por lo que los picos de memoria son más
relevantes que el uso estable mostrado por Docker Desktop.

La estimación canónica para Minikube local está documentada en
[Deployers y Topologías](./35_deployers_and_topologies.md#dimensionamiento-local).
Como baseline reproducible para validar `inesdata` y `edc` en la misma
topología local, usa `10 CPU / 18432 MB` solo si Docker Desktop dispone de
margen suficiente. Si Docker Desktop permanece alrededor de `14.9 GB`, el
entorno local completo no debe considerarse estable para `Level 6` con ambos
adapters; usa un adapter cada vez o mueve la validación completa a `vm-single`.

El overlay local versionable está en:

```text
deployers/infrastructure/topologies/local.config
```

Puede subirse al repositorio siempre que conserve solo valores no sensibles,
como `localhost`, hostnames de desarrollo y recursos de Minikube. No debe
contener contraseñas, tokens, rutas personales, IP privadas de una instalación
real ni credenciales cloud. Los secretos siguen viviendo en los
`deployer.config` locales o en artefactos runtime ignorados por Git.

La configuración local de referencia para un adapter cada vez es:

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

Para coexistencia local limpia de `inesdata` y `edc`, cambia el perfil a
`LOCAL_RESOURCE_PROFILE=coexistence`, sube `MINIKUBE_MEMORY` a `18432` y recrea
el cluster desde `Level 1`. Si Docker Desktop no puede asignar esa memoria,
mantén la ejecución local en un adapter cada vez o usa `vm-single`. En ese caso,
el framework avisará en `Level 1` y bloqueará `Level 3/4/5` cuando detecte que
se intenta instalar un segundo adapter sobre una capacidad local insuficiente.
Si el usuario confirma el cambio en una terminal interactiva, el framework puede
eliminar solo el adapter local anterior: borra sus namespaces gestionados y sus
artefactos runtime bajo `deployers/<adapter>/deployments`, preservando
`common-srvs`. En ejecución no interactiva, la limpieza requiere
`PIONERA_LOCAL_ADAPTER_SWITCH_CONFIRM` con el valor exacto que muestra el
framework, por ejemplo `SWITCH TO EDC`.

## Namespaces Locales

| Rol | Namespace habitual |
| --- | --- |
| Servicios comunes | `common-srvs` |
| Dataspace INESData / control | `core-control` |
| Conector INESData provider | `provider` |
| Conector INESData consumer | `consumer` |
| Dataspace EDC / control | `edc-control` |
| Conector EDC provider | `edc-provider` |
| Conector EDC consumer | `edc-consumer` |
| Componentes | `components` |

Los nombres reales se resuelven desde `deployers/<adapter>/deployer.config`,
variables `PIONERA_*` y los defaults del deployer.

## Servicios Comunes

Los servicios comunes son compartidos por los adapters:

- PostgreSQL para persistencia;
- Keycloak para identidad y clientes técnicos;
- MinIO para almacenamiento S3;
- Vault para secretos y material criptografico.

Los charts fuente viven en `deployers/shared/common/`. Los ficheros runtime con
secretos o valores generados no se versionan.

## Dataspace y Conectores

`Level 3` despliega el dataspace base. `Level 4` despliega los conectores del
adapter activo:

| Adapter | Runtime de conectores |
| --- | --- |
| `inesdata` | Conectores INESData con interfaz propia |
| `edc` | Runtime EDC generico con dashboard EDC |

La convencion local de host para conectores es:

```text
conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm
```

La interfaz INESData no vive en la raiz del host. Se accede normalmente con:

```text
http://conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm/inesdata-connector-interface
```

El dashboard EDC usa:

```text
http://conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm/edc-dashboard/
```

## Hosts Locales

El framework puede planificar y aplicar entradas en `/etc/hosts` o en el fichero
indicado por `PIONERA_HOSTS_FILE`. La sincronización es idempotente: las entradas
existentes se omiten y solo se agregan las faltantes.

Comando de planificacion:

```bash
python3 main.py edc hosts --topology local --dry-run
```

Comando de aplicación:

```bash
PIONERA_SYNC_HOSTS=true python3 main.py edc hosts --topology local
```

## Hostnames, Ingress y Port-forwards

En topología `local`, los accesos funcionales deben resolverse mediante
hostnames locales e Ingress. Esto aplica a Keycloak, MinIO, registration
service, conectores y componentes cuando están habilitados.

Para que esos hostnames sean accesibles desde la maquina host, normalmente debe
mantenerse `minikube tunnel` abierto en otra terminal:

```bash
minikube tunnel
```

Los `port-forward` no reemplazan los endpoints funcionales del dataspace. El
framework puede usarlos como mecanismo de soporte interno para comprobaciones
puntuales o para clientes host-side, por ejemplo durante la validación
EDC+Kafka, pero las validaciones de navegador y API deben ejercitar las rutas
publicas por hostname siempre que sea posible.

Para PostgreSQL, el servicio del cluster sigue usando el puerto `5432`. El
soporte interno intenta usar `PG_PORT=5432` como puerto local preferente para
conectar con `common-srvs-postgresql` desde el proceso Python del framework. Si
ese puerto local está ocupado por un PostgreSQL externo al entorno PIONERA, el
framework falla con un diagnóstico y no termina procesos externos
automáticamente. Solo libera `kubectl port-forward` antiguos que pertenezcan al
propio framework.

El fallback de `port-forward` para conectores queda desactivado por defecto. En
diagnosticos de desarrollo puede habilitarse explicitamente con:

```bash
PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK=true
```

## Artefactos Runtime

Cada deployer escribe sus artefactos generados bajo:

```text
deployers/<adapter>/deployments/<ENV>/<dataspace>/
```

Estas carpetas pueden contener credenciales, certificados, policies, values de
Helm y configuraciones generadas. Por eso permanecen ignoradas por Git.

## Validación

`Level 6` ejecuta la validación integral:

- Newman para flujos API;
- validación funcional EDC+Kafka después de Newman cuando el adapter la soporta;
- Playwright del adapter activo;
- comprobaciones MinIO/storage;
- validaciones de componentes cuando el perfil las habilita;
- persistencia del resultado en `experiments/`.
