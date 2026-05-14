# 23. Contrato Comun de Deployer

Los deployers implementan un contrato comun para que `main.py` pueda orquestar
adapters sin conocer detalles internos de cada runtime.

## Clases Compartidas

| Clase | Ruta | Uso |
| --- | --- | --- |
| `DeploymentContext` | `deployers/infrastructure/lib/contracts.py` | contexto efectivo de despliegue |
| `NamespaceRoles` | `deployers/infrastructure/lib/contracts.py` | roles logicos de namespaces |
| `TopologyProfile` | `deployers/infrastructure/lib/contracts.py` | direcciones por topología y rol |
| `ValidationProfile` | `deployers/infrastructure/lib/contracts.py` | configuración de validación |
| `DeployerOrchestrator` | `deployers/infrastructure/lib/orchestrator.py` | ejecución comun |

## Metodos del Deployer

| Metodo | Uso |
| --- | --- |
| `supported_topologies()` | declara topologías aceptadas |
| `resolve_context(topology)` | construye `DeploymentContext` |
| `deploy_infrastructure(context)` | `Level 1` |
| `deploy_common_services(context)` | `Level 2` |
| `deploy_dataspace(context)` | `Level 3` |
| `deploy_connectors(context)` | `Level 4` |
| `deploy_components(context)` | `Level 5` |
| `get_validation_profile(context)` | perfil de `Level 6` |

No todos los deployers tienen que ejecutar todos los niveles de forma real en
todas las topologías. Si una capacidad no está habilitada, debe responder de
forma explícita.

## ValidationProfile

El perfil de validación define:

| Campo | Uso |
| --- | --- |
| `adapter` | adapter activo |
| `newman_enabled` | ejecución de colecciones Newman |
| `playwright_enabled` | ejecución de Playwright |
| `playwright_config` | config Playwright del adapter |
| `component_validation_enabled` | validaciones de componentes |

`Level 6` usa este perfil para ejecutar la suite correcta del adapter activo.

## Hosts

La gestion de hosts se hace desde el contexto y el perfil de topología. El
manager genera bloques para:

- servicios comunes;
- dataspace;
- conectores;
- componentes.

La sincronización omite entradas existentes y solo agrega las faltantes.
