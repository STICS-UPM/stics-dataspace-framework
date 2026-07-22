# 49. Bavenir Hands-On Session — Connector Onboarding Runbook

## Purpose

Live runbook for standing up one new EDC connector on bavenir's own
infrastructure, connected to the STICS dataspace, with UPM on the call in
case something goes wrong. Unlike `deployment-guide.md`, this assumes the
target VM, its public hostname, and its DNS are **not known yet** — Step 0
decides them live, and every command below is written with placeholders for
exactly that reason.

Each step is tagged with who runs it:

- **[BAVENIR]** — runs on bavenir's own VM/cluster. UPM has no access there.
- **[UPM]** — must run from the `stics2test` VM, using the framework's own
  virtualenv or its Postgres/Kubernetes access. Bavenir cannot run these.
- **[JOINT]** — a decision or check both sides do together.

Placeholders used throughout: `<CONNECTOR_NAME>`, `<NAMESPACE>`,
`<PUBLIC_HOSTNAME>`, `<VM_IP>`, `<DB_NAME>`/`<DB_USER>`/`<DB_PASSWORD>`.

---

## Step 0 — Decide Three Things [JOINT]

1. **Connector name** (participant ID). Must match `^[a-z][a-z0-9-]{1,19}$`
   — max 20 characters, lowercase, digits, hyphens, starting with a letter.
2. **Target VM.** Ask directly, don't assume: does this VM already run a
   connector? If yes, Step 6 must use bridge networking with a port offset,
   not `network_mode: host`.
3. **Public hostname**, e.g. `<something>.bavenir.eu`. Must be a domain
   bavenir can point at the target VM's public IP. Confirm live:

```bash
nslookup <PUBLIC_HOSTNAME> 8.8.8.8
```

If it does not resolve yet, bavenir creates the DNS `A` record now — the
rest of the steps can proceed in parallel, but Step 11 (TLS) and the final
verification (Step 12) cannot complete until it does.

**Everything below needs these three values. Nothing in Step 3 onward can
start until Step 0 is resolved.**

---

## Step 1 — Confirm the VM Has the Required Tooling [BAVENIR]

Run directly on the target VM:

```bash
docker --version
docker compose version
java -version
```

Missing Docker/Compose → install Docker Engine for Ubuntu before continuing.
This is the one step worth pre-checking before the session starts, since
installing Docker eats session time for no interesting reason.

---

## Step 2 — Provision the Connector's PostgreSQL Database [BAVENIR]

On the target VM's local PostgreSQL:

```bash
sudo -u postgres psql << 'EOF'
DROP DATABASE IF EXISTS <DB_NAME>;
DROP ROLE IF EXISTS <DB_NAME>;
CREATE ROLE <DB_NAME> LOGIN PASSWORD '<DB_PASSWORD>';
CREATE DATABASE <DB_NAME> OWNER <DB_NAME>;
EOF
```

Use one consistent name for role, database, and (with hyphens replaced by
underscores) the connector itself, e.g. connector `acme-stics` →
`acme_stics`.

---

## Step 3 — Provision the Connector's Identity [UPM]

Runs on `stics2test`, using the framework's own virtualenv. Creates the
Keycloak OAuth2 client, the Vault signing keypair, the MinIO bucket
(scoped to `stics-<CONNECTOR_NAME>` only, not a wildcard), and registers
the connector with the registration service (URL fixed later, Step 9b).

