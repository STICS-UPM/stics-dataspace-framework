# Ontology Hub Validation

Esta carpeta agrupa toda la validacion de `Ontology Hub` dentro del framework.

## Estructura

- `integration/`: validacion PT5 de integracion tecnica del componente dentro del framework.
- `functional/`: flujos funcionales Playwright trazados contra la hoja `Ontology Hub` del Excel A5.2.
- `ui/`: infraestructura Playwright compartida por ambas suites (`fixtures`, `pages`, `support`, runtime comun).
- `runtime_config.py`: resolucion comun de runtime para el componente.
- `tools/`: utilidades auxiliares de mantenimiento y trazabilidad.

## Uso recomendado

- Si quieres validar la integracion oficial del componente en el framework: revisa `validation/components/ontology_hub/integration/`.
- Si quieres validar los flujos funcionales del componente como aplicacion: revisa `validation/components/ontology_hub/functional/`.

## Suites

### Integration

- Proposito: casos PT5 y checks de soporte de integracion del componente dentro del framework.
- Entrada principal: `validation/components/ontology_hub/integration/component_runner.py`.
- Catalogo de casos: `validation/components/ontology_hub/integration/test_cases.yaml`.
- Documentacion: `validation/components/ontology_hub/integration/README.md`.

### Functional

- Proposito: reproduccion funcional de los 27 casos del Excel `docs/A5.2_Casos_Prueba_.xlsx`.
- Suite PT5 ejecutada por defecto para `ontology-hub` en `Level 6`.
- Entrada desde menu: `python3 main.py menu` -> `U - UI Validation` -> `2 - Ontology Hub Tests` -> modo -> `2 - Ontology Hub Functional`.
- Documentacion: `validation/components/ontology_hub/functional/README.md`.
- Trazabilidad: `docs/11_ontology_hub_validation.md`.

## Artefactos

Los artefactos de ejecucion del framework deben quedar bajo:

- `Validation-Environment/experiments/`

Cuando los runners del framework se lanzan sin `experiment_dir`, la salida por
defecto se redirige a:

- `Validation-Environment/experiments/_standalone/components/ontology-hub/functional/`
- `Validation-Environment/experiments/_standalone/components/ontology-hub/ui/`

Las carpetas Playwright locales (`test-results`, `playwright-report`,
`blob-report`) solo deben aparecer en ejecuciones Playwright directas de
desarrollo, por ejemplo con `npx playwright test ...`.
