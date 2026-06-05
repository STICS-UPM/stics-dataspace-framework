# Estado Actual del Framework

Este documento resume el estado operativo actual del Validation Environment en
la rama `main`. Está orientado a revisión pública, auditoría técnica y
onboarding de personas que necesitan entender qué está implementado, qué se
valida y qué queda fuera del alcance de cierre.

## Entrada Principal

La entrada canónica es:

```bash
python3 main.py menu
```

También existen comandos directos para automatización:

```bash
python3 main.py inesdata deploy --topology local
python3 main.py inesdata validate --topology local
python3 main.py edc deploy --topology vm-distributed
python3 main.py edc validate --topology vm-distributed
```

El menú y los comandos comparten el mismo modelo de ejecución por niveles.

## Niveles

| Nivel | Función | Estado |
| --- | --- | --- |
| `1` | Preparar cluster Kubernetes | Operativo en `local` y `vm-single` |
| `2` | Desplegar servicios comunes | Operativo |
| `3` | Desplegar dataspace/control plane | Operativo |
| `4` | Desplegar conectores | Operativo para `inesdata` y `edc` |
| `5` | Desplegar componentes opcionales | Operativo para componentes INESData configurados |
| `6` | Ejecutar validación | Operativo con Newman, Kafka, Playwright y validación de componentes según adapter |

## Topologías

| Topología | Estado actual | Uso recomendado |
| --- | --- | --- |
| `local` | Ruta estable de desarrollo y validación local | Validación diaria, depuración y reproducción controlada |
| `vm-single` | Ruta operativa sobre una VM con Kubernetes gestionado | Validación final en entorno tipo VM y smoke de integración |
| `vm-distributed` | Ruta distribuida parametrizable con roles físicos separados | Validación de entornos con servicios comunes, conectores y componentes en VMs distintas |

## Alcance de Cierre por Adapter y Topología

El soporte de código y la evidencia oficial de cierre no son lo mismo. Para
auditoría, la lectura vigente es:

| Adapter | `local` | `vm-single` | `vm-distributed` |
| --- | --- | --- | --- |
| `inesdata` | Implementado y usado como ruta local de desarrollo/validación | Implementado y validado como entorno VM de referencia | Implementado y validado como entorno distribuido de referencia |
| `edc` | Implementado; pasó validaciones antes de la conciliación reciente de topologías y debe revalidarse antes de usarse como evidencia vigente | Implementado; no validado oficialmente después de la conciliación reciente | Implementado y probado oficialmente como ruta de cierre para EDC |

La documentación de operación mantiene comandos y configuración para las rutas
implementadas, pero las evidencias oficiales de `edc` deben generarse en
`vm-distributed` hasta que se ejecute una revalidación explícita de `local` o
`vm-single`.

## Adapters

| Adapter | Estado |
| --- | --- |
| `inesdata` | Despliegue y validación `Level 1-6` operativos |
| `edc` | Despliegue y validación core implementados; evidencia oficial de cierre limitada a `vm-distributed` |

## Namespaces Actuales

La rama `main` usa un perfil `role-aligned` para INESData. Las topologías deben
respetar estos nombres para evitar divergencias entre diagramas, despliegue y
validación:

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

Interpretación:

- `common-srvs`: Keycloak, MinIO, PostgreSQL y Vault.
- `core-control`: registration-service y control plane del dataspace.
- `provider`: conector proveedor.
- `consumer`: conector consumidor.
- `components`: Ontology Hub, AI Model Hub y Semantic Virtualization.
- `ingress-nginx` y `kube-system`: infraestructura Kubernetes.

La resolución centralizada está en:

```text
deployers/shared/lib/namespaces.py
deployers/inesdata/deployer.config.example
```

## Validación

`Level 6` puede ejecutar:

- limpieza segura de datos de prueba;
- colecciones Newman/Postman;
- validación funcional EDC+Kafka;
- Playwright para flujos UI;
- validaciones de componentes;
- métricas y reportes de experimento.

En Semantic Virtualization, el alcance automatizado actual considera
`morph-kgv` como API de virtualización, `mapping-editor` como UI/editor de
mappings y `Automap` como herramienta de generación de mappings. `morph-kgv` se
valida como runtime principal del virtualizador: `Level 6` comprueba su
contrato versionable de ejecución, incluyendo `run_query.py`, el comando
`morph-kgv serve config.ini`, ejemplos `config.ini` y el endpoint `/sparql`.
Automap se sincroniza como fuente del componente y se valida en dos pasos: primero como
readiness/trazabilidad de código fuente y después con una línea base
determinista que ejercita extracción de esquema, extracción de ontología,
reutilización de una ontología gobernable por Ontology Hub, materialización RDF
controlada y métricas de comparación contra KGs de referencia. La ruta LLM
completa de Automap no se ejecuta por defecto en `Level 6` porque requiere
configuración de modelo y secretos externos a la baseline versionable; Automap
no se despliega como servicio runtime en la baseline actual.

Los artefactos se escriben bajo `experiments/`, que es salida generada y no debe
versionarse.

## Colecciones Newman/Postman

Las colecciones ejecutadas por `Level 6` viven en:

```text
validation/core/collections/
```

Las colecciones y entornos pensados para importación manual en Postman viven en:

```text
validation/core/collections/postman/
```

La guía específica está en
[31_postman_newman_collections.md](./31_postman_newman_collections.md).

## Documentación Vigente

Para entender el framework actual, la ruta recomendada es:

1. [README de documentación](./README.md)
2. [Entregable E5.2](./47_entregable_e52_validacion_componentes.md)
3. [Inicio rápido](./32_getting_started.md)
4. [Arquitectura](./34_architecture.md)
5. [Deployers y topologías](./35_deployers_and_topologies.md)
6. [Validación](./37_validation.md)
7. [Colecciones Newman/Postman](./31_postman_newman_collections.md)

Los documentos numerados históricos siguen disponibles como trazabilidad de
diseño, pero este documento y el índice público deben considerarse la referencia
operativa inicial.