```bash
cd /home/stics2/Validation-Environment
cat > /tmp/provision_<CONNECTOR_NAME>.py << 'PYEOF'
import os, sys
REPO_ROOT = "/home/stics2/Validation-Environment"
os.chdir(REPO_ROOT); sys.path.insert(0, REPO_ROOT)

CONNECTOR_NAME = "<CONNECTOR_NAME>"
DS_NAME = "stics"
NAMESPACE = "<NAMESPACE>"

os.environ["PIONERA_DS_1_NAME"] = DS_NAME
os.environ["PIONERA_DS_1_NAMESPACE"] = "core-control"
os.environ["PIONERA_DS_1_CONNECTORS"] = CONNECTOR_NAME
os.environ["PIONERA_DS_1_CONNECTOR_NAMESPACES"] = f"{CONNECTOR_NAME}:{NAMESPACE}"
os.environ["PIONERA_DS_1_REGISTRATION_NAMESPACE"] = "core-control"
os.environ["PIONERA_NAMESPACE_PROFILE"] = "role-aligned"
os.environ["PIONERA_COMMON_SERVICES_NAMESPACE"] = "common-srvs"
os.environ["PIONERA_DOMAIN_BASE"] = "dev.linkeddata.es"
os.environ["PIONERA_DS_DOMAIN_BASE"] = "dev.linkeddata.es"

import main as framework_main
adapter = framework_main.build_adapter("edc", topology="vm-distributed")
repo_dir, python_exec = adapter.connectors._prepare_runtime_prerequisites()
ok = adapter.connectors._prepare_connector_prerequisites(
    CONNECTOR_NAME, DS_NAME, NAMESPACE, repo_dir, python_exec)
print("RESULT:", "OK" if ok else "FAILED")
print("Credentials file:",
      adapter.connectors._connector_credentials_file_path(CONNECTOR_NAME, DS_NAME))
PYEOF
.venv/bin/python3 /tmp/provision_<CONNECTOR_NAME>.py
```

Output file to keep at hand for Step 5:

```text
deployers/edc/deployments/DEV/vm-distributed/stics/connectors/<CONNECTOR_NAME>/credentials.json
```

Contains the Vault token (needed in Step 5) and, only if the connector ends
up on `stics2test` itself, an already-created database's name/user/password.

---

## Step 4 — Hand Over the Connector `.jar` [UPM → BAVENIR]

Same binary for every connector — identity is external, in the
`.properties` file. UPM copies it from any existing connector and sends it
to bavenir (scp, or any file transfer both sides agree on during the call):

```bash
scp ~/edc-connector-stics/provider-connector.jar bavenir@<VM_IP>:~/edc-<CONNECTOR_NAME>/<CONNECTOR_NAME>.jar
```

---

## Step 5 — Write the `.properties` File [BAVENIR]

Save as `<CONNECTOR_NAME>-configuration-docker.properties`. Fields that
actually change per connector are marked; the rest is boilerplate, copy
verbatim.

