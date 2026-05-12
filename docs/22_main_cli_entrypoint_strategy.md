# 22. Entrada `main.py`

`main.py` es la entrada canónica del framework. Todas las operaciones de uso,
despliegue, validación, métricas, hosts y topologías deben ejecutarse desde este
punto.

## Entrada Recomendada

```bash
python3 main.py menu
python3 main.py inesdata deploy --topology local
python3 main.py edc deploy --topology local
python3 main.py inesdata validate --topology local
python3 main.py edc validate --topology local
```

## Por Qué `main.py`

`main.py` es neutral respecto al adapter:

- selecciona `inesdata` o `edc`;
- selecciona topologia;
- orquesta niveles;
- ejecuta hosts, metricas, validacion y run completo;
- expone menu guiado para usuarios no tecnicos;
- mantiene una interfaz reproducible para automatizacion.

## Menu Guiado

El menu de `main.py` conserva las acciones importantes del flujo historico:

- niveles `1` a `6`;
- `Run All Levels`;
- seleccion de adapter;
- plan de despliegue;
- hosts;
- metricas;
- herramientas de desarrollo;
- validaciones UI.

Las opciones legacy como bootstrap, doctor, recovery, cleanup, build de imagenes
y suites UI siguen disponibles desde submenus para no romper el flujo de trabajo
existente.

## Organización Interna

Las operaciones compartidas viven en:

| Modulo | Uso |
| --- | --- |
| `framework/local_menu_tools.py` | bootstrap, doctor, recovery, cleanup, imagenes locales |
| `validation/ui/interactive_menu.py` | submenus de validacion UI |
| `validation/orchestration/` | orquestacion de `Level 6` |
| `deployers/infrastructure/lib` | contratos y utilidades compartidas |

El objetivo es que la ergonomia historica se mantenga, pero la arquitectura
quede centralizada en `main.py` y en contratos reutilizables por adapter.
