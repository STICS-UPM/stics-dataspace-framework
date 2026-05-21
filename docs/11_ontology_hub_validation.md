# 11. Validación de Ontology Hub

Este documento resume como queda integrado `Ontology Hub` en el framework de
validación. La referencia operativa detallada vive junto al código del
componente, pero este documento centraliza las rutas, el despliegue, las suites
y la trazabilidad PT5.

## Rutas Principales

| Elemento | Ruta |
| --- | --- |
| Suite funcional | `validation/components/ontology_hub/functional/` |
| Suite de integración API | `validation/components/ontology_hub/integration/` |
| Infraestructura Playwright compartida | `validation/components/ontology_hub/ui/` |
| Runner comun de componentes | `validation/components/runner.py` |
| Chart Helm | `deployers/shared/components/ontology-hub/` |
| Artefactos de experimentos | `experiments/.../components/ontology-hub/` |

## Despliegue

`Ontology Hub` se despliega como componente opcional de `Level 5`. En el modo
local actual, el chart fuente se mantiene en `deployers/shared/components` y
los valores runtime se resuelven desde el deployer activo.

| Propiedad | Valor habitual local |
| --- | --- |
| Namespace | `components` |
| Release Helm | `<dataspace>-ontology-hub` |
| Host público | `ontology-hub-<dataspace>.dev.ds.dataspaceunit.upm` |
| Servicio interno | `ClusterIP` en puerto `3333` |
| Dependencias | MongoDB y Elasticsearch |
| Imagen local | `ontology-hub:local` cuando se usa build local |

El chart puede inyectar `hostAliases` para que el hostname público del
componente sea resoluble también desde dentro del pod. Esto evita fallos de
autoacceso del backend en operaciones como análisis de versiones.

## Puntos de Entrada

| URL | Uso |
| --- | --- |
| `http://ontology-hub-<dataspace>.dev.ds.dataspaceunit.upm/` | Home publica |
| `http://ontology-hub-<dataspace>.dev.ds.dataspaceunit.upm/dataset` | Catálogo público |
| `http://ontology-hub-<dataspace>.dev.ds.dataspaceunit.upm/edition` | Area autenticada |
| `http://ontology-hub-<dataspace>.dev.ds.dataspaceunit.upm/edition/login` | Login |
| `http://ontology-hub-<dataspace>.dev.ds.dataspaceunit.upm/dataset/lov/api` | API histórica del componente |

## Suites

La suite `functional/` valida el comportamiento observable del componente. Se
usa por defecto cuando `Level 6` ejecuta validación de componentes.

La suite `integration/` aparece en consola y reportes como `Ontology Hub API
integration`. Conserva pruebas técnicas y casos PT5 normalizados para comprobar
endpoints, estado interno y compatibilidad técnica del componente.

## Estado Funcional Reproducido

La ejecución local validada el `2026-04-29` reproduce `21` casos funcionales
correctos y `6` fallos de `Ontology Hub`. Estos fallos no se tratan como
inestabilidad del framework: Newman, Playwright core y la validación EDC+Kafka
pueden completar correctamente mientras la validación del componente queda en
warning por errores propios de la aplicación.

| Caso | Síntoma observado | Lectura técnica |
| --- | --- | --- |
| `OH-APP-08` | El facet `Tag` muestra `N/A (2)` aunque la metadata del vocabulario contiene `Services`. | Posible problema de indexación o normalización de facets del catálogo. |
| `OH-APP-09` | El facet `Language` muestra `N/A (2)` aunque la metadata del vocabulario contiene `en` y `es`. | Posible problema de indexación o normalización de idioma en el catálogo. |
| `OH-APP-12` | La edición de una versión devuelve `502 Bad Gateway`. | Error server-side durante el flujo de edición de versión. |
| `OH-APP-13` | La zona de edición queda temporalmente no disponible al borrar una versión. | Puede ser efecto cascada del fallo previo de edición. |
| `OH-APP-17` | La página de administracion de usuarios devuelve `500`. | Error server-side que bloquea la promoción de usuario a admin. |
| `OH-APP-22` | La página de patrones devuelve `500`. | Error server-side que bloquea la generación del zip. |

La ejecución `vm-single` reproducida el `2026-04-30 14:00:47`, tras corregir la
cascada inicial de publicación de vocabularios y montar `/app/versions` en el
chart, queda en `23/27`. `AI Model Hub` pasa en el mismo experimento y
`Ontology Hub` queda en warning por cuatro fallos propios del componente:

| Caso | Síntoma observado en `vm-single` | Lectura técnica |
| --- | --- | --- |
| `OH-APP-05` | El detalle público expone metadata, enlace `.n3`, incoming/outgoing links y versión history, pero la automatización esperaba un tab `Version History`. | Desalineación puntual de selector frente a la UI actual; no apunta a infraestructura. |
| `OH-APP-10` | Tras editar metadata, el detalle público sigue mostrando el tag anterior `Services` en lugar de `Vocabularies`. | Posible problema de persistencia o reindexado de tags en Ontology Hub. |
| `OH-APP-17` | La promoción a admin no encuentra `a[href='/edition/signup']`; la página de edición muestra `+ Vocab` y `+ Agent`, pero no `+ USER`. | Diferencia de permisos/estado de usuario en la UI; el flujo no puede completar la promoción esperada por el caso. |
| `OH-APP-22` | La página de patrones devuelve `500 - Oops! something went wrong - 500`. | Error server-side ya observado en local que bloquea la generación del zip. |

