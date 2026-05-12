# Ontology Hub Integration

Esta carpeta define la implementacion de referencia para la validacion de componentes PT5 dentro de `validation/components/`.

## Fuentes Oficiales

Esta bateria se construye a partir de la normalizacion local de:

- los casos oficiales PT5 del componente `Ontology Hub`
- la trazabilidad funcional asociada al componente
- la superficie real expuesta por la instancia desplegada en el framework

En el repositorio publico, la fuente normativa que debe consultarse es:

- `validation/components/ontology_hub/integration/test_cases.yaml`

La utilidad `tools/extract_ontology_hub_cases.py` se conserva como herramienta interna de regeneracion cuando se dispone localmente de las fuentes crudas originales. No es necesaria para ejecutar la validacion automatica del framework.

## Casos Normalizados

Los casos estructurados estan en:

- `validation/components/ontology_hub/integration/test_cases.yaml`

El catalogo local distingue ahora dos grupos:

- `test_cases`: casos oficiales PT5
- `support_checks`: comprobaciones auxiliares necesarias para estabilizar la ejecucion automatica sin contarlas como cobertura PT5 oficial

Ademas, cada entrada puede declarar:

- `validation_type`
- `dataspace_dimension`
- `execution_mode`
- `coverage_status`
- `mapping_status`

## Agrupacion por Flujos

### 1. Gestion de vocabularios

- `PT5-OH-01` crear entrada
- `PT5-OH-02` editar entrada
- `PT5-OH-03` eliminar entrada
- `PT5-OH-04` gestion de etiquetas
- `PT5-OH-07` compatibilidad RDF / OWL

### 2. Gobernanza y control

- `PT5-OH-05` usuarios y roles
- `PT5-OH-06` registro de acciones

### 3. Descubrimiento y visualizacion

- `PT5-OH-08` busqueda de vocabularios
- `PT5-OH-09` filtrado de vocabularios
- `PT5-OH-10` seleccion de versiones
- `PT5-OH-11` visualizacion completa
- `PT5-OH-12` estadisticas
- `PT5-OH-15` acceso via UI y API

### 4. Servicios semanticos

- `PT5-OH-13` consulta SPARQL
- `PT5-OH-14` servicios externos

### 5. Integracion en espacio de datos

- `PT5-OH-16` conexion con el conector

## Mapeo a Flujos Reales

| Caso | Tipo | Mapeo real | Estado | Notas |
| --- | --- | --- | --- | --- |
| `PT5-OH-01` | `api` | Ingestion de ontologias + catalogo LOV | `partial` | La documentacion confirma ingestion y catalogo, pero no documenta el endpoint de alta. |
| `PT5-OH-02` | `api` | Edicion de metadatos de ontologia | `partial` | No hay endpoint o formulario de edicion documentado localmente. |
| `PT5-OH-03` | `api` | Eliminacion de ontologia | `partial` | No hay endpoint o accion UI documentada localmente. |
| `PT5-OH-04` | `ui` | Tags en catalogo: `/dataset/lov/vocabs?tag=<tag>` | `partial` | Existen enlaces por tag en la home, pero no se documenta CRUD completo de etiquetas. |
| `PT5-OH-05` | `ui` | Gestion de usuarios y roles | `partial` | No se documentan pantallas ni endpoints de usuarios/roles. |
| `PT5-OH-06` | `api` | Auditoria de operaciones | `partial` | No se documenta endpoint de logs o auditoria. |
| `PT5-OH-07` | `api` | Registro de RDF/OWL | `partial` | La compatibilidad RDF/OWL esta descrita, pero sin contrato API concreto. |
| `PT5-OH-08` | `api` | `GET /dataset/lov/api/v2/term/search?q=<q>&type=<type>` | `mapped` | Endpoint documentado en `/dataset/lov/api` y validado con contenido real sembrado por el framework. |
| `PT5-OH-09` | `ui` | `GET /dataset/lov/terms?q=Person` + filtros visibles `Tag` y `Vocabulary` | `mapped` | La UI publica expone filtros por tag y vocabulario desde la vista de terminos. |
| `PT5-OH-10` | `ui` | Historial de versiones en `/dataset/lov/vocabs/<prefix>` + recursos `.n3` versionados | `partial` | La UI ya publica el historial y los recursos versionados; la seleccion visual fina de versiones sigue siendo limitada. |
| `PT5-OH-11` | `ui` | Ficha de ontologia: `/dataset/lov/vocabs/<prefix>` | `mapped` | La ficha queda soportada por la semilla Mongo/versiones del framework y se automatiza con Playwright. |
| `PT5-OH-12` | `ui` | Estadisticas y popularidad en la ficha `/dataset/lov/vocabs/<prefix>` | `mapped` | La ficha publica expone `Statistics`, grafica de elementos y uso en LOD. |
| `PT5-OH-13` | `api` | `GET /dataset/lov/sparql?query=ASK {...}` | `mapped` | La validacion automatica ejecuta una consulta SPARQL real sobre la ontologia de ejemplo sembrada y espera `boolean=true`. |
| `PT5-OH-14` | `api` | `GET /dataset/lov/patterns` | `partial` | La ruta existe en navegacion y se valida su publicacion como servicio accesible. |
| `PT5-OH-15` | `ui` | UI: `/dataset/lov/`, API docs: `/dataset/lov/api` | `mapped` | Se valida con Playwright la publicacion coordinada de la UI principal y la documentacion API. |
| `PT5-OH-16` | `api` | Integracion con conector / espacio de datos | `partial` | No hay contrato tecnico local que documente esta integracion extremo a extremo. |

