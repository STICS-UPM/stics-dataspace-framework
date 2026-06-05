# E5.2 - Validación de Componentes y Framework de Validación

Este documento consolida el entregable E5.2 desde la perspectiva del
Validation Environment. Su objetivo es adaptar la estructura oficial de
entregables PIONERA a la naturaleza de A5.2: validación de componentes en un
entorno reproducible de espacios de datos.

El documento combina tres dimensiones:

1. reporte oficial de validación;
2. manual técnico reproducible del framework;
3. manual de usuario y pruebas para ejecutar, interpretar y auditar la
   validación.

## 1. Introducción

### 1.1. Objetivo del Documento

El objetivo de E5.2 es reportar la ejecución de la validación de componentes
PIONERA, describir el framework utilizado para reproducir esa validación y
explicar las evidencias generadas. A diferencia de un entregable de desarrollo
de un único componente, E5.2 documenta un sistema de validación transversal:
despliegue, ejecución de pruebas, recolección de resultados, trazabilidad y
alineación con criterios de revisión.

### 1.2. Alcance de la Validación A5.2

El alcance de A5.2 cubre la validación funcional, de integración e
interoperabilidad de componentes en un espacio de datos. El framework valida:

- conectores y servicios comunes del espacio de datos;
- flujos proveedor-consumidor;
- integración de componentes PIONERA con el dataspace;
- componentes Ontology Hub, AI Model Hub y Semantic Virtualization;
- evidencias de ejecución generadas por Newman, Playwright, runners Python,
  Kafka cuando se activa, métricas y reportes.

El workbook principal de resultados es
[E5.2_Resultados_Validacion_Componentes.xlsx](./E5.2_Resultados_Validacion_Componentes.xlsx).
El workbook principal de casos de prueba es
[A5.2_Casos_Prueba_.xlsx](./A5.2_Casos_Prueba_.xlsx).

### 1.3. Cambios Respecto al Entregable de Planificación E5.1

E5.1/A5.1 funcionaba como planificación: roles, dimensiones, funcionalidades,
casos esperados y criterios de aceptación. E5.2 actualiza esa planificación con
ejecución real y evidencias. Los cambios principales son:

| Ámbito | E5.1/A5.1 | E5.2 |
| --- | --- | --- |
| Alcance | Plan de validación y casos previstos | Ejecución de casos, resultados y limitaciones |
| Topologías | Escenarios previstos | `local`, `vm-single` y `vm-distributed` implementadas con estados diferenciados |
| Adaptadores | Validación conceptual sobre dataspace | Adaptadores `inesdata` y `edc` contemplados |
| Pruebas | Casos funcionales planificados | Suites Newman, Playwright, runners de componentes, Kafka y métricas |
| Evidencias | Evidencias esperadas | Artefactos en `experiments/`, workbook E5.2 y reportes |
| UNE 0087 | Relación prevista | Matriz no certificante de alineación con criterios y limitaciones |
| Resultados | No aplica o pendiente | Resultados por suite, componente, caso y evidencia |

### 1.4. Relación con E2.1, E3.1 y E4.1

E5.2 no sustituye los entregables técnicos de componentes. Los utiliza como
contexto para definir qué se valida y cómo se interpreta la evidencia:

- E2.1 aporta contexto de arquitectura y servicios del espacio de datos.
- E3.1 aporta contexto de conectores, interoperabilidad y operación del
  dataspace.
- E4.1 aporta contexto técnico de componentes que se integran o se validan en
  A5.2.

Este documento referencia esos ámbitos de forma operativa, pero no replica su
contenido técnico completo.

## 2. Visión General del Framework de Validación

### 2.1. Descripción a Alto Nivel

El Validation Environment es un framework de despliegue y validación de espacios
de datos. La entrada principal es `main.py`, que ofrece menú guiado y comandos
directos. El framework organiza la ejecución en niveles:

