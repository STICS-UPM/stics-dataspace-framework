# Getting Started

## Requirements

The recommended way to operate the framework from a workstation is Windows
with WSL. In that mode, WSL runs `main.py`, Docker Desktop provides the
container engine for `local`, and the framework manages the SSH access,
kubeconfigs, and tunnels required by `vm-single` and `vm-distributed`.

The framework also supports running directly inside a VM when the operator
installs the repository there, but the main documented operation and
debugging path for workstations is WSL on Windows.

For local execution, the framework expects:

- Python 3.10 or later;
- Git;
- Docker;
- Minikube;
- Helm;
- `kubectl`;
- Node.js and `npm`;
- a PostgreSQL client;
- permissions to update the system `hosts` file when hosts synchronization is enabled.

The local topology uses Minikube on the development machine. The `vm-single`
topology uses k3s managed inside the VM, and `Level 1` prepares it to keep a
reproducible configuration. `vm-distributed` uses parameterizable
configuration for VMs, SSH, kubeconfig, DNS/Ingress, and public URLs.

## Closure Scope

If the goal is to generate closure evidence, use this reading:

| Adapter | Recommended path |
| --- | --- |
| `inesdata` | `local`, `vm-single`, or `vm-distributed`, depending on the environment you want to evidence |
| `edc` | `vm-distributed` |

EDC keeps implemented paths on `local` and `vm-single`, but `local` must be
revalidated after the recent topology reconciliation, and `vm-single` has not
been officially validated since that reconciliation.

## Local View

The following diagram summarizes the local validation environment:

![PIONERA local validation environment](<./pionera_local_validation_environment.png>)

## Bootstrap

From the repository root:

```bash
node --version
npm --version
bash scripts/bootstrap_framework.sh
```

`npm` is mandatory because the framework installs Newman and Playwright for
the functional validations. Java 17+ is mandatory to build the local EDC/INESData
connector images that are then loaded into Minikube. On a fresh Ubuntu VM,
the bootstrap installs Node.js with `npm` and OpenJDK 17 automatically through
`apt-get` when they are missing. If you use `--without-system-deps` or your
environment doesn't allow installing system packages, install them before the
bootstrap:

```bash
sudo apt-get update
sudo apt-get install -y nodejs npm openjdk-17-jdk
```

The bootstrap requires Python `3.10+`. If `python3` points to an older
version but the machine already has another compatible version installed, the
script automatically uses the first available option among `python3.10`,
`python3.11`, `python3.12`, and `python3.13`. You can also force it
explicitly with:

```bash
PIONERA_PYTHON_BIN=python3.11 bash scripts/bootstrap_framework.sh
```

On Linux/WSL, the bootstrap installs Playwright with its system dependencies
so that UI validations don't fail when starting the browser. In environments
where system packages can't be installed, use
`bash scripts/bootstrap_framework.sh --without-system-deps`.

The bootstrap also automatically creates the local `deployer.config` files and
the `deployers/infrastructure/topologies/*.config` overlays from their
`.example` files when they don't exist yet. If they already exist, it reuses
them and doesn't overwrite them.

Then activate the root Python environment:

```bash
source .venv/bin/activate
```

For a basic local run you don't have to create configuration by hand. Review
the generated configuration only if you need to adjust credentials, domains,
dataspaces, or components:

```text
deployers/infrastructure/deployer.config
deployers/infrastructure/topologies/local.config
deployers/infrastructure/topologies/vm-single.config
deployers/infrastructure/topologies/vm-distributed.config
deployers/inesdata/deployer.config
deployers/edc/deployer.config
```

Finally, open the guided menu:

```bash
python3 main.py menu
```

## Configuration

The common infrastructure configuration lives in:

```text
deployers/infrastructure/deployer.config
```

The adapter-specific configuration lives in:

```text
deployers/inesdata/deployer.config
deployers/edc/deployer.config
```

Use the `.example` files as templates when they exist. The local
`deployer.config` and `deployers/infrastructure/topologies/*.config` files
contain environment-specific configuration, including credentials, paths, or
addresses when the deployment requires them. They must not be pushed to the
repository.

The local topology has its own overlay in:

```text
deployers/infrastructure/topologies/local.config
```

This file is local and is created from `local.config.example` during the
bootstrap if it doesn't exist yet. It must not be versioned. The reference
local configuration doesn't include credentials, tokens, user paths, or
private IPs: it uses `localhost`, development hostnames, the Docker driver,
and Minikube resources.

Recommended local values for one adapter at a time:

```ini
PG_HOST=localhost
VT_URL=http://localhost:8200
LOCAL_HOSTS_ADDRESS=
LOCAL_INGRESS_EXTERNAL_IP=
LOCAL_RESOURCE_PROFILE=single-adapter
MINIKUBE_DRIVER=docker
MINIKUBE_CPUS=10
MINIKUBE_MEMORY=14336
MINIKUBE_PROFILE=minikube
```

Before running `Level 1`, make sure Docker Desktop can allocate at least that
much memory. If your Docker Desktop has less headroom, reduce
`MINIKUBE_MEMORY` or use a temporary override, for example
`PIONERA_MINIKUBE_MEMORY=12288`. To validate `inesdata` and `edc` coexisting
on the same local topology, switch to `LOCAL_RESOURCE_PROFILE=coexistence`;
the recommended baseline is still `10 CPU / 18432 MB`. If Docker can't
allocate it, validate one adapter at a time or use a suitable VM topology.
For `edc` closure evidence, use `vm-distributed`. In stable mode, `Level 1`
warns if Docker only supports one local adapter, and `Level 3/4/5` block the
installation of the second adapter if another one is already active with
effective memory below that baseline. In an interactive terminal, that block
opens a controlled adapter switch: the framework shows the managed namespaces
and runtime artifacts it is going to delete, preserves `common-srvs`, and only
continues if you confirm the exact text it shows. In non-interactive runs, use
the `PIONERA_LOCAL_ADAPTER_SWITCH_CONFIRM` variable with the value
`SWITCH TO EDC` or `SWITCH TO INESDATA`, depending on the target adapter.
`Level 6` keeps the same guard so results are not contaminated.

## Adapter Coexistence

`inesdata` and `edc` reuse the common services in `common-srvs` when both
adapters are tested on the same local cluster.

The important restriction is that each adapter must use an isolated
dataspace:

```text
inesdata -> DS_1_NAME=pionera, DS_1_NAMESPACE=core-control
            DS_1_PROVIDER_NAMESPACE=provider
            DS_1_CONSUMER_NAMESPACE=consumer
            COMPONENTS_NAMESPACE=components

edc      -> DS_1_NAME=pionera-edc, DS_1_NAMESPACE=edc-control
            DS_1_PROVIDER_NAMESPACE=edc-provider
            DS_1_CONSUMER_NAMESPACE=edc-consumer
```

Don't reuse the same `DS_1_NAME` or `DS_1_NAMESPACE` for two different
adapters on the same cluster. The problem would not be sharing PostgreSQL,
Keycloak, MinIO, or Vault, but colliding on namespaces, registration-service,
databases, users, and artifacts generated by `Level 3`.

## Hosts

The framework plans or applies `hosts` entries for the selected adapter and
topology:

```bash
python3 main.py inesdata hosts --topology local --dry-run
python3 main.py edc hosts --topology local --dry-run
```

To apply entries, state the target file explicitly:

```bash
PIONERA_SYNC_HOSTS=true \
PIONERA_HOSTS_FILE=/etc/hosts \
python3 main.py edc hosts --topology local
```

From WSL, the Windows `hosts` file is usually at:

```text
/mnt/c/Windows/System32/drivers/etc/hosts
```

Use the Windows `hosts` file only for local topologies. In distributed topologies with real domains, such as `vm-distributed`, resolution must come from DNS/VPN and the configured public URLs.

Synchronization is idempotent: if an entry already exists outside the managed blocks, it is skipped instead of duplicated.

## Menu Levels

The menu exposes six levels:

- `Level 1`: prepares the cluster.
- `Level 2`: deploys common services.
- `Level 3`: deploys the dataspace.
- `Level 4`: deploys connectors.
- `Level 5`: deploys optional components.
- `Level 6`: runs validations.

For a local deployment from scratch, run the levels sequentially from `1` to `6`, or use menu option `0`.

In an interactive terminal, `python3 main.py` first asks for the active
topology and then shows the menu. Use `python3 main.py menu --topology local`
or `python3 main.py menu --topology vm-single` if you want to go straight in.

The full menu reference is in [Menu reference](./33_menu_reference.md).

## Minikube Tunnel

In full local deployments, keep `minikube tunnel` open so services are
reachable through the ingress:

```bash
minikube tunnel
```

Leave it running in another terminal during deployment and validation.

Functional validations must use the local hostnames published by the
Ingress. The framework reserves `port-forward` for internal checks or
development diagnostics; it doesn't use it as a replacement for the normal
browser or API path.

For PostgreSQL, the cluster service still uses port `5432`. The framework
uses `PG_PORT=5432` as the preferred local port. If that port is taken by an
old framework `kubectl port-forward`, it frees and recreates it. If it
belongs to Windows, WSL, or another local environment, the framework fails
with a diagnostic and doesn't terminate external processes automatically.