## Rutas Reales Confirmadas

Las siguientes rutas se han confirmado directamente en la instancia demo:

- `/`
- `/dataset/lov/`
- `/dataset/lov/vocabs`
- `/dataset/lov/terms`
- `/dataset/lov/agents`
- `/dataset/lov/sparql`
- `/dataset/lov/patterns`
- `/dataset/lov/api`
- `/dataset/lov/api/v2/term/search`
- `/dataset/lov/api/v2/term/autocomplete`
- `/dataset/lov/api/v2/term/suggest`
- `/dataset/lov/api/v2/term/search/metadata`

## Bateria Automatizada Implementada

La bateria automatizada actual implementa cinco casos PT5 por API, seis casos PT5 por UI y dos checks de soporte por UI.

API:

- `PT5-OH-08` busqueda de vocabularios por texto libre
- `PT5-OH-09` busqueda filtrada equivalente por API
- `PT5-OH-13` consulta SPARQL real sobre la ontologia de ejemplo
- `PT5-OH-14` acceso al servicio de patrones
- `PT5-OH-15` disponibilidad coordinada de UI y documentacion API

UI:

- `PT5-OH-01` creacion de vocabulario desde la fuente configurada en runtime, por URI o repositorio
- `PT5-OH-09` filtrado de vocabularios por tag y vocabulario
- `PT5-OH-10` historial de versiones y recursos `.n3` versionados
- `PT5-OH-11` visualizacion completa de la ficha de ontologia
- `PT5-OH-12` estadisticas visibles en la ficha
- `PT5-OH-15` acceso coordinado a la UI publica y a la documentacion API

Checks de soporte UI:

- `OH-LOGIN` acceso autenticado al area de edicion
- `OH-LIST-SEARCH` listado publico y apertura de resultado

Archivos:

- `validation/components/ontology_hub/integration/runner.py`
- `validation/components/ontology_hub/integration/playwright.config.js`
- `validation/components/ontology_hub/integration/specs/*.spec.js`
- `validation/components/ontology_hub/integration/state/ontology-hub-bootstrap.json`

Comportamiento API:

- ejecuta `GET /dataset/lov/api/v2/term/search?q=Person&type=class`
- ejecuta una consulta `ASK` real contra `/dataset/lov/sparql`
- valida publicacion de `/dataset/lov/patterns`, `/dataset/lov/` y `/dataset/lov/api`
- marca fallo si el payload contiene errores embebidos como `statusCode >= 400`, `error` o `msg`
- marca fallo si una pagina HTML responde `200` pero renderiza una pagina rota de servidor, por ejemplo `500 - Oops! something went wrong - 500`
- exige resultados reales para `PT5-OH-08`, no solo `HTTP 200`

Comportamiento UI:

- autentica en `/edition/login` cuando el flujo lo requiere
- resuelve las credenciales UI desde `deployers/shared/components/ontology-hub/values.yaml` y `values-<dataspace>.yaml`, en `validation.ui.adminEmail` y `validation.ui.adminPassword`
- permite sobrescribirlas por entorno con `ONTOLOGY_HUB_ADMIN_EMAIL`, `ONTOLOGY_HUB_ADMIN_PASSWORD`, `ONTOLOGY_HUB_ADMIN_EMAIL_FILE` y `ONTOLOGY_HUB_ADMIN_PASSWORD_FILE`. El estado persistido del bootstrap se puede redirigir con `ONTOLOGY_HUB_INTEGRATION_STATE_FILE` y mantiene compatibilidad con `ONTOLOGY_HUB_BOOTSTRAP_STATE_FILE`
- abre `/dataset`, `/dataset/terms` y `/dataset/vocabs/<prefix>` segun el caso
- valida metadatos, estadisticas, historial y documentacion API sobre la publicacion actual en `/dataset`
- en `PT5-OH-01` espera a que la propia aplicacion publique el vocabulario en el catalogo; ya no acepta como valido ningun postproceso manual externo tipo `lovInitialization.sh`
- mantiene checks de soporte para login y navegacion publica

Nota:

- la superficie UI actual se valida sobre `/dataset`
- la superficie API automatizada mantiene compatibilidad sobre `/dataset/lov`
- esta coexistencia queda reflejada en `integration/test_cases.yaml` y en el reporting combinado