| Nivel | Función |
| --- | --- |
| `1` | Preparar cluster Kubernetes |
| `2` | Desplegar servicios comunes |
| `3` | Desplegar dataspace o control plane |
| `4` | Desplegar conectores |
| `5` | Desplegar componentes |
| `6` | Ejecutar validación y generar evidencias |

### 2.2. Componentes PIONERA Objeto de Validación

El alcance documentado incluye:

- Ontology Hub;
- AI Model Hub;
- Semantic Virtualization;
- integración con INESData;
- flujos de interoperabilidad entre conectores;
- soporte EDC como adapter de espacio de datos.

### 2.3. Alineación con Arquitecturas de Espacios de Datos

El framework reproduce elementos comunes de un espacio de datos:

- identidad y autenticación mediante Keycloak;
- almacenamiento y buckets mediante MinIO;
- persistencia mediante PostgreSQL;
- gestión de secretos mediante Vault;
- conectores proveedor y consumidor;
- catálogo, negociación, transferencia y trazabilidad;
- servicios y componentes compartidos.

La validación no se limita a comprobar que existen pods. Comprueba rutas de
usuario, APIs, catálogos, contratos, transferencia, componentes y evidencias.

### 2.4. Alineación con INESData

INESData se usa como implementación principal para validar componentes
integrados al dataspace. El adapter `inesdata` despliega servicios, conectores,
interfaz de conector, componentes y suites de integración. El workbook E5.2
consolida la evidencia principal de componentes sobre una ejecución INESData.

### 2.5. Topologías Contempladas

| Topología | Estado documentado | Uso |
| --- | --- | --- |
| `local` | Implementada y usada como ruta de desarrollo/validación local | Reproducción controlada y depuración |
| `vm-single` | Implementada y validada como entorno VM de referencia para INESData | Validación en una VM con Kubernetes gestionado |
| `vm-distributed` | Implementada y parametrizable con roles físicos separados | Servicios comunes, conectores y componentes en VMs distintas |

La vía recomendada de operación desde estación de trabajo es Windows con WSL.
La ejecución directa dentro de una VM también está soportada cuando el operador
instala allí el repositorio.

### 2.6. Adaptadores Contemplados

| Adapter | Estado de soporte | Estado de evidencia |
| --- | --- | --- |
| `inesdata` | Despliegue y validación `Level 1-6` operativos | Evidencia consolidada en workbook E5.2 y experimentos |
| `edc` | Despliegue y validación core implementados | Ruta oficial de cierre documentada en `vm-distributed`; no se encontraron metadatos de experimento EDC versionados en `experiments/` en este checkout |

Esta separación evita confundir soporte de código con evidencia auditada. Si se
usa EDC como evidencia oficial, el experimento EDC correspondiente debe quedar
identificado y conservado.

### 2.7. Escenario Principal Validado o Declarado para Cierre

La documentación vigente declara `edc + vm-distributed` como ruta oficial de
cierre para EDC. La evidencia consolidada de componentes disponible en el
workbook E5.2 corresponde a una ejecución INESData local:
`experiment_2026-05-26_18-18-09`, con estado `passed` según el workbook.

Por tanto, E5.2 distingue:

- escenario principal de componentes evidenciado: `inesdata + local`;
- ruta oficial de cierre para EDC: `edc + vm-distributed`;
- condición para presentar EDC como evidencia: conservar e identificar el
  experimento EDC correspondiente.

## 3. Especificación del Framework de Validación

### 3.1. Requisitos del Framework

El framework debe:

- desplegar servicios comunes, dataspaces, conectores y componentes;
- parametrizar adaptador y topología;
- ejecutar casos de prueba de forma reproducible;
- generar evidencias por experimento;
- registrar métricas cuando existan;
- distinguir pruebas ejecutadas, pendientes y no evidenciadas;
- evitar contaminación entre topologías;
- evitar credenciales reales en documentación versionada;
- producir resultados interpretables para auditoría.

### 3.2. Roles y Control de Acceso