En esta ejecución ya pasan `OH-APP-14` y `OH-APP-24`, que habían fallado en
sondeos previos de `vm-single`.

### Bug OH-APP-14: versiones y ficheros `.n3`

En sondeos previos de `vm-single`, el crash de `OH-APP-14` dejo este stack trace en el pod
`<dataspace>-ontology-hub`:

```text
Error: ENOENT: no such file or directory, unlink './versions/<vocab-id>/<vocab-id>_2026-01-01.n3'
```

La secuencia es:

1. `OH-APP-11` crea una versión con fecha `2026-03-31` y sube un `.n3`.
2. `OH-APP-12` edita la versión y cambia la fecha a `2026-01-01`, según la hoja `Ontology Hub`.
3. Ontology Hub actualiza la metadata en MongoDB y después intenta renombrar o borrar el fichero físico asociado.
4. Si el fichero no existe en `/app/versions`, el controlador `versions.js` lanza la excepción con `throw err`.
5. La excepción termina el proceso Node y Kubernetes reinicia el pod.

El bug principal está en la aplicación: las operaciones `fs.rename`/`fs.unlink`
de versiones no deberian terminar el proceso ante `ENOENT`; deberian mantener
MongoDB y el filesystem en un estado consistente o devolver un error controlado.

El framework mitiga la parte de infraestructura montando `/app/versions` como
volumen del chart de Ontology Hub. Por defecto usa `emptyDir` para mantener
compatibilidad con despliegues efimeros, y permite activar PVC con:

```yaml
versions:
  persistence:
    enabled: true
    size: 1Gi
```

Esto reduce la desincronizacion entre MongoDB y los ficheros `.n3` cuando hay
reinicios del pod. En el experimento `2026-04-30 14:00:47`, `OH-APP-14` ya no
se reproduce como fallo, aunque la correccion defensiva en `versions.js` sigue
siendo recomendable para evitar que un `ENOENT` pueda terminar el proceso Node.

`Level 6` puede terminar como `Succeeded` porque el nivel se ejecuto de forma
controlada y genero los artefactos esperados. Eso no significa que todos los
casos funcionales del componente hayan pasado; el detalle vive en
`experiments/.../components/ontology-hub/functional/`.

## Trazabilidad PT5

La trazabilidad se lee en tres capas:

| Capa | Papel |
| --- | --- |
| `A5.1_Funcionalidades_Ex.1` | Funcionalidades atómicas `OntHub-*` |
| `A5.1_Casos_Prueba_Ex.1` | Casos PT5 normalizados `PT5-OH-*` |
| Hoja `Ontology Hub` | Casos operativos detallados del componente |

La suite funcional modela los 27 casos operativos de la hoja `Ontology Hub`.
La numeración tiene una excepción histórica: `OH-APP-00` cubre el caso `1`,
`OH-APP-01` cubre el caso `2` y no existe `OH-APP-02`.

| Caso hoja `Ontology Hub` | Automatización |
| --- | --- |
| `1` | `OH-APP-00` |
| `2` | `OH-APP-01` |
| `3` a `27` | `OH-APP-03` a `OH-APP-27` |

La cobertura PT5 se reparte entre `functional/` e `integration/`.

| Caso PT5 | Cobertura actual |
| --- | --- |
| `PT5-OH-01` | si |
| `PT5-OH-02` | si |
| `PT5-OH-03` | si |
| `PT5-OH-04` | si |
| `PT5-OH-05` | parcial |
| `PT5-OH-06` | no automatizada de forma funcional |
| `PT5-OH-07` | no explícita como aserción semántica RDF/OWL |
| `PT5-OH-08` | parcial |
| `PT5-OH-09` | si |
| `PT5-OH-10` | si |
| `PT5-OH-11` | parcial |
| `PT5-OH-12` | no explícita |
| `PT5-OH-13` | cubierta desde integración, no desde funcional |
| `PT5-OH-14` | si, sustancial |
| `PT5-OH-15` | parcial |
| `PT5-OH-16` | cubierta como integración INESData, no como funcional directa |

## Integración Semántica con INESData

El framework integra la extensión semántica del conector INESData de forma
selectiva:

- la interfaz del conector permite seleccionar vocabularios de `Ontology Hub`;
- el flujo detecta archivos RDF y lanza validación semántica antes de crear el
  asset;
- el conector incluye la extensión `ontology-validator`;
- `ONTOLOGY_URL` se genera desde el dataspace activo y se inyecta en
  `app.config.json`;
- las URLs `ontology-hub-<dataspace>.<dominio>` se traducen internamente a
  `http://<dataspace>-ontology-hub:3333`.

Las credenciales administrativas de `Ontology Hub` no se hardcodean en el
frontend. Cualquier flujo que necesite secretos debe resolverse mediante
configuración segura o backend intermedio.
