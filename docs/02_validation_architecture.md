# 02. Arquitectura de Validación

## Qué valida hoy el sistema

La validación actual comprueba la interoperabilidad básica entre conectores del dataspace.

El foco hoy está en el núcleo compartido del sistema:

- estado del entorno
- API de gestión del conector
- preparación del proveedor
- descubrimiento por catálogo
- negociación
- transferencia o acceso

Estas pruebas viven en `validation/core/collections/`.

## Qué significa `core`

`core` es la validación común que cualquier despliegue funcional del dataspace debe superar.

No está pensada para un componente concreto. Está pensada para responder a una pregunta muy práctica:

“¿Los conectores desplegados pueden interoperar entre sí en el flujo base esperado?”

## Qué significa `components`

La carpeta `validation/components/` separa validaciones específicas por componente.

Hoy conviven dos situaciones:

- `ontology_hub/` ya actúa como implementación de referencia y sí puede ejecutarse automáticamente desde `Level 6`.
- `ai_model_hub/` ya dispone de estructura base y catálogo PT5, pero todavía no tiene runner registrado ni se ejecuta automáticamente.
- `semantic_virtualization/` sigue siendo estructura reservada para futuras implementaciones.

La ejecución automática de una validación de componente depende de dos condiciones:

1. el componente debe estar declarado en `COMPONENTS` en `deployers/inesdata/deployer.config`. Ejemplo: `COMPONENTS=ontology-hub,ai-model-hub`
2. debe existir un runner registrado para ese componente

## Qué significa `shared`

`validation/shared/api/` contiene utilidades comunes que pueden reutilizar varias colecciones.

Hoy se usa sobre todo para centralizar el script compartido `common_tests.js`.

## Diferencia entre pruebas API y pruebas UI

### Pruebas API

Son las pruebas que constituyen la base obligatoria del framework.

Se ejecutan con Newman y verifican contratos, respuestas y flujos backend.

Sirven para comprobar interoperabilidad y consistencia de las APIs implicadas en el dataspace.

Además de la validación core, algunos componentes pueden tener también pruebas API específicas dentro de `validation/components/`.

### Pruebas UI

La carpeta `validation/ui/` contiene suites Playwright activas para:

- login y shell del conector
- flujo provider
- flujo consumer
- negociación
- transferencia
- comprobaciones visuales opcionales de MinIO Console

`Level 6` ejecuta por defecto un smoke UI estable por conector y, cuando la suite existe, la comprobacion UI de MinIO. Esa comprobacion puede desactivarse con `LEVEL6_RUN_UI_OPS=false`.

Además, `ontology_hub` dispone de su propia suite UI dentro de `validation/components/ontology_hub/ui/`, separada de la UI del dataspace core.

## Qué debe saber un desarrollador de componentes

Los desarrolladores de componentes no deben implementar ni modificar la lógica de validación del framework.

La responsabilidad práctica está separada así:

- el desarrollador integra el componente en despliegue o en código fuente
- el framework mantiene las pruebas en `validation/`

En otras palabras:

- sí debes conocer qué valida el sistema
- no debes asumir que integrar el componente equivale a modificar `framework/`
- la capa de validación se mantiene desde el framework y puede ampliarse después de que el componente esté desplegado
