# Sistema de Experimentos

La evolución del framework se ha dividido por fases. En esta serie, la `Fase 1` corresponde al sistema de experimentos, la `Fase 2` al pipeline de métricas, la `Fase 3` a Kafka y la `Fase 4` a la validación UI.

Dentro de esa secuencia, la Fase 1 define el contrato mínimo de artefactos para cualquier ejecución de experimento en `integration_pionera`.

## Alcance

Esta fase cubre los dos caminos de ejecución usados actualmente en el proyecto:

- `python main.py inesdata run`
- `python main.py menu` -> `Level 6 - Run Validation Tests`

Ambos caminos deben dejar un esqueleto de experimento consistente en disco, incluso si la validación falla después de que el experimento haya comenzado.

## Contrato Mínimo de Artefactos

Todo experimento debe crear:

- `experiments/experiment_<timestamp>/metadata.json`
- `experiments/experiment_<timestamp>/experiment_results.json`
- `experiments/experiment_<timestamp>/newman_reports/`

## Estructura Esperada

```text
experiments/
  experiment_<timestamp>/
    metadata.json
    experiment_results.json
    newman_reports/
    storage_checks/                # opcional, cuando hay post-check de transferencia real
```

Artefactos adicionales como métricas, gráficas, resúmenes y evidencias UI pueden añadirse en fases posteriores, pero las tres entradas anteriores son el contrato mínimo de la Fase 1.

En el estado actual del framework, un experimento de validación puede generar además:

- `raw_requests.jsonl`
- `aggregated_metrics.json`
- `test_results.json`
- `negotiation_metrics.json`
- `kafka_metrics.json`
- `kafka_transfer_results.json`
- `ui/`
- `kafka_transfer/`
- `components/`
- `storage_checks/`

La carpeta `storage_checks/` contiene post-checks técnicos de almacenamiento para transferencias INESData. No forma parte del contrato mínimo histórico de la Fase 1, pero hoy es una evidencia complementaria importante cuando `06_consumer_transfer.json` se ejecuta con `experiment_dir`.

## Comportamiento en Ejecución

### `main.py inesdata run`

- crea el directorio del experimento antes de que empiece la validación
- materializa `newman_reports/` antes de la primera iteración de validación
- escribe un `experiment_results.json` inicial con `status=running`
- actualiza `experiment_results.json` conforme avanza la ejecución
- reescribe `experiment_results.json` con `status=failed` si la validación o las métricas lanzan una excepción

### `main.py menu` Level 6

- crea el directorio del experimento antes de iniciar la validación del dataspace
- pasa `experiment_dir` a `ValidationEngine.run_all_dataspace_tests(...)`
- crea `newman_reports/` antes de la validación
- escribe `experiment_results.json` con `status=running`, `completed` o `failed`
- preserva las salidas de validación incluso cuando fallan pasos posteriores

## Semántica de Fallo

Si la ejecución falla después de que el directorio del experimento haya sido creado:

- `metadata.json` debe seguir existiendo
- `experiment_results.json` debe seguir existiendo
- `experiment_results.json` debe incluir un bloque de error normalizado con:
  - `type`
  - `message`

## Notas

- No cambia la lógica de validación en sí misma.
- Sólo se garantiza persistencia reproducible del experimento y trazabilidad de fallos.
