# Ontology Hub API Integration

Esta carpeta conserva la validación técnica de integración API de Ontology Hub para Level 6. En consola y reportes aparece como `Ontology Hub API integration` para distinguirla de la suite UI funcional.

La validación UI PT5 del componente se ejecuta desde `validation/components/ontology_hub/functional/`. La antigua suite Playwright de `integration/` se retiró porque duplicaba casos ya cubiertos por `OH-APP-*` y podía producir `skipped` engañosos en el reporte.

## Alcance

La suite actual ejecuta cinco casos técnicos:

- `PT5-OH-08`: búsqueda pública de términos.
- `PT5-OH-09`: búsqueda filtrada equivalente por API.
- `PT5-OH-13`: consulta SPARQL real.
- `PT5-OH-14`: acceso al servicio de patrones.
- `PT5-OH-15`: disponibilidad coordinada de UI pública y documentación API.

Los flujos de UI equivalentes quedan cubiertos por la suite funcional `OH-APP-*` y por la integración read-only desde INESData cuando aplica.

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
