# STICS Dataspace Framework

This repository deploys, operates, and validates the **STICS dataspace**, the
data space of the Smart Transformational and Innovation Consortium Slovakia
(STICS). It is a fork of PIONERA's
[Validation-Environment](https://github.com/ProyectoPIONERA/Validation-Environment)
and builds on that framework, adding what STICS needs on top of it: connector
onboarding for partners, interoperability evidence, operational tooling, and
STICS branding.

## STICS Architecture

The STICS dataspace runs on a **hybrid architecture**:

- **Common services** (Keycloak, Vault, MinIO, PostgreSQL, and the INESData
  registration service) run in a k3s cluster on one VM. This is the only part
  of the stack the framework manages inside Kubernetes. It uses the
  framework's `vm-distributed` topology with the `edc` adapter.
- **Connectors** (EDC) run outside Kubernetes, as Docker Compose
  deployments on the VM of each participant. Each connector can optionally
  have its own web interface.
- Every VM is reached through a public hostname behind ingress-nginx. The
  dataspace shares one self-signed TLS certificate; the deployment guide also
  covers per-VM Let's Encrypt certificates for external clients.

## Getting Started with STICS

Start here if your goal is to operate or extend STICS:

| Guide | Use it to |
| --- | --- |
| [Dataspace setup guide](./dataspace-setup-guide.md) | Stand up a new STICS-style dataspace from scratch: VM requirements and the shared common services. |
| [Connector deployment guide](./deployment-guide.md) | Add a new connector (and, optionally, its web interface) to the dataspace, outside Kubernetes. Includes the ingress-nginx and Let's Encrypt setup. |
| [New connector guide for beginners](./docs/48_new_connector_setup_guide_for_dummies.md) | Same process, step by step, explaining the *why* of each step. |
| [Partner onboarding runbook](./docs/49_bavenir_hands_on_session_guide.md) | Run a live onboarding session to bring up a connector on a partner's own infrastructure. |
| [Connector automation guide](./docs/50_connector_automation_guide.md) | Publish and consume data from an external system through the connector Management API. |
| [EDC interoperability evidence](./docs/47_stics_edc_interop_evidence.md) | Reproduce the provider ↔ consumer evidence: OAuth2, DSP catalog, contract negotiation, and transfers. |

## What This Fork Adds

| Area | Location | Description |
| --- | --- | --- |
| Connector provisioning API | [`provisioning-api/`](./provisioning-api/README.md) | Self-service registration and connector provisioning for STICS partners. Increment 1 of 4 (registration and approval). |
| Connector client and Postman toolbox | [`docs/examples/stics_connector_client.py`](./docs/examples/stics_connector_client.py), `validation/core/collections/postman/07_stics_connector_toolbox.json` | Reference Python client and Postman collection for automating asset publication and consumption. |
| Interoperability collections | `validation/core/collections/postman/04_stics_edc_interop.json`, `05_connector_bavenir_pull_transfer.json` | Executable evidence of end-to-end interoperation between STICS connectors. |
| Ontology Hub STICS overlay | [`adapters/inesdata/overlays/ontology-hub/`](./adapters/inesdata/overlays/ontology-hub/README.md) | STICS branding and funding acknowledgement, applied at build time on top of the upstream Ontology Hub. |
| Vault operations | `deployers/shared/common/vault-ops/` | Nightly backup of the common-services Vault. The auto-unseal manifest holds the unseal key, so it stays local and git-ignored. |
| Use case data | `use_cases/` | Datasets and models used in the dataspace use cases (mobility, FLARES). |

### Ongoing Research Work

- **Connector store concurrency benchmark**: a reproducible JMeter benchmark
  that compares the connector's PostgreSQL store with a SPARQL triplestore
  extension under sequential and concurrent asset operations. Its assets are
  built from real metadata of the Slovak National Open Data Catalogue. It is
  under development in the
  [`feature/store-concurrency-benchmark`](https://github.com/STICS-UPM/stics-dataspace-framework/tree/feature/store-concurrency-benchmark/validation/performance/triplestore_concurrency)
  branch.

## Installation

```bash
git clone https://github.com/STICS-UPM/stics-dataspace-framework.git
cd stics-dataspace-framework
git submodule update --init --recursive
bash scripts/bootstrap_framework.sh
source .venv/bin/activate
python3 main.py menu
```

`bootstrap_framework.sh` installs Python/Node/Playwright dependencies and, on
Linux/WSL, the system packages Playwright needs. Node.js/npm are required for
Newman and Playwright; Java 17+ is required to build connector images. Use
`--without-system-deps` if your environment can't install system packages.
The bootstrap also creates `deployer.config` and topology overlay files from
their `.example` templates the first time, without overwriting existing ones.

Real domain, IP, SSH, kubeconfig, and credential values stay in local,
git-ignored files or environment variables — never in versioned files.

## The Underlying Framework

The framework deploys dataspaces level by level, validates connectors, runs
functional tests, collects metrics, and stores traceable evidence under
`experiments/`. The main entry point is `main.py`:

```bash
python3 main.py menu
```

| Level | Action |
| --- | --- |
| `1` | Setup Cluster |
| `2` | Deploy Common Services |
| `3` | Deploy Dataspace |
| `4` | Deploy Connectors |
| `5` | Deploy Components |
| `6` | Run Validation Tests |

- **Adapters**: `inesdata` (INESData connectors and portal) and `edc`
  (generic EDC connectors). STICS uses `edc`.
- **Topologies**: `local`, `vm-single`, and `vm-distributed`. STICS uses
  `vm-distributed` for its common services.
- **Validation**: Newman (API), Playwright (UI), MinIO/storage checks,
  component validation, metrics, and optional Kafka benchmarks.

Detailed status of the framework:
[docs/30_framework_current_state.md](./docs/30_framework_current_state.md).

### Requirements

| Group | Main tools |
| --- | --- |
| Local base | Python 3.10+, Git, Docker |
| Kubernetes | k3s or Minikube, Helm, `kubectl` |
| Validation | Node.js, npm, Newman, Playwright |
| Connector builds | Java 17+ / OpenJDK 17 |
| Operations | `psql`, permissions to edit `hosts` when applicable |

### Framework Documentation

Full documentation: [docs/](./docs/README.md). Recommended reading order:

- [Getting started](./docs/32_getting_started.md)
- [Menu reference](./docs/33_menu_reference.md)
- [Architecture](./docs/34_architecture.md)
- [Deployers and topologies](./docs/35_deployers_and_topologies.md)
- [Adapters](./docs/36_adapters.md)
- [Validation](./docs/37_validation.md)
- [Development and testing](./docs/38_development_and_testing.md)
- [Troubleshooting](./docs/39_troubleshooting.md)
- [vm-distributed runbook](./docs/46_vm_distributed_runbook.md)

## Repository Structure

| Path | Description |
| --- | --- |
| `dataspace-setup-guide.md`, `deployment-guide.md` | STICS dataspace and connector guides |
| `provisioning-api/` | STICS connector provisioning API |
| `main.py` | Main CLI and guided menu |
| `framework/` | Reusable validation, metrics, and reporting core |
| `adapters/` | Adapter-specific integrations, including the STICS Ontology Hub overlay |
| `deployers/` | Deployers, configuration, and deployment artifacts |
| `validation/` | Newman, Playwright, and component validation suites |
| `use_cases/` | Use case datasets and models |
| `tests/` | Framework unit tests |
| `docs/` | Framework and STICS documentation |

## Tests

```bash
python3 -m unittest discover tests
```

## Contributing

Work happens in this repository (`STICS-UPM/stics-dataspace-framework`):

1. Create a working branch from `main`.
2. Run the relevant tests before opening a pull request.
3. Open the pull request against `main` of **this repository**. GitHub
   proposes the upstream PIONERA repository as the default base for forks,
   so check the base repository before creating it.

Never include credentials, tokens, private keys, real kubeconfigs, secrets in
logs, or personal data in commits, issues, or pull requests.

## Technical References

- [PIONERA Validation-Environment (upstream)](https://github.com/ProyectoPIONERA/Validation-Environment)
- [INESData local environment](https://github.com/INESData/inesdata-local-env)
- [Eclipse EDC Management API](https://eclipse-edc.github.io/Connector/openapi/management-api/#/)
- [Eclipse Dataspace Protocol](https://eclipse-dataspace-protocol-base.github.io/DataspaceProtocol/)
- [Eclipse EDC Kafka sample](https://github.com/eclipse-edc/Samples/tree/main/transfer/transfer-06-kafka-broker)

## Acknowledgments and Funding

This work has received funding from the EU NextGenerationEU through the
Recovery and Resilience Plan for Slovakia under the project within the
**Smart Transformational and Innovation Consortium Slovakia (STICS)**,
No. 09I02-03-V01-00011.

<div align="center">
  <img src="adapters/inesdata/overlays/ontology-hub/public/img/stics-funding-acknowledgement.png" alt="STICS funding acknowledgement" width="900" />
</div>

The underlying framework was developed within the **PIONERA project**
(Enhancing interoperability in data spaces through artificial intelligence),
funded under the call for Technological Products and Services for Data Spaces
of the Spanish Ministry for Digital Transformation and the Civil Service,
within the PRTR framework funded by the European Union (NextGenerationEU).

<div align="center">
  <img src="funding_label.png" alt="PIONERA funding logos" width="900" />
</div>

---

## Authors and Contact

For questions, issues, or change proposals, use the GitHub issues and pull
requests of this repository.

- **STICS dataspace authors:**
  - Lucía Martín-Núñez (<lucia.martin.nunez@upm.es>)
  - Raúl García-Castro (<r.garcia@upm.es>)
  - Andrea Cimmino Arriaga (<andreajesus.cimmino@upm.es>)
  - María Poveda Villalón (<m.poveda@upm.es>)
- **Original framework authors (PIONERA project, upstream
  [Validation-Environment](https://github.com/ProyectoPIONERA/Validation-Environment)):**
  - Adrián Vargas (<adrian.vargas@upm.es>)
  - Raffaele Cuzzaniti (<r.cuzzaniti@upm.es>)

## License

This repository is available under the **[Apache License 2.0](./LICENSE)**,
the same license as the upstream PIONERA Validation-Environment it derives from.
