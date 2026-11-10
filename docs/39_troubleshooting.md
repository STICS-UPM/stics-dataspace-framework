# Troubleshooting

## Windows Reaches the Bastion but WSL Doesn't

On the `vm-distributed` topology, a WSL terminal may not correctly inherit
Windows' connectivity to the VPN, corporate network, or lab network. The
typical symptom is that `Test-NetConnection` works in PowerShell, but in WSL
DNS resolution or the TCP connection to the bastion fails.

Check from Windows first:

```powershell
Test-NetConnection <bastion-host> -Port <bastion-port>
```

Then check from WSL:

```bash
getent hosts <bastion-host>
nc -vz <bastion-host> <bastion-port>
```

If Windows works and WSL fails, enable mirrored networking in
`%UserProfile%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
firewall=true
```

Restart WSL from PowerShell:

```powershell
wsl --shutdown
```

When you open WSL again, repeat `getent` and `nc` before trying SSH. For
`vm-distributed`, use an SSH key dedicated to the VM environment; don't reuse
personal keys or shared private keys. The full guide is in
[External connector readiness](./45_external_connector_readiness.md#operación-desde-windows-y-wsl) (ES).

## Hosts Entries Don't Resolve

Preview the expected entries:

```bash
python3 main.py edc hosts --topology local --dry-run
```

Apply entries only with explicit synchronization:

```bash
PIONERA_SYNC_HOSTS=true \
PIONERA_HOSTS_FILE=/etc/hosts \
python3 main.py edc hosts --topology local
```

If an entry already exists, the hosts manager skips it instead of duplicating it.

## Minikube Services Are Not Reachable

In local deployments, keep this open in another terminal:

```bash
minikube tunnel
```

Also check:

```bash
kubectl get pods -A
kubectl get ingress -A
helm list -A
```

If the problem appears when launching `Level 6`, remember that the full
validation uses public hostnames by default. A one-off `port-forward` can help
with diagnosis, but it doesn't remove the need for the Ingress, `hosts`, and
`minikube tunnel` to actually work.

## Level 2 Shows `failed post-install`

On clean local installations, Helm can leave `common-srvs` in `failed` state
if a hook takes longer than the initial timeout, even though the pods end up
starting correctly a few seconds later.

`Level 2` first checks the real `common-srvs` services, configures Vault, and,
if the runtime is healthy but Helm is still `failed`, runs Helm again with
more headroom to reconcile the release to `deployed`. If the release still
fails after that second attempt, the level fails because the Helm state is no
longer reliable enough to continue with `Level 3`.

## Connectors Only Work with Port-forward

Locally, the correct result is for connectors to be reachable through their
public Ingress hostname, for example:

```text
http://conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm/inesdata-connector-interface
http://conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm/edc-dashboard/
```

If they only work with `kubectl port-forward`, check first:

- that `minikube tunnel` is open;
- that the `hosts` entries exist for the dataspace and its connectors;
- that the namespace's Ingress exists and has an address;
- that the connector's pods and endpoints are ready.

Useful commands:

```bash
python3 main.py inesdata hosts --topology local --dry-run
python3 main.py edc hosts --topology local --dry-run
kubectl get ingress -A
kubectl get endpoints -A
```

The connector `port-forward` fallback is disabled by default so as not to
hide real routing problems. Use it only as a temporary diagnostic:

```bash
PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK=true
```

## Keycloak Admin Authentication Fails

Check that:

- the common services are running;
- the Keycloak admin URL resolves;
- the credentials in `deployers/infrastructure/deployer.config` are correct;
- the `hosts` file contains the Keycloak entries;
- the local tunnel or ingress is available.

## Level 3 Fails with PostgreSQL `password authentication failed`

If `Level 3` tries to run `psql` with a placeholder password such as
`CHANGE_ME`, the local `deployers/infrastructure/deployer.config` file is not
aligned with the real `common-srvs` secrets.

Before creating the dataspace, `Level 3` syncs the local common credentials
from the PostgreSQL, Keycloak, and MinIO Kubernetes secrets. This makes it
possible to reuse already deployed common services from a clean copy of the
framework without recreating `common-srvs`.

The cluster's PostgreSQL service still uses port `5432`. If `localhost:5432`
is already taken by a PostgreSQL on the machine, the framework must not treat
it as the cluster's PostgreSQL or terminate it automatically. If the occupant
is an old `kubectl port-forward` of the framework itself, it frees it and
recreates it as `127.0.0.1:5432 -> common-srvs-postgresql:5432`. If the
occupant is external, the level fails with a diagnostic so the user can free
the port by hand.

## Level 3 Fails with `Timeout waiting for dataspace pods`

If the log shows that `registration-service` is `Running`, but the level fails
because there are old connectors in `Init`, `CrashLoopBackOff`, or another
unstable state, the problem is not the base dataspace. Those connectors belong
to `Level 4`.

`Level 3` must only validate the base dataspace pods, mainly
`registration-service`. Connectors are deployed, updated, and validated in
`Level 4`, so they must not block the recreation of a dataspace.

After a successful `Level 3`, run `Level 4` to deploy or update the connectors
of the active adapter.

## Vault Reports an Obsolete Token

If level 2 or level 4 reports that the Vault token is not valid for the
running Vault, it means that Vault's persistent state and the local artifact
`deployers/shared/common/init-keys-vault.json` don't match.

Don't retry level 4 in a loop. First recover the current Vault root token, if
it exists, or recreate the level 2 common services in a local environment so
the framework generates consistent keys again. Then run level 3 and level 4
again.

On the `local` topology, the framework tries to prevent this case by
automatically reconciling the shared artifact and `deployer.config` with any
local token that is valid against the running Vault. If no valid token
remains, EDC's `Level 4` can perform a controlled repair: it temporarily
moves the obsolete artifact, deletes `common-srvs`, runs `Level 2` again, runs
`Level 3` again, and retries `Level 4`. The temporary backup is deleted if the
repair succeeds and restored if it fails.

The framework asks for interactive confirmation before doing so. In
non-interactive runs it must be enabled explicitly:

```bash
PIONERA_LEVEL4_REPAIR_COMMON_SERVICES=true python3 main.py inesdata deploy --topology local
```

Don't enable this variable if you want to preserve the current state of
`common-srvs`; recreating the common services affects the adapters that share
that local cluster.

The framework must not copy tokens from the adapter's legacy runtimes or
overwrite `VT_TOKEN` with a token that hasn't been validated against the
running Vault. The canonical source is
`deployers/shared/common/init-keys-vault.json`.

In a healthy environment it should not be necessary to recreate `common-srvs`
on every deployment. If it happens again, check whether the same cluster was
run from two different copies of the framework, whether old PVCs were kept,
or whether `init-keys-vault.json` was copied from another environment.

## Level 4 Fails with Keycloak 415

If `Level 4` fails when creating connectors with a Keycloak `415` error
during the service account role mapping, check that you are using a framework
version that restores `Content-Type: application/json` after uploading the
connector's public certificate.

The typical symptom appears right after:

```text
Client certificate for <connector> synchronized
```

The fix is part of the INESData bootstrap and lets you recreate connectors
with certificates, scopes, and service account roles reproducibly.

## Kafka Transfer Is Skipped Because of an Old INESData Image

If `Level 6` shows `SKIP Kafka transfer` with the reason
`kafka_dataaddress_not_supported`, Kafka hasn't necessarily failed. That
result indicates that the broker and the logins worked, but the connector
runtime rejected assets with `DataAddress.type=Kafka`.

Check the deployed image:

```bash
kubectl get deploy -n provider -o wide
kubectl get deploy -n consumer -o wide
```

Locally, `Level 4` must prepare and deploy a local `inesdata-connector` image
compatible with Kafka. If you see an old remote image, run `Level 4` again or
force the strict behavior:

```bash
INESDATA_LOCAL_IMAGES_MODE=required python3 main.py inesdata deploy --topology local
```

On `vm-distributed`, don't assume that the chart's remote image has the same
content as the local image rebuilt from `sources/`. If the Kafka suite is
going to run in a distributed closure, set `INESDATA_CONNECTOR_IMAGE_NAME` and
`INESDATA_CONNECTOR_IMAGE_TAG` to a published image that includes
`data-plane-kafka` support, or explicitly enable remote image import during a
development session.

## Level 4 Fails While Preparing INESData Images

On the `local` topology, `Level 4` recompiles `inesdata-connector` and
`inesdata-connector-interface` before creating the connectors. If the log
fails at `Preparing artifacts for connector` with a `Gradle Worker Daemon`
error, the problem is in the local build before the deployment, not in Helm
or Kubernetes.

The framework runs Gradle conservatively by default:

```text
--no-daemon --no-parallel -Dorg.gradle.workers.max=1
```

If a development machine has more resources and you want to speed up the
build, you can override it with:

```bash
GRADLE_MAX_WORKERS=2 python3 main.py menu
```

## EDC Rejects the Default Image

On the `local` topology, Level 4 automatically prepares the local EDC
connector image when there are no explicit overrides. To do so it uses:

```text
adapters/edc/scripts/build_image.sh --apply
```

If you want to force a specific image, or if you are preparing a VM topology,
define explicit overrides:

```bash
PIONERA_EDC_CONNECTOR_IMAGE_NAME=validation-environment/edc-connector \
PIONERA_EDC_CONNECTOR_IMAGE_TAG=<tag> \
python3 main.py edc deploy --topology vm-distributed
```

This protection prevents deploying an unverified default image. If the
automatic preparation fails, check that Docker, Minikube, and the repository
under `adapters/edc/sources/connector` are available.

## EDC Level 4 Fails with Docker Credentials on WSL

On WSL with Docker Desktop, `~/.docker/config.json` can contain
`credsStore=desktop` or `credsStore=desktop.exe`. If that configuration is not
usable from the WSL terminal, EDC's `Level 4` can fail during the automatic
preparation of local images with a message similar to:

```text
ERROR [internal] load metadata for docker.io/library/python:3.12-alpine
error getting credentials - err: exit status 1
```

The failure happens before the Kubernetes deployment: Docker can't resolve
the credentials to download or inspect the base image. The framework
validates the WSL Docker configuration before building local EDC images and
automatically removes those problematic `credsStore` entries, keeping the
rest of the file. Then run `Level 4` again from the same menu.

## EDC Playwright Gets a 503 from NGINX

If all EDC UI tests fail with a login error and the screenshot shows:

```text
503 Service Temporarily Unavailable
nginx
```

it means the browser didn't reach Keycloak or the dashboard. Usually the
ingress exists, but the `*-dashboard` or `*-dashboard-proxy` services don't
have ready endpoints.

Check:

```bash
kubectl get pods -n <dataspace>
kubectl get endpoints -n <dataspace>
```

Locally, Level 4 automatically prepares the images:

```text
validation-environment/edc-dashboard:latest
validation-environment/edc-dashboard-proxy:latest
```

Level 6 checks the availability of those endpoints before launching
Playwright. If they are not ready, it stores the diagnostics in
`experiments/<experiment>/ui/edc/dashboard_readiness.json`.

## INESData Playwright Fails Before Opening the Portal

If `Level 6` fails before launching Playwright for `inesdata`, or if the
message says the portal is not ready, the problem is usually in the
connector's public path and not in the suite itself.

Check:

```bash
kubectl get pods -n <dataspace>
kubectl get endpoints -n <dataspace>
```

And check that the public path really responds:

```text
http://conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm/inesdata-connector-interface/
```

`Level 6` validates Keycloak, the `*-interface` services, and that public
path before launching Playwright. If it fails, it stores the diagnostics in:

```text
experiments/<experiment>/ui/inesdata/portal_readiness.json
```

## A VM Topology Requires an Address

`vm-single` needs a VM address:

```bash
PIONERA_VM_EXTERNAL_IP=192.0.2.10 \
python3 main.py inesdata hosts --topology vm-single --dry-run
```

If no address is configured, the CLI fails with a clear topology error.

## Playwright Fails Intermittently

Check:

- that the target URL resolves from the browser's environment;
- that the `hosts` entries exist;
- that the dashboard or portal is deployed;
- that the authentication mode matches the expected suite;
- that the report in `experiments/` contains screenshots, traces, or error details.

## Full Level 6 Fails Because of Unreachable Public Endpoints

If `Level 6` fails before Newman, Playwright, or Kafka with a message about
unreachable public hostnames, the framework is correctly detecting that the
local public layer is not ready.

Check:

- `minikube tunnel` active in another terminal;
- `hosts` entries synchronized;
- Ingress with an address and active backends;
- DNS/hosts resolution from the same machine that runs the framework.

Useful commands:

```bash
python3 main.py edc hosts --topology local --dry-run
kubectl get ingress -A
kubectl get endpoints -A
kubectl get endpointslices -A
```

In this situation, don't try to "force" a full `Level 6` through
`port-forward`. The framework's current decision is to keep `hostname` as the
normal path for full validation on `local`, consistently with an environment
closer to production.

## Auto-provisioned Kafka Is Not Ready in Time

If `Level 6` fails in the Kafka part with messages about `port-forward`,
`bootstrap server`, or `framework-kafka`, the problem usually comes from the
stabilization of the temporary broker in local Kubernetes.

Check:

```bash
kubectl get pods -n <dataspace>
kubectl get events -n <dataspace>
```

The framework validates the broker's internal listener and the external
listener used by `port-forward` before launching the Kafka suite. If it still
fails, check:

- that `minikube` hasn't gone into `NodeNotReady`;
- that `framework-kafka` and `framework-kafka-external` exist in the namespace;
- that `minikube tunnel` is still active if the local environment requires it;
- the `kafka_runtime_preparation.json` artifact inside the experiment.

If the local broker integrated in Kubernetes is still unstable on `local`, you
can try the opt-in variant:

```bash
PIONERA_KAFKA_PROVISIONER=kubernetes-split-kraft python3 main.py inesdata validate --topology local
```

This variant keeps Kafka inside Kubernetes, but separates `controller` and
`broker` to reduce flakes of the local provisioner.

When the problem is not in the broker but in local HTTP access to Keycloak or
the management APIs during the Kafka suite, the framework can also use an
opt-in HTTP fallback:

```bash
PIONERA_LEVEL6_LOCAL_HTTP_PORT_FORWARD_FALLBACK=true
```

That fallback is meant for the Kafka phase of `Level 6` on `local`. It must
not be interpreted as a replacement for the public access required by the
level's full validation.

## INESData Playwright and Transfers in STARTED

If the E2E transfer test creates the asset, completes the negotiation, and
starts the transfer, `STARTED` is an accepted state for the INESData UI
validation. The UI validates that the transfer was accepted and started; the
strong evidence of data movement must come from Newman, MinIO, or separate
storage checks.

If the suite fails even though the history shows `STARTED`, or if the storage
validations fail, check:

- the `e2e-transfer-report.json` or `consumer-transfer-report.json` report inside the experiment;
- the Newman collection `06_consumer_transfer`;
- the consumer and provider connector logs;
- the availability of MinIO and the data plane;
- whether `minikube tunnel` asked for a password and didn't actually stay active.

Don't solve this case by replacing the hostname with `port-forward`, because
that can validate a different path from the one the local environment
published by the Ingress would use.

## Transfer Fails with Assets Uploaded into a Folder

If an asset created from the UI appears in the catalog but the transfer
doesn't find the object in MinIO/S3, check whether it was uploaded with a
value in the `Folder` field.

The physical object and the asset's `DataAddress` must use the same key. For
uploads with a folder, the expected key is:

```text
<folder>/<file>
```

The E2E flow `adapters/inesdata/specs/05-e2e-transfer-flow.spec.ts` covers this case because it creates an
asset with a folder, publishes it, discovers it from the consumer, and runs
negotiation and transfer.

## EDC+Kafka Stays in STARTED or Doesn't Consume Messages

When Kafka is enabled with `PIONERA_LEVEL6_RUN_KAFKA=true`, `Level 6` runs the
EDC+Kafka functional validation after Newman if the adapter supports Kafka.
Locally, the default managed broker is created inside Kubernetes so the
connectors' data plane can reach it through cluster DNS:

```text
framework-kafka.<namespace>.svc.cluster.local:9092
```

The framework's Python process can open a temporary `port-forward` to
`127.0.0.1:<port>` to create topics and verify messages from the host. That
`port-forward` is internal to the validation and must not be used as the
connector's endpoint.

If you see errors against `host.minikube.internal:<port>` or transfers that
stay in `STARTED`, check that there are no old overrides such as:

```text
KAFKA_BOOTSTRAP_SERVERS
KAFKA_CLUSTER_BOOTSTRAP_SERVERS
```

For the normal local path, use the default mode:

```text
KAFKA_PROVISIONER=kubernetes
```

During a run you can inspect the temporary broker with:

```bash
kubectl get pods,svc -n <dataspace> -l app=framework-kafka
```

If the broker is `ready`, the topics are created correctly, and the transfer
still ends in `TERMINATED` right after `start_transfer`, the usual cause is no
longer the broker but the local EDC connector image. That pattern indicates
that the control plane accepted the transfer, but the deployed runtime didn't
include the effective Kafka data plane or was still reusing an obsolete
`connector.jar`. Since this version, `adapters/edc/scripts/build_image.sh`
automatically rebuilds the jar when the runtime inputs change, to avoid that
misalignment.

On `vm-distributed`, `Level 6` runs a specific preflight before the Kafka
suite. If the result is `kafka_runtime_preflight_failed`, check the
experiment's `kafka_runtime_preflight.json` artifact. The most common causes
are:

- `KAFKA_CLUSTER_BOOTSTRAP_SERVERS` empty.
- `KAFKA_CLUSTER_BOOTSTRAP_SERVERS` pointing to `localhost`, to
  `host.minikube.internal`, or to an internal Kubernetes `*.svc` DNS name.
- Connector image not pinned, and the local image/remote import flow
  disabled.

For distributed setups, the Kafka address in the `DataAddress` must be a path
reachable from all connector VMs, for example a `NodePort` exposed by the
common services VM or an equivalent endpoint agreed for that environment.

## Validation Data Accumulates

Enable or run prior cleanup when repeated tests create too much data.

Cleanup must be adapter-aware and write a report under the current experiment's folder.
