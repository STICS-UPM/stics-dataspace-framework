# 15. Validacion de AI Model Hub

`AI Model Hub` se trata como componente opcional de `Level 5` y como objetivo
de validacion funcional en `Level 6` cuando esta habilitado.

## Rutas Principales

| Elemento | Ruta |
| --- | --- |
| Chart Helm | `deployers/shared/components/ai-model-hub/` |
| Runner de componente | `validation/components/ai_model_hub/` |
| Menu interactivo UI | `validation/ui/interactive_menu.py` |
| Orquestacion UI comun | `validation/orchestration/ui.py` |
| Artefactos de experimentos | `experiments/.../components/ai-model-hub/` |

## Despliegue

El componente se habilita desde la configuracion del deployer activo, por
ejemplo con `COMPONENTS=ai-model-hub` o junto a `ontology-hub`.

| Propiedad | Valor habitual local |
| --- | --- |
| Host publico | `ai-model-hub-<dataspace>.dev.ds.dataspaceunit.upm` |
| Chart fuente | `deployers/shared/components/ai-model-hub/` |
| Nivel de despliegue | `Level 5` |
| Nivel de validacion | `Level 6` |
| Namespace esperado | `components` en el layout `role-aligned` |

Los valores runtime se generan fuera del chart compartido para no mezclar
artefactos fuente con configuracion de entorno.

En la ruta actual de `inesdata`, `Level 5` publica el componente con:

- `ingress.enabled=true`;
- host publico propio;
- `config.edcConnectorConfig` derivado de las URLs reales de provider y
  consumer del dataspace activo.

## Validacion Actual

La validacion automatizada comprueba:

- disponibilidad del componente;
- carga de configuracion runtime;
- estructura esperada de `app-config.json`;
- existencia de elementos de menu cuando aplica;
- suite UI PT5 opt-in cuando `AI_MODEL_HUB_ENABLE_UI_VALIDATION=1`;
- persistencia de evidencias en el experimento.

La validacion de flujos avanzados de ejecucion y comparacion de modelos debe
activarse solo cuando el entorno tenga modelos, datasets y endpoints de
inferencia preparados.

## Relacion con el Dataspace

`AI Model Hub` debe poder operar como componente del dataspace, pero no debe
quedar acoplado a un portal concreto. En la arquitectura actual:

- INESData puede desplegar el componente desde `Level 5`;
- EDC mantiene la base arquitectonica para componentes compartidos, pero su
  integracion completa de `Level 5` se documenta como limitacion actual en
  `docs/26_edc_shared_components_integration_plan.md`;
- las validaciones oficiales siguen ejecutandose desde `Level 6`;
- el bootstrap del componente ya forma parte del runner comun;
- la UI del componente sigue siendo opt-in para no introducir tiempo extra por
  defecto en todas las ejecuciones.

## Evidencias

Las evidencias se guardan en:

```text
experiments/<experiment_id>/components/ai-model-hub/
```

El reporte debe contener estado, aserciones, errores, URLs evaluadas y capturas
o artefactos cuando la suite los genere.
