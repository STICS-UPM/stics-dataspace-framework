# Documentación del Validation Environment

Esta carpeta contiene la documentación pública y estable del framework. Está
organizada para que una persona pueda empezar, operar, validar, extender o
auditar el repositorio sin tener que leer todos los documentos numerados.

La documentación no debe incluir notas personales, contraseñas, tokens, claves
privadas, rutas personales, kubeconfigs reales ni datos sensibles. Los
artefactos generados por ejecución viven en `experiments/` y no sustituyen a la
documentación estable de `docs/`.

## Dónde Empezar

| Necesidad | Ruta recomendada |
| --- | --- |
| Primera ejecución | [Inicio rápido](./32_getting_started.md) |
| Usar el menú | [Referencia del menú](./33_menu_reference.md) |
| Entender la arquitectura | [Arquitectura](./34_architecture.md) |
| Elegir topología | [Deployers y topologías](./35_deployers_and_topologies.md) |
| Ejecutar validación | [Validación](./37_validation.md) |
| Revisar resultados | [Visor de reportes](./40_report_viewer.md) |
| Resolver errores | [Troubleshooting](./39_troubleshooting.md) |
| Auditar el framework | [Guía de navegación para auditoría](./44_audit_navigation_guide.md) |

## Estructura Pública del Repositorio Software

La documentación sigue esta estructura de referencia para facilitar revisión,
uso y auditoría.

