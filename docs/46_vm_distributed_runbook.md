# vm-distributed Operations Runbook

## Goal

This guide turns the experience of distributed deployment into a repeatable,
verifiable procedure that can be shared without exposing sensitive
environment data.

The goal is not for the person to remember every detail of networking, SSH,
kubeconfig, DNS, Ingress, and validation. The goal is for the framework to
guide them along a clear, verifiable path with low cognitive load.

## Operating Principles

| Principle | Practical rule |
| --- | --- |
| Explicit configuration | Real values live in local `.config` files or environment variables, not in `docs/` or Git |
| Access security | SSH authentication uses a key dedicated to the environment, never a shared private key |
| Preflight before deploying | Network, SSH, kubeconfig, HTTP, and Ingress are checked first; then the levels are run |
| Auditable evidence | Each level must leave verifiable outputs and results under `experiments/` when applicable |
| Consistent topologies | `local`, `vm-single`, and `vm-distributed` share level names, namespaces, and adapter contracts |
| Additive changes when appropriate | Additive reconciliation is used to add connectors to a live dataspace |

## vm-distributed Roles

`vm-distributed` splits the environment into roles. The implementation
supports a common Kubernetes cluster with several nodes and also k3s clusters
controlled by different kubeconfigs.

| Role | Responsibility |
| --- | --- |
| `common` | Common services: Keycloak, Vault, PostgreSQL, MinIO, and base services |
| `provider` | Connectors on the provider side of the validation environment |
| `consumer` | Connectors on the consumer side of the validation environment |
| `components` | Shared components such as Ontology Hub, AI Model Hub, and Semantic Virtualization |

The canonical namespaces stay stable:

| Namespace | Use |
| --- | --- |
| `common-srvs` | Common services |
| `core-control` | Dataspace services |
| `provider` | Connectors of the provider group |
| `consumer` | Connectors of the consumer group |
| `components` | Shared components |

## Flow from Scratch

The recommended flow for a new environment is to run the levels in order,
with checks between them.

1. Prepare the operator workstation's network.
2. Prepare SSH with a dedicated key.
3. Prepare a dedicated kubeconfig for the topology.
4. Configure `vm-distributed` with the assistant.
5. Run the static and remote preflight.
6. Run `Level 1`.
7. Run `Level 2`.
8. Run `Level 3`.
9. Run `Level 4`.
10. Run `Level 5`.
11. Run `Level 6`.
12. Store evidence and results.

## Network and SSH

On Windows with WSL, first confirm that WSL sees the same network or VPN as
Windows. If Windows reaches the bastion but WSL doesn't, enable mirrored
networking in `%UserProfile%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
firewall=true
```

Then restart WSL:

```powershell
wsl --shutdown
```

The SSH key must be dedicated to the VM environment:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_<environment> -C "<environment>-<user>"
```

The preflight uses `BatchMode=yes`, so authentication must work without
asking for an interactive password:

```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519_<environment> -p <bastion-port> <user>@<bastion> hostname
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519_<environment> -J <user>@<bastion>:<bastion-port> <user>@<vm-common> hostname
```

## Dedicated Kubeconfig

To avoid mixing `local`, `vm-single`, and `vm-distributed`, use a dedicated
kubeconfig for this topology.

If the k3s API is only reachable from the remote VM, open an SSH tunnel:

```bash
ssh -N -L 127.0.0.1:<local-port>:127.0.0.1:6443 -J <user>@<bastion>:<bastion-port> <user>@<vm-common>
```

The local kubeconfig must point to that port:

```yaml
server: https://127.0.0.1:<local-port>
```

Check:

```bash
kubectl --kubeconfig <vm-distributed-kubeconfig-path> get nodes
kubectl --kubeconfig <vm-distributed-kubeconfig-path> get ns
```

## Configuration with the Assistant

Open the menu:

```bash
python3 main.py menu
```

Then:

```text
T - Select topology
3 - vm-distributed
W - vm-distributed assistant
```

Use:

| Option | Use |
| --- | --- |
| `1` | Create or update local `.config` files |
| `2` | View the topology and static preflight |
| `3` | Preview deployment and hosts |
| `4` | Run the non-destructive SSH/HTTP preflight |

If you don't know which value to put in an assistant field, type `?`.

## Public Access

The recommended pattern is to expose each VM through a public domain or
stable URL managed by the organization.

Conceptual example:

| Role | Public URL |
| --- | --- |
| `common` | `https://org1.<domain>` |
| `provider` | `https://org2.<domain>` |
| `consumer` | `https://org3.<domain>` |

