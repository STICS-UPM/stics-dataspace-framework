# Ontology Hub API Integration

Esta carpeta conserva la validación técnica de integración API de Ontology Hub para Level 6. En consola y reportes aparece como `Ontology Hub API integration` para distinguirla de la suite UI funcional.

La validación UI PT5 del componente se ejecuta desde `validation/components/ontology_hub/functional/`. La antigua suite Playwright de `integration/` se retiró porque duplicaba casos ya cubiertos por `OH-APP-*` y podía producir `skipped` engañosos en el reporte.

## Alcance

La suite actual ejecuta cinco casos técnicos:

- `PT5-OH-08`: búsqueda pública de términos.
- `PT5-OH-09`: búsqueda filtrada con cobertura compuesta UI+API.
- `PT5-OH-13`: consulta SPARQL real sobre el recurso RDF sembrado, con doble evidencia: ejecución interna en Kubernetes y exposición pública por ingress.
- `PT5-OH-14`: servicios ontológicos con cobertura compuesta UI+API.
- `PT5-OH-15`: disponibilidad coordinada de UI pública y documentación API con cobertura compuesta UI+API.

Los flujos de UI equivalentes quedan cubiertos por la suite funcional `OH-APP-*` y por la integración read-only desde INESData cuando aplica.

Los casos `PT5-OH-09`, `PT5-OH-14` y `PT5-OH-15` se declaran como cobertura
compuesta: la evidencia de usuario vive en la suite funcional `OH-APP-*` y esta
suite conserva el check técnico API/HTTP que permite defender la integración sin
duplicar pasos de Playwright.

## Archivos

- `runner.py`: ejecuta los checks API.
- `component_runner.py`: normaliza resultados y genera los artefactos de integración.
- `test_cases.yaml`: declara únicamente los casos ejecutados por esta suite.

## Integración Con Level 6

Level 6 ejecuta esta suite después de la suite funcional de Ontology Hub. El resultado esperado ya no incluye una sub-suite `ui` dentro de `integration`; por tanto, no deben aparecer los 9 `skipped` legacy.

Artefactos esperados:

- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_integration_component_validation.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_integration_pt5_case_results.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_integration_support_checks.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_integration_evidence_index.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_integration_findings.json`
- `experiments/<experiment_id>/components/ontology-hub/ontology_hub_integration_catalog_alignment.json`

## Criterio De Cierre

Si un caso falla porque el componente responde `500`, `502` u otra respuesta funcionalmente inválida, el fallo se conserva como incidencia del componente o de su integración. No debe transformarse en `skipped`.

Para `PT5-OH-13`, el criterio principal es que la consulta `ASK` funcione desde
dentro del clúster sobre el endpoint del componente. La misma consulta se ejecuta
también por el endpoint público para dejar evidencia de exposición. Si el check
interno pasa y el ingress falla, la suite conserva el caso como automatizado y
registra el fallo público como advertencia diagnóstica en el artefacto
`pt5-oh-13-response.json`.

Si el primer intento interno no encuentra datos en Fuseki, el runner puede
preparar el almacén RDF temporal del pod a partir de `/app/public/lov.nq` y
reintentar la consulta. Este comportamiento está activado por defecto mediante
`ONTOLOGY_HUB_PREPARE_SPARQL_STORE=true` y puede desactivarse si se quiere
validar únicamente el estado exacto en que quedó el componente tras el despliegue.
El recurso consultado se puede ajustar con
`ONTOLOGY_HUB_EXPECTED_SPARQL_RESOURCE_URI`.
