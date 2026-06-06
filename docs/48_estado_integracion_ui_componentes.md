# Estado de Integración UI de Componentes

Este documento resume el estado de cierre de la integración de interfaces de
componentes en el framework de validación.

## Alcance Cerrado

La integración UI de componentes queda cubierta en el adapter `inesdata` mediante
la interfaz del conector y sus suites automatizadas de `Level 6`.

La interfaz del conector incluye rutas y vistas para:

- `AI Model Browser`;
- `AI Model Execution`;
- `AI Model Benchmarking`;
- `AI Model Observer`;
- `Ontologies`, conectada con `Ontology Hub`;
- flujos de vocabularios y creación de assets que consumen metadatos de
  ontologías y vocabularios de modelos.

Las suites Playwright de INESData cubren la integración de estos componentes con
los conectores:

- `08-ontology-hub-inesdata-readonly.spec.ts`;
- `09-ai-model-hub-httpdata.spec.ts`;
- `10-ai-model-observer.spec.ts`;
- `11-ai-model-browser.spec.ts`;
- `12-ai-model-execution.spec.ts`;
- `13-ai-model-benchmarking.spec.ts`;
- `14-ai-model-daimo-vocabulary.spec.ts`;
- `15-ai-model-external-execution.spec.ts`;
- `16-ai-model-observer-participant-summary.spec.ts`.

Además, `Level 6` ejecuta validaciones de componentes registradas para:

- `ontology-hub`;
- `ai-model-hub`;
- `semantic-virtualization`.

## EDC

El adapter `edc` incluye dashboard, proxy y suites Playwright propias para los
flujos del conector EDC. La ruta oficial de cierre para `edc` es
`vm-distributed`.

La integración UI de componentes en EDC se apoya en el dashboard EDC oficial
versionado como submódulo Git del framework. Los overlays del framework solo
añaden configuración o adaptación necesaria para la validación. El dashboard
incorpora:

- navegación de activos de modelos (`ML Assets`);
- ejecución de modelos (`Model Execution`);
- benchmarking de modelos (`Model Benchmarking`);
- navegación de ontologías (`Ontologies`) conectada con `Ontology Hub`;
- resolución de URLs de componentes desde la configuración runtime del
  despliegue.

Las validaciones de EDC pueden combinar pruebas Playwright del dashboard con
validaciones API, porque EDC y su dashboard no replican exactamente la
estructura de la interfaz INESData. La integración queda parametrizada mediante
los ficheros de topología y adapter, especialmente para la URL pública de
`Ontology Hub`.

La suite Playwright de EDC incluye pruebas análogas a las de INESData para:

- catálogo, negociación, transferencia y almacenamiento;
- `semantic-virtualization` como asset `HttpData`;
- `Ontology Hub` en modo read-only;
- `AI Model Hub` como asset `HttpData`;
- `AI Model Browser`;
- `AI Model Execution`;
- `AI Model Benchmarking`;
- `Model Observer`;
- metadatos DAIMO de modelos;
- ejecución externa de modelos negociados.

Las pruebas de paridad de `Model Observer` se ejecutan contra la ruta real
`/edc-dashboard/model-observer` cuando se habilita
`UI_EDC_MODEL_OBSERVER_DEMO=1`. El framework no convierte una ausencia de UI en
un falso éxito: si el dashboard desplegado no contiene esa ruta, la validación
falla con causa explícita.

## Topologías

Las tres topologías coexisten en el framework:

- `local`;
- `vm-single`;
- `vm-distributed`.

La evidencia oficial de cierre debe asociarse a la topología y adapter con los
que fue generada. Para componentes sobre INESData, la referencia consolidada de
resultados se documenta en el entregable E5.2. Para EDC, la evidencia oficial se
limita a `vm-distributed` salvo que se genere una revalidación posterior en otra
topología.

## Condiciones Operativas

La integración UI de componentes no debe depender de rutas hardcodeadas de un
entorno concreto. Las URLs públicas de componentes y conectores se resuelven
desde los ficheros de configuración de topología y adapter.

Cuando un componente requiere una exposición especial, como el editor Streamlit
de `semantic-virtualization`, el framework permite configurar una URL pública
dedicada para evitar reescrituras de ruta incompatibles con WebSocket.

## Estado de Cierre

El framework queda preparado para presentar la integración UI de componentes
como cerrada para `inesdata`, con suites automatizadas, rutas de interfaz y
evidencias de `Level 6`.

Para `edc`, el framework queda preparado con el dashboard oficial versionado,
integración UI de `AI Model Hub`, `Ontology Hub` y `Model Observer`, y
validación de componentes por dashboard, contrato/API y evidencias asociadas a
la ruta `vm-distributed`.
