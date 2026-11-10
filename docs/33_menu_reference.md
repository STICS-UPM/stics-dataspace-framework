# Menu Reference

The guided menu opens with:

```bash
python3 main.py menu
```

The menu is in English to stay aligned with command names, code, and technical artifacts. This guide explains when to use each option.

## Header

By default, the menu no longer shows a block with the active adapter or the
list of available adapters. The idea is to reduce cognitive load on the
normal usage path.

If an action depends on the adapter, the framework:

- uses the adapter you preselected with `S`;
- or asks for it at that moment if none has been chosen yet.

When you open the framework with `python3 main.py`, the initial selector shows
an `Other actions` section with the same `G - Validate target` option that
later appears in `[Operations]`. That entry is used to validate external
targets without choosing a PIONERA topology. The default topology is marked
as `current`; `Back` only appears in submenus you have already entered.

## Full Deployment

`0 - Run All Levels (1-6) sequentially`

Use this option for a full deployment from scratch or to rebuild the whole environment in order. It runs cluster preparation, common services, dataspace, connectors, components, and validation.

## Individual Levels

`1 - Level 1: Setup Cluster`

Prepares the base cluster. On `local`, this path uses Minikube.

`2 - Level 2: Deploy Common Services`

Deploys or updates common services such as Keycloak, MinIO, PostgreSQL, and Vault.

`3 - Level 3: Deploy Dataspace`

Deploys the base dataspace runtime and the registration service. When it
finishes successfully, the normal next step is to run `Level 4` to deploy or
update the connectors of the active adapter.

`4 - Level 4: Deploy Connectors`

Deploys the connectors of the active adapter. With `inesdata`, it deploys INESData connectors. With `edc`, it deploys EDC connectors.

On the `local` topology, `inesdata` automatically prepares the local images of
`inesdata-connector` and `inesdata-connector-interface` before creating the
connectors, as long as the sources exist under `adapters/inesdata/sources/`.
This behavior can be disabled with `INESDATA_LOCAL_IMAGES_MODE=disabled` or
made strict with `INESDATA_LOCAL_IMAGES_MODE=required`.

On the `vm-single` and `vm-distributed` topologies, the framework uses by
default the images configured in the charts or explicit overrides. To build
and import images from sources on a VM, enable development mode with
`INESDATA_LOCAL_IMAGES_MODE=auto` or `LEVEL4_LOCAL_IMAGES_MODE=auto`.

`5 - Level 5: Deploy Components`

Deploys the configured optional components, such as Ontology Hub or AI Model Hub, when they apply to the active adapter and configuration.

When you want to deploy only a subset without modifying `deployer.config`
files, the recommended option is the `Components` section of the menu. That
section internally runs `Level 5` with temporary overrides and lets you
explicitly select Ontology Hub, AI Model Hub, Semantic Virtualization, and the
AI Model Hub model server.

`6 - Level 6: Run Validation Tests`

Runs the full validation of the active adapter. Depending on the validation
profile, it includes prior cleanup, Newman, storage checks, Playwright,
components, and metrics.

For closure evidence, use `vm-distributed` with the `edc` adapter. The EDC
`local` and `vm-single` paths are implemented, but they must be revalidated
before being presented as updated official evidence.

On the `local` topology, this option expects the hostnames published by the
Ingress to be reachable. Keep `minikube tunnel` open and enter the password in
that terminal if the sudo prompt appears. For connectors that are already
deployed, run `Level 6` from the same checkout that ran `Level 4`, because
that is where the local credentials used by the validation are generated.

Before launching Playwright, `Level 6` also runs a real HTTP preflight of the
adapter's portal:

- `inesdata`: checks Keycloak, the `*-interface` services, and the public
  path `http://<connector>.../inesdata-connector-interface/`;
- `edc`: checks Keycloak, the dashboard, the proxy, and the public management
  paths.

If that preflight fails, the level ends with a clear cause and persists the
adapter's diagnostics in `experiments/`.

## Operations

`S - Select adapter`

Lets you preselect the adapter for the current menu session. It's an optional
shortcut: if you don't use it, the framework will ask for the adapter when an
operation from `Level 3` to `Level 6` actually needs it.