| Rol | Responsabilidad |
| --- | --- |
| Operador del espacio de datos | Configura topología, ejecuta niveles y conserva evidencias |
| Proveedor | Publica assets, políticas y contratos |
| Consumidor | Descubre catálogo, negocia contratos y consume datos o servicios |
| Responsable de validación o QA | Ejecuta Level 6, revisa resultados y limita conclusiones |
| Desarrollador/integrador | Añade componentes, adapters o casos de prueba |
| Evaluador UNE | Revisa checklist, evidencias y limitaciones |

El control de acceso operativo se valida mediante identidad, usuarios de
conectores, APIs protegidas y flujos de login donde aplica.

### 3.3. Requisitos de Reproducibilidad

La reproducibilidad se apoya en:

- ejecución por niveles;
- configuración `.config` local ignorada por Git;
- perfiles `.profiles/` cuando aplica;
- comandos CLI equivalentes al menú;
- artefactos generados bajo `experiments/`;
- workbooks de casos y resultados en `docs/`;
- rutas documentadas para despliegue local, VM y distribuido.

### 3.4. Requisitos de Trazabilidad y Evidencias

Cada validación debe dejar:

- `metadata.json`;
- `level6_console.log`;
- resultados Newman;
- resultados Playwright cuando aplica;
- JSON de runners de componentes;
- métricas agregadas cuando existan;
- alineación UNE cuando se genera;
- dashboard `framework-report/index.html` cuando está disponible.

### 3.5. Requisitos de Medición y Resultados

El framework registra métricas disponibles en `aggregated_metrics.json`,
`negotiation_metrics.json`, resultados Newman, resultados Kafka y reportes de
componentes. Si una métrica no está sistematizada, E5.2 debe indicarlo como
limitación y no inventar tiempos de respuesta.

### 3.6. Relación con el Checklist UNE 0087:2025

El checklist UNE 0087:2025 se implementa como matriz de apoyo no certificante.
El workbook E5.2 indica 23 criterios: 12 cubiertos, 9 parciales y 2 no cubiertos.
Los criterios técnicos se apoyan en evidencias de Level 6; los criterios de
negocio y gobernanza requieren documentación externa aprobada.

## 4. Diseño del Framework de Validación

### 4.1. Arquitectura Lógica

La arquitectura lógica se organiza en:

| Capa | Ubicación | Responsabilidad |
| --- | --- | --- |
| CLI/orquestador | `main.py` | Menú, comandos y selección de niveles |
| Núcleo | `framework/` | Validación, métricas, reportes y utilidades |
| Adapters | `adapters/` | Comportamiento específico de INESData y EDC |
| Deployers | `deployers/` | Charts, configuración y despliegue |
| Validación | `validation/` | Newman, Playwright, componentes y targets |
| Evidencias | `experiments/` | Resultados generados por ejecución |

### 4.2. Flujos de Ejecución y Diagramas de Secuencia

El flujo de validación es:

```text
configuración -> Level 1 -> Level 2 -> Level 3 -> Level 4 -> Level 5 -> Level 6
              -> resultados -> dashboard -> workbook/checklist
```

El flujo proveedor-consumidor cubre:

```text
login provider -> asset -> policy -> contract definition -> catálogo consumer
-> negociación -> agreement -> transferencia -> evidencia
```

### 4.3. Definición de Interfaces

Interfaces relevantes:

- CLI: `python3 main.py menu`, `python3 main.py <adapter> deploy`,
  `python3 main.py <adapter> validate`;
- configuración: `deployers/infrastructure/deployer.config`,
  `deployers/infrastructure/topologies/*.config`,
  `deployers/<adapter>/deployer.config`;
- variables de entorno `PIONERA_*`;
- colecciones Newman en `validation/core/collections/`;
- Playwright en `validation/ui/`;
- runners de componentes en `validation/components/`;
- Excel de casos y resultados en `docs/`;
- evidencias en `experiments/<experimento>/`.

