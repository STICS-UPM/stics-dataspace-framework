# Validation

## Level 5 and Datasets

`Level 5` prepares the configured components and also syncs the dataset
sources those components need for their validations. The clones are placed
in a neutral framework path:

```text
validation/datasets/sources/
```

These sources are currently registered:

| Dataset | Components that use it | Repository |
| --- | --- | --- |
| `FLARES` | `ai-model-hub` | `https://github.com/rsepulveda911112/Flares-dataset` |
| `GTFS-Madrid-Bench` | `ai-model-hub`, `semantic-virtualization` | `https://github.com/oeg-upm/gtfs-bench` |

For the AI Model Hub use cases, the framework can also prepare a
`model-server` associated with the `ProyectoPIONERA/AIModelHub-Use-Cases`
repository. That server is configured from `Level 5` when the profile enables
it and exposes model and dataset discovery endpoints used by asset seeding.

If the environment has no access to GitHub, `Level 5` leaves a warning by
default and doesn't break existing deployments. To require the
synchronization to fail strictly, use:

```bash
PIONERA_LEVEL5_DATASET_SYNC_STRICT=true python3 main.py inesdata run --topology local
```

`Level 6` doesn't clone repositories: it validates and consumes the sources
already prepared by `Level 5`. When a suite needs a controlled sample, it
derives it during the run and stores it as experiment evidence, not as a
versioned reduced dataset.

## Level 6

Level 6 is the validation level. It must validate the deployed dataspace and the enabled components without requiring an additional service validation level.

## Closure Validation Scope

For this closure version, validation evidence is interpreted per adapter and
topology:

| Adapter | `local` | `vm-single` | `vm-distributed` |
| --- | --- | --- | --- |
| `inesdata` | Local development/validation path implemented | VM path implemented and validated as reference | Distributed path implemented and validated as reference |
| `edc` | Implemented; requires revalidation after the recent topology reconciliation | Implemented; not officially validated after the recent reconciliation | Official closure path for EDC |

The repository contains `Level 6` suites for more combinations than those
used as official evidence. Before using a result as closure evidence, check
that the experiment corresponds to a combination validated in this matrix.

For external environments the framework doesn't deploy, such as an existing
production INESData, the target path is to use a `validation target` in
`validation-only` mode. That path is documented in
[External INESData validation](./29_inesdata_external_validation_targets.md) (ES).
The current base exposes this path from the menu with `G - Validate target`
in a safe read-only mode: it validates the YAML, shows the plan, and runs
`read-only` Playwright specs when they are explicitly enabled in
`project_suites`. It doesn't run cleanup, writes, production Newman, or
production Kafka.

Depending on the adapter and the deployer profile, level 6 runs:

- test data cleanup;
- Newman/Postman collections;
- EDC+Kafka functional validation after Newman when the adapter supports it;
- Playwright UI suites;
- component validations;
- metrics collection;
- experiment report generation.

When there are configured components with a registered runner, `Level 6` runs
their validation after the dataspace suites. In the current state:

- `ontology-hub` runs its functional and integration suites;
- `ai-model-hub` runs bootstrap, functional UI, the linguistic suite,
  benchmarking, mobility, model execution, connector governance, and the
  Observer API;
- `semantic-virtualization` runs API, mappings, GTFS-Bench traceability,
  materialization, functional UI, and cross-traceability with AI Model Hub
  and Ontology Hub before its integration checks.

In `ai-model-hub`, model execution is validated through a controlled input
and output contract. The framework keeps a `mock` mode for deterministic
validations and has `use-cases` and `combined` modes to expose the models and
datasets of the real use cases. The `combined` mode is the operational mode
used to prepare reproducible demos: it keeps controlled fixtures when needed
and, at the same time, publishes the `/models` and `/datasets` endpoints
consumed by asset seeding.

For the `FLARES` and mobility use cases, the framework's closure criterion is
to validate the complete flow inside the data space with synced sources,
registered assets, available contracts, and DSP negotiations when the adapter
is EDC. The validation does not aim to prove that the best possible models
have been selected or to measure predictive quality with full datasets.

The `scripts/seed_ml_assets_for_connectors.sh` script is adapter-aware. On
`inesdata` it uses the adapter-specific APIs for datasets and models. On
`edc` it creates standard `HttpData` assets, policies, and contracts, and can
run negotiations between the pairs configured in `DS_1_VALIDATION_PAIRS`.