Ejecucion manual de la suite UI:

```bash
cd validation/ui
./node_modules/.bin/playwright test --config=../components/ontology_hub/integration/playwright.config.js
```

Esto permite detectar fallos de integracion aunque el endpoint responda con `200` pero arrastre un error interno del backend.

## Semilla de Ontologias de Ejemplo

Para que `PT5-OH-08`, `PT5-OH-09`, `PT5-OH-10`, `PT5-OH-11`, `PT5-OH-12` y `PT5-OH-13` validen contenido real, el chart de despliegue de `ontology-hub` ahora siembra datos de ejemplo en cuatro capas durante el despliegue:

- un vocabulario `demohub`
- una clase `demohub:Person`
- una propiedad `demohub:name`
- dos versiones `.n3` descargables del vocabulario
- un fichero RDF `lov.nq` que se carga en Fuseki/TDB para la consulta SPARQL
- un documento Mongo `vocabularies` con la ficha publica
- un documento Mongo `statvocabularies` con soporte minimo para la vista de detalle

La semilla se configura en:

- `deployers/shared/components/ontology-hub/values.yaml`
- `deployers/shared/components/ontology-hub/templates/`

Y se aplica desde el propio deployment para dejar:

- el indice `lov` de Elasticsearch preparado para las busquedas
- la coleccion `vocabularies` de Mongo preparada para la ficha `/dataset/lov/vocabs/demohub`
- la coleccion `statvocabularies` preparada para la vista de detalle
- el directorio `/app/versions/<id>/` con recursos `.n3` versionados
- el dataset RDF de Fuseki cargado antes de arrancar la app Node

## Integracion con Level 6

La validacion de componentes se ejecuta desde `Level 6` sin tocar `validation/core`.

En el estado actual del framework, `Level 6` usa por defecto la suite
`validation/components/ontology_hub/functional/` para `ontology-hub`, porque es
la suite PT5 funcional ya detallada y estabilizada para PIONERA.

Esta carpeta `integration/` se conserva como suite tecnica complementaria de
integracion del componente en el framework. Sigue siendo ejecutable de forma
directa y util para comprobaciones tecnicas, pero ya no es el flujo automatico
por defecto de `Level 6`.

Historicamente, el flujo integrado combinaba dos suites:

- `api`: runner tecnico de `validation/components/ontology_hub/integration/runner.py`
- `ui`: suite Playwright de `validation/components/ontology_hub/integration/`

Reglas:

- se ejecuta por defecto si `COMPONENTS` incluye componentes con validador registrado, como `ontology-hub`
- `LEVEL6_RUN_COMPONENT_VALIDATION=false` permite desactivarla de forma explicita
- `LEVEL6_RUN_COMPONENT_VALIDATION=true` mantiene el comportamiento habilitado de forma explicita
- solo valida componentes presentes en `COMPONENTS`
- solo ejecuta componentes con validador registrado
- si Playwright no esta disponible en tiempo de ejecucion, la suite UI del componente queda en `skipped`, pero la suite API sigue ejecutandose y el resultado combinado se persiste igualmente

Artefactos esperados en experimento:

- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_component_validation.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_pt5_case_results.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_support_checks.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_evidence_index.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_findings.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_catalog_alignment.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_validation.json`
- `experiments/<experiment_id>/components/ontology-hub/ui/ontology_hub_ui_validation.json`
- `experiments/<experiment_id>/components/ontology-hub/ui/results.json`
- `experiments/<experiment_id>/components/ontology-hub/ui/playwright-report/`
- `experiments/<experiment_id>/components/ontology-hub/ui/blob-report/`
- `experiments/<experiment_id>/components/ontology-hub/ui/test-results/`
- `experiments/<experiment_id>/components/ontology-hub/pt5-oh-08-response.json`
- `experiments/<experiment_id>/components/ontology-hub/pt5-oh-09-response.json`
- `experiments/<experiment_id>/components/ontology-hub/pt5-oh-13-response.json`
- `experiments/<experiment_id>/components/ontology-hub/pt5-oh-14-response.json`
- `experiments/<experiment_id>/components/ontology-hub/pt5-oh-15-response.json`

El resultado combinado se registra en `experiment_results.json` bajo `component_results[]`, con esta estructura de alto nivel:

- `component`
- `status`
- `summary`
- `suites.api`
- `suites.ui`
- `executed_cases`
- `pt5_case_results`
- `pt5_summary`
- `support_checks`
- `support_summary`
- `evidence_index`
- `findings`
- `catalog_alignment`

## Estructura Objetivo

```text
validation/components/
  runner.py
  ontology_hub/
    __init__.py
    README.md
    runner.py
    integration/test_cases.yaml
    ui/
      playwright.config.js
      fixtures.js
      runtime.js
      pages/
      specs/
```

Esta estructura se deja como referencia para replicar el mismo patron en:

- `validation/components/ai_model_hub/`
- `validation/components/semantic_virtualization/`
