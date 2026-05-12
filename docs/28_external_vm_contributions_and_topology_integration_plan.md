# 28. Topologias VM y Contribuciones Tecnicas

Este documento resume como encajan las contribuciones tecnicas relacionadas con
VMs y routing en la arquitectura actual del framework.

## Estado Implementado

El framework ya contiene una base comun para topologias:

| Elemento | Estado |
| --- | --- |
| `--topology local` | ejecucion real habilitada |
| `--topology vm-single` | perfil y plan de hosts disponibles |
| `--topology vm-distributed` | perfil y plan de hosts disponibles |
| `TopologyProfile` | implementado |
| hosts por rol | implementado |
| guardas para despliegue VM real | implementadas |

Ejemplo:

```bash
PIONERA_VM_COMMON_IP=192.0.2.10 \
PIONERA_VM_PROVIDER_IP=192.0.2.11 \
PIONERA_VM_CONSUMER_IP=192.0.2.12 \
python3 main.py edc hosts --topology vm-distributed --dry-run
```

## Contribuciones Tecnicas Usadas como Referencia

Las ramas y repositorios externos revisados aportan ideas reutilizables:

- dominios dinamicos;
- deteccion de IP externa de VM;
- parcheo de Ingress para exposicion externa;
- sincronizacion de hosts;
- autocuracion de token Vault;
- limpieza robusta de PostgreSQL antes de recrear bases de datos;
- timeouts y readiness checks mas robustos;
- experimentos de routing basado en path.

No se incorporan ramas completas de forma directa si estan basadas en la
arquitectura anterior. Las piezas utiles deben migrarse de forma selectiva hacia
`deployers/infrastructure/lib` y los deployers actuales.

## Autoría y Trazabilidad

Cuando se reutilice codigo externo concreto, la integracion debe preservar
autoria mediante PR, cherry-pick selectivo o commits con `Co-authored-by`.

Cuando solo se reutilice una idea tecnica, la documentacion debe registrar la
decision sin copiar codigo.

## Routing

El modo por defecto sigue siendo routing por hostname. Es el que mejor encaja
con la arquitectura actual de charts e ingress.

El routing por path queda como capacidad avanzada. Puede ser util si un entorno
solo permite un dominio publico, pero requiere mas cuidado con:

- reescrituras de ingress;
- bases href de frontends;
- callbacks OIDC;
- rutas absolutas de APIs;
- compatibilidad de portales y dashboards.

## Encaje con `vm-distributed`

`vm-distributed` representa tres roles:

| Rol | Direccion |
| --- | --- |
| `common` | `PIONERA_VM_COMMON_IP` |
| `provider` | `PIONERA_VM_PROVIDER_IP` |
| `consumer` | `PIONERA_VM_CONSUMER_IP` |

El plan de hosts coloca cada hostname en la IP del rol correspondiente. El
despliegue real de workloads sobre nodos VM debe activarse solo cuando existan
labels, ingress, certificados y registry preparados.

## Criterio de Integracion

La prioridad es conservar estable el modo `local` y añadir VM por capas:

1. perfil de topologia;
2. plan de hosts;
3. resolucion de dominios;
4. placement por rol;
5. ingress y TLS;
6. despliegue real;
7. validacion `Level 6`.

El estado actual cubre las dos primeras capas y deja las siguientes como puntos
de extension tecnica sin romper el baseline local.