### 4.4. Arquitecturas de Despliegue

| Arquitectura | Descripción |
| --- | --- |
| `local` | Minikube y hostnames locales con `minikube tunnel` |
| `vm-single` | Una VM con Kubernetes gestionado y rutas públicas por path |
| `vm-distributed` | Roles separados para servicios comunes, conectores y componentes |

No se debe afirmar validación oficial de una combinación topología-adapter sin
experimento o workbook que lo respalde.

### 4.5. Stack Tecnológico

El stack incluye:

- Python;
- Docker y Docker Desktop para la ruta local desde WSL;
- Kubernetes, Minikube o k3s según topología;
- Helm;
- Keycloak, MinIO, PostgreSQL y Vault;
- Newman/Postman;
- Playwright;
- Kafka cuando se activa la validación streaming;
- adapters `inesdata` y `edc`;
- Excel como artefacto de trazabilidad;
- JSON, logs y dashboard como evidencias.

## 5. Manual Técnico

### 5.1. Implementación del Framework

El framework está implementado como repositorio Python con módulos de
orquestación, deployers por adapter y suites de validación. La ejecución real se
controla desde `main.py` y se delega en adapters/deployers.

### 5.2. Descripción Técnica de Módulos

| Ruta | Uso |
| --- | --- |
| `framework/` | Núcleo reutilizable de validación y reportes |
| `adapters/inesdata/` | Integración específica INESData |
| `adapters/edc/` | Integración específica EDC |
| `deployers/shared/` | Charts y artefactos comunes |
| `deployers/infrastructure/` | Topologías, hosts y configuración transversal |
| `validation/core/collections/` | Newman/Postman |
| `validation/ui/` | Playwright |
| `validation/components/` | Validación de componentes |
| `tests/` | Pruebas unitarias del framework |

### 5.3. Integración con Conectores, Adaptadores y Componentes

Los adapters resuelven URLs, credenciales, conectores, namespaces, limpieza y
validación. Los componentes se despliegan en Level 5 y se validan en Level 6
cuando el runner está registrado.

### 5.4. Dependencias y Librerías Utilizadas

Las dependencias principales son Python 3.10+, Node.js, npm, Java 17+, Docker,
Kubernetes, Helm, Newman y Playwright. El bootstrap instala dependencias del
framework y prepara navegadores Playwright cuando el entorno lo permite.

### 5.5. Despliegue Desde Cero

Flujo recomendado desde WSL:

```bash
bash scripts/bootstrap_framework.sh
source .venv/bin/activate
python3 main.py menu
```

En el menú:

```text
S - Select adapter
T - Select topology
1 - Level 1
2 - Level 2
3 - Level 3
4 - Level 4
5 - Level 5
6 - Level 6
```

Para `local`, mantén `minikube tunnel` abierto. Para `vm-single` y
`vm-distributed`, prepara kubeconfigs, SSH, DNS/Ingress y URLs públicas según la
documentación de topologías.

### 5.6. Despliegue Sobre Espacio de Datos Existente

Aplica cuando ya existen conectores o servicios externos y el framework se usa
para validar sin recrear todo el entorno. Deben adaptarse:

- adapter activo;
- topología;
- URLs públicas;
- credenciales de prueba;
- targets o conectores externos;
- alcance de validación.

La ruta documentada para targets externos de INESData está en
[29_inesdata_external_validation_targets.md](./29_inesdata_external_validation_targets.md).

### 5.7. Configuración del Framework

La configuración versionable usa `.example`. Los valores reales se escriben en
ficheros locales ignorados por Git:

```text
deployers/infrastructure/deployer.config
deployers/infrastructure/topologies/local.config
deployers/infrastructure/topologies/vm-single.config
deployers/infrastructure/topologies/vm-distributed.config
deployers/inesdata/deployer.config
deployers/edc/deployer.config
.profiles/*.env
```

### 5.8. Scripts de Despliegue y Automatización

