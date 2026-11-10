# Current State of the Framework

This document summarizes the current operational state of the Validation
Environment according to the code versioned in this copy of the repository.
It is aimed at public review, technical auditing, and onboarding people who
need to understand what is implemented, what is validated, and what is out of
the closure scope.

## Main Entry Point

The canonical entry point is:

```bash
python3 main.py menu
```

There are also direct commands for automation:

```bash
python3 main.py inesdata deploy --topology local
python3 main.py inesdata validate --topology local
python3 main.py edc deploy --topology vm-distributed
python3 main.py edc validate --topology vm-distributed
```

The menu and the commands share the same level-based execution model.

## Levels

| Level | Function | Status |
| --- | --- | --- |
| `1` | Prepare the Kubernetes cluster | Operational on `local` and `vm-single` |
| `2` | Deploy common services | Operational |
| `3` | Deploy dataspace/control plane | Operational |
| `4` | Deploy connectors | Operational for `inesdata` and `edc` |
| `5` | Deploy optional components | Operational for the shared components configured in `inesdata` and `edc` |
| `6` | Run validation | Operational with Newman, Kafka, Playwright, and component validation depending on the adapter |

## Topologies

| Topology | Current status | Recommended use |
| --- | --- | --- |
| `local` | Stable local development and validation path | Daily validation, debugging, and controlled reproduction |
| `vm-single` | Operational path on one VM with managed Kubernetes | Final validation in a VM-like environment and integration smoke tests |
| `vm-distributed` | Parameterizable distributed path with separate physical roles | Validation of environments with common services, connectors, and components on different VMs |

## Closure Scope by Adapter and Topology

Code support and official closure evidence are not the same thing. For
auditing, the current reading is:

| Adapter | `local` | `vm-single` | `vm-distributed` |
| --- | --- | --- | --- |
| `inesdata` | Implemented and used as the local development/validation path | Implemented and validated as the reference VM environment | Implemented and validated as the reference distributed environment |
| `edc` | Implemented; passed validation before the recent topology reconciliation and must be revalidated before being used as current evidence | Implemented; not officially validated after the recent reconciliation | Implemented and officially tested as the closure path for EDC |

The operational documentation keeps commands and configuration for the
implemented paths, but official `edc` evidence must be generated on
`vm-distributed` until an explicit revalidation of `local` or `vm-single` is
run.

## Adapters

| Adapter | Status |
| --- | --- |
| `inesdata` | `Level 1-6` deployment and validation operational |
| `edc` | Core deployment and validation implemented; official closure evidence limited to `vm-distributed` |

## Current Namespaces

The framework uses a `role-aligned` profile for INESData. Topologies must
respect these names to avoid divergence between diagrams, deployment, and
validation:

```ini
COMMON_SERVICES_NAMESPACE=common-srvs
DS_1_NAME=pionera
DS_1_NAMESPACE=core-control
NAMESPACE_PROFILE=role-aligned
DS_1_REGISTRATION_NAMESPACE=core-control
DS_1_PROVIDER_NAMESPACE=provider
DS_1_CONSUMER_NAMESPACE=consumer
COMPONENTS_NAMESPACE=components
```

Interpretation:

- `common-srvs`: Keycloak, MinIO, PostgreSQL, and Vault.
- `core-control`: registration-service and dataspace control plane.
- `provider`: provider connector.
- `consumer`: consumer connector.
- `components`: Ontology Hub, AI Model Hub, and Semantic Virtualization.
- `ingress-nginx` and `kube-system`: Kubernetes infrastructure.

The centralized resolution lives in:

```text
deployers/shared/lib/namespaces.py
deployers/inesdata/deployer.config.example
```

## Validation

`Level 6` can run:

- safe cleanup of test data;
- Newman/Postman collections;
- EDC+Kafka functional validation;
- Playwright for UI flows;
- component validations;
- experiment metrics and reports.

For Semantic Virtualization, the current automated scope covers `morph-kgv` as
the virtualization API, `mapping-editor` as the mappings UI/editor, and
`Automap` as the mapping generation tool. `morph-kgv` is validated as the
virtualizer's main runtime: `Level 6` checks its versionable execution
contract, including `run_query.py`, the `morph-kgv serve config.ini` command,
the `config.ini` examples, and the `/sparql` endpoint.
Automap is synced as the component's source and validated in two steps: first
as source code readiness/traceability, and then with a deterministic baseline
that exercises schema extraction, ontology extraction, reuse of an ontology
governed by Ontology Hub, controlled RDF materialization, and comparison
metrics against reference KGs. The full Automap LLM path is not run by
default in `Level 6` because it requires model configuration and secrets
outside the versionable baseline; Automap is not deployed as a runtime
service in the current baseline.

Artifacts are written under `experiments/`, which is generated output and must
not be versioned.

## AI Model Hub and Use Cases

The current state of the framework includes specific automation to prepare
the AI Model Hub use cases on `vm-distributed`. This automation does not
replace the normal level-based deployment; it complements it with an
operational assistant inside the `vm-distributed` assistant.

The implemented flow prepares a demo profile with a combined `model-server`,
runs `Level 5`, and lets you seed the connectors with the datasets and models
associated with the use cases:

- `Step 9`: registration of benchmark datasets as dataspace assets;
- `Step 10`: registration of the FLARES and Mobility models discovered from
  the `model-server` `/models` endpoint;
- for EDC, creation of `HttpData` assets, policies, contracts, and DSP
  negotiation tests between the configured connectors;
- for INESData, the specific flow based on the adapter's APIs is kept.

The `model-server` supports `mock`, `use-cases`, `combined`, and `external`
modes. The `combined` mode integrates the use case model and dataset
endpoints without dropping compatibility with the framework's controlled
fixtures. The operational artifacts and logs of this flow are stored outside
`docs/`.

## Newman/Postman Collections

The collections run by `Level 6` live in:

```text
validation/core/collections/
```

The collections and environments meant for manual import into Postman live
in:

```text
validation/core/collections/postman/
```

The specific guide is
[31_postman_newman_collections.md](./31_postman_newman_collections.md).

## Current Documentation

To understand the current framework, the recommended path is:

1. [Documentation README](./README.md)
2. [Getting started](./32_getting_started.md)
3. [Architecture](./34_architecture.md)
4. [Deployers and topologies](./35_deployers_and_topologies.md)
5. [Validation](./37_validation.md)
6. [Newman/Postman collections](./31_postman_newman_collections.md)
7. [vm-distributed operations runbook](./46_vm_distributed_runbook.md)

The historical numbered documents remain available as design traceability,
but this document and the public index should be considered the initial
operational reference.
