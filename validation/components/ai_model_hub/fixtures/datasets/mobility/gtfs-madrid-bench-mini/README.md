# GTFS-Madrid-Bench-mini

`GTFS-Madrid-Bench-mini` es un fixture local, pequeno y no sensible para abrir
la primera rebanada de movilidad de `AI Model Hub` en A5.2.

No es una copia de un feed GTFS operativo de Madrid. Es una muestra sintetica,
estable y versionable, inspirada en la estructura GTFS publica: paradas, rutas,
viajes, horarios y casos esperados de consulta. Su objetivo es permitir pruebas
reproducibles sin depender de descargas externas ni de datos grandes.

## Uso Previsto

- publicar una muestra de movilidad como asset de dataset;
- preparar `MH-MOB-01` como caso funcional opt-in;
- servir como entrada controlada para integracion con virtualizacion semantica;
- validar joins minimos por `route_id`, `trip_id` y `stop_id`;
- dejar preparada la comparacion esperada de rutas/duraciones.

## Archivos

- `metadata.json`: metadatos del fixture y de su publicacion prevista;
- `schema.json`: referencia de estructura para la muestra GTFS-like;
- `benchmark_sample.json`: muestra sintetica con paradas, rutas, viajes,
  horarios y casos benchmark;
- `expected_outputs.json`: salidas esperadas reproducibles para la muestra.

## Limitaciones

Este fixture valida estructura, trazabilidad y preparacion de benchmarking. No
certifica precision operativa de transporte publico ni sustituye un feed GTFS
real. La conexion con inferencia o benchmarking real queda como paso posterior
de `MH-MOB-01`.
