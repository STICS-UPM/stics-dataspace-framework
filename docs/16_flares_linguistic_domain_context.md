# 16. Contexto Linguistico FLARES

`FLARES` se usa como contexto funcional para validar escenarios linguisticos en
`AI Model Hub`. El objetivo dentro del framework es disponer de un dataset
pequeno, reproducible y publicable como asset del dataspace.

## Uso en el Framework

El subconjunto de pruebas se denomina `FLARES-mini`. Debe servir para:

- alimentar casos linguisticos de `AI Model Hub`;
- publicar un recurso negociable en el dataspace;
- comprobar discovery, negociacion y consumo;
- validar una salida esperada de forma reproducible.

## Contenido Esperado de `FLARES-mini`

| Fichero | Uso |
| --- | --- |
| `README.md` | descripcion del fixture |
| `metadata.json` | metadatos del asset |
| `schema.json` | estructura de los ejemplos |
| `subtask2_trial_sample.json` | muestra pequena de validacion |
| `subtask2_test_sample.json` | muestra pequena de prueba |
| `expected_outputs.json` | salidas esperadas |

La seleccion inicial se centra en `Subtask 2`, porque permite construir un
fixture mas compacto para clasificacion de fiabilidad.

## Metadatos del Asset

| Campo | Valor sugerido |
| --- | --- |
| `datasetName` | `FLARES-mini` |
| `domain` | `linguistic` |
| `task` | `5W1H-based reliability classification` |
| `format` | `JSON` |
| `language` | `es` |
| `source` | `FLARES` |
| `license` | `Apache-2.0` |
| `keywords` | `NLP`, `5W1H`, `reliability`, `linguistic` |

## Flujo End-to-End

El flujo fiel al dataspace es:

1. publicar `FLARES-mini` como asset del provider;
2. crear policy y contract definition;
3. descubrir el asset desde el consumer;
4. negociar contrato;
5. transferir o consumir el recurso;
6. usarlo dentro del caso funcional de `AI Model Hub`;
7. comparar la salida con `expected_outputs.json`.

## Estado

El documento fija el contexto de datos y la estructura esperada del fixture. La
automatizacion completa depende de que el entorno de `AI Model Hub` tenga los
modelos, datasets y endpoints necesarios para ejecutar el flujo funcional.
