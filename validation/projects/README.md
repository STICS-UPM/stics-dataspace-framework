# Suites de proyecto

Esta carpeta está reservada para validaciones específicas de proyectos que
reutilizan el framework sin modificar las suites base.

Uso recomendado:

- `validation/core/`: contrato común Newman del dataspace.
- `validation/ui/`: Playwright core actual por adapter.
- `validation/components/`: componentes desplegados desde Level 5, como
  `ontology-hub` o `ai-model-hub`.
- `validation/projects/<project>/`: pruebas propias de un proyecto externo o
  productivo.

Cada proyecto declara sus suites en `project_suites.yaml`:

- `active`: suite madura incluida por el target indicado, por ejemplo
  `execution: level6_default`;
- `scaffold`: suite preparada para extensión, sin ejecución automática hasta que
  tenga casos, fixtures y evidencias aceptadas.

Kafka/streaming transfer es el único bloque de Level 6 que requiere activación
explícita por coste temporal.
