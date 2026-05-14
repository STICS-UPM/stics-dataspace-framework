# 28. Topologías VM y Contribuciones Técnicas

Este documento resume como encajan las contribuciones técnicas relacionadas con
VMs y routing en la arquitectura actual del framework.

## Estado Implementado

El framework ya contiene una base comun para topologías:

| Elemento | Estado |
| --- | --- |
| `--topology local` | ejecución real habilitada |
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

## Contribuciones Técnicas Usadas como Referencia

Las ramas y repositorios externos revisados aportan ideas reutilizables:

- dominios dinamicos;
- deteccion de IP externa de VM;
- parcheo de Ingress para exposicion externa;
- sincronización de hosts;
- autocuracion de token Vault;
- limpieza robusta de PostgreSQL antes de recrear bases de datos;
- timeouts y readiness checks más robustos;
- experimentos de routing basado en path.

No se incorporan ramas completas de forma directa si están basadas en la
arquitectura anterior. Las piezas utiles deben migrarse de forma selectiva hacia
`deployers/infrastructure/lib` y los deployers actuales.

## Autoría y Trazabilidad

Cuando se reutilice código externo concreto, la integración debe preservar
autoria mediante PR, cherry-pick selectivo o commits con `Co-authored-by`.

Cuando solo se reutilice una idea técnica, la documentación debe registrar la
decisión sin copiar código.

## Routing

El modo por defecto sigue siendo routing por hostname. Es el que mejor encaja
con la arquitectura actual de charts e ingress.

El routing por path queda como capacidad avanzada. Puede ser útil si un entorno
solo permite un dominio público, pero requiere más cuidado con:

- reescrituras de ingress;
- bases href de frontends;
- callbacks OIDC;
- rutas absolutas de APIs;
- compatibilidad de portales y dashboards.

## Encaje con `vm-distributed`

`vm-distributed` representa tres roles:

| Rol | Dirección |
| --- | --- |
| `common` | `PIONERA_VM_COMMON_IP` |
| `provider` | `PIONERA_VM_PROVIDER_IP` |
| `consumer` | `PIONERA_VM_CONSUMER_IP` |

El plan de hosts coloca cada hostname en la IP del rol correspondiente. El
despliegue real de workloads sobre nodos VM debe activarse solo cuando existan
labels, ingress, certificados y registry preparados.

## Criterio de Integración

La prioridad es conservar estable el modo `local` y añadir VM por capas:

1. perfil de topología;
2. plan de hosts;
3. resolucion de dominios;
4. placement por rol;
5. ingress y TLS;
6. despliegue real;
7. validación `Level 6`.

El estado actual cubre las dos primeras capas y deja las siguientes como puntos
de extensión técnica sin romper el baseline local.
