# 24. Matriz de Niveles y Ejecución

> Documento de trazabilidad histórica. Para el alcance vigente de cierre usa
> [30 Estado actual del framework](./30_framework_current_state.md),
> [35 Deployers y topologías](./35_deployers_and_topologies.md) y
> [44 Guía de navegación para auditoría](./44_audit_navigation_guide.md).

El framework mantiene seis niveles. Cada adapter resuelve cómo ejecutarlos según
su deployer y topología.

## Niveles

| Nivel | Accion | Metodo de deployer |
| --- | --- | --- |
| `1` | Setup cluster | `deploy_infrastructure` |
| `2` | Deploy common services | `deploy_common_services` |
| `3` | Deploy dataspace | `deploy_dataspace` |
| `4` | Deploy connectors | `deploy_connectors` |
| `5` | Deploy components | `deploy_components` |
| `6` | Run validation tests | `validate` / perfil de validación |

## Comandos

| Comando | Uso |
| --- | --- |
| `python3 main.py menu` | menú guiado |
| `python3 main.py <adapter> deploy --topology local` | niveles de despliegue |
| `python3 main.py <adapter> validate --topology local` | `Level 6` |
| `python3 main.py <adapter> run --topology local` | despliegue + validación |
| `python3 main.py <adapter> hosts --topology local` | plan/aplicación de hosts |
| `python3 main.py <adapter> metrics --topology local` | experimento de métricas |

## Estado por Topología

| Topología | Hosts | Despliegue real `1-5` | Validación |
| --- | --- | --- | --- |
| `local` | habilitado | habilitado según adapter | habilitada |
| `vm-single` | habilitado por perfil VM | habilitado según adapter y nivel | habilitada según adapter; EDC pendiente de revalidación de cierre |
| `vm-distributed` | planificado por perfil VM | habilitado con preflight y configuración de VMs | ruta oficial de cierre para EDC |

El soporte implementado no equivale automáticamente a evidencia oficial. En la
versión de cierre, EDC se considera probado oficialmente en `vm-distributed`;
`local` debe revalidarse tras la conciliación reciente de topologías y
`vm-single` no se ha validado oficialmente después de esa conciliación.

## INESData

| Nivel | Estado |
| --- | --- |
| `1` a `4` | flujo operativo en `local` y `vm-single` |
| `5` | componentes compartidos operativos cuando están configurados |
| `6` | Newman, Playwright INESData, storage, componentes y reportes |

## EDC

| Nivel | Estado |
| --- | --- |
| `1` a `3` | reutiliza infraestructura y servicios compartidos; ruta oficial de cierre en `vm-distributed` |
| `4` | conectores EDC y dashboard EDC implementados; evidencia de cierre en `vm-distributed` |
| `5` | componentes compartidos operativos cuando están configurados y el conector registra sus extensiones requeridas |
| `6` | Newman, Playwright EDC, storage, componentes y reportes; usar `vm-distributed` para evidencia oficial |

## Recreate Dataspace

El comando `recreate-dataspace` permite borrar y recrear el dataspace de forma
controlada:

```bash
python3 main.py edc recreate-dataspace --topology local --confirm-dataspace pionera-edc
python3 main.py edc recreate-dataspace --topology local --confirm-dataspace pionera-edc --with-connectors
```

Sin `--with-connectors`, se recrea el dataspace sin forzar recreación de
conectores.
