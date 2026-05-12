# Suites de proyecto

Esta carpeta está reservada para validaciones específicas de proyectos que
reutilizan el framework sin modificar las suites base.

Uso recomendado:

- `validation/core/`: contrato común Newman del dataspace.
- `validation/ui/`: Playwright core actual por adapter.
- `validation/components/`: componentes opcionales como `ontology-hub` o
  `ai-model-hub`.
- `validation/projects/<project>/`: pruebas propias de un proyecto externo o
  productivo.

Las suites de proyecto deben ser opt-in desde un target de validación. No deben
ejecutarse por defecto ni modificar las pruebas base.
