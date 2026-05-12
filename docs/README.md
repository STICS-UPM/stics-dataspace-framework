# Documentación del Validation Environment

Esta carpeta contiene la documentación estable para usar, desarrollar y probar el framework de validación de PIONERA.

La documentación es intencionadamente compacta. Describe cómo funciona el framework hoy y evita incluir planes históricos, notas internas o contexto de trabajo.

## Orden de Lectura

1. [Inicio rápido](./getting-started.md): instalación, configuración y menú guiado.
2. [Referencia del menú](./menu-reference.md): opciones del menú, submenús y cuándo usar cada acción.
3. [Arquitectura](./architecture.md): estructura del repositorio y modelo por niveles.
4. [Deployers y topologías](./deployers-and-topologies.md): `local`, `vm-single` y `vm-distributed`.
5. [Adapters](./adapters.md): adapters `inesdata` y `edc`.
6. [Validación](./validation.md): nivel 6, Newman, Playwright, métricas y reportes.
7. [Validación de INESData externo](./29_inesdata_external_validation_targets.md): guía objetivo para targets externos y suites extendidas.
8. [Desarrollo y testing](./development-and-testing.md): cómo extender el framework y ejecutar pruebas focalizadas.
9. [Troubleshooting](./troubleshooting.md): problemas frecuentes y cómo resolverlos.

## Entrada Principal

Usa `main.py` para el trabajo diario:

```bash
python3 main.py menu
python3 main.py inesdata deploy --topology local
python3 main.py edc validate --topology local
python3 main.py edc hosts --topology local --dry-run
```

El menú guiado es la entrada recomendada para usuarios no especializados. El CLI directo es la entrada recomendada para automatización y ejecuciones reproducibles.

## Documentos Numerados

Los documentos `00` a `10` conservan la documentacion historica principal del
framework. Los documentos `11` a `29` recogen el estado implementado, decisiones
tecnicas consolidadas y guias objetivo sin incluir notas internas de
planificacion.

| Doc | Tema |
| --- | --- |
| [00](./00_overview.md) | Vision general |
| [01](./01_framework_architecture.md) | Arquitectura del framework |
| [02](./02_validation_architecture.md) | Arquitectura de validacion |
| [03](./03_integration_guide.md) | Guia de integracion |
| [04](./04_execution_flow.md) | Flujo de ejecucion |
| [05](./05_repository_structure.md) | Estructura del repositorio |
| [06](./06_information_exchange_flow.md) | Flujo de intercambio de informacion |
| [07](./07_experiment_system.md) | Sistema de experimentos |
| [08](./08_metrics_pipeline.md) | Pipeline de metricas |
| [09](./09_kafka_real_measurements.md) | Mediciones reales con Kafka |
| [10](./10_ui_validation_core.md) | Validacion UI core |
| [11](./11_ontology_hub_validation.md) | Validacion de Ontology Hub |
| [12](./12_local_validation_environment.md) | Entorno local de validacion |
| [13](./13_test_cases.md) | Casos de prueba y correlacion PT5 |
| [14](./14_production_environment_plan.md) | Entorno productivo de validacion |
| [15](./15_ai_model_hub_validation_plan.md) | Validacion de AI Model Hub |
| [16](./16_flares_linguistic_domain_context.md) | Contexto linguistico FLARES |
| [17](./17_edc_adapter_design_and_implementation_plan.md) | Adapter EDC |
| [18](./18_edc_portal_and_ui_validation_strategy.md) | Portal EDC y validacion UI |
| [19](./19_playwright_adapter_strategy_for_edc_and_future_adapters.md) | Playwright por adapter |
| [20](./20_edc_playwright_phase1_baseline.md) | Baseline Playwright EDC |
| [21](./21_deployers_migration_namespace_roles_and_level5_strategy.md) | Arquitectura deployers, roles y Level 5 |
| [22](./22_main_cli_entrypoint_strategy.md) | Entrada `main.py` |
| [23](./23_common_deployer_contract_and_orchestration_strategy.md) | Contrato comun de deployer |
| [24](./24_deployer_level_mapping_and_execution_matrix.md) | Matriz de niveles y ejecucion |
| [25](./25_validation_issues_and_test_data_cleanup_strategy.md) | Issues de validacion y limpieza |
| [26](./26_edc_shared_components_integration_plan.md) | Componentes compartidos en EDC |
| [27](./27_legacy_deployment_folders_removal.md) | Carpetas legacy de despliegue |
| [28](./28_external_vm_contributions_and_topology_integration_plan.md) | Topologias VM y contribuciones tecnicas |
| [29](./29_inesdata_external_validation_targets.md) | Validacion de INESData externo |
