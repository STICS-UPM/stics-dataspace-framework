# Benchmark de concurrencia de stores del conector (Postgres vs triplestore SPARQL)

Banco de pruebas reproducible para medir cómo responde el store de un conector EDC
ante operaciones secuenciales y concurrentes sobre assets. Se ejecuta primero contra
nuestros conectores INESData (Postgres) como línea base y, después, con la misma matriz,
contra el conector con la extensión triplestore de Andrea
([STICS-UPM/triplestore-extension-connector](https://github.com/STICS-UPM/triplestore-extension-connector)).

## Estructura

```
dataset/fetch_sk_catalog.py    congela un snapshot del catálogo nacional eslovaco (SPARQL, con red)
dataset/sources/sk-catalog/    snapshots commiteados (fuente por defecto del benchmark)
dataset/generate_assets.py     genera los payloads EDC desde el snapshot o en modo sintético (sin red)
jmeter/S1_S2_create_assets.jmx S1 (secuencial) / S2 (paralelo): creación de assets
scripts/install_jmeter.sh      descarga JMeter 5.6.3 fijado y verifica SHA-512 (en .tools/)
scripts/run_create.sh          ejecuta la matriz hilos x repeticiones y guarda resultados
analysis/summarize.py          resume los JTL en summary.csv (percentiles, throughput, consistencia)
env/stics.properties.example   plantilla del entorno objetivo (sin contraseña)
```

## Dataset

### Fuente por defecto: catálogo nacional de datos abiertos de Eslovaquia

Los assets se construyen con metadatos **reales** del *Národný katalóg otvorených dát*
(`data.slovensko.sk`, ~22.600 datasets en DCAT-AP), consultados con su endpoint SPARQL
público `https://data.slovensko.sk/api/sparql`.

Para que sea reproducible se trabaja en dos pasos:

1. **Snapshot** (con red, se ejecuta una sola vez y se commitea):
   ```bash
   python3 dataset/fetch_sk_catalog.py --themes TRAN,ENVI,ENER,ECON,GOVE,REGI --per-theme 200
   ```
   Selección determinista:
   - título en eslovaco y descripción;
   - tema EU Data Theme;
   - al menos una distribución con `downloadURL` en CSV o JSON, licenciada **CC BY 4.0 o CC0**
     según los *terms of use* del catálogo;
   - en cada tema, orden por IRI y límite por tema.

   El snapshot guarda las consultas SPARQL exactas y su hash, la fecha de descarga y el
   hash de los registros. Dos descargas del mismo día dan el mismo `records_sha256`.

   Snapshot actual: `snapshot-2026-10-21.json`, con 962 datasets
   (TRAN 200, ENVI 200, ENER 17, ECON 200, GOVE 193, REGI 152).
2. **Generación** (sin red, determinista):
   ```bash
   python3 dataset/generate_assets.py --count 100          # --source sk-catalog por defecto
   ```
   Los registros se reparten de forma rotatoria entre los temas, así que cualquier tamaño
   queda equilibrado. Con 100 assets: 17 por tema (ENER aporta sus 17) y 16 en GOVE y REGI.

   Cada asset conserva:
   - título, descripción, palabras clave, editor, fechas, periodicidad, ámbito espacial (NUTS),
     licencia, formato y landing page originales;
   - la procedencia: `dct:source` (IRI del dataset en el catálogo) y `dct:identifier`;
   - la URL de descarga original, en `dcat:downloadURL`.

   El `dataAddress` apunta a esa distribución original. Para medir transfers (S8) sin ruido
   de red externa, usa `--data-base-url http://<mirror-local>`: el asset apuntará a
   `<mirror>/<asset_id>`.

   Referencia: `--count 100` sobre `snapshot-2026-10-21.json` →
   `dataset_sha256 = 63672607284edd5c7142ccb848d78adafca3fe1908b8223abf9bc01657f74443`.

El `manifest.json` de la salida registra el snapshot (fichero, SHA-256, fecha y endpoint)
y la lista de IRIs de origen. Esa lista se copia a cada experimento en `dataset_manifest.json`.

Pendiente de confirmar antes de publicar:
- La licencia de los **metadatos** del propio catálogo. Las licencias CC BY / CC0 filtradas
  son las de las distribuciones; hay que citar la fuente en el paper.
- El significado de los códigos `personal-data-occurence-type/1|2|3`: el catálogo no los
  resuelve. Se guardan sin filtrar en el snapshot (en el actual: 851 con el código 2, 108 con
  el 3 y 3 con el 1). Afecta solo si se copian los datos para S8, no a los metadatos.

### Fuente alternativa: sintética

```bash
python3 dataset/generate_assets.py --source synthetic --count 100 --seed 20261014
```

Metadatos STICS ficticios de cinco dominios a partir de una semilla. No necesita snapshot y
escala a cualquier tamaño, útil para pruebas sin red o para tamaños mayores que el snapshot.
Referencia: `dataset_sha256 = eb401b19e61fb5cce06695ff625df25287ca7fba4de73b88884f7e3c6201277e`.

En ambas fuentes la salida incluye un JSON de creación y otro de actualización por asset
(Management API v3), `assets.csv` para JMeter y `manifest.json` con el SHA-256 de cada
fichero. Si cambia el generador, sube `GENERATOR_VERSION` y actualiza los hashes de referencia.

## S1 / S2: creación de assets

El plan JMeter tiene tres fases:

| Fase | Qué hace | Etiqueta en el JTL |
|---|---|---|
| setUp | login Keycloak (password grant) y borrado previo de los assets del dataset (204/404) | `AUTH token`, `PRE delete asset` |
| main | `POST /v3/assets`; los hilos comparten un único lector CSV, de modo que cada asset se crea exactamente una vez por ejecución | `CREATE asset` (**la medida**) |
| tearDown | borra los assets creados (204) | `TEARDOWN delete asset` |

Con `threads=1` es S1 (secuencial); con `threads>1`, S2 (paralelo, ramp-up 0).

### Ejecución

```bash
cp env/stics.properties.example env/stics.properties   # ajustar conector / usuario
export BENCH_PASSWORD='...'                            # credentials.json del conector
scripts/run_create.sh -e env/stics.properties -t "1 5 10 25 50" -r 5
```

Opciones: `-S` fuente del dataset (`sk-catalog` por defecto, o `synthetic`), `-w` ejecuciones
de warm-up por configuración (por defecto 1), `-n` número de assets, `-s` semilla (solo en
modo sintético), `-p` pausa entre ejecuciones en segundos.

La contraseña solo se escribe en un fichero de propiedades temporal con permisos 600 y
nunca aparece en la línea de comandos de JMeter.

### Resultados

Se guardan en `experiments/perf_store_concurrency_<timestamp>/` (carpeta gitignored):

- `metadata.json`: commit, `target_label`, URL objetivo, hash del dataset, versiones de JMeter
  y Java, y hardware del cliente.
- `dataset_manifest.json`
- `jtl/<S1|S2>_t<hilos>_r<rep>.jtl` (los de warm-up empiezan por `warmup_`) y `logs/`
- `summary.csv`: muestras, errores, media/p50/p95/p99/máx en ms, tiempo de pared,
  ops/s, códigos de respuesta y `consistent` (creaciones correctas == tamaño del dataset).

Para comparar Postgres con el triplestore, ejecuta la misma matriz contra cada conector
cambiando solo el fichero `env/` (y `target_label`).

## Próximos escenarios

S3 lectura/consulta (por ejemplo, filtros por `dcat:theme` o `dct:publisher`), S4 actualización (los payloads `update/` ya se generan), S5 borrado,
S6 carga mixta, S7 conflicto sobre el mismo asset y S8 negociación/transfer con varias
réplicas del control plane (valida el algoritmo de lease de la extensión).
