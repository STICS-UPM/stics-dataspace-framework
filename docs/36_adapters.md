# Adapters

## Purpose

Adapters isolate the behavior specific to each dataspace implementation.

The current adapters are:

```text
adapters/inesdata/
adapters/edc/
```

Both adapters can coexist on the same local cluster and share `common-srvs`.
For that coexistence to be reproducible, each adapter must use its own
dataspace and namespace. The reference local configuration uses `pionera` for
INESData and `pionera-edc` for EDC.

The same `DS_1_NAME` or `DS_1_NAMESPACE` must not be reused between adapters
on the same cluster. That reuse can mix up the registration-service,
databases, users, hostnames, and deployment artifacts.

Each adapter can provide:

- deployment operations;
- connector discovery;
- URL generation;
- credential loading;
- data cleanup;
- validation-specific configuration;
- support for building local images.

## INESData Adapter

The INESData adapter supports the INESData-based deployment.

Relevant configuration:

```text
deployers/infrastructure/deployer.config
deployers/infrastructure/topologies/<topology>.config
deployers/inesdata/deployer.config
```

In the current state of the framework, `INESData` doesn't need its own
topology overlays inside `deployers/inesdata/`. Its `deployer.config` remains
the adapter layer and must stay focused on dataspace identity, connectors,
components, and functional flags; the `local`, `vm-single`, and
`vm-distributed` differences belong to the shared infrastructure layer.

Relevant deployer:

```text
deployers/inesdata/deployer.py
```

Optional components are configured in the adapter's `deployer.config` and are deployed in level 5 when enabled.

The INESData adapter can also propagate branding variables to the connector
interface and the portal. The recommended configuration lives in
`identity/branding.config.example`. For a specific deployment, copy that file
as `identity/branding.config` and adjust the needed values:

```ini
INESDATA_BRAND_NAME=PIONERA
INESDATA_BRAND_SHOW_MENU_TEXT=false
INESDATA_BRAND_THEME=theme-1
INESDATA_BRAND_PRIMARY_COLOR=#025B77
INESDATA_BRAND_SECONDARY_COLOR=#2FA0B5
INESDATA_BRAND_ASSETS_DIR=identity
INESDATA_BRAND_LOGO_FILES=pionera-logo.svg
INESDATA_BRAND_LOGO_URLS=
INESDATA_BRAND_FOOTER_LOGO_FILES=pionera-logo.svg,funding-logos.png,oeg.png
INESDATA_BRAND_FOOTER_LOGO_URLS=
INESDATA_BRAND_FOOTER_TEXT=
INESDATA_BRAND_POWERED_BY_TEXT=Powered by:
INESDATA_BRAND_POWERED_BY_LOGO_FILES=inesdta.png
INESDATA_BRAND_POWERED_BY_LOGO_URLS=
INESDATA_BRAND_CONNECTOR_ASSET_BASE_URL=/inesdata-connector-interface/assets/branding
INESDATA_BRAND_PORTAL_ASSET_BASE_URL=/assets/branding
INESDATA_LOCAL_STORE_LABEL=LocalStore
```

In local deployments, level 4 rebuilds the connector interface applying the
visual customization temporarily on the sources and restores the original
files when the build finishes. `INESDATA_BRAND_SHOW_MENU_TEXT=false` hides the
side menu's text name when the logo already includes the brand.
`InesDataStore` remains the technical type used by the transfer APIs;
`INESDATA_LOCAL_STORE_LABEL=LocalStore` must be read as the visual name of
that functional option, not as a replacement for the technical value.

The versionable visual assets live in `identity/`. To use your own logos, add
files to that folder and reference their names in
`INESDATA_BRAND_LOGO_FILES`, `INESDATA_BRAND_FOOTER_LOGO_FILES`, or
`INESDATA_BRAND_POWERED_BY_LOGO_FILES`. The framework packages them as Helm
ConfigMaps and mounts them in the frontends at `/assets/branding` or at the
base path configured for the connector interface. If external URLs are
needed, they can be set directly in `INESDATA_BRAND_LOGO_URLS`,
`INESDATA_BRAND_FOOTER_LOGO_URLS`, or `INESDATA_BRAND_POWERED_BY_LOGO_URLS`.

For compatibility, the same variables can also be defined in
`deployers/inesdata/deployer.config`; if they appear there, they override the
configuration from `identity/`.

## EDC Adapter

The EDC adapter supports a generic EDC deployment.

### EDC Closure Scope

In the repository's closure version, EDC must be described as follows:

| Topology | Closure status |
| --- | --- |
| `vm-distributed` | Officially tested path for EDC. |
| `local` | Implemented path, useful for development; it passed validation before the recent topology reconciliation, but must be revalidated before being presented as current evidence. |
| `vm-single` | Implemented path; not officially validated after the recent reconciliation. |

This distinction avoids confusing code support with audited evidence. If you
need to close EDC on `local` or `vm-single`, run a full revalidation from
levels `1-6` and keep the resulting experiment.

Relevant configuration:

```text
deployers/infrastructure/deployer.config
deployers/infrastructure/topologies/<topology>.config
deployers/edc/deployer.config
```

In the current state of the framework, `EDC` doesn't need its own topology
overlays inside `deployers/edc/` either. Its `deployer.config` must remain
topology-agnostic and describe only the dataspace, its connectors, and the
adapter's specific flags. If a real per-topology divergence appears in the
future, that need must be justified before adding `deployers/edc/topologies/`.

Relevant deployer:

```text
deployers/edc/deployer.py
```

