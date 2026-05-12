# 00. Visión General

## Qué hace este repositorio

Este repositorio sirve para levantar un entorno local del dataspace PIONERA y validar que los conectores funcionan correctamente.

Hoy cubre principalmente:

- despliegue local del cluster y servicios base
- despliegue del dataspace y de los conectores
- despliegue opcional de componentes adicionales
- validación API core con Newman
- validación UI con Playwright
- validación específica de componentes cuando existe runner registrado
- persistencia de experimentos, métricas y artefactos de ejecución

## Qué problema resuelve

PIONERA necesita un entorno reproducible donde se pueda comprobar que:

- los conectores arrancan correctamente
- el dataspace queda operativo
- los flujos básicos de interoperabilidad funcionan
- los componentes adicionales pueden integrarse sin romper el resto del entorno

Sin este framework, cada integración tendría que resolverse de forma manual y sería difícil comparar resultados entre ejecuciones.

## Idea general de la arquitectura

La estructura actual del repositorio se entiende bien si la miramos en cinco bloques:

1. `main.py` es la entrada canónica del framework.
2. `adapters/` encapsula la lógica específica de cada adapter.
3. `deployers/` contiene charts, bootstrap y artefactos de despliegue por adapter.
4. `framework/` contiene la lógica genérica de validación y resultados.
5. `validation/` contiene las suites API, UI y por componente.

## Qué está implementado

- La validación core del dataspace se ejecuta con Newman desde `validation/core/collections/`.
- Las colecciones activas están en `validation/core/collections/`.
- Los scripts JS activos están en `validation/core/tests/` y `validation/shared/api/`.
- `Level 6` crea un experimento y persiste artefactos en `experiments/experiment_<timestamp>/`.
- El pipeline de métricas transforma los reportes de Newman en artefactos persistidos del experimento.
- Kafka puede medirse como benchmark real y dejar `kafka_metrics.json`.
- `validation/ui/` contiene suites Playwright activas; `Level 6` ejecuta un smoke estable por conector y, cuando la suite existe, la comprobacion `ops` de MinIO salvo opt-out explicito.
- `validation/components/` ya no es solo estructura: `ontology_hub` se valida automáticamente en `Level 6` cuando está configurado en `COMPONENTS`.

## Qué debe leer un desarrollador nuevo

Si tu propósito es entender el framework completo, el orden recomendado es:

1. [01_framework_architecture.md](./01_framework_architecture.md)
2. [02_validation_architecture.md](./02_validation_architecture.md)
3. [04_execution_flow.md](./04_execution_flow.md)
4. [05_repository_structure.md](./05_repository_structure.md)
5. [07_experiment_system.md](./07_experiment_system.md)
6. [08_metrics_pipeline.md](./08_metrics_pipeline.md)
7. [09_kafka_real_measurements.md](./09_kafka_real_measurements.md)
8. [10_ui_validation_core.md](./10_ui_validation_core.md)

Si tu propósito es integrar o mantener un componente:

1. [01_framework_architecture.md](./01_framework_architecture.md).
2. [03_integration_guide.md](./03_integration_guide.md).
2. [05_repository_structure.md](./05_repository_structure.md).
3. [02_validation_architecture.md](./02_validation_architecture.md).

Si tu propósito es entender la validación:

1. [02_validation_architecture.md](./02_validation_architecture.md).
2. [04_execution_flow.md](./04_execution_flow.md).
3. [07_experiment_system.md](./07_experiment_system.md) a [10_ui_validation_core.md](./10_ui_validation_core.md).
