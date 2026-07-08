# STICS Dataspace — New Dataspace Setup Guide

## Purpose

This guide explains, end to end, how to stand up a brand new STICS-style
dataspace from nothing: which VMs are needed, what runs where, and how to
bring up the shared common services (Keycloak, Vault, MinIO, PostgreSQL, and
the registration service) using the framework itself.

Adding connectors to the dataspace once it exists is a separate, mostly
manual process, covered in
[`deployment-guide.md`](./deployment-guide.md). This guide only covers the
part that comes before that: the dataspace's shared infrastructure.

## Architecture Overview

- One VM acts as **common services**. It runs a full k3s cluster hosting
  Keycloak, Vault, MinIO, PostgreSQL, and the INESData registration service.
  This is the only part of the stack the framework manages inside
  Kubernetes.
- Every **connector** runs outside Kubernetes, as a plain Docker container,
  on whichever VM is designated for it — the common-services VM itself, or a
  separate one. See `deployment-guide.md` for that part.
- Every VM needs a public hostname resolving to it, either directly or via a
  shared entry point that forwards traffic to it, and every hostname in the
  dataspace is covered by one shared, self-signed TLS certificate.

Nothing about this architecture is STICS-specific — it is the framework's
own `vm-distributed` topology with the `edc` adapter. What is specific to
this project is how connectors are then added on top of it manually, rather
than through the framework's own (currently unreliable) Kubernetes-managed
connector deployment.

## Step 1: VM Requirements

### Common-services VM

- Ubuntu 22.04/24.04 LTS (or an equivalent Linux distribution), reachable
  over SSH with sudo access.
- Enough resources for k3s plus five services (Keycloak, Vault, MinIO,
  PostgreSQL, registration service). 8 vCPU / 16 GB RAM is a realistic
  baseline — the common-services VM used for this project runs comfortably
  within that.
- A public hostname (or several) resolving to this VM's public IP, for
  Keycloak, the MinIO API, the MinIO console, and the registration service.
- Docker, if this VM will also host a connector (see `deployment-guide.md`).

### Each connector VM

May or may not be the same machine as the common-services VM.

- Ubuntu (or equivalent), reachable over SSH.
- Docker and Docker Compose.
- A local PostgreSQL instance, unless it is the common-services VM, whose
  shared instance can also host connector databases (see
  `deployment-guide.md`, Step 2).
- Its own public hostname.

### DNS, in General