On the common VM, services coexist by path:

```ini
VM_COMMON_PUBLIC_URL=https://org1.<common-domain>
VM_PROVIDER_PUBLIC_URL=https://org2.<dataspace-domain>
VM_CONSUMER_PUBLIC_URL=https://org3.<dataspace-domain>
KEYCLOAK_FRONTEND_URL=https://org1.<common-domain>/auth
MINIO_CONSOLE_PUBLIC_URL=https://org1.<common-domain>/s3-console
COMPONENTS_PUBLIC_BASE_URL=https://org1.<common-domain>
COMPONENTS_PUBLIC_PATH_REWRITE=true
```

If these URLs are left empty, the framework infers default values from
`DOMAIN_BASE` and `DS_DOMAIN_BASE`: `org1` for common services, `org2` for the
provider connector, and `org3` for the consumer connector. Those names are a
convention, not an obligation.

The rule of thumb is:

1. An explicitly configured full URL takes priority.
2. If there is no explicit URL, the `org1/org2/org3` convention is used.
3. If an organization uses other domains, subdomains, or proxy paths, it must
   configure the corresponding full URL.

With that configuration, the components are published as:

| Component | Public URL |
| --- | --- |
| `ontology-hub` | `https://org1.<common-domain>/ontology-hub` |
| `ai-model-hub` | `https://org1.<common-domain>/ai-model-hub` |
| `semantic-virtualization` | `https://org1.<common-domain>/semantic-virtualization` |

The Semantic Virtualization graphical editor is based on Streamlit and uses
WebSocket. In the upstream (PIONERA) reference distributed environment it is published through a
dedicated domain to avoid the usual reverse-proxy problems with subpaths:

```ini
SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL=https://streamlit.pionera.linkeddata.es
SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_EXPOSURE_MODE=host-port
SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST_PORT=5678
```

With that pattern, the internal service still lives on the common services
and components VM, but public access to the editor doesn't depend on
`/semantic-virtualization-editor`.

If a frontend loads HTML but fails to load JavaScript, CSS, or internal
paths, the problem is usually the component's base path. In that case,
configure the image's base path or use dedicated domains for that component.

Example with custom domains per service:

```ini
KEYCLOAK_FRONTEND_URL=https://login.<common-domain>
MINIO_CONSOLE_PUBLIC_URL=https://objects.<common-domain>
ONTOLOGY_HUB_PUBLIC_URL=https://ontologies.<components-domain>
AI_MODEL_HUB_PUBLIC_URL=https://models.<components-domain>
SEMANTIC_VIRTUALIZATION_PUBLIC_URL=https://virtualization.<components-domain>
```

## Ingress TLS and Truststores

On VM topologies, the framework reconciles Ingress TLS for the configured
public hostnames. The reconciliation creates or updates the shared TLS secret
used by the Ingress and, when the adapter requires it, prepares a connector
truststore in the `common-tls-cacerts` secret.

This adjustment is needed because the connectors make DSP calls and internal
HTTP calls to public or semi-public URLs of the environment itself. If the
Java truststore is replaced by one that only contains the internal CA, the
connector can stop trusting public certificates, for example certificates
issued by a CA recognized by the system. For that reason, the truststore
generated by the framework starts from Java's base `cacerts` and adds the
Ingress's internal CA, instead of completely replacing the set of CAs.

The operating rule is:

- `local` uses the local development path and doesn't enable this VM TLS
  reconciliation by default;
- `vm-single` and `vm-distributed` enable it by default, unless the local
  configuration says otherwise;
- the generated secrets, certificates, and truststores are environment
  artifacts and must not be versioned;
- if the connectors show `PKIX`, `certificate_unknown`, or timeout errors
  during DSP over HTTPS, check the Ingress TLS reconciliation and the
  `common-tls-cacerts` secret first.

## SSH Access and Idempotency

The distributed topology must use a key dedicated to the validation
environment, not a reused personal key. The private key stays on the host
that runs the framework, and only the public key is installed on the target
VMs.

Conceptual configuration:

```ini
SSH_ACCESS_MODE=direct
SSH_IDENTITY_FILE=<path-to-dedicated-key>
VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE=manual
VM_DISTRIBUTED_EXECUTION_HOST=external
VM_COMMON_SSH_HOST=<common-host>
VM_COMMON_SSH_USER=<operator-user>
VM_PROVIDER_SSH_HOST=<provider-host>
VM_PROVIDER_SSH_USER=<operator-user>
VM_CONSUMER_SSH_HOST=<consumer-host>
VM_CONSUMER_SSH_USER=<operator-user>
```

