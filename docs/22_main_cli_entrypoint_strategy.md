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
- selecciona topología;
- orquesta niveles;
- ejecuta hosts, métricas, validación y run completo;
- expone menú guiado para usuarios no técnicos;
- mantiene una interfaz reproducible para automatización.

## Menú Guiado

El menú de `main.py` conserva las acciones importantes del flujo histórico:

- niveles `1` a `6`;
- `Run All Levels`;
- seleccion de adapter;
- plan de despliegue;
- hosts;
- métricas;
- herramientas de desarrollo;
- validaciones UI.

Las opciones legacy como bootstrap, doctor, recovery, cleanup, build de imagenes
y suites UI siguen disponibles desde submenús para no romper el flujo de trabajo
existente.

## Organización Interna

Las operaciones compartidas viven en:

| Modulo | Uso |
| --- | --- |
| `framework/local_menu_tools.py` | bootstrap, doctor, recovery, cleanup, imagenes locales |
| `validation/ui/interactive_menu.py` | submenús de validación UI |
| `validation/orchestration/` | orquestación de `Level 6` |
| `deployers/infrastructure/lib` | contratos y utilidades compartidas |

El objetivo es que la ergonomía histórica se mantenga, pero la arquitectura
quede centralizada en `main.py` y en contratos reutilizables por adapter.
