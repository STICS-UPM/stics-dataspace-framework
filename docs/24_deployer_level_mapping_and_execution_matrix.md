# 24. Matriz de Niveles y Ejecucion

El framework mantiene seis niveles. Cada adapter resuelve como ejecutarlos segun
su deployer y topologia.

## Niveles

| Nivel | Accion | Metodo de deployer |
| --- | --- | --- |
| `1` | Setup cluster | `deploy_infrastructure` |
| `2` | Deploy common services | `deploy_common_services` |
| `3` | Deploy dataspace | `deploy_dataspace` |
| `4` | Deploy connectors | `deploy_connectors` |
| `5` | Deploy components | `deploy_components` |
| `6` | Run validation tests | `validate` / perfil de validacion |

## Comandos

| Comando | Uso |
| --- | --- |
| `python3 main.py menu` | menu guiado |
| `python3 main.py <adapter> deploy --topology local` | niveles de despliegue |
| `python3 main.py <adapter> validate --topology local` | `Level 6` |
| `python3 main.py <adapter> run --topology local` | despliegue + validacion |
| `python3 main.py <adapter> hosts --topology local` | plan/aplicacion de hosts |
| `python3 main.py <adapter> metrics --topology local` | experimento de metricas |

## Estado por Topologia

| Topologia | Hosts | Despliegue real `1-5` | Validacion |
| --- | --- | --- | --- |
| `local` | habilitado | habilitado segun adapter | habilitada |
| `vm-single` | habilitado por perfil VM | habilitado segun adapter y nivel | habilitada |
| `vm-distributed` | planificado por perfil VM | protegido por guarda | no habilitada como ejecucion real completa |

La proteccion de VM sigue aplicando a `vm-distributed` y a rutas todavia no
habilitadas para un adapter concreto, como `Level 5` real de componentes en
`edc`.

## INESData

| Nivel | Estado |
| --- | --- |
| `1` a `4` | flujo operativo en `local` y `vm-single` |
| `5` | componentes compartidos operativos cuando estan configurados |
| `6` | Newman, Playwright INESData, storage, componentes y reportes |

## EDC

| Nivel | Estado |
| --- | --- |
| `1` a `3` | reutiliza infraestructura y servicios compartidos en `local` y `vm-single` |
| `4` | conectores EDC y dashboard EDC operativos en `local` y `vm-single` |
| `5` | componentes compartidos no habilitados todavia para despliegue real EDC |
| `6` | Newman, Playwright EDC y storage operativos |

## Recreate Dataspace

El comando `recreate-dataspace` permite borrar y recrear el dataspace de forma
controlada:

```bash
python3 main.py edc recreate-dataspace --topology local --confirm-dataspace pionera-edc
python3 main.py edc recreate-dataspace --topology local --confirm-dataspace pionera-edc --with-connectors
```

Sin `--with-connectors`, se recrea el dataspace sin forzar recreacion de
conectores.
