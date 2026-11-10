# Validation Environment Documentation

> To operate or extend the **STICS** dataspace specifically, start with
> [`dataspace-setup-guide.md`](../dataspace-setup-guide.md) and
> [`deployment-guide.md`](../deployment-guide.md) at the repository root, and
> the [STICS documents](#stics-documents) below. The rest of this page is
> general framework documentation, not specific to STICS.

This folder contains the public, stable documentation of the framework. It is
organized so that a person can get started, operate, validate, extend, or
audit the repository without reading every numbered document.

Documentation must not include personal notes, passwords, tokens, private
keys, personal paths, real kubeconfigs, or sensitive data. Artifacts generated
by each run live in `experiments/` and do not replace the stable documentation
in `docs/`.

> **Language note:** the documentation is being translated to English.
> Documents marked **(ES)** are still in Spanish.

## STICS Documents

| Document | Purpose |
| --- | --- |
| [47 STICS interoperability evidence](./47_stics_edc_interop_evidence.md) | Verified `curl`/Postman commands: contract negotiation and real `HttpData-PULL`/`HttpData-PUSH` transfers between provider and consumer |
| [48 Beginner's guide: new connector](./48_new_connector_setup_guide_for_dummies.md) | Complete step-by-step guide, with an error cheat sheet, to set up a new EDC connector from scratch (identity, Postgres, properties, docker-compose, network bridge, TLS) |
| [49 Partner onboarding runbook](./49_bavenir_hands_on_session_guide.md) | Live runbook to bring up a connector on a partner's own infrastructure |
| [50 Connector automation guide](./50_connector_automation_guide.md) | Publishing and consuming data from an external system through the Management API |
| [Deployment video script](./video_script_deployment.md) | Script for a video showing how to deploy an environment from scratch, levels 1 to 5 |

## Where to Start

| Need | Recommended path |
| --- | --- |
| First run | [Getting started](./32_getting_started.md) |
| Using the menu | [Menu reference](./33_menu_reference.md) |
| Understanding the architecture | [Architecture](./34_architecture.md) |
| Choosing a topology | [Deployers and topologies](./35_deployers_and_topologies.md) |
| Running validation | [Validation](./37_validation.md) |
| Reviewing results | [Report viewer](./40_report_viewer.md) (ES) |
| Fixing errors | [Troubleshooting](./39_troubleshooting.md) |
| Auditing the framework | [Audit navigation guide](./44_audit_navigation_guide.md) (ES), [current state](./30_framework_current_state.md), [validation](./37_validation.md), and the A5.2/E5.2 tabular artifacts |

## Public Structure of the Software Repository

The documentation follows this reference structure to make review, use, and
auditing easier.

| Expected element | Main location |
| --- | --- |
| Project title and description | [Main README](../README.md) |
| Current project status | [30 Current state](./30_framework_current_state.md) |
| Index or table of contents | [Main README](../README.md) and this index |
| Main features | [Main README](../README.md#what-this-fork-adds) and [The underlying framework](../README.md#the-underlying-framework) |
| Repository structure | [Main README](../README.md#repository-structure) and [Architecture](./34_architecture.md) |
| Technical requirements and dependencies | [Main README](../README.md#requirements) and [Getting started](./32_getting_started.md) |
| Installation and build | [Main README](../README.md#installation) and [Getting started](./32_getting_started.md) |
| Usage guide with examples | [Main README](../README.md#the-underlying-framework), [Menu reference](./33_menu_reference.md), and [Validation](./37_validation.md) |
| How to contribute | [Main README](../README.md#contributing) |
| Acknowledgments and funding | [Main README](../README.md#acknowledgments-and-funding) |
| Authors and contact | [Main README](../README.md#authors-and-contact) |
| Project license | [Main README](../README.md#license) and [`LICENSE`](../LICENSE) |
| Tests and how to run them | [Main README](../README.md#tests) and [Development and testing](./38_development_and_testing.md) |
| Explanatory images, diagrams, or videos | [Diagrams and evidence](#diagrams-and-evidence) and the [deployment video script](./video_script_deployment.md) |

## Reading Paths

### Operating the Framework

1. [Current state of the framework](./30_framework_current_state.md)
2. [Getting started](./32_getting_started.md)
3. [Menu reference](./33_menu_reference.md)
4. [Deployers and topologies](./35_deployers_and_topologies.md)
5. [Validation](./37_validation.md)
6. [Troubleshooting](./39_troubleshooting.md)

### Dataspace Validation

1. [Validation](./37_validation.md)
2. [Newman and Postman collections](./31_postman_newman_collections.md) (ES)
3. [Core UI validation](./10_ui_validation_core.md) (ES)
4. [Ontology Hub](./11_ontology_hub_validation.md) (ES)
5. [AI Model Hub](./15_ai_model_hub_validation_plan.md) (ES)
6. [Report viewer](./40_report_viewer.md) (ES)

### VM Deployments

1. [Deployers and topologies](./35_deployers_and_topologies.md)
2. [External connector readiness](./45_external_connector_readiness.md) (ES)
3. [vm-distributed operations runbook](./46_vm_distributed_runbook.md)
4. [Troubleshooting](./39_troubleshooting.md)

### Development and Extension

1. [Architecture](./34_architecture.md)
2. [Adapters](./36_adapters.md)
3. [Development and testing](./38_development_and_testing.md)
4. [Historical integration guide](./03_integration_guide.md) (ES)
5. [Shared components in EDC](./26_edc_shared_components_integration_plan.md) (ES)

### Technical Audit

1. [Audit navigation guide](./44_audit_navigation_guide.md) (ES)
2. [Current state of the framework](./30_framework_current_state.md)
3. [Architecture](./34_architecture.md)
4. [Deployers and topologies](./35_deployers_and_topologies.md)
5. [Validation](./37_validation.md)
6. [Newman and Postman collections](./31_postman_newman_collections.md) (ES)
7. [Report viewer](./40_report_viewer.md) (ES)
8. [A5.2/E5.2 tabular results](./E5.2_Resultados_Validacion_Componentes.xlsx) (ES)

## Main Entry Point

Use `main.py` for day-to-day work:

```bash
python3 main.py menu
python3 main.py inesdata deploy --topology local
python3 main.py inesdata validate --topology local
python3 main.py edc validate --topology vm-distributed
python3 main.py edc hosts --topology vm-distributed --dry-run
python3 main.py batch --plan .profiles/runs/full-validation.yaml --secrets .secrets/pionera.env
```

The guided menu is the recommended entry point for interactive use. The
direct CLI is the recommended entry point for automation and reproducible
runs. The `batch` mode runs local, versionable operation profiles, but their
secrets must stay in files ignored by Git.
For EDC, the official documented closure path is `vm-distributed`. The EDC
`local` and `vm-single` topologies remain implemented and are useful for
development or revalidation, but they do not replace the distributed closure
evidence.

## Current Documentation

| Document | Purpose |
| --- | --- |
| [30 Current state](./30_framework_current_state.md) | Current summary of levels, topologies, adapters, namespaces, and validation |
| [31 Newman/Postman](./31_postman_newman_collections.md) (ES) | Collections run by the framework and importable into Postman |
| [32 Getting started](./32_getting_started.md) | Installation, bootstrap, basic configuration, and first deployment |
| [33 Menu reference](./33_menu_reference.md) | Menu options, submenus, and usage criteria |
| [34 Architecture](./34_architecture.md) | Main repository components and their responsibilities |
| [35 Deployers and topologies](./35_deployers_and_topologies.md) | `local`, `vm-single`, `vm-distributed`, overlays, and namespaces |
| [36 Adapters](./36_adapters.md) | Status and responsibilities of `inesdata` and `edc` |
| [37 Validation](./37_validation.md) | `Level 6`, Newman, Kafka, Playwright, components, metrics, and reports |
| [38 Development and testing](./38_development_and_testing.md) | Tests, development conventions, and maintenance |
| [39 Troubleshooting](./39_troubleshooting.md) | Diagnosing common failures |
| [40 Report viewer](./40_report_viewer.md) (ES) | Local review of generated experiments |
| [41 PIONERA connector external access](./41_pionera_connector_external_access.md) (ES) | Reference for public URLs, connector access, and publication criteria |
| [42 Model Clearing House](./42_model_clearing_house_plan.md) | Technical evolution plan for model governance and clearing |
| [43 Model Observer](./43_model_observer_additive_backlog.md) | Additive technical backlog of the model observer |
| [44 Audit guide](./44_audit_navigation_guide.md) (ES) | Reading order, scope, evidence, and security limits |
| [45 External connectors](./45_external_connector_readiness.md) (ES) | Checklist for external connectors and environments |
| [46 vm-distributed](./46_vm_distributed_runbook.md) | Operating procedure for the distributed topology |
| [47 STICS interoperability evidence](./47_stics_edc_interop_evidence.md) | See [STICS documents](#stics-documents) |
| [48 Beginner's guide: new connector](./48_new_connector_setup_guide_for_dummies.md) | See [STICS documents](#stics-documents) |

## Historical Traceability

Documents `00` to `29` (ES) keep decisions, design, technical evolution, and
earlier plans. They remain navigable for auditing and maintenance, but they
are not the starting path for operating the framework.

| Range | Use |
| --- | --- |
| `00` to `13` | Initial concepts, historical architecture, and base validation |
| `14` to `20` | Production, AI Model Hub, EDC, and Playwright plans |
| `21` to `29` | Deployer migration, external targets, and topology evolution |

The historical manual INESData flow is kept in
[legacy_inesdata_manual](./legacy_inesdata_manual/00_historical_inesdata_manual_flow.md) (ES)
only as a traceability reference.

## Diagrams and Evidence

- [Local validation environment](<./pionera_local_validation_environment.png>)
- [Distributed validation environment](<./pionera_distributed_validation_environment.png>)
- [Test environment architecture](<./test_environment_architecture.png>)
- [Test environment inventory](./test_environment_inventory.pdf)
- [Component validation results](./E5.2_Resultados_Validacion_Componentes.xlsx) (ES)
- [Test cases](./A5.2_Casos_Prueba_.xlsx) (ES)

The diagrams should be read together with
[Deployers and topologies](./35_deployers_and_topologies.md), especially for
the alignment of namespaces and roles across topologies.