The API validation of these use cases runs inside `Level 6` as the
`AI Model Hub use cases` suite. In `mock` mode it is recorded as `skipped`.
In `use-cases` or `combined` modes, it validates that the `model-server`
exposes models and datasets discovered through `/models` and `/datasets`. The
inference endpoints are only invoked when the profile defines explicit paths
for that validation.

Kafka/streaming transfer is the only A5.2 suite that remains disabled by
default because of its time cost. It is enabled explicitly with
`PIONERA_LEVEL6_RUN_KAFKA=true`.

On the `local` topology, before cleaning data or running suites, `Level 6`
checks that the environment's public hostnames are reachable from the
machine launching the framework. If this check fails, make sure
`minikube tunnel` is still open in another terminal. If that terminal shows
`[sudo] password for <user>:`, enter the Linux/WSL password in that same
terminal and launch the level again.

That public preflight is part of the framework's expected behavior on
`local`. A full `Level 6` must run against the environment's public path, not
against `port-forward` as the main path.

In local stable mode, the framework also runs capacity and stability guards.
`Level 1` warns if Docker Desktop only supports one local adapter.
`Level 3/4/5` block the installation of the second adapter when another one
is already active and the effective capacity is below `18432 MB`. In an
interactive terminal, they offer a controlled adapter switch: with exact
confirmation, they delete only the managed local resources of the previous
adapter and preserve `common-srvs`. `Level 6` repeats the check before the
suites to avoid false results caused by Minikube pressure. It then waits for
the node and the relevant pods to be ready, records restarts and
`NodeNotReady` events, and leaves evidence in:

```text
local_capacity_preflight.json
local_stability_preflight.json
local_stability_postflight.json
```

If the local runtime is not ready after the waiting window, the framework
fails early with an actionable message instead of running suites on a
clearly unstable cluster. For exceptional diagnosis, disable it with
`PIONERA_LOCAL_STABILITY_CHECKS=false`. The coexistence capacity guard is
downgraded to a warning with `PIONERA_LOCAL_COEXISTENCE_GUARD=warn` or
disabled with `PIONERA_LOCAL_COEXISTENCE_GUARD=off`. Adjust the window with
`PIONERA_LOCAL_STABILITY_TIMEOUT_SECONDS` and
`PIONERA_LOCAL_STABILITY_POLL_SECONDS`.

To automate an adapter switch in a non-interactive run, set
`PIONERA_LOCAL_ADAPTER_SWITCH_CONFIRM` to the exact value shown by the
framework, for example `SWITCH TO EDC` or `SWITCH TO INESDATA`.

After that general check, `Level 6` runs adapter-specific preflights before
opening Playwright:

- `inesdata`: validates Keycloak, the `*-interface` services, and the public
  path `http://<connector>.../inesdata-connector-interface/`. If it fails, it
  leaves `ui/inesdata/portal_readiness.json` inside the experiment.
- `edc`: validates Keycloak, the dashboard, the proxy, and the public paths
  of the dashboard and the management API. If it fails, it leaves
  `ui/edc/dashboard_readiness.json`.

For validations on connectors that are already deployed, run `Level 6` from
the same checkout that ran `Level 4`. The local artifacts under
`deployers/<adapter>/deployments/<environment>/<dataspace>/` contain the
credentials generated for Keycloak, MinIO, and the connectors. If you validate
from another checkout with different artifacts, errors such as
`invalid_grant`, `Invalid user credentials`, or `InvalidAccessKeyId` appear.

## Newman

Newman validates API behavior and end-to-end dataspace flows.

Typical coverage includes:

- authentication on connectors;
- asset publication;
- catalog discovery;
- contract negotiation;
- transfer start;
- transfer storage verification when applicable.

The real sequence run by the framework and the collections importable into
Postman are documented in
[Newman and Postman collections](./31_postman_newman_collections.md) (ES).

## Playwright

Playwright validates flows visible in the browser.

The UI suites are adapter-aware. They must validate user dashboards and portals without replacing the API validations.

The framework doesn't start Playwright just because Kubernetes reports pods or
endpoints as ready. It first waits for the adapter's required public HTTP
paths to actually respond. This reduces flakes caused by `503`, proxies not
yet synced, or portals not yet reachable through the Ingress.

Typical commands:

```bash
python3 main.py inesdata validate --topology local
python3 main.py edc validate --topology vm-distributed
```

