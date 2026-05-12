# FLARES-mini

Fixture local y estable para el dominio lingüístico de `AI Model Hub`.

## Origen

Este subconjunto se deriva del repositorio público `FLARES`:

- `https://github.com/rsepulveda911112/Flares-dataset`

Archivos fuente usados para construir el fixture:

- `5w1h_subtask_2_trial.json`
- `5w1h_subtarea_2_test.json`

## Propósito

`FLARES-mini` sirve para arrancar la `Fase 3` del dominio lingüístico en el framework:

- bootstrap del dataset como asset del provider;
- descubrimiento y negociación posteriores desde el consumer;
- preparación de `MH-LING-01`.

## Contenido

- `subtask2_trial_sample.json`: subconjunto anotado y etiquetado;
- `subtask2_test_sample.json`: subconjunto no etiquetado para futuras comprobaciones de inferencia;
- `metadata.json`: metadatos del fixture y de su publicación prevista en el dataspace;
- `schema.json`: esquema mínimo esperado para ambos subconjuntos;
- `expected_outputs.json`: expectativas mínimas reproducibles para la muestra anotada.

## Criterios de selección

La muestra se ha reducido para mantener:

- cobertura de las dimensiones `WHO`, `WHAT`, `WHEN`, `WHERE`, `HOW` y `WHY`;
- presencia de las clases `confiable`, `semiconfiable` y `no confiable`;
- tamaño manejable para una suite funcional opt-in.

## Nota operativa

Este fixture no se refresca automáticamente desde GitHub durante la ejecución normal del framework. La sincronización con el dataset upstream debe ser una tarea explícita de mantenimiento.
