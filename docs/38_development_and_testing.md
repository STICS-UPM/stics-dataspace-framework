# Development and Testing

## Safe Development Flow

Work with small changes and validate them with focused tests before running broad suites.

Recommended loop:

```bash
python3 -m unittest tests.test_main_cli
python3 -m unittest tests.test_deployer_shared_contracts
python3 -m unittest tests.test_deployer_shared_hosts_manager
```

For UI changes, run the relevant Playwright suite from `validation/ui/`.

## Testing Local Images

Use `L - Build and Deploy Local Images` when you modify sources under
`adapters/<adapter>/sources/` and want to test them on the local cluster.

Expected behavior:

- in `Level 4 local`, INESData automatically prepares `inesdata-connector` and
  `inesdata-connector-interface` before creating connectors;
- the registered recipes build the image from a specific source;
- images are loaded into Minikube when the recipe requires it;
- `Ontology Hub` and `AI Model Hub` restart their deployment if they are
  already deployed;
- if the deployment doesn't exist, the image is left prepared and the
  component must be deployed with `Level 5`;
- for changes to INESData connectors, the build script recompiles the Java
  runtime when the artifact is missing or it detects local changes;
- the INESData quick options in `L` redeploy while preserving data: they
  reuse the existing Helm values and don't recreate credentials or common
  services;
- the EDC quick options in `L` build/load the local connector and/or
  dashboard images and restart existing EDC deployments without recreating
  data;
- EDC's `Level 4` also prepares the needed local images in `auto` mode on the
  `local` topology, before the Helm deployment, unless explicit overrides
  have been defined. On VM topologies, the recommended path is to use
  prebuilt images and configure the image overrides.

Available modes for `Level 4 local`:

- `INESDATA_LOCAL_IMAGES_MODE=auto`: default value on the `local` topology;
  uses local sources if they exist and skips the step if they're missing.
- `INESDATA_LOCAL_IMAGES_MODE=required`: fails if it can't prepare the local
  images.
- `INESDATA_LOCAL_IMAGES_MODE=disabled`: default value on the `vm-single` and
  `vm-distributed` topologies; uses the images configured in the Helm values
  or in the explicit overrides.

For `Level 5` components, `LEVEL5_AUTO_BUILD_LOCAL_IMAGES=true` is the
default behavior of the supported topologies, to avoid reusing old local
tags. On VM topologies, the framework rebuilds the image and imports it into
the remote k3s when the configuration allows it. For `ontology-hub`,
`ai-model-hub`, `semantic-virtualization`, `mapping-editor`, `automap`, and
the real `model-server`, the configuration examples point to `main` and
enable `*_SOURCE_REFRESH=true`; therefore, the local checkout is refreshed
before the build. The `*_SOURCE_REF` fields accept a branch, tag, or commit.
If frozen reproducibility is required for a report or audit, set
`*_SOURCE_REF` to a specific commit or tag. If the checkout has tracked local
changes, the framework stops before refreshing so as not to mix local work
with remote sources. If you prefer a registry image, set `*_IMAGE_REF` to a
full reference and explicitly disable the local build.

After loading a local image, validate with a focused test before running the
whole suite. For the INESData connector, the recommended E2E flow is:

```bash
cd validation/ui
UI_ADAPTER=inesdata npx playwright test adapters/inesdata/specs/05-e2e-transfer-flow.spec.ts --config=playwright.inesdata.config.ts --workers=1
```

## Extending Deployers

Shared deployer logic belongs to:

```text
deployers/infrastructure/lib/
```

Adapter-specific behavior belongs to:

```text
deployers/<adapter>/
adapters/<adapter>/
```

Avoid adding adapter-specific behavior to shared helpers unless it is explicitly parameterized.

## Extending Topologies

Topology resolution is centralized in:

```text
deployers/infrastructure/lib/topology.py
deployers/shared/lib/topology.py
```

The deployer context must describe:

- topology name;
- default address;
- per-role addresses;
- ingress external IP;
- routing mode.

The real execution of a topology must only be enabled after its preflights have been implemented and tested.

## Extending Validations

New validations must follow this order:

1. Add API checks when possible.
2. Add UI checks only for visible behavior.
3. Add cleanup of generated data.
4. Store artifacts in `experiments/`.
5. Add focused orchestration and configuration tests.

For tests specific to an external or production INESData, don't modify the
base suites. Create project suites under `validation/projects/inesdata/`,
declare them in `project_suites.yaml`, and enable them from the corresponding
target, as described in
[External INESData validation](./29_inesdata_external_validation_targets.md) (ES).

## Generated and Sensitive Files

Don't push:

- local `deployer.config` files;
- generated deployments;
- experiment outputs;
- Playwright reports;
- local source repositories under ignored folders;
- internal development context.

Use `.gitignore` as the source of truth before preparing commits.

## Broad Suites

Some broad legacy suites may require external services or old assumptions. For day-to-day development, prioritize focused tests of the modified area and expand coverage when the environment is ready.