`T - Select topology`

Lets you change the active topology for the current menu session. It doesn't
write any value to `deployer.config`: it only changes the interactive context
between `local`, `vm-single`, and `vm-distributed` until you leave the menu.

`W - vm-distributed assistant`

If the active topology is not `vm-distributed` yet, it keeps the historical
shortcut: it switches topology, with confirmation, and opens the
configuration wizard directly. When `vm-distributed` is already active, it
opens the operational assistant to prepare local configuration, show the VM
plan, run the static preflight, preview deployment/hosts, and launch
non-destructive SSH/HTTP checks with explicit confirmation. The assistant
asks for domains, VM IPs/DNS, an optional SSH user for remote NGINX
synchronization, preflight SSH metadata, k3s kubeconfigs, the connector
inventory, connector placement, and validation pairs. If you don't know how
to get a value, type `?` in the corresponding field. The generated
configuration is written only to local `.config` files ignored by Git. For
`vm-distributed`, the wizard also updates the common hostnames derived from
`DOMAIN_BASE` when it detects empty values or generated defaults, without
overwriting custom values.

Inside this assistant there is the option
`10 - AI Model Hub use-case demo preparation`. This option prepares the use
case profile with `model-server` in `use-cases` mode, shows the `Level 5` and
seeding commands, registers the DAIMO Model/Dataset vocabularies (`Step 8`),
runs the benchmark dataset registration (`Step 9`), and registers the
FLARES/Mobility models discovered from `/models` (`Step 10`). The flow is
adapter-aware: on `inesdata` it uses the adapter's own APIs, and on `edc` it
creates `HttpData` assets, policies, contracts, and DSP negotiations between
the configured pairs.

`P - Preview deployment plan`

Shows a deployment plan without modifying the environment. Use it before running destructive changes or when you want to review the expected dataspace, connectors, components, namespaces, and hosts. If the operation needs an adapter and none has been chosen yet, the menu asks for it at that moment.

`H - Plan/apply hosts entries`

Plans or applies entries in the `hosts` file. By default it only plans. The
output shows the concrete hostnames per level and the reason if the sync ends
up as `Skipped`.

If automatic sync is not enabled, the interactive menu offers to apply the
plan when it detects a resolvable `hosts` file. To apply changes explicitly
outside the interactive prompt, use `PIONERA_SYNC_HOSTS=true` and
`PIONERA_HOSTS_FILE`.

In the interactive menu, if the adapter chosen for the operation exposes
public hostnames and you are going to run levels `3-6`, the framework first
checks whether hostnames are missing from the local `hosts` file. If they
are, it shows the list and asks whether you want to reconcile the framework's
managed block before continuing. If you cancel or the system doesn't allow
writing the file, the level is not run.

Outside the menu, the equivalent and more direct path for this repair is:

```bash
python3 main.py <adapter> local-repair --topology local
```

`U - Show available access URLs`

Shows the access URLs derived from the active adapter configuration in a
readable format. It's useful after `Level 2`, `Level 4`, or `Level 5` when you
want to quickly see portals, dashboards, APIs, components, or shared access
points without searching through artifacts or configuration files.

Depending on the active configuration, the output includes:

- `Keycloak`
- `MinIO API`
- `MinIO Console`
- `registration-service`
- portal, connector, and component URLs
- `MinIO Bucket` per connector when applicable

On the `vm-single` topology, the output adds a `Local Browser Access` section
with values detected automatically from the VM: the VM's candidate IP, the
Minikube IP, the SSH user, the SSH tunnel command, entries for the local
machine's `hosts` file, and URLs you can open in your local browser.

`G - Validate target`

Opens the guided flow for external validation targets, initially intended for
production INESData or environments the framework doesn't deploy. This flow
doesn't select or change the active adapter used by the deployment levels; it
is shown as an external validation project in `validation-only` mode.

The current flow includes a minimal, safe runner:

- lets you select a target under `validation/targets/`;
- validates the target YAML;
- shows the required dataspaces, suites, components, and secrets;
- doesn't run cleanup or delete data;
- doesn't run writes;
- doesn't run `Levels 1-5`;
- runs only `read-only` Playwright specs explicitly enabled in
  `project_suites`;
- if only `*.example.*` templates exist, it ends as `skipped` without running
  Playwright.

Use it to check that the base configuration of an external INESData is
complete, or to generate read-only Playwright evidence when real specs
exist. Production Newman and Kafka are out of scope for this first phase.

`E - View experiment reports`

Opens a local viewer of validation experiments. It doesn't require selecting
an adapter because it doesn't deploy or run validations: it only reads
artifacts already generated under `experiments/`.

The flow lets you:

- list the available experiments;
- open the latest experiment or select an earlier one;
- generate the framework's own HTML dashboard;
- open Playwright reports with `npx playwright show-report`;
- see artifact paths without printing long JSON to the console.

The dashboard is served only on `127.0.0.1` and works as the experiment's
index for Playwright, Newman, Kafka, components, and local postflight when
those reports exist.

The `Dashboard status` field summarizes the viewer's findings; it doesn't
replace the `Level 6` execution status.

More detail in [Experiment report viewer](./40_report_viewer.md) (ES).

`M - Run metrics / benchmarks`

Runs standalone metrics or benchmarks on the adapter chosen for that operation. The Kafka benchmark measures the broker standalone and stores results in `experiments/`, but it doesn't replace the functional validation of `Level 6`. The dataspace's E2E Kafka validation is opt-in within `Level 6`; enable it with `PIONERA_LEVEL6_RUN_KAFKA=true` when you want to include it.

`X - Recreate dataspace`

Destroys and recreates the selected dataspace while preserving common services. It requires typing the exact dataspace name. It invalidates the level 4 connectors and lets you recreate them immediately if confirmed.

## Components

`CM - Deploy selected components`

Runs `Level 5` for a specific selection of components of the active adapter
and topology. The selection doesn't persist changes to `deployer.config`; the
framework uses `PIONERA_COMPONENTS` during that run to limit the deployment
scope.

The submenu lets you choose Ontology Hub, AI Model Hub, Semantic
Virtualization, the list configured in the adapter, or all deployable shared
components. The model server is shown as an explicit option and is enabled
only for that run through `PIONERA_AI_MODEL_HUB_MODEL_SERVER_ENABLED=true`.
Technically it is deployed under AI Model Hub, so selecting the server also
adds `ai-model-hub` to the `Level 5` run.

When components are built from framework-managed sources, `Level 5` refreshes
the configured checkouts before building the image. The configuration
examples use `main` to deploy the latest available version; for reproducible
runs, set `*_SOURCE_REF` to a tag or commit.

`AMH - AI Model Hub use-case Steps 7-10`

Opens the AI Model Hub use case preparation assistant directly. If the
session is not on `vm-distributed`, the menu offers to switch to that
topology. From that assistant, the full-flow option applies the use case
profile, runs `Level 5` as `Step 7` of the official repository, and then runs
the seeding steps `Step 8`, `Step 9`, and `Step 10`.

## Developer

`B - Bootstrap Framework Dependencies`

Installs or repairs the framework dependencies. Use it on a clean machine or after dependency problems; on Linux/WSL it also prepares the system dependencies needed by Playwright.

`D - Run Framework Doctor`

Runs local readiness checks. Use it before deploying or to diagnose environment failures.

`R - Repair Local Access / Connectors`

Runs a guided recovery of local access. It first reconciles the framework's
managed `hosts` block and then lets you restart the connectors if the cluster
was still deployed after restarting WSL or the local environment. When the
`hosts` block is ready, it also checks the minimum public endpoints the
framework expects before `Level 6`.

The equivalent CLI path is:

```bash
python3 main.py <adapter> local-repair --topology local
python3 main.py <adapter> local-repair --topology local --recover-connectors
```

`C - Cleanup Workspace`

Cleans generated artifacts, caches, or previous outputs that make it harder to reason about the current state.

`L - Build and Deploy Local Images`

