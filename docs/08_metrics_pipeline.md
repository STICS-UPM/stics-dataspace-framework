# Pipeline de Metricas

En la secuencia de evolución descrita desde [07_experiment_system.md](./07_experiment_system.md), la Fase 2 transforma los reportes exportados de Newman en artefactos estables del experimento.

## Alcance

Esta fase no modifica las colecciones de validacion. Extiende el flujo de ejecucion existente para que cualquier experimento con reportes JSON exportados por Newman persista tambien ficheros de metricas normalizados.

El pipeline de metricas se ejecuta ahora desde:

- `python main.py inesdata validate`
- `python main.py inesdata run`
- `python main.py menu` -> `Level 6 - Run Validation Tests`

## Entrada

La entrada de esta fase es el conjunto de reportes JSON exportados bajo:

```text
experiments/experiment_<timestamp>/newman_reports/
```

Los reportes pueden estar anidados por ejecucion y por par de conectores, por ejemplo:

```text
newman_reports/
  run_001/
    conn-a__conn-b/
      01_environment_health.json
      05_consumer_negotiation.json
      06_consumer_transfer.json
```

## Artefactos de Salida

El pipeline de metricas debe producir:

- `newman_results.json`
- `raw_requests.jsonl`
- `test_results.json`
- `negotiation_metrics.json`
- `aggregated_metrics.json`

## Cadena de Artefactos

```text
Reportes JSON de Newman
  -> extraccion de requests
  -> extraccion de resultados de test
  -> extraccion de metricas de negociacion
  -> agregacion
  -> persistencia como artefactos del experimento
```

## Responsabilidades de Procesado

- `framework/metrics/collector.py`
  - carga los reportes exportados de Newman
  - extrae metricas de peticiones crudas
  - extrae resultados de aserciones
  - deriva indicios temporales de negociacion y transferencia

- `framework/metrics/aggregator.py`
  - calcula conteos por endpoint
  - calcula medias y percentiles de latencia
  - resume totales de tests correctos y fallidos
  - agrega tiempos de negociacion

- `framework/metrics_collector.py`
  - orquesta la generacion de artefactos para un directorio de experimento
  - persiste salidas normalizadas a traves de `ExperimentStorage`

## Comportamiento ante Fallos

- Si la validacion termina correctamente, la extraccion de metricas debe ejecutarse automaticamente.
- Si la validacion falla despues de exportar algunos reportes de Newman, la extraccion de metricas sigue ejecutandose sobre los reportes exportados siempre que sea posible.
- Se espera que la extraccion de metricas produzca artefactos parciales pero validos a partir de conjuntos de reportes parciales.

## Notas

- `aggregated_metrics.json` almacena metricas de peticion, metricas agregadas de negociacion y el resumen de tests en un unico documento normalizado.
- `raw_requests.jsonl` sigue siendo el artefacto fuente para la generacion posterior de graficas y para analisis mas profundos.
