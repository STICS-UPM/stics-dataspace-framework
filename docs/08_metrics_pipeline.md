# Pipeline de Métricas

En la secuencia de evolución descrita desde [07_experiment_system.md](./07_experiment_system.md), la Fase 2 transforma los reportes exportados de Newman en artefactos estables del experimento.

## Alcance

Esta fase no modifica las colecciones de validación. Extiende el flujo de ejecución existente para que cualquier experimento con reportes JSON exportados por Newman persista también ficheros de métricas normalizados.

El pipeline de métricas se ejecuta ahora desde:

- `python main.py inesdata validate`
- `python main.py inesdata run`
- `python main.py menu` -> `Level 6 - Run Validation Tests`

## Entrada

La entrada de esta fase es el conjunto de reportes JSON exportados bajo:

```text
experiments/experiment_<timestamp>/newman_reports/
```

Los reportes pueden estar anidados por ejecución y por par de conectores, por ejemplo:

```text
newman_reports/
  run_001/
    conn-a__conn-b/
      01_environment_health.json
      05_consumer_negotiation.json
      06_consumer_transfer.json
```

## Artefactos de Salida

El pipeline de métricas debe producir:

- `newman_results.json`
- `raw_requests.jsonl`
- `test_results.json`
- `negotiation_metrics.json`
- `aggregated_metrics.json`

## Cadena de Artefactos

```text
Reportes JSON de Newman
  -> extracción de requests
  -> extracción de resultados de test
  -> extracción de métricas de negociación
  -> agregacion
  -> persistencia como artefactos del experimento
```

## Responsabilidades de Procesado

- `framework/metrics/collector.py`
  - carga los reportes exportados de Newman
  - extrae métricas de peticiones crudas
  - extrae resultados de aserciones
  - deriva indicios temporales de negociación y transferencia

- `framework/metrics/aggregator.py`
  - calcula conteos por endpoint
  - calcula medias y percentiles de latencia
  - resume totales de tests correctos y fallidos
  - agrega tiempos de negociación

- `framework/metrics_collector.py`
  - orquesta la generación de artefactos para un directorio de experimento
  - persiste salidas normalizadas a traves de `ExperimentStorage`

## Comportamiento ante Fallos

- Si la validación termina correctamente, la extracción de métricas debe ejecutarse automáticamente.
- Si la validación falla después de exportar algunos reportes de Newman, la extracción de métricas sigue ejecutándose sobre los reportes exportados siempre que sea posible.
- Se espera que la extracción de métricas produzca artefactos parciales pero válidos a partir de conjuntos de reportes parciales.

## Notas

- `aggregated_metrics.json` almacena métricas de petición, métricas agregadas de negociación y el resumen de tests en un único documento normalizado.
- `raw_requests.jsonl` sigue siendo el artefacto fuente para la generación posterior de gráficas y para análisis más profundos.