Scripts y comandos relevantes:

- `scripts/bootstrap_framework.sh`;
- `scripts/clean_workspace.sh`;
- `python3 main.py menu`;
- `python3 main.py <adapter> deploy --topology <topology>`;
- `python3 main.py <adapter> validate --topology <topology>`;
- `python3 main.py report-viewer`;
- asistente `W` para `vm-distributed`;
- opción `J` para añadir conectores a un dataspace existente.

### 5.9. Código Fuente, Binarios y Repositorios

El código fuente versionable vive en este repositorio. Los binarios, imágenes y
artefactos generados durante ejecución no sustituyen el código fuente. Los
resultados generados viven en `experiments/` y los artefactos consolidados de
auditoría en `docs/`.

## 6. Manual de Usuario

### 6.1. Roles de Usuario

El operador ejecuta niveles y conserva evidencias. El responsable QA interpreta
resultados. El desarrollador añade componentes o pruebas. El evaluador revisa el
workbook, el checklist y los reportes.

### 6.2. Funciones Principales

El framework permite:

- seleccionar adapter;
- seleccionar topología;
- desplegar servicios, dataspaces, conectores y componentes;
- ejecutar validación;
- consultar URLs;
- reparar acceso local;
- ver reportes;
- añadir conectores;
- revisar evidencias.

### 6.3. Ejecución Paso a Paso del Escenario Principal

Para INESData/componentes:

```bash
python3 main.py menu
```

Después selecciona adapter `inesdata`, topología correspondiente y ejecuta los
niveles `1` a `6`. Para EDC de cierre, selecciona adapter `edc` y topología
`vm-distributed`, y conserva el experimento resultante.

### 6.4. Ejecución de Pruebas

La ejecución completa se realiza con Level 6:

```bash
python3 main.py inesdata validate --topology local
python3 main.py edc validate --topology vm-distributed
```

Kafka/streaming transfer se activa explícitamente cuando se requiere evidencia
de streaming:

```bash
PIONERA_LEVEL6_RUN_KAFKA=true python3 main.py inesdata validate --topology local
```

### 6.5. Consulta de Resultados

Los resultados se consultan en:

- `experiments/<experimento>/framework-report/index.html`;
- `experiments/<experimento>/level6_console.log`;
- `experiments/<experimento>/test_results.json`;
- `experiments/<experimento>/newman_results.json`;
- JSON de componentes;
- workbook E5.2.

### 6.6. Interpretación del Checklist UNE

El checklist UNE es una matriz de apoyo. Sus estados son:

- cubierto;
- parcial;
- no cubierto;
- no aplicable cuando corresponda.

No constituye certificación. Los criterios técnicos se apoyan en Level 6; los
criterios de negocio y gobernanza requieren documentación externa.

### 6.7. Localización de Evidencias

| Evidencia | Ubicación |
| --- | --- |
| Casos de prueba | `docs/A5.2_Casos_Prueba_.xlsx` |
| Resultados consolidados | `docs/E5.2_Resultados_Validacion_Componentes.xlsx` |
| Experimentos | `experiments/<experimento>/` |
| Reportes Playwright | `experiments/<experimento>/ui/...` |
| Newman | `experiments/<experimento>/newman_*` |
| UNE | `experiments/<experimento>/une_0087_alignment.*` |

## 7. Pruebas

### 7.1. Casos de Prueba y Criterios de Aceptación

El workbook A5.2 contiene hojas de roles, funcionalidades, dimensiones,
componentes, reproducción e índice de pruebas. Cada caso debe leerse con:

- ID del caso;
- componente evaluado;
- funcionalidad;
- tipo de prueba;
- precondiciones;
- pasos;
- resultado esperado;
- criterio de aceptación;
- evidencia esperada;
- relación con requisitos y UNE cuando aplica.

### 7.2. Pruebas Funcionales