The SSH bootstrap must be idempotent:

- it doesn't regenerate a key if one already exists;
- it doesn't duplicate `authorized_keys` entries;
- it checks access with `BatchMode=yes`;
- it doesn't store private keys, passwords, or kubeconfigs in versioned
  files.

Before touching real VMs, check that the framework knows how to create a new
SSH key from scratch:

```bash
python3 main.py inesdata ssh-access self-test --topology vm-distributed
```

This test creates a temporary key, checks that the public key matches the
private one, validates safe permissions, repeats the creation to check
idempotency, and deletes the temporary files. It doesn't use your current
keys, doesn't connect to the VMs, and doesn't modify `authorized_keys`.

To review the plan without touching the VMs:

```bash
python3 main.py inesdata ssh-access plan --topology vm-distributed
```

The command no longer shows a long list of commands as its first option. It
shows the recommended interactive guide and explains why it exists: the SSH
preparation asks for passwords only once, while the key isn't installed yet,
and must be run from the right machine. The interactive guide walks the
operator step by step, asks before running each command, and never stores
passwords.

With `VM_DISTRIBUTED_EXECUTION_HOST=external`, run the guide from the same
terminal where you run the framework, for example WSL or the operations
workstation. It is not run inside the target VMs. With
`VM_DISTRIBUTED_EXECUTION_HOST=common-services`, run it from the common
services VM once the remote workspace is prepared.

To start the interactive guide:

```bash
python3 main.py inesdata ssh-access assistant --topology vm-distributed
```

Use it by reading each step, answering yes only when you are ready, and typing
passwords only when the SSH prompt asks for them. After the public key is
installed, the check and the following deployments must work without asking
for a password.

The guide automatically detects whether it is running from WSL, from the
common services VM, or from another operations terminal. The SSH path is not
asked for: it is read from the configuration files. If the configuration
defines a bastion, the guide uses it; if it defines a direct connection, it
uses a direct connection. It only asks about the location when what it
detects doesn't match the configuration, and it shows the question progress
as `Question 1/N`.

Before the first question, the guide only shows a compact summary: topology,
dedicated key, detected location, configured SSH path, and number of
questions.

If the guide detects that it is running inside a configured VM and the SSH
path uses a bastion, it doesn't continue silently. It flags it as a situation
to review, because the VM would have to reach the bastion and the bastion
would have to be able to come back to the target VMs.

To get the full plan in JSON, useful for automation or auditing:

```bash
python3 main.py inesdata ssh-access plan --topology vm-distributed --json
```

To explicitly reconcile the dedicated SSH access:

```bash
python3 main.py inesdata ssh-access reconcile --topology vm-distributed
```

`reconcile` creates or reuses the local dedicated key and adds its public key
to `authorized_keys` on the configured VMs. If there is no approved initial
access path, the command fails without insisting and shows the minimum next
step.

When the framework runs from the common VM, use:

```ini
VM_DISTRIBUTED_EXECUTION_HOST=common-services
VM_COMMON_REMOTE_WORKDIR=<remote-framework-path>
```

In that mode, the common VM acts as the execution host and must be able to
reach the VMs where the connectors live over SSH.

## Running the Levels

| Level | What it validates or deploys | Checkpoint |
| --- | --- | --- |
| `Level 1` | Cluster access, runtime, and Ingress | `kubectl get nodes` and a successful preflight |
| `Level 2` | Common services | `common-srvs` pods ready |
| `Level 3` | Dataspace and core services | `core-control` pods ready |
| `Level 4` | Connectors | Connectors in `provider` and `consumer` ready |
| `Level 5` | Components | Components in `components` and public paths ready |
| `Level 6` | Validation | Reports under `experiments/` |

For a new installation, use full reconciliation in Level 4:

```ini
LEVEL4_CONNECTOR_RECONCILIATION_MODE=full
```

To add connectors to a live dataspace, use additive reconciliation.

## Adding Connectors to an Existing Dataspace

This is the recommended flow for the case requested by the supervisor: adding
connectors to data spaces that already have connectors deployed.

The guided way is to use the main menu:

```bash
python3 main.py menu
```

Then select:

```text
J - Add connector to existing dataspace
```

