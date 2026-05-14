# GTFS-Madrid-Bench-mini

`GTFS-Madrid-Bench-mini` es un fixture local, pequeño y no sensible para abrir
la primera rebanada de movilidad de `AI Model Hub` en A5.2.

No es una copia de un feed GTFS operativo de Madrid. Es una muestra sintética,
estable y versionable, inspirada en la estructura GTFS pública: paradas, rutas,
viajes, horarios y casos esperados de consulta. Su objetivo es permitir pruebas
reproducibles sin depender de descargas externas ni de datos grandes.

## Uso Previsto

- publicar una muestra de movilidad como asset de dataset;
- preparar `MH-MOB-01` como caso funcional de `Level 6`;
- servir como entrada controlada para integración con virtualización semántica;
- validar joins mínimos por `route_id`, `trip_id` y `stop_id`;
- dejar preparada la comparación esperada de rutas/duraciones.

## Archivos

- `metadata.json`: metadatos del fixture y de su publicación prevista;
- `schema.json`: referencia de estructura para la muestra GTFS-like;
- `benchmark_sample.json`: muestra sintética con paradas, rutas, viajes,
  horarios y casos benchmark;
- `expected_outputs.json`: salidas esperadas reproducibles para la muestra.

## Limitaciones

Este fixture valida estructura, trazabilidad y preparación de benchmarking. No
certifica precisión operativa de transporte público ni sustituye un feed GTFS
real. La conexión con inferencia o benchmarking real queda como paso posterior
de `MH-MOB-01`.
