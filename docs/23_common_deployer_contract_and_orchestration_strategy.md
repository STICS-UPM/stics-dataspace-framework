# 23. Contrato Comun de Deployer

Los deployers implementan un contrato comun para que `main.py` pueda orquestar
adapters sin conocer detalles internos de cada runtime.

## Clases Compartidas

| Clase | Ruta | Uso |
| --- | --- | --- |
| `DeploymentContext` | `deployers/infrastructure/lib/contracts.py` | contexto efectivo de despliegue |
| `NamespaceRoles` | `deployers/infrastructure/lib/contracts.py` | roles logicos de namespaces |
| `TopologyProfile` | `deployers/infrastructure/lib/contracts.py` | direcciones por topologia y rol |
| `ValidationProfile` | `deployers/infrastructure/lib/contracts.py` | configuracion de validacion |
| `DeployerOrchestrator` | `deployers/infrastructure/lib/orchestrator.py` | ejecucion comun |

## Metodos del Deployer

| Metodo | Uso |
| --- | --- |
| `supported_topologies()` | declara topologias aceptadas |
| `resolve_context(topology)` | construye `DeploymentContext` |
| `deploy_infrastructure(context)` | `Level 1` |
| `deploy_common_services(context)` | `Level 2` |
| `deploy_dataspace(context)` | `Level 3` |
| `deploy_connectors(context)` | `Level 4` |
| `deploy_components(context)` | `Level 5` |
| `get_validation_profile(context)` | perfil de `Level 6` |

No todos los deployers tienen que ejecutar todos los niveles de forma real en
todas las topologias. Si una capacidad no esta habilitada, debe responder de
forma explicita.

## ValidationProfile

El perfil de validacion define:

| Campo | Uso |
| --- | --- |
| `adapter` | adapter activo |
| `newman_enabled` | ejecucion de colecciones Newman |
| `playwright_enabled` | ejecucion de Playwright |
| `playwright_config` | config Playwright del adapter |
| `component_validation_enabled` | validaciones de componentes |

`Level 6` usa este perfil para ejecutar la suite correcta del adapter activo.

## Hosts

La gestion de hosts se hace desde el contexto y el perfil de topologia. El
manager genera bloques para:

- servicios comunes;
- dataspace;
- conectores;
- componentes.

La sincronizacion omite entradas existentes y solo agrega las faltantes.
