# 16. Contexto Lingüístico FLARES

`FLARES` se usa como contexto funcional para validar escenarios lingüísticos en
`AI Model Hub`. El objetivo dentro del framework es disponer de un dataset
fuente trazable y sincronizado desde su repositorio, sin versionar copias
reducidas dentro del árbol del framework.

## Uso en el Framework

`Level 5` sincroniza el repositorio público de FLARES en:

```text
validation/datasets/sources/flares-dataset/
```

Las validaciones consumen directamente los ficheros sincronizados por `Level 5`.
El framework puede derivar durante la ejecución las estructuras necesarias para
publicación, benchmark y evidencias, pero esas estructuras no se guardan como
dataset reducido versionado. El dataset fuente debe servir para:

- alimentar casos lingüísticos de `AI Model Hub`;
- publicar un recurso negociable en el dataspace;
- comprobar discovery, negociación y consumo;
- validar una salida esperada de forma reproducible.

## Contenido Esperado de la Fuente FLARES

| Fichero | Uso |
| --- | --- |
| `5w1h_subtask_2_trial.json` | registros etiquetados para validación |
| `5w1h_subtarea_2_test.json` | registros de prueba sin etiqueta objetivo |

La validación se centra en `Subtask 2`, porque permite construir el flujo de
clasificación de fiabilidad 5W1H. Las salidas esperadas se calculan desde las
etiquetas presentes en la fuente sincronizada.

## Metadatos del Asset

| Campo | Valor sugerido |
| --- | --- |
| `datasetName` | `FLARES` |
| `domain` | `linguistic` |
| `task` | `5W1H-based reliability classification` |
| `format` | `JSON` |
| `language` | `es` |
| `source` | `FLARES` |
| `license` | `Apache-2.0` |
| `keywords` | `NLP`, `5W1H`, `reliability`, `linguistic` |

La evidencia debe conservar la relación:

```text
repositorio fuente -> commit sincronizado -> estructuras derivadas en runtime -> caso de prueba
```

## Flujo End-to-End

El flujo fiel al dataspace es:

1. publicar `FLARES` como asset del provider;
2. crear policy y contract definition;
3. descubrir el asset desde el consumer;
4. negociar contrato;
5. transferir o consumir el recurso;
6. usarlo dentro del caso funcional de `AI Model Hub`;
7. comparar la salida con las etiquetas esperadas derivadas desde la fuente.

## Estado

El documento fija el contexto de datos y la estructura esperada de la fuente
sincronizada. La automatización completa depende de que el entorno de
`AI Model Hub` tenga los modelos, datasets y endpoints necesarios para ejecutar
el flujo funcional.