EDC's `Level 3` temporarily reuses the shared bootstrap logic of the base
dataspace, but reads its configuration from `deployers/edc/deployer.config`.
Therefore, the EDC dataspace remains isolated:

```text
DS_1_NAME=pionera-edc
DS_1_NAMESPACE=edc-control
NAMESPACE_PROFILE=role-aligned
DS_1_REGISTRATION_NAMESPACE=edc-control
DS_1_PROVIDER_NAMESPACE=edc-provider
DS_1_CONSUMER_NAMESPACE=edc-consumer
DS_1_CONNECTORS=citycounciledc,companyedc
```

For more than two connectors, the adapter accepts the same pattern as
INESData: `DS_1_CONNECTORS` defines the inventory, `DS_1_CONNECTOR_NAMESPACES`
assigns each connector to a namespace or deployment group, and
`DS_1_VALIDATION_PAIRS` defines the pairs used in the validations. The
`edc-provider` and `edc-consumer` namespaces are operational groups of the
test environment, not exclusive functional roles of the connector.

If `DS_1_CONNECTOR_NAMESPACES` and `DS_1_VALIDATION_PAIRS` are left empty in
the `deployer.config`, the framework keeps the base deployment: first
connector as validation source, second connector as validation destination,
and placement derived from the namespaces configured for the adapter. To
control a deployment with more connectors, use the format:

```ini
DS_1_CONNECTOR_NAMESPACES=citycounciledc:edc-provider,companyedc:edc-consumer,partneredc:edc-provider
DS_1_VALIDATION_PAIRS=citycounciledc>companyedc,partneredc>citycounciledc
```

The `LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive` mode lets you add new
connectors while preserving existing, healthy connectors. The default mode is
`full`, which keeps the clean reconciliation used by the closure validations.

The operational behavior of `Level 3` must be equivalent to INESData's: it
runs the bootstrap of the active adapter's dataspace even if the namespace
already exists. After `Level 3`, run `Level 4` to deploy or update the EDC
connectors.

The EDC adapter can build or use a configured connector image. On the `local` topology, if no overrides have been defined, Level 4 automatically prepares the local image from `adapters/edc/sources/connector`, loads it into Minikube, and uses `validation-environment/edc-connector:local` for that run. This preparation also lives inside the EDC adapter, so it works both from the level-based menu and from direct adapter calls.

If `EDC_DASHBOARD_ENABLED=true`, Level 4 also prepares and loads into Minikube the local images of the dashboard and the proxy:

```text
validation-environment/edc-dashboard:latest
validation-environment/edc-dashboard-proxy:latest
```

On VM topologies, or when you want to use an image published in a registry, define explicit overrides to avoid deploying an unverified default image.

Common override variables:

```text
PIONERA_EDC_CONNECTOR_IMAGE_NAME
PIONERA_EDC_CONNECTOR_IMAGE_TAG
```

Optional variables to change the automatic local image:

```text
PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_NAME
PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_TAG
```

Optional variables to change the dashboard images:

```text
PIONERA_EDC_DASHBOARD_REPO_URL
PIONERA_EDC_DASHBOARD_REPO_REF
PIONERA_EDC_DASHBOARD_IMAGE_NAME
PIONERA_EDC_DASHBOARD_IMAGE_TAG
PIONERA_EDC_DASHBOARD_PROXY_IMAGE_NAME
PIONERA_EDC_DASHBOARD_PROXY_IMAGE_TAG
```

The EDC dashboard is kept as a Git submodule in
`adapters/edc/sources/dashboard` and points to the official
`ProyectoPIONERA/EDC-asset-filter-dashboard` repository. The framework keeps
its own configuration and overlays in separate paths so as not to mix
authorship or generate divergent copies of the official dashboard.

When `EDC_DASHBOARD_PROXY_AUTH_MODE=oidc-bff`, public access to the dashboard
must go through Keycloak before showing internal portal pages. If a private
window can directly access paths such as `/edc-dashboard/home` without prior
authentication, it is considered a proxy or Ingress configuration deviation
and must be fixed before using the run as UI validation evidence.

Local preparation can be enabled with `PIONERA_EDC_LOCAL_IMAGES_MODE=auto` or made strict with `PIONERA_EDC_LOCAL_IMAGES_MODE=required`. The default value is `auto` on the `local` topology and `disabled` on VM topologies. On `vm-single` and `vm-distributed`, the recommended path is to define explicit EDC connector image overrides before deploying.

The EDC dashboard is optional and serves as visual support for UI validation. API validations with Newman remain the main end-to-end validation mechanism.

EDC's `Level 5` reuses the shared components registered in
`deployers/shared/components/`, including `ontology-hub`, `ai-model-hub`, and
`semantic-virtualization` when they are enabled. For AI Model Hub, the same
`model-server` and asset seeding flow used by INESData is parameterized for
EDC. The `model-server` deployment is independent of the component's
deployment: it is only managed when `AI_MODEL_HUB_MODEL_SERVER_ENABLED=true`;
in that case, standard `HttpData` assets, policies, and contracts are created,
and DSP negotiations between the configured pairs are validated.

In the interactive menu, the EDC adapter includes a prior hostname check
before running levels `3-6` on the `local` topology. If entries are missing,
the user can apply only the missing ones before continuing; if they don't
confirm, the level is cancelled to avoid less clear failures later on.

## Adding an Adapter

To add another adapter:

1. Create `adapters/<name>/`.
2. Create `deployers/<name>/`.
3. Implement a deployer with the shared contract.
4. Register the adapter and deployer in `main.py`.
5. Define the default validation profile.
6. Add focused unit tests.
7. Add documentation only when the behavior is stable.