## Test Data Cleanup

Validation starts with cleanup when the active profile requires it, to make
traceability easier and avoid saturation from data of previous runs.

Cleanup must be safe by default and report what it deleted or skipped.

## Kafka in Level 6

The EDC+Kafka functional validation is not the same flow as the optional
broker benchmark. In `Level 6`, it is disabled by default to save time in
routine validations. In interactive runs, `Level 6` asks
`Run Kafka validation suites too?` as the first visible action before
launching Newman, so Kafka can be prepared in parallel when the mode allows
it. In non-interactive runs, it is enabled with
`PIONERA_LEVEL6_RUN_KAFKA=true`. When enabled, it runs after Newman for the
compatible adapters and validates the path `asset -> catalog -> negotiation
-> Kafka transfer -> consumption of the destination topic`.

In `fast` mode, the Kafka broker preparation starts at the beginning of
`Level 6` while Newman keeps running in the foreground. In local `stable`
mode, which is the default for `local`, that preparation is deferred until
the Kafka phase to reduce operational overlap and improve reproducibility.

After the contract negotiation finishes, the suite waits for the agreement to
be visible on provider and consumer before starting `Kafka-PUSH`. This guard
avoids transient races where the transfer is launched right after
`FINALIZED`, but the EDC runtime still can't resolve the agreement through
the protocol and responds `404 Not found`. The default timeout is 30 seconds;
adjust it with `KAFKA_EDC_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS`.

The full `Level 6` flow still requires Keycloak, MinIO,
`registration-service`, and the connectors to be reachable by public
hostname. The Kafka part uses local support mechanisms for the framework's
own process, but that doesn't make a full `Level 6` a correct validation if
the local public layer is not available.

On the `local` topology, the default managed broker is deployed inside
Kubernetes. The connectors use the internal cluster endpoint:

```text
framework-kafka.<namespace>.svc.cluster.local:9092
```

The framework uses a temporary `port-forward` so the host's Python process
can create topics, produce test messages, and verify the destination topic.
That `port-forward` is an internal support mechanism of the validation, not a
public dataspace endpoint.

When you need a more stable variant of the local Kafka broker without leaving
Kubernetes, enable it explicitly:

```bash
PIONERA_KAFKA_PROVISIONER=kubernetes-split-kraft python3 main.py inesdata validate --topology local
```

That variant remains opt-in. The default mode doesn't change automatically.

For very specific Kafka diagnostics on `local`, there is also an opt-in HTTP
fallback in the framework:

```bash
PIONERA_LEVEL6_LOCAL_HTTP_PORT_FORWARD_FALLBACK=true
```

That fallback only acts as technical help for the Kafka suite once the flow
has reached that phase. It doesn't replace the `Level 6` public preflight,
and it must not be used to declare a full run valid without access to the
environment's public hostnames.

The console uses neutral messages under the name `Kafka transfer validation`.
By default it prints the result per connector pair as each test finishes,
with icons and a final summary. The experiment's JSON artifacts keep the full
detail. To show samples of message IDs on the console during diagnosis:

```bash
PIONERA_KAFKA_TRANSFER_LOG_MESSAGES=true python3 main.py inesdata validate --topology local
```

Component preparations avoid printing long scripts to the console by
default. If during diagnosis you need to see the full command of an internal
preparation, enable it with:

```bash
PIONERA_VERBOSE_COMMANDS=true python3 main.py inesdata validate --topology local
```

## Metrics

Metrics are run from the menu or the CLI:

```bash
python3 main.py inesdata metrics --topology local
python3 main.py inesdata metrics --topology local --kafka
```

Metrics and validation artifacts are stored in:

```text
experiments/
```

This folder is generated output and must not be pushed to the repository.

## Reports

The recommended way to review generated reports is from the menu:

```bash
python3 main.py
```

Select:

```text
E - View experiment reports
```

That viewer lists the experiments under `experiments/`, generates a local
HTML dashboard per experiment, and summarizes long Newman, Kafka, component,
and postflight artifacts without printing full JSON to the console. Reports
are served only on `127.0.0.1`.

After a validation or experiment:

```bash
python3 main.py report <experiment_id>
python3 main.py compare <experiment_a> <experiment_b>
```

More detail in [Experiment report viewer](./40_report_viewer.md) (ES).

Reports must state the adapter, topology, connectors, and suites run.
