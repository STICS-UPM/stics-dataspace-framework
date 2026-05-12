# 04. Flujo de Ejecución

## Flujo general desde `main.py menu`

El repositorio está organizado en niveles secuenciales.

El flujo habitual es este:

1. `Level 1`: prepara el cluster local.
2. `Level 2`: despliega servicios comunes.
3. `Level 3`: despliega el dataspace base.
4. `Level 4`: despliega los conectores.
5. `Level 5`: despliega componentes opcionales.
6. `Level 6`: ejecuta la validación.

`Level 3` deja preparado el dataspace base y el registration-service. No valida
ni repara conectores existentes; después de un `Level 3` correcto, ejecuta
`Level 4` para desplegar o actualizar los conectores del adapter activo.

## Qué hace hoy `Level 6`

`Level 6` ya no ejecuta solo la validación API del núcleo del dataspace. Hoy orquesta un experimento completo y persiste sus artefactos.

La secuencia común de orquestación vive en `validation/orchestration/runner.py`. Cada adapter/deployer debe aportar un `Level6Runtime` con sus dependencias concretas. `main.py` resuelve el adapter activo y ejecuta esta orquestación común.

El flujo actual es:

1. Comprueba que Newman está disponible.
2. Detecta los conectores desplegados en el cluster.
3. Verifica que hay al menos dos conectores.
4. Crea el directorio del experimento y sus artefactos base.
5. Comprueba que el despliegue de conectores es válido.
6. Llama a `ValidationEngine.run_all_dataspace_tests(connectors)`.
7. Genera métricas derivadas de los reportes de Newman.
8. Ejecuta el benchmark Kafka y persiste `kafka_metrics.json`.
9. Ejecuta el smoke UI estable del dataspace para cada conector.
10. Ejecuta la suite UI `ops` de MinIO cuando esta disponible, salvo que `LEVEL6_RUN_UI_OPS=false`.
11. Ejecuta validaciones de componentes cuando `COMPONENTS` contiene componentes con runner registrado.
12. Persiste `experiment_results.json` con resultados API, UI, Kafka y componentes.

La validacion de componentes se ejecuta despues del smoke UI del dataspace. Esto
permite separar:

- validacion del dataspace base del adapter activo;
- validacion de componentes opcionales desplegados en `Level 5`.

## Qué hace `ValidationEngine`

`ValidationEngine` toma la lista de conectores y genera todas las parejas proveedor-consumidor.

Para cada pareja:

1. limpia entidades de prueba antiguas si hace falta
2. prepara variables de entorno para Newman
3. delega la ejecución real a `NewmanExecutor`

Los resultados de cada pareja se persisten en el experimento activo.

## Qué hace `NewmanExecutor`

`NewmanExecutor` ejecuta secuencialmente las seis colecciones core:

1. `01_environment_health.json`
2. `02_connector_management_api.json`
3. `03_provider_setup.json`
4. `04_consumer_catalog.json`
5. `05_consumer_negotiation.json`
6. `06_consumer_transfer.json`

Además:

- carga `validation/shared/api/common_tests.js`
- añade el script específico de cada colección desde `validation/core/tests/`
- exporta reportes JSON que después se reutilizan para métricas y reporting

## Qué pasa con métricas, Kafka y UI

Una vez terminada la validación core:

- `framework/metrics_collector.py` transforma los reportes exportados en artefactos de métricas
- la capa Kafka genera `kafka_metrics.json` con estado explícito `completed` o `skipped`
- la capa UI ejecuta un smoke Playwright estable por conector y guarda sus artefactos dentro del experimento

Por tanto, `Level 6` ya no debe entenderse como “solo Newman”, sino como el nivel que consolida la validación observable del entorno.

## Qué pasa con los componentes

`Level 5` y `Level 6` siguen teniendo responsabilidades distintas, pero ya no están aislados entre sí:

- `Level 5` despliega componentes opcionales
- `Level 6` valida automáticamente los componentes configurados cuando existe runner registrado

En la práctica:

- `COMPONENTS=ontology-hub` hace que `Level 5` lo despliegue
- `COMPONENTS=ai-model-hub` hace que `Level 5` lo despliegue para `inesdata`
  cuando el adapter tiene soporte real
- en el layout `role-aligned`, los componentes se publican en
  `components_namespace`, no en el namespace compacto del dataspace
- para `ontology-hub`, `Level 5` usa un checkout local en `adapters/inesdata/sources/Ontology-Hub`; si no existe, lo clona automáticamente
- `Level 5` reconstruye esa imagen en el host y la carga en minikube antes del despliegue
- ese flujo es deliberadamente estricto: no usa overrides de `source dir` ni de imagen para `ontology-hub`
- y hace que `Level 6` intente validarlo automáticamente
- para `ai-model-hub`, `Level 6` ejecuta siempre el bootstrap del componente y
  solo lanza la UI PT5 si `AI_MODEL_HUB_ENABLE_UI_VALIDATION=1`
- si el componente no tiene runner o no puede inferirse su URL, queda como `skipped` en vez de romper toda la ejecución

## Qué papel tiene cada capa de validación

- `validation/core/` contiene la validación obligatoria del dataspace
- `validation/ui/` contiene la validación UI del dataspace core
- `validation/components/` contiene validaciones específicas por componente
- `framework/` coordina experimentos, métricas, reporting y persistencia

## Cómo se extiende el framework

La evolución prevista, sin cambiar la estructura actual, sigue siendo simple:

1. mantener `core` como validación obligatoria
2. añadir runners por componente en `validation/components/`
3. mantener la UI como espejo funcional de los flujos API