| Elemento esperado | Ubicación principal |
| --- | --- |
| Título y descripción del proyecto | [README principal](../README.md) |
| Estado actual del proyecto | [30 Estado actual](./30_framework_current_state.md) |
| Índice o tabla de contenido | [README principal](../README.md) y este índice |
| Funcionalidades principales | [README principal](../README.md#funcionalidades-principales) |
| Estructura del repositorio | [README principal](../README.md#estructura-del-repositorio) y [Arquitectura](./34_architecture.md) |
| Requisitos técnicos y dependencias | [README principal](../README.md#requisitos-técnicos-y-dependencias) e [Inicio rápido](./32_getting_started.md) |
| Instalación y compilación | [README principal](../README.md#instalación-y-compilación) e [Inicio rápido](./32_getting_started.md) |
| Guía de uso con ejemplos | [README principal](../README.md#guía-de-uso-con-ejemplos), [Referencia del menú](./33_menu_reference.md) y [Validación](./37_validation.md) |
| Cómo contribuir | [README principal](../README.md#cómo-contribuir) |
| Agradecimientos y financiación | [README principal](../README.md#agradecimientos-y-fuentes-de-financiación) |
| Autores y contacto | [README principal](../README.md#autores-y-contacto) |
| Licencia del proyecto | [README principal](../README.md#licencia) y [`LICENSE`](../LICENSE) |
| Pruebas y cómo ejecutarlas | [README principal](../README.md#pruebas-y-cómo-ejecutarlas) y [Desarrollo y testing](./38_development_and_testing.md) |
| Imágenes, diagramas o vídeos explicativos | [README principal](../README.md#imágenes-diagramas-y-vídeos-explicativos) y [diagramas](#diagramas-y-evidencias) |

## Rutas de Lectura

### Operación del Framework

1. [Estado actual del framework](./30_framework_current_state.md)
2. [Inicio rápido](./32_getting_started.md)
3. [Referencia del menú](./33_menu_reference.md)
4. [Deployers y topologías](./35_deployers_and_topologies.md)
5. [Validación](./37_validation.md)
6. [Troubleshooting](./39_troubleshooting.md)

### Validación de Espacios de Datos

1. [Validación](./37_validation.md)
2. [Colecciones Newman y Postman](./31_postman_newman_collections.md)
3. [Validación UI core](./10_ui_validation_core.md)
4. [Ontology Hub](./11_ontology_hub_validation.md)
5. [AI Model Hub](./15_ai_model_hub_validation_plan.md)
6. [Visor de reportes](./40_report_viewer.md)

### Despliegues con VM

1. [Deployers y topologías](./35_deployers_and_topologies.md)
2. [Preparación de conectores externos](./45_external_connector_readiness.md)
3. [Guía operativa de vm-distributed](./46_vm_distributed_runbook.md)
4. [Troubleshooting](./39_troubleshooting.md)

### Desarrollo y Extensión

1. [Arquitectura](./34_architecture.md)
2. [Adapters](./36_adapters.md)
3. [Desarrollo y testing](./38_development_and_testing.md)
4. [Guía de integración histórica](./03_integration_guide.md)
5. [Componentes compartidos en EDC](./26_edc_shared_components_integration_plan.md)

### Auditoría Técnica

1. [Guía de navegación para auditoría](./44_audit_navigation_guide.md)
2. [Estado actual del framework](./30_framework_current_state.md)
3. [Arquitectura](./34_architecture.md)
4. [Deployers y topologías](./35_deployers_and_topologies.md)
5. [Validación](./37_validation.md)
6. [Colecciones Newman y Postman](./31_postman_newman_collections.md)
7. [Visor de reportes](./40_report_viewer.md)

## Entrada Principal

Usa `main.py` para el trabajo diario:

```bash
python3 main.py menu
python3 main.py inesdata deploy --topology local
python3 main.py inesdata validate --topology local
python3 main.py edc validate --topology local
python3 main.py edc hosts --topology local --dry-run
```

El menú guiado es la entrada recomendada para uso interactivo. El CLI directo
es la entrada recomendada para automatización y ejecuciones reproducibles.

## Documentación Vigente

| Documento | Propósito |
| --- | --- |
| [30 Estado actual](./30_framework_current_state.md) | Resumen vigente de niveles, topologías, adapters, namespaces y validación |
| [31 Newman/Postman](./31_postman_newman_collections.md) | Colecciones ejecutadas por el framework e importables en Postman |
| [32 Inicio rápido](./32_getting_started.md) | Instalación, bootstrap, configuración básica y primer despliegue |
| [33 Referencia del menú](./33_menu_reference.md) | Opciones del menú, submenús y criterios de uso |
| [34 Arquitectura](./34_architecture.md) | Componentes principales del repositorio y responsabilidades |
| [35 Deployers y topologías](./35_deployers_and_topologies.md) | `local`, `vm-single`, `vm-distributed`, overlays y namespaces |
| [36 Adapters](./36_adapters.md) | Estado y responsabilidades de `inesdata` y `edc` |
| [37 Validación](./37_validation.md) | `Level 6`, Newman, Kafka, Playwright, componentes, métricas y reportes |
| [38 Desarrollo y testing](./38_development_and_testing.md) | Pruebas, convenciones de desarrollo y mantenimiento |
| [39 Troubleshooting](./39_troubleshooting.md) | Diagnóstico de fallos frecuentes |
| [40 Visor de reportes](./40_report_viewer.md) | Revisión local de experimentos generados |
| [44 Guía de auditoría](./44_audit_navigation_guide.md) | Orden de lectura, alcance, evidencias y límites de seguridad |
| [45 Conectores externos](./45_external_connector_readiness.md) | Checklist para conectores y entornos externos |
| [46 vm-distributed](./46_vm_distributed_runbook.md) | Procedimiento operativo de topología distribuida |

## Trazabilidad Histórica

Los documentos `00` a `29` conservan decisiones, diseño, evolución técnica y
planes previos. Se mantienen navegables para auditoría y mantenimiento, pero no
son la ruta inicial para operar el framework.

| Rango | Uso |
| --- | --- |
| `00` a `13` | Conceptos iniciales, arquitectura histórica y validación base |
| `14` a `20` | Planes de producción, AI Model Hub, EDC y Playwright |
| `21` a `29` | Migración de deployers, targets externos y evolución de topologías |

El flujo manual histórico de INESData se conserva en
[legacy_inesdata_manual](./legacy_inesdata_manual/00_historical_inesdata_manual_flow.md)
solo como referencia de trazabilidad.

## Diagramas y Evidencias

- [Entorno local de validación](<./pionera_local_validation_environment.png>)
- [Entorno distribuido de validación](<./pionera_distributed_validation_environment.png>)
- [Arquitectura del entorno de pruebas](<./test_environment_architecture.png>)
- [Inventario del entorno de pruebas](./test_environment_inventory.pdf)
- [Resultados de validación de componentes](./E5.2_Resultados_Validacion_Componentes.xlsx)
- [Casos de prueba](./A5.2_Casos_Prueba_.xlsx)

Los diagramas deben interpretarse junto con
[Deployers y topologías](./35_deployers_and_topologies.md), especialmente por el
alineamiento de namespaces y roles entre topologías.