The assistant asks for the connector's short name, its placement, and the
optional validation pair. Before writing files, it shows a plan. If the
operator confirms, it updates the inventory, switches `Level 4` to additive
mode, and offers to run `Level 4` right away.

The equivalent result in configuration is:

Example:

```ini
DS_1_CONNECTORS=org2,org3,partnera
DS_1_CONNECTOR_NAMESPACES=org2:provider,org3:consumer,partnera:provider
DS_1_VALIDATION_PAIRS=org2>org3,partnera>org2
LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive
```

Also review the plan manually with:

```bash
python3 main.py inesdata deploy --topology vm-distributed --dry-run
```

In additive mode, healthy connectors are preserved and the framework adds the
missing ones.

To generate clean-installation evidence, use `full` again in a controlled
environment or in a full rebuild.

## Components and Development

`Level 5` deploys shared components. On `vm-distributed`, the component
images must reach the remote Kubernetes runtime. There are two recommended
strategies:

| Strategy | When to use it |
| --- | --- |
| Team registry | Preferred path for CI/CD and shared deployments |
| Remote import into k3s | Useful for controlled validation from a workstation |

Remote import is enabled with:

```ini
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT=true
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND=sudo -n k3s ctr -n k8s.io images import
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY=false
SSH_IDENTITY_FILE=<path-to-dedicated-key>
```

The `sudo -n` option avoids waiting for an interactive password. If that
check fails, use a registry reachable by the cluster or configure a
non-interactive, scoped permission to import images into k3s.

For a manual validation from a real terminal, enable interactive mode:

```ini
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE=true
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY=true
```

In that mode the framework allocates an SSH pseudo-terminal and lets you type
the `sudo` password when the image is imported. This mode is useful to
unblock a manual validation, but it must not be used as the basis for CI/CD.

To develop components, the desired contract is:

- image configurable through `.config`;
- Helm chart with versionable values;
- public endpoints declared through configuration;
- Level 6 tests registered under `validation/components/`;
- evidence generated under `experiments/`.

## Experiments with Large Workloads

For experiments with large datasets or models, record beforehand:

- estimated size of the datasets;
- estimated size of the models;
- number of runs;
- whether GPU or CPU is required;
- whether the results must be kept after the validation.

Before running Level 5 or Level 6 with large workloads, check the disk
capacity:

```bash
df -h
docker system df
kubectl --kubeconfig <kubeconfig> get pvc -A
```

## Evidence for Auditing

For an auditable run, keep:

| Evidence | Recommended location |
| --- | --- |
| Configuration without secrets | sanitized operational annex |
| Hosts and URL plan | output of `hosts --dry-run` |
| Static preflight | output of `W -> 2` |
| Remote preflight | output of `W -> 4` |
| Kubernetes state per level | outputs of `kubectl get` |
| Level results | console log |
| Validation results | `experiments/<experiment>/` |
| Incidents and mitigations | sanitized handover document |

Don't store passwords, tokens, private keys, cookies, or real kubeconfigs in
versioned documentation.

## Priority Automation

To reduce cognitive load, the following improvements should be prioritized:

| Improvement | Benefit |
| --- | --- |
| Guided dedicated SSH key generator | Avoids reusing personal keys and reduces permission errors |
| SSH tunnel manager for kubeconfig | Avoids opening manual terminals for the k3s API |
| Dedicated kubeconfig assistant | Separates `local`, `vm-single`, and `vm-distributed` |
| Disk and PVC preflight | Detects lack of capacity before Level 5 and Level 6 |
| "Add connector" flow | Changes config, previews, and runs an additive Level 4 in a guided way |
| Evidence package | Generates a sanitized summary for auditing |
| Public path validator | Tests Keycloak, MinIO, connectors, and components from the operator workstation |
| Component template | Makes it easier to add charts, images, configuration, and tests |

## Short Checklist

Before deploying:

```text
[ ] WSL or the operator workstation sees the required VPN/network
[ ] SSH through the bastion works with BatchMode=yes
[ ] The dedicated kubeconfig responds to kubectl get nodes
[ ] W -> 2 doesn't show missing values
[ ] W -> 3 shows the expected hosts and namespaces
[ ] W -> 4 passes or clearly documents which HTTP check doesn't apply
[ ] There is enough disk capacity for components, datasets, and models
[ ] Level 4 uses full for a new installation or additive to add connectors
[ ] The expected public URLs are defined in the topology
[ ] Level 6 will generate evidence under experiments/
```
