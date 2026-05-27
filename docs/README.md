# Documentación del Validation Environment

Esta carpeta contiene la documentación estable del framework de validación.
Está organizada para que una persona auditora, integradora o
desarrolladora pueda entender qué hace el framework, cómo se ejecuta y dónde
encontrar la evidencia técnica.

La documentación evita incluir notas personales, contraseñas, tokens, rutas
privadas o información sensible. Los artefactos generados por ejecución viven
en `experiments/` y no forman parte de la documentación estable de `docs/`.

## Ruta Para Auditoría

1. [Guía de navegación para auditoría](./44_audit_navigation_guide.md)
2. [Estado actual del framework](./30_framework_current_state.md)
3. [Arquitectura](./34_architecture.md)
4. [Deployers y topologías](./35_deployers_and_topologies.md)
5. [Validación](./37_validation.md)
6. [Colecciones Newman y Postman](./31_postman_newman_collections.md)
7. [Visor de reportes](./40_report_viewer.md)
8. [Preparación de conectores externos](./45_external_connector_readiness.md)
9. [Troubleshooting](./39_troubleshooting.md)

Esta ruta separa la documentación vigente de la trazabilidad histórica. Los
documentos de trazabilidad siguen siendo útiles para revisar decisiones y
evolución técnica, pero no deben sustituir a la documentación operativa actual.

## Ruta Operativa

1. [Estado actual del framework](./30_framework_current_state.md)
2. [Inicio rápido](./32_getting_started.md)
3. [Referencia del menú](./33_menu_reference.md)
4. [Arquitectura](./34_architecture.md)
5. [Deployers y topologías](./35_deployers_and_topologies.md)
6. [Adapters](./36_adapters.md)
7. [Validación](./37_validation.md)
8. [Colecciones Newman y Postman](./31_postman_newman_collections.md)
9. [Preparación de conectores externos](./45_external_connector_readiness.md)
10. [Desarrollo y testing](./38_development_and_testing.md)
11. [Troubleshooting](./39_troubleshooting.md)

## Entrada Principal

Usa `main.py` para el trabajo diario:

```bash
python3 main.py menu
python3 main.py inesdata deploy --topology local
python3 main.py inesdata validate --topology local
python3 main.py edc validate --topology local
python3 main.py edc hosts --topology local --dry-run
```

El menú guiado es la entrada recomendada para uso interactivo. El CLI directo es
la entrada recomendada para automatización y ejecuciones reproducibles.

## Documentos Operativos

| Documento | Propósito |
| --- | --- |
| [Guía de navegación para auditoría](./44_audit_navigation_guide.md) | Orden de lectura, alcance de auditoría, evidencia esperada y límites de seguridad |
| [30 Estado actual](./30_framework_current_state.md) | Resumen vigente de niveles, topologías, adapters, namespaces y validación |
| [Inicio rápido](./32_getting_started.md) | Instalación, bootstrap, configuración básica y primer despliegue |
| [Referencia del menú](./33_menu_reference.md) | Opciones del menú, submenús y criterios de uso |
| [Arquitectura](./34_architecture.md) | Componentes principales del repositorio y responsabilidades |
| [Deployers y topologías](./35_deployers_and_topologies.md) | `local`, `vm-single`, `vm-distributed`, overlays y namespaces |
| [Adapters](./36_adapters.md) | Estado y responsabilidades de `inesdata` y `edc` |
| [Validación](./37_validation.md) | `Level 6`, Newman, Kafka, Playwright, componentes, métricas y reportes |
| [31 Newman/Postman](./31_postman_newman_collections.md) | Colecciones ejecutadas por el framework e importables en Postman |
| [Visor de reportes](./40_report_viewer.md) | Revisión local de experimentos generados |
| [Preparación de conectores externos](./45_external_connector_readiness.md) | Datos, límites y checklist para topología distribuida y conectores externos |
| [Targets externos](./29_inesdata_external_validation_targets.md) | Validación read-only de targets no desplegados por el framework |
| [Flujo manual histórico INESData](./legacy_inesdata_manual/00_historical_inesdata_manual_flow.md) | Flujo manual histórico de INESData, conservado solo para trazabilidad |

