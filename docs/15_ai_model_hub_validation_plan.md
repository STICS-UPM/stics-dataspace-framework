# 15. Validación de AI Model Hub

`AI Model Hub` se trata como componente opcional de `Level 5` y como objetivo
de validación funcional en `Level 6` cuando está habilitado.

## Rutas Principales

| Elemento | Ruta |
| --- | --- |
| Chart Helm | `deployers/shared/components/ai-model-hub/` |
| Runner de componente | `validation/components/ai_model_hub/` |
| Soporte de model-server | `deployers/shared/lib/ai_model_hub_model_server.py` |
| Sembrado de assets | `scripts/seed_ml_assets_for_connectors.sh` |
| Menú interactivo UI | `validation/ui/interactive_menu.py` |
| Orquestación UI común | `validation/orchestration/ui.py` |
| Artefactos de experimentos | `experiments/.../components/ai-model-hub/` |

## Despliegue

El componente se habilita desde la configuración del deployer activo, por
ejemplo con `COMPONENTS=ai-model-hub` o junto a `ontology-hub`.

| Propiedad | Valor habitual local |
| --- | --- |
| Host público | `ai-model-hub-<dataspace>.dev.ds.dataspaceunit.upm` |
| Chart fuente | `deployers/shared/components/ai-model-hub/` |
| Nivel de despliegue | `Level 5` |
| Nivel de validación | `Level 6` |
| Namespace esperado | `components` en el layout `role-aligned` |

Los valores runtime se generan fuera del chart compartido para no mezclar
artefactos fuente con configuración de entorno.

En la ruta actual de `inesdata`, `Level 5` publica el componente con:

- `ingress.enabled=true`;
- host público propio;
- `config.edcConnectorConfig` derivado de las URLs reales de provider y
  consumer del dataspace activo.

En `edc`, `Level 5` reutiliza el chart compartido del componente y espera que
los conectores desplegados expongan las capacidades requeridas para registrar
assets, contratos y flujos de observabilidad. La ruta con evidencia operativa
actual para EDC es `vm-distributed`.

## Model-Server de Casos de Uso

El framework incluye soporte explícito para desplegar un `model-server`
asociado a AI Model Hub. Los modos disponibles son:

| Modo | Uso |
| --- | --- |
| `mock` | Línea base determinista y controlada del framework. |
| `use-cases` | Servidor construido desde fuentes de casos de uso. |
| `combined` | Modo combinado que conserva compatibilidad con fixtures y expone modelos/datasets de casos de uso. |
| `external` | Servidor gestionado fuera del framework. |

Para las demostraciones reproducibles de casos de uso, el modo operativo es
`combined`. Este modo usa el repositorio de casos de uso configurado en el
perfil, por defecto `ProyectoPIONERA/AIModelHub-Use-Cases`, y expone:

- `/models`, para descubrir modelos FLARES y Mobility;
- `/datasets`, para descubrir datasets de benchmark;
- `/datasets/{filename}`, para servir los ficheros de dataset referenciados
  como assets `HttpData`.

El asistente de `vm-distributed` incorpora la opción
`10 - AI Model Hub use-case demo preparation`. Esta opción puede preparar el
perfil, mostrar comandos, ejecutar `Level 5` y sembrar los pasos operativos:

- `Step 9`: registro de datasets de benchmark;
- `Step 10`: registro de modelos FLARES/Mobility;
- flujo completo: perfil, `Level 5`, `Step 9` y `Step 10`.

Los valores concretos de imagen, commit, URLs, kubeconfigs y credenciales viven
en perfiles locales o secretos de ejecución, no en `docs/`.

## Validación Actual

La validación automatizada comprueba:

- disponibilidad del componente;
- carga de configuración runtime;
- estructura esperada de `app-config.json`;
- existencia de elementos de menú cuando aplica;
- suite UI PT5 del componente;
- persistencia de evidencias en el experimento.

La validación de flujos avanzados de ejecución, comparación de modelos,
movilidad, gobierno de conectores y observabilidad se ejecuta desde `Level 6`
por defecto. Para depuración puntual, cada suite puede omitirse definiendo su
variable `AI_MODEL_HUB_ENABLE_*` en `false`, `0`, `no` o dejándola vacía.

El sembrado de datasets y modelos se ejecuta fuera del runner Playwright. El
script `scripts/seed_ml_assets_for_connectors.sh` lee credenciales generadas por
el framework en tiempo de ejecución y no requiere que esas credenciales estén
versionadas. En modo `edc`, el sembrado crea assets `HttpData`, políticas,
contratos y negociaciones DSP entre los pares configurados; en modo `inesdata`,
usa las APIs propias del adapter.

En `Level 6`, la suite API visible como `AI Model Hub use cases` valida el
contrato del `model-server` cuando el modo es `use-cases`, `combined` o
`external` con validación habilitada. La suite comprueba por defecto `/models` y
`/datasets`; los endpoints de inferencia se prueban solo si se declaran en
`AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINTS`.

## Relación con el Dataspace

`AI Model Hub` debe poder operar como componente del dataspace, pero no debe
quedar acoplado a un portal concreto. En la arquitectura actual:

- INESData y EDC pueden desplegar el componente desde `Level 5`;
- en EDC, el despliegue exige que el conector registre las extensiones
  requeridas para integrar el componente;
- las validaciones oficiales siguen ejecutándose desde `Level 6`;
- el bootstrap del componente ya forma parte del runner común;
- la UI y las suites funcionales/de integración del componente forman parte del
  alcance por defecto de `Level 6`.

## Evidencias

Las evidencias se guardan en:

```text
experiments/<experiment_id>/components/ai-model-hub/
```

El reporte debe contener estado, aserciones, errores, URLs evaluadas y capturas
o artefactos cuando la suite los genere.