Builds and loads local images. Use it during development when you have modified the source code of connectors, dashboards, or components that must be tested in the cluster.

The submenu separates the usual development path from the advanced recipes:

- `Quick actions`: quick actions specific to the active adapter. On
  INESData they do `build/load/redeploy` while preserving data: the redeploy
  uses `helm upgrade --reuse-values` on existing releases and doesn't
  reinstall missing releases with base values. On EDC they build/load the
  local connector and/or dashboard images and restart existing EDC
  deployments so they pick up the new image without recreating data.
- `Advanced recipes`: registered recipes to build, load, and, when selected,
  redeploy a specific source of the active adapter.

If the release doesn't exist, first run the corresponding level (`Level 4`
for connectors or `Level 5` for components).

For registered component recipes, such as `Ontology Hub` or `AI Model Hub`, if
the deployment already exists in the active dataspace's namespace, the
framework restarts it so it picks up the local image loaded into Minikube. If
it doesn't exist, the option only prepares the image; then run `Level 5` to
deploy the component.

## Validation

`I - INESData UI Tests (Normal/Live/Debug)`

Runs UI validations of the INESData portal independently of the full level 6.
The submenu separates `Core` from the component integrations seen from
INESData:

- `Ontology Hub Integration with INESData`: runs `DS-UI-OH-01`.
- `AI Model Hub Integration with INESData`: runs `DS-UI-AMH-01`,
  `DS-UI-AMH-BROWSER-01`, `DS-UI-AMH-EXEC-01`, and `DS-UI-AMH-BENCH-01`.
- `Semantic Virtualization Integration with INESData`: runs `DS-UI-SV-01`.

`O - Ontology Hub UI Tests (Normal/Live/Debug)`

Runs Ontology Hub's own UI validations, that is, on the component's
application and its technical/functional suites, not on INESData.

`A - AI Model Hub UI Tests (Normal/Live/Debug)`

Runs AI Model Hub's own UI validations, not the integration validation from
INESData.

`V - Semantic Virtualization UI Tests (Normal/Live/Debug)`

Runs UI/read-only validations of the semantic virtualizer. The suite opens
the public endpoint from Playwright, validates the OpenAPI document, and
checks that the query endpoint responds from the browser context. It also
covers the virtualizer's UI/editor when it is enabled; the validation from
INESData is run from `I`.

In level 6, Semantic Virtualization also validates on the console the
readiness of its supporting sources: `morph-kgv`, `mapping-editor`, the
official datasets, and Automap. For `morph-kgv`, it checks the documented
execution contract: the `run_query.py` CLI, the `morph-kgv serve config.ini`
command, the `config.ini` examples, and the `/sparql` endpoint. Automap is
treated as a mapping generation and scope traceability tool, not as a service
deployed in Kubernetes. In addition, `Level 6` runs a deterministic Automap
baseline without an LLM: it validates a small mobility fixture, extracts the
schema and ontology, reuses an ontology governed by Ontology Hub, materializes
controlled RDF, and computes metrics against reference KGs.

`F - Dataspace Interoperability Tests (Newman/Kafka)`

Opens a submenu to run interoperability tests without launching the whole
level 6:

- `1 - Newman connector interoperability tests`: runs the Newman
  interoperability collections between connectors and stores their artifacts
  in a new experiment.
- `2 - Kafka transfer interoperability tests`: runs only the validation of
  Kafka transfers between connectors. It requires explicit confirmation
  because it usually takes longer than the Newman validations.

These options reuse the same validation logic as level 6, but let you repeat
only the interoperability part you want to review.

## Control

`? - Help`

Shows a short help inside the menu itself.

`Q - Exit`

Leaves the menu.

## Topology

The topology is selected in two ways:

- from the CLI with `--topology`
- from the menu itself with `T - Select topology`

CLI examples:

```bash
python3 main.py inesdata deploy --topology local
python3 main.py inesdata hosts --topology vm-single --dry-run
```

Canonical topologies:

```text
local
vm-single
vm-distributed
```

Inside the menu, the active topology is shown in the header and applies to
all actions of the current session until you change it with `T` or leave the
menu.