Incluyen flujos UI y API de Ontology Hub, AI Model Hub, Semantic Virtualization e
INESData. El workbook E5.2 indica como evidencia consolidada:

- Ontology Hub funcional: 27/27 passed;
- AI Model Hub component validation: 27/27 passed;
- Semantic Virtualization component validation: 30/30 passed;
- INESData Playwright integration: 18/18 passed.

### 7.3. Pruebas de Integración

Incluyen integración de componentes con INESData, APIs de Ontology Hub,
validaciones de AI Model Hub y trazabilidad de Semantic Virtualization. El
workbook E5.2 indica Ontology Hub API integration: 5/5 passed.

### 7.4. Pruebas de Interoperabilidad

Incluyen Newman connector interoperability y Kafka transfer interoperability
cuando se activa. El workbook E5.2 indica:

- Newman connector interoperability: 14/14 passed;
- Kafka transfer interoperability: 2/2 passed.

### 7.5. Pruebas Transversales UNE

El checklist UNE organiza evidencias técnicas y documentales. El estado
consolidado del workbook es 12 criterios cubiertos, 9 parciales y 2 no
cubiertos. Los criterios no técnicos no deben presentarse como superados por el
framework si requieren documentación externa.

### 7.6. Entorno de Pruebas

El entorno de pruebas incluye topología, adapter, conectores, servicios comunes,
componentes, datasets y dependencias. Los datasets documentados incluyen FLARES
y GTFS-Madrid-Bench. La evidencia consolidada del workbook corresponde al
experimento `experiment_2026-05-26_18-18-09` en topología `local` con adapter
INESData.

### 7.7. Procedimiento de Ejecución

Procedimiento reproducible:

1. preparar dependencias con bootstrap;
2. seleccionar adapter y topología;
3. ejecutar Level 1 a Level 5;
4. ejecutar Level 6;
5. revisar consola y dashboard;
6. revisar JSON de resultados;
7. actualizar o consultar workbook de resultados;
8. conservar evidencias del experimento.

### 7.8. Resultados y Métricas

El workbook E5.2 consolida 97/97 automatizaciones ejecutadas, incluyendo Kafka,
con estado de cierre técnico `passed`. No deben inventarse métricas no
registradas. Cuando no existen tiempos de respuesta sistematizados, deben
declararse como limitación o mejora pendiente.

### 7.9. Evidencias Generadas

El índice de evidencias del workbook incluye:

- `framework-report/index.html`;
- `level6_console.log`;
- `metadata.json`;
- `newman_reports`;
- `newman_results.json`;
- `test_results.json`;
- `kafka_transfer_results.json`;
- `kafka_edc_results.json`;
- resultados Playwright;
- resultados de componentes;
- `une_0087_alignment.json`;
- `une_0087_alignment.md`.

## 8. Implementación del Checklist UNE 0087:2025

### 8.1. Propósito del Checklist

El checklist proporciona una estructura de revisión para relacionar evidencias
A5.2/E5.2 con criterios de la Guía UNE 0087:2025.

### 8.2. Dimensiones Cubiertas

Incluye dimensiones de negocio, gobernanza, solución técnica, seguridad,
interoperabilidad y evidencias operativas, según la matriz del workbook.

### 8.3. Criterios Evaluados

El workbook E5.2 registra 23 criterios. Cada criterio incluye requisito,
evidencia esperada, estado, artefacto principal, justificación, acción pendiente
y tipo de evidencia.

### 8.4. Tipos de Evidencia

Los tipos principales son:

- documental;
- técnica;
- ejecución automatizada;
- reporte;
- trazabilidad.

### 8.5. Estados de Cumplimiento

Los estados son cubierto, parcial, pendiente/no cubierto y no aplicable cuando
corresponda. El estado parcial significa que existe evidencia técnica, pero no
necesariamente la evidencia documental formal.

### 8.6. Relación con Casos de Prueba

Los casos de prueba aportan evidencias técnicas que alimentan criterios UNE
técnicos. No todos los criterios UNE se cubren con pruebas automatizadas.