## Documentos Numerados de Trazabilidad

Los documentos `00` a `29` conservan contexto técnico, decisiones de diseño y
evolución histórica. Se mantienen navegables porque son útiles para auditoría,
pero la referencia operativa inicial debe ser la ruta de auditoría y la ruta
operativa anteriores.

| Doc | Tema |
| --- | --- |
| [00](./00_overview.md) | Visión general |
| [01](./01_framework_architecture.md) | Arquitectura del framework |
| [02](./02_validation_architecture.md) | Arquitectura de validación |
| [03](./03_integration_guide.md) | Guía de integración |
| [04](./04_execution_flow.md) | Flujo de ejecución |
| [05](./05_repository_structure.md) | Estructura del repositorio |
| [06](./06_information_exchange_flow.md) | Flujo de intercambio de información |
| [07](./07_experiment_system.md) | Sistema de experimentos |
| [08](./08_metrics_pipeline.md) | Pipeline de métricas |
| [09](./09_kafka_real_measurements.md) | Mediciones reales con Kafka |
| [10](./10_ui_validation_core.md) | Validación UI core |
| [11](./11_ontology_hub_validation.md) | Validación de Ontology Hub |
| [12](./12_local_validation_environment.md) | Entorno local de validación |
| [13](./13_test_cases.md) | Casos de prueba y correlación PT5 |
| [14](./14_production_environment_plan.md) | Entorno productivo de validación |
| [15](./15_ai_model_hub_validation_plan.md) | Validación de AI Model Hub |
| [16](./16_flares_linguistic_domain_context.md) | Contexto lingüístico FLARES |
| [17](./17_edc_adapter_design_and_implementation_plan.md) | Adapter EDC |
| [18](./18_edc_portal_and_ui_validation_strategy.md) | Portal EDC y validación UI |
| [19](./19_playwright_adapter_strategy_for_edc_and_future_adapters.md) | Playwright por adapter |
| [20](./20_edc_playwright_phase1_baseline.md) | Baseline Playwright EDC |
| [21](./21_deployers_migration_namespace_roles_and_level5_strategy.md) | Deployers, roles y Level 5 |
| [22](./22_main_cli_entrypoint_strategy.md) | Entrada `main.py` |
| [23](./23_common_deployer_contract_and_orchestration_strategy.md) | Contrato común de deployer |
| [24](./24_deployer_level_mapping_and_execution_matrix.md) | Matriz de niveles y ejecución |
| [25](./25_validation_issues_and_test_data_cleanup_strategy.md) | Issues de validación y limpieza |
| [26](./26_edc_shared_components_integration_plan.md) | Componentes compartidos en EDC |
| [27](./27_legacy_deployment_folders_removal.md) | Carpetas legacy de despliegue |
| [28](./28_external_vm_contributions_and_topology_integration_plan.md) | Topologías VM e integración técnica |
| [29](./29_inesdata_external_validation_targets.md) | Validación de INESData externo |
| [30](./30_framework_current_state.md) | Estado actual del framework |
| [31](./31_postman_newman_collections.md) | Colecciones Newman y Postman |

## Referencias Complementarias

| Doc | Tema |
| --- | --- |
| [41](./41_pionera_connector_external_access.md) | Acceso externo a conectores |
| [42](./42_model_clearing_house_plan.md) | Plan de Model Clearing House |
| [43](./43_model_observer_additive_backlog.md) | Backlog aditivo de Model Observer |
| [44](./44_audit_navigation_guide.md) | Guía de navegación para auditoría |
| [45](./45_external_connector_readiness.md) | Preparación de conectores externos |
| [Inventario de entorno de pruebas](./test_environment_inventory.pdf) | Inventario público del entorno de pruebas |

## Diagramas

- [Entorno local de validación](<./pionera_local_validation_environment.png>)
- [Entorno distribuido de validación](<./pionera_distributed_validation_environment.png>)

Los diagramas deben interpretarse junto con
[Deployers y topologías](./35_deployers_and_topologies.md), especialmente por el
alineamiento actual de namespaces.