```properties
edc.participant.id=<CONNECTOR_NAME>
edc.runtime.id=stics-<CONNECTOR_NAME>

edc.dsp.callback.address=https://<PUBLIC_HOSTNAME>/protocol

web.http.port=19191
web.http.path=/api
web.http.management.port=19193
web.http.management.path=/management
web.http.protocol.port=19194
web.http.protocol.path=/protocol
web.http.public.port=19291
web.http.public.path=/public
edc.dataplane.api.public.baseurl=https://<PUBLIC_HOSTNAME>/public
edc.dataplane.proxy.public.endpoint=https://<PUBLIC_HOSTNAME>/public
web.http.control.port=19192
web.http.control.path=/control
web.http.version.port=19195
web.http.version.path=/version
web.http.shared.port=19196
web.http.shared.path=/shared

edc.transfer.proxy.token.signer.privatekey.alias=stics/<CONNECTOR_NAME>/private-key
edc.transfer.proxy.token.verifier.publickey.alias=stics/<CONNECTOR_NAME>/public-key

edc.web.rest.cors.enabled=true
edc.web.rest.cors.origins=http://localhost:4200
edc.web.rest.cors.methods=GET,POST,PUT,DELETE,OPTIONS
edc.web.rest.cors.headers=origin, content-type, accept, authorization, x-api-key

edc.vault.hashicorp.url=https://conn-citycouncil-demo.dev.linkeddata.es
edc.vault.hashicorp.token=<VAULT_TOKEN_FROM_credentials.json>
edc.edr.vault.path=stics/<CONNECTOR_NAME>/

edc.datasource.default.url=jdbc:postgresql://<POSTGRES_HOST>:5432/<DB_NAME>
edc.datasource.default.user=<DB_USER>
edc.datasource.default.password=<DB_PASSWORD>
edc.datasource.default.pool.maxIdleConnections=10
edc.datasource.default.pool.maxTotalConnections=10
edc.datasource.default.pool.minIdleConnections=5
edc.sql.schema.autocreate=true

edc.aws.access.key=stics/<CONNECTOR_NAME>/aws-access-key
edc.aws.secret.access.key=stics/<CONNECTOR_NAME>/aws-secret-key
edc.aws.endpoint.override=https://minio.dev.linkeddata.es
edc.aws.region=eu-central-1
edc.aws.bucket.name=stics-<CONNECTOR_NAME>

edc.oauth.token.url=https://auth.dev.linkeddata.es/realms/stics/protocol/openid-connect/token
edc.oauth.provider.audience=https://auth.dev.linkeddata.es/realms/stics
edc.oauth.endpoint.audience=https://auth.dev.linkeddata.es/realms/stics
edc.oauth.provider.jwks.url=https://auth.dev.linkeddata.es/realms/stics/protocol/openid-connect/certs
edc.oauth.certificate.alias=stics/<CONNECTOR_NAME>/public-key
edc.oauth.private.key.alias=stics/<CONNECTOR_NAME>/private-key
edc.oauth.client.id=<CONNECTOR_NAME>
edc.oauth.validation.nbf.leeway=10

edc.api.auth.oauth2.allowedRoles.1.role=connector-admin
edc.api.auth.oauth2.allowedRoles.2.role=connector-management
edc.api.auth.oauth2.allowedRoles.3.role=connector-user

edc.catalog.registration.service.host=https://registration-service-demo.dev.linkeddata.es/api
edc.catalog.cache.execution.period.seconds=60
edc.catalog.cache.partition.num.crawlers=2
edc.catalog.cache.execution.delay.seconds=5
edc.participants.cache.execution.period.seconds=1800
```

`<POSTGRES_HOST>`: `127.0.0.1` if Step 6 uses `network_mode: host`; the
Docker bridge gateway IP (check with
`docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'`)
if Step 6 uses bridge networking.

---

## Step 6 — `docker-compose.yml` [BAVENIR]

The choice depends on the Step 0 answer: does the target VM already run
another connector?

### 6a. No other connector on this VM (simple case)

```yaml
services:
  <CONNECTOR_NAME>:
    image: eclipse-temurin:17-jre
    container_name: <CONNECTOR_NAME>
    working_dir: /workspace
    command:
      - java
      - -Djavax.net.ssl.trustStore=/workspace/cacerts.jks
      - -Djavax.net.ssl.trustStorePassword=dataspaceunit
      - -Dedc.fs.config=/workspace/<CONNECTOR_NAME>-configuration-docker.properties
      - -jar
      - /workspace/<CONNECTOR_NAME>.jar
    volumes:
      - ./<CONNECTOR_NAME>.jar:/workspace/<CONNECTOR_NAME>.jar:ro
      - ./<CONNECTOR_NAME>-configuration-docker.properties:/workspace/<CONNECTOR_NAME>-configuration-docker.properties:ro
      - ./cacerts.jks:/workspace/cacerts.jks:ro
    network_mode: host
    restart: unless-stopped
```

### 6b. Another connector already runs on this VM

Do not use `network_mode: host` — it collides on every port, including the
fixed internal port `17171` used by the federated-catalog extension (not
configurable). Use bridge networking with an explicit +10000 port offset
instead — properties file keeps the normal ports internally, only the
external mapping changes:

```yaml
services:
  <CONNECTOR_NAME>:
    image: eclipse-temurin:17-jre
    container_name: <CONNECTOR_NAME>
    working_dir: /workspace
    command:
      - java
      - -Djavax.net.ssl.trustStore=/workspace/cacerts.jks
      - -Djavax.net.ssl.trustStorePassword=dataspaceunit
      - -Dedc.fs.config=/workspace/<CONNECTOR_NAME>-configuration-docker.properties
      - -jar
      - /workspace/<CONNECTOR_NAME>.jar
    volumes:
      - ./<CONNECTOR_NAME>.jar:/workspace/<CONNECTOR_NAME>.jar:ro
      - ./<CONNECTOR_NAME>-configuration-docker.properties:/workspace/<CONNECTOR_NAME>-configuration-docker.properties:ro
      - ./cacerts.jks:/workspace/cacerts.jks:ro
    ports:
      - "29191:19191"
      - "29192:19192"
      - "29193:19193"
      - "29194:19194"
      - "29195:19195"
      - "29196:19196"
      - "29291:19291"
      - "27171:17171"
    restart: unless-stopped
```

Also required in bridge mode, on the VM itself:

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET listen_addresses = '*';"
echo "host    all    all    172.16.0.0/12    md5" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf
sudo systemctl restart postgresql
```

---

## Step 7 — Shared TLS Truststore [UPM → BAVENIR]

Every service in the dataspace uses a self-signed CA. Without this file the
connector fails to start with `PKIX path building failed`.

UPM, from any cluster that has it:

```bash
kubectl -n core-control get secret common-tls-cacerts -o jsonpath='{.data.cacerts\.jks}' | base64 -d > cacerts.jks
scp cacerts.jks bavenir@<VM_IP>:~/edc-<CONNECTOR_NAME>/cacerts.jks
```

Password is always `dataspaceunit` (already in the `.properties` above).
**If Step 11 regenerates the certificate later in the session, this file
must be re-sent — the one handed over here becomes stale.**

---

## Step 8 — Start the Connector [BAVENIR]

```bash
cd ~/edc-<CONNECTOR_NAME> && docker compose up -d
sleep 10
docker logs <CONNECTOR_NAME> --tail 30
```

Look for `Runtime stics-<CONNECTOR_NAME> ready`. Errors at this point are
almost always Step 5 typos or Step 2/6 database connectivity — see the
troubleshooting table.

---

## Step 9 — Two Fixes Every Connector Needs After First Start

### 9a. INESData Tables Not Covered by Autocreate [BAVENIR]

```bash
psql -h <POSTGRES_HOST> -U <DB_USER> -d <DB_NAME> \
  -f adapters/inesdata/sources/inesdata-connector/resources/sql/060_federated-catalog-schema.sql
psql -h <POSTGRES_HOST> -U <DB_USER> -d <DB_NAME> \
  -f adapters/inesdata/sources/inesdata-connector/resources/sql/060_vocabulary-schema.sql
```

(UPM sends these two `.sql` files if bavenir doesn't have a checkout of this
repo.) Symptom if skipped: `relation "edc_catalog" does not exist`.

### 9b. Correct the Registered Participant URL [UPM]

Step 3 registers a placeholder internal URL. Fix against the
registration-service database, only reachable from `stics2test`:

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d stics_rs -c "
UPDATE public.edc_participant
SET url = 'https://<PUBLIC_HOSTNAME>/protocol',
    shared_url = 'https://<PUBLIC_HOSTNAME>/shared'
WHERE participant_id = '<CONNECTOR_NAME>';
"
```

Then, bavenir restarts:

```bash
cd ~/edc-<CONNECTOR_NAME> && docker compose restart
```

---

## Step 10 — The Network Bridge [BAVENIR, guided live by UPM]

Goal: `https://<PUBLIC_HOSTNAME>/...` reaches the connector's ports on its
own VM through that VM's own Kubernetes cluster (k3s intercepts 80/443
before any host-level nginx sees them).

**10.0 — Confirm the ingress controller first:**

```bash
kubectl get ingressclass
```

If it says `traefik` and not `nginx`, migrate before going further — Traefik
has a known history in this project of silently serving a stale TLS
certificate even after the `Secret`/`Ingress` are updated correctly:

```bash
kubectl delete helmchart traefik -n kube-system
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx \
  -n ingress-nginx --create-namespace \
  --set controller.service.type=LoadBalancer \
  --set controller.watchIngressWithoutClass=true \
  --set controller.allowSnippetAnnotations=true \
  --set controller.config.allow-snippet-annotations=true \
  --set controller.config.annotations-risk-level=Critical \
  --wait --timeout 180s
```

**10.1 — Apply the bridge** (Service with no pod selector + manual
Endpoints + Ingress), on bavenir's own cluster:

```bash
cat > /tmp/<CONNECTOR_NAME>-bridge.yaml << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: <NAMESPACE>
---
apiVersion: v1
kind: Service
metadata:
  name: <CONNECTOR_NAME>-external
  namespace: <NAMESPACE>
spec:
  ports:
    - { name: "19191", port: 19191, protocol: TCP }
    - { name: "19192", port: 19192, protocol: TCP }
    - { name: "19193", port: 19193, protocol: TCP }
    - { name: "19194", port: 19194, protocol: TCP }
    - { name: "19195", port: 19195, protocol: TCP }
    - { name: "19196", port: 19196, protocol: TCP }
    - { name: "19291", port: 19291, protocol: TCP }
---
apiVersion: v1
kind: Endpoints
metadata:
  name: <CONNECTOR_NAME>-external
  namespace: <NAMESPACE>
subsets:
  - addresses:
      - ip: <VM_IP>
    ports:
      # host-network mode: left port == right port (19191, ...)
      # bridge mode with +10000 offset: right side is the published port (29191, ...)
      - { name: "19191", port: 19191, protocol: TCP }
      - { name: "19192", port: 19192, protocol: TCP }
      - { name: "19193", port: 19193, protocol: TCP }
      - { name: "19194", port: 19194, protocol: TCP }
      - { name: "19195", port: 19195, protocol: TCP }
      - { name: "19196", port: 19196, protocol: TCP }
      - { name: "19291", port: 19291, protocol: TCP }
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: <CONNECTOR_NAME>-ingress
  namespace: <NAMESPACE>
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "false"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "false"
    nginx.ingress.kubernetes.io/proxy-body-size: "800m"
spec:
  ingressClassName: nginx
  tls:
    - hosts: ["<PUBLIC_HOSTNAME>"]
      secretName: pionera-internal-ingress-tls
  rules:
    - host: <PUBLIC_HOSTNAME>
      http:
        paths:
          - { path: /api,        pathType: Prefix, backend: { service: { name: <CONNECTOR_NAME>-external, port: { number: 19191 } } } }
          - { path: /control,    pathType: Prefix, backend: { service: { name: <CONNECTOR_NAME>-external, port: { number: 19192 } } } }
          - { path: /management, pathType: Prefix, backend: { service: { name: <CONNECTOR_NAME>-external, port: { number: 19193 } } } }
          - { path: /protocol,   pathType: Prefix, backend: { service: { name: <CONNECTOR_NAME>-external, port: { number: 19194 } } } }
          - { path: /version,    pathType: Prefix, backend: { service: { name: <CONNECTOR_NAME>-external, port: { number: 19195 } } } }
          - { path: /shared,     pathType: Prefix, backend: { service: { name: <CONNECTOR_NAME>-external, port: { number: 19196 } } } }
          - { path: /public,     pathType: Prefix, backend: { service: { name: <CONNECTOR_NAME>-external, port: { number: 19291 } } } }
EOF
kubectl apply -f /tmp/<CONNECTOR_NAME>-bridge.yaml
```

Note: `secretName: pionera-internal-ingress-tls` only resolves once UPM has
synced that secret into this cluster/namespace — coordinate with Step 11.

**Diagnostics** if `curl -k https://<PUBLIC_HOSTNAME>/...` doesn't behave:

| Response | Meaning |
|---|---|
| `404 page not found`, no `Server:` header | Reached Kubernetes, no Ingress rule matches — wrong host or wrong cluster |
| `503`, `Server: nginx/...` | Routing correct, Service has no healthy backend — check Endpoints IP/ports |
| Nothing in `kubectl -n ingress-nginx logs deploy/ingress-nginx-controller` | Not reaching this cluster at all — recheck DNS target |