### 8.7. Relación con Resultados

El experimento base y el workbook E5.2 vinculan resultados con artefactos. La
matriz UNE debe revisarse junto con los resultados de Level 6.

### 8.8. Limitaciones del Checklist

El checklist no sustituye evidencia legal, organizativa o de gobernanza. Tampoco
certifica por sí mismo cumplimiento normativo.

### 8.9. Alcance no Certificador

La matriz UNE es no certificante. Sirve para revisión, trazabilidad y preparación
de auditoría, no para emitir una certificación formal.

## 9. Resultados de Validación

### 9.1. Resultados por Componente

| Componente | Resultado consolidado |
| --- | --- |
| Ontology Hub | 27/27 funcional y 5/5 integración API passed |
| AI Model Hub | 27/27 component validation passed |
| Semantic Virtualization | 30/30 component validation passed |
| INESData UI/integración | 18/18 Playwright passed |

### 9.2. Resultados por Caso de Prueba

El detalle por ID oficial PT5 y por ID ejecutable está en la hoja
`10_Indice_Pruebas` y en la hoja `11_Level6_Results` del workbook E5.2.

### 9.3. Resultados por Dimensión UNE

El detalle por criterio y dimensión está en la hoja `12_UNE_0087_Checklist`.

### 9.4. Resultados del Escenario EDC + vm-distributed

La ruta `edc + vm-distributed` está documentada como ruta oficial de cierre para
EDC. En este checkout no se encontraron metadatos de experimento EDC versionados
en `experiments/`. Para presentar este escenario como resultado de E5.2, debe
asociarse el experimento EDC correspondiente y conservar sus evidencias.

### 9.5. Casos no Ejecutados o no Evidenciados

Se consideran no evidenciados los casos sin resultado en workbook, sin artefacto
de experimento o sin runner registrado. También se consideran limitados los
criterios UNE que requieren documentos de negocio o gobernanza externos.

## 10. Limitaciones

### 10.1. Limitaciones de Topologías

No todas las combinaciones adapter-topología tienen la misma evidencia. `local`,
`vm-single` y `vm-distributed` están implementadas, pero la evidencia oficial
debe revisarse por adapter.

### 10.2. Limitaciones de Adaptadores

INESData tiene evidencia consolidada de componentes en el workbook E5.2. EDC
está implementado y documentado para `vm-distributed`, pero requiere asociar el
experimento correspondiente para auditoría si no está presente en el checkout.

### 10.3. Limitaciones de Evidencia

Los logs locales y artefactos ignorados por Git no sustituyen evidencias
consolidadas. Las evidencias deben conservarse en rutas auditables o
referenciarse mediante workbook y experimento.

### 10.4. Limitaciones de Métricas

No todos los tiempos de respuesta están sistematizados. Si no existe métrica
registrada, debe declararse como no disponible.

### 10.5. Trabajo Pendiente

Trabajo pendiente o dependiente del contexto:

- adjuntar evidencia documental de negocio y gobernanza para criterios UNE
  parciales o pendientes;
- conservar experimento EDC + vm-distributed si se usa como evidencia oficial;
- revalidar EDC en `local` o `vm-single` si se desea presentarlo en esas
  topologías;
- actualizar workbook cuando se agreguen nuevos componentes, modelos o suites.

## 11. Conclusiones

E5.2 consolida el Validation Environment como metodología operativa para
validar componentes PIONERA en un espacio de datos. El framework permite
desplegar entornos, ejecutar pruebas, generar evidencias y relacionarlas con un
checklist UNE no certificante. La evidencia de componentes consolidada en el
workbook E5.2 muestra cierre técnico `passed` para el experimento INESData local
registrado. El soporte EDC y la topología `vm-distributed` quedan documentados
como ruta oficial de cierre para EDC, con la condición de conservar e identificar
el experimento correspondiente cuando se use como evidencia auditada.