Every public hostname used anywhere in the dataspace (Keycloak, MinIO,
registration service, every connector, every connector's web interface) must
resolve, via real DNS, to the public IP of the VM that actually serves it —
or to a shared entry point (a gateway VM, or an external reverse proxy) that
forwards traffic to the right machine. Confirm this for every hostname
before assuming it works:

```bash
nslookup <hostname> 8.8.8.8
```

If a hostname resolves to a machine other than the one you expect, do not
proceed until that is resolved — building the wrong Ingress in the wrong
cluster is a common and confusing mistake (see `deployment-guide.md`, Step
10, for how to confirm which cluster a hostname actually reaches).

## Step 2: Prepare the Framework and Its Configuration

On the common-services VM (or the operator workstation, if operating
remotely over SSH):

```bash
git clone https://github.com/ProyectoPIONERA/Validation-Environment.git
cd Validation-Environment
git submodule update --init --recursive
bash scripts/bootstrap_framework.sh
source .venv/bin/activate
```

Edit the topology configuration for `vm-distributed`,
`deployers/infrastructure/topologies/vm-distributed.config` (copy it from
its `.example` template the first time). At minimum:

```ini
VM_EXTERNAL_IP=<common-services VM public/private IP>
VM_COMMON_IP=<common-services VM IP>
VM_SSH_USER=<ssh user used to reach every VM>
INGRESS_EXTERNAL_IP=<common-services VM IP>
K3S_INSTALL_EXEC=--disable=traefik
K3S_INGRESS_CONTROLLER=ingress-nginx
KEYCLOAK_FRONTEND_URL=https://<your-keycloak-hostname>
KEYCLOAK_PUBLIC_URL=https://<your-keycloak-hostname>
MINIO_API_PUBLIC_URL=https://<your-minio-api-hostname>
MINIO_CONSOLE_PUBLIC_URL=https://<your-minio-console-hostname>
```

`K3S_INSTALL_EXEC=--disable=traefik` and `K3S_INGRESS_CONTROLLER=ingress-nginx`
are this project's convention: every Ingress created afterwards, including
the manual bridges described in `deployment-guide.md`, assumes
`ingress-nginx`, not the k3s-default Traefik.

The dataspace's own name and namespace are set on top of this, either in
`deployers/edc/deployer.config` or as `PIONERA_*` environment variable
overrides at run time — the latter is convenient for keeping a
project-specific name out of a shared config file:

```bash
export PIONERA_DS_1_NAME=stics
export PIONERA_DS_1_NAMESPACE=stics
```

## Step 3: Deploy the Cluster and Common Services

Open the guided menu:

```bash
python3 main.py menu --topology vm-distributed
```

Select the `edc` adapter, then run, in order:

- **Level 1 — Setup Cluster**: installs k3s (with the ingress controller
  configured above) on the common-services VM.
- **Level 2 — Deploy Common Services**: deploys Keycloak, Vault, MinIO,
  PostgreSQL, and the registration service into that cluster.
- **Level 3 — Deploy Dataspace**: registers the dataspace itself
  (`PIONERA_DS_1_NAME`) against the registration service.

Do not run **Level 4 — Deploy Connectors** through the menu for this
project — connectors are added manually afterwards, following
`deployment-guide.md`. Level 4's own Kubernetes-managed connector path is
what this project moved away from.

After Level 1, confirm the cluster is healthy before continuing:

```bash
kubectl get nodes
kubectl get ingress -A
```

After Level 2, confirm the common services are reachable at their public
hostnames:

```bash
curl -k https://<your-keycloak-hostname>/realms/master
curl -k https://<your-minio-api-hostname>
```

## Step 4: Retrieve the Shared Secrets Needed Later

Deployment-guide.md's connector provisioning script and TLS reconciliation
both need two pieces of information generated during Level 1/2. Keep them
at hand:

```bash
# MinIO root credentials (used for policy/bucket administration)
kubectl get secret common-srvs-minio -n common-srvs -o jsonpath='{.data.rootUser}' | base64 -d; echo
kubectl get secret common-srvs-minio -n common-srvs -o jsonpath='{.data.rootPassword}' | base64 -d; echo

# The shared TLS truststore, needed by every connector (see deployment-guide.md, Step 7)
kubectl -n core-control get secret common-tls-cacerts -o jsonpath='{.data.cacerts\.jks}' | base64 -d > cacerts.jks
```

(Namespace names above match this project's `role-aligned` layout; adjust if
a different `PIONERA_NAMESPACE_PROFILE` was used.)

## Step 5: Add the First Connector

The dataspace now has identity, storage, and a database backend, but no
connectors and nothing to browse. Follow
[`deployment-guide.md`](./deployment-guide.md) from Step 0 onward to add the
first one — the exact same process applies whether this is the very first
connector in a brand new dataspace or the fifth one in an existing one.

## Troubleshooting Reference

| Symptom | Meaning | Resolution |
| --- | --- | --- |
| `kubectl get nodes` shows the node `NotReady` after Level 1 | k3s did not finish initializing, or ran out of resources | Re-check the VM's CPU/RAM against Step 1's baseline; re-run Level 1 |
| Level 2 succeeds but a public hostname (Keycloak, MinIO) does not respond | DNS for that hostname does not point at this VM, or the Ingress TLS secret does not yet cover it | `nslookup` the hostname; confirm the shared certificate's SAN list includes it (see `deployment-guide.md`, Step 11) |
| `python3 main.py menu` asks for a topology every time | `--topology vm-distributed` was not passed and no topology was pre-selected | Pass `--topology vm-distributed` explicitly, or select it when prompted |
| Level 4 (Kubernetes-managed connectors) fails or produces a broken/`CrashLoopBackOff` pod | This is the exact reason this project uses the manual Docker Compose process instead | Do not debug Level 4 for this project — go directly to `deployment-guide.md` |
| A VM inherited from elsewhere already has k3s installed with its default Traefik ingress, instead of `ingress-nginx` | `K3S_INSTALL_EXEC=--disable=traefik` above only takes effect on a fresh k3s install | Traefik was found to handle dynamic TLS certificate updates unreliably; migrate it to `ingress-nginx` before relying on TLS on that VM — see `deployment-guide.md`, Step 10.1, for the exact (no-root-required) migration steps |

---

*Questions or suggested improvements to this guide are welcome — please open
an issue or a pull request against this document.*