---

## Step 11 — Add the Hostname to the Shared TLS Certificate [UPM — high blast radius]

⚠️ **This is the one step that touches every existing connector, not just
the new one.** By default the certificate on disk is reused as-is even if a
new hostname needs adding — regeneration must be forced:

```bash
cd /home/stics2/Validation-Environment
export PIONERA_VM_INGRESS_TLS_HOSTS="<PUBLIC_HOSTNAME>"
rm -f .local/artifacts/ingress-tls/vm-distributed/stics/tls.crt
rm -f .local/artifacts/ingress-tls/vm-distributed/stics/tls.key

.venv/bin/python3 << 'EOF'
import os, sys
sys.path.insert(0, "/home/stics2/Validation-Environment")
os.chdir("/home/stics2/Validation-Environment")
os.environ["PIONERA_VM_INGRESS_TLS_HOSTS"] = "<PUBLIC_HOSTNAME>"
import main as framework_main
adapter = framework_main.build_adapter("inesdata", topology="vm-distributed")
adapter.infrastructure._sync_vm_ingress_tls("vm-distributed")
EOF
```

If any output line reads `secret/... configured` (not `unchanged`), the key
pair genuinely changed. **Re-send `cacerts.jks` (Step 7) to all four
existing connectors** (`connector-stics`, `conlab-stics`, `contest-stics`,
`contest-bavenir`) **and the new one**, then restart every one of them:

```bash
docker compose restart   # on every connector VM, including the new one
```

Confirm nothing broke before moving on:

```bash
curl -k https://stics.bavenir.eu/api/check/health
curl -k https://con-lab.stics.linkeddata.es/api/check/health
curl -k https://con-test.stics.linkeddata.es/api/check/health
curl -k https://con-test.stics.bavenir.eu/api/check/health
```

All four must still return `200` before declaring the session's new
connector done.

---

## Step 12 — Final Verification [JOINT]

```bash
curl -k https://<PUBLIC_HOSTNAME>/api/check/health
# expect: HTTP 200

sleep 75   # federated-catalog cycle
docker logs <CONNECTOR_NAME> --since 90s 2>&1 | grep -iE "error|exception"
# expect: no output
```

Optional, if time allows: run a real contract negotiation + transfer
against an existing connector following
[`docs/47_stics_edc_interop_evidence.md`](./47_stics_edc_interop_evidence.md).

---

## Troubleshooting Quick Reference

| Symptom | Fix |
|---|---|
| `ValueError: Invalid connector name` | Name too long — max 20 chars (Step 0) |
| `Connection to 127.0.0.1:5432 refused` | Host-network mode: confirm Postgres listens there. Bridge mode: point to the Docker bridge gateway IP, not `127.0.0.1` |
| `no pg_hba.conf entry for host "172.x.x.x"` | Add the `172.16.0.0/12` line + `listen_addresses='*'` (Step 6b), restart Postgres |
| `relation "edc_catalog"/"edc_vocabulary" does not exist` | Apply the two SQL files (Step 9a) |
| Crawler: `Temporary failure in name resolution` | Placeholder URL → fix Step 9b. DNS not live yet → wait |
| `PKIX path building failed` | Stale `cacerts.jks` — re-copy from Step 7 (all connectors, if Step 11 just ran) |
| `curl` → `404`, no `Server:` header | Wrong host or wrong cluster — revisit Step 10 |
| `curl` → `503`, `Server: nginx/...` | Endpoints has no healthy backend — check IP/ports |
| Request missing from `ingress-nginx-controller` logs entirely | DNS points somewhere else — recheck Step 0 |
| TLS cert keeps reverting to stale/self-signed on one host | Cluster still runs Traefik — migrate it (Step 10.0) |

---

*Companion to [`deployment-guide.md`](../deployment-guide.md), which covers
the same process for UPM operators working from a known VM/hostname, with
fuller explanations. This version exists purely as a fast, role-tagged
runbook for the live session.*
