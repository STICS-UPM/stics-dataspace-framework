# 48. Beginner's Guide: How to Set Up a New EDC Connector from Scratch

## Who this guide is for

For anyone who needs to add **one more EDC connector** to the `stics`
dataspace without having attended the session where it was done the first
time. It assumes no prior knowledge of the framework: it explains the *why*
of each step, not just the command.

It is based exactly on how the 4 connectors that exist today were set up
(`connector-stics`, `conlab-stics`, `contest-stics`, `contest-bavenir`),
including the real stumbling blocks we hit and how they were solved.

## The big picture before you start

An EDC connector in this project **does not live inside Kubernetes** (unlike
how the framework does it "out of the box"). It lives as a plain Java program
(`connector.jar`), running inside a Docker container, on the VM of your
choice. The only things that still live in Kubernetes are the **common
services** (Keycloak, Vault, MinIO, registration-service), deployed on the
`stics2test` VM (`192.168.122.2`).

For the new connector to work, it needs 4 things:

1. **An identity** in the dataspace: a client in Keycloak, a key pair in
   Vault, a bucket in MinIO. An existing script generates all of this; you
   don't create it by hand.
2. **A Postgres database** to store its own data (assets, contracts,
   transfers).
3. **A configuration file** (`.properties`) that tells the connector how to
   reach Keycloak/Vault/MinIO/Postgres and which identity to use.
4. **A network "bridge"** so the outside world (other connectors, browsers)
   can reach it over HTTPS with a public name.

Let's go step by step.

---

## Step 0: Decide 3 things before touching anything

- **Connector name** (its "participant id" in the dataspace). Important rule:
  **20 characters maximum**. If you go over, the provisioning script fails
  with `ValueError: Invalid connector name`. Example: `contest-bavenir`
  (15 characters) instead of `contest-bavenir-stics` (22, too long).
- **Which VM it will live on** (a new VM, or one that already has another
  connector? This matters a lot; see the warning below).
- **Which public hostname it will have** (e.g. `my-connector.stics.linkeddata.es`).
  It must be a domain that **already resolves** through DNS to the public IP
  of the chosen VM. Check it like this before continuing:

  ```bash
  nslookup my-connector.stics.linkeddata.es 8.8.8.8
  ```

  If it doesn't resolve, someone has to register it in DNS before you
  continue (usually OEG-UPM for `*.linkeddata.es`, or the VM provider for
  other domains). You can prepare everything else in the meantime, but you
  won't be able to verify public access until the DNS is active.

### ⚠️ Important warning: check whether the VM already has another connector

Before assuming it's a "new VM", really check. It happened to us: someone gave
us an IP as if it were a different machine, and it turned out to be **the
same VM** where we already had a connector running (just with a different
system user). Check it like this:

```bash
ssh user_you_already_know@VM_IP 'hostname; hostname -I; getent passwd new_user_you_were_given'
```

If the `hostname` matches a VM you already know, it's the same machine. This
matters because **two connectors on the same VM can't use the same ports**:
you have to use different ports and Docker *bridge* networking instead of
`network_mode: host` (explained in Step 6).

---

## Step 1: Check that the VM has what it needs

Connect to the VM and check:

```bash
ssh user@VM_IP 'docker --version; docker compose version; java -version'
```

If Docker or Docker Compose is missing, install them before continuing (not
covered in this guide; it's a standard Docker Engine installation on Ubuntu).

---

## Step 2: Prepare the connector's Postgres database

The connector needs its own Postgres to store its assets, contracts, and
transfers (tables `edc_asset`, `edc_contract_negotiation`, etc.).

### Case A: the VM already has its own local Postgres (the usual case)

```bash
ssh user@VM_IP 'sudo -u postgres psql' << 'EOF'
DROP DATABASE IF EXISTS <DB_NAME>;
DROP ROLE IF EXISTS <DB_NAME>;
CREATE ROLE <DB_NAME> LOGIN PASSWORD '<STRONG_PASSWORD>';
CREATE DATABASE <DB_NAME> OWNER <DB_NAME>;
EOF
```

Use the same name for the role and the database, matching the connector name
(with underscores instead of hyphens if needed, e.g. `contest_bavenir_stics`).

### Case B: the connector will live on the SAME VM as the common services (`stics2test`)

Pleasant surprise: on that particular VM, the shared Postgres of
Keycloak/registration-service **is already reachable directly at
`127.0.0.1:5432`**, without tunnels. Even better: **the Step 3 provisioning
script already creates a database there for the connector automatically**,
so you don't need to create anything by hand in this case. You only need to
read the name/user/password the script generated from the `credentials.json`
file (see Step 3).

---

## Step 3: Provision the identity (Keycloak + Vault + MinIO)

This is the most "magical" part of the process, but it's already solved: a
framework function does exactly this for you, without deploying anything to
Kubernetes. Save this script (adjusting `CONNECTOR_NAME` and `NAMESPACE`) and
run it **from the `stics2test` VM** (where the framework lives):

```python
# save as provision_<name>.py and run it with the framework venv:
# /home/stics2/Validation-Environment/.venv/bin/python3 provision_<name>.py
import os
import sys

REPO_ROOT = "/home/stics2/Validation-Environment"
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

CONNECTOR_NAME = "MY-CONNECTOR"       # <-- 20 characters maximum
DS_NAME = "stics"
NAMESPACE = "MY-NAMESPACE"            # <-- any short word, e.g. "contest"

os.environ["PIONERA_DS_1_NAME"] = DS_NAME
os.environ["PIONERA_DS_1_NAMESPACE"] = "core-control"
os.environ["PIONERA_DS_1_CONNECTORS"] = CONNECTOR_NAME
os.environ["PIONERA_DS_1_CONNECTOR_NAMESPACES"] = f"{CONNECTOR_NAME}:{NAMESPACE}"
os.environ["PIONERA_DS_1_REGISTRATION_NAMESPACE"] = "core-control"
os.environ["PIONERA_NAMESPACE_PROFILE"] = "role-aligned"
os.environ["PIONERA_COMMON_SERVICES_NAMESPACE"] = "common-srvs"
os.environ["PIONERA_DOMAIN_BASE"] = "dev.linkeddata.es"
os.environ["PIONERA_DS_DOMAIN_BASE"] = "dev.linkeddata.es"

import main as framework_main  # noqa: E402

print("Building the 'edc' adapter ...")
adapter = framework_main.build_adapter("edc", topology="vm-distributed")

print("Checking prerequisites (Vault, Postgres, Keycloak) ...")
repo_dir, python_exec = adapter.connectors._prepare_runtime_prerequisites()

print(f"Provisioning identity for '{CONNECTOR_NAME}' ...")
ok = adapter.connectors._prepare_connector_prerequisites(
    CONNECTOR_NAME, DS_NAME, NAMESPACE, repo_dir, python_exec
)
print("RESULT:", "OK" if ok else "FAILED")

credentials_path = adapter.connectors._connector_credentials_file_path(CONNECTOR_NAME, DS_NAME)
print("Credentials file:", credentials_path)
```

**What this actually does, in plain words:**

- Creates an OAuth2 client in Keycloak (so the connector can authenticate).
- Generates a key pair (private/public) and stores it in Vault (to sign
  transfer tokens).
- Creates a bucket in MinIO and grants permissions on it.
- Registers the connector as a "participant" in the registration-service
  (although with a provisional URL that **must be fixed later**, see Step 9).
- Writes all of the above (except the Vault keys themselves, which stay in
  Vault) to a JSON file:

  ```text
  deployers/edc/deployments/DEV/vm-distributed/stics/connectors/<CONNECTOR_NAME>/credentials.json
  ```

  That file contains, among other things, the **Vault token** and (if
  applicable, see Step 2 Case B) the name/user/password of an already created
  database. Treat it as a secret; don't commit it to git (it's already in
  `.gitignore`).

---

## Step 4: Get the connector `.jar`

No need to compile anything. The same `connector.jar` works for any connector
(the identity is configured outside it, in the `.properties`). Copy it from a
connector that already works:

```bash
scp user@VM_WITH_EXISTING_CONNECTOR:~/edc-<something>/connector.jar ~/edc-<my-connector>/my-connector.jar
```

(or whatever the file is called on that connector; in our case it's
`provider-connector.jar`, `consumer-connector.jar`, etc. The contents are
identical.)

---

## Step 5: Write the `.properties` file

This is the complete template we have already used 4 times. Copy it, replace
the `<FIELDS>`, and save it as `<my-connector>-configuration-docker.properties`:

```properties
edc.participant.id=<CONNECTOR_NAME>
edc.runtime.id=stics-<CONNECTOR_NAME>

edc.dsp.callback.address=https://<MY_PUBLIC_HOSTNAME>/protocol

web.http.port=19191
web.http.path=/api
web.http.management.port=19193
web.http.management.path=/management
web.http.protocol.port=19194
web.http.protocol.path=/protocol
web.http.public.port=19291
web.http.public.path=/public
edc.dataplane.api.public.baseurl=https://<MY_PUBLIC_HOSTNAME>/public
edc.dataplane.proxy.public.endpoint=https://<MY_PUBLIC_HOSTNAME>/public
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

# These two are NOT real keys; they are "aliases" pointing to Vault. The
# connector resolves them by itself at runtime. There is no need to fill them
# in with real values.
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

**`<POSTGRES_HOST>` depends on where the database is relative to the
container** (important, see Step 6):
- If the container uses `network_mode: host` → `127.0.0.1`.
- If the container uses *bridge* networking with Postgres on the same host →
  the Docker gateway IP (usually `172.17.0.1`; check it with
  `docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'`).

---

## Step 6: The `docker-compose.yml`, which is the important decision

### If your VM does NOT already have another connector running (simple case)

```yaml
services:
  my-connector:
    image: eclipse-temurin:17-jre
    container_name: my-connector
    working_dir: /workspace
    command:
      - java
      - -Djavax.net.ssl.trustStore=/workspace/cacerts.jks
      - -Djavax.net.ssl.trustStorePassword=dataspaceunit
      - -Dedc.fs.config=/workspace/my-connector-configuration-docker.properties
      - -jar
      - /workspace/my-connector.jar
    volumes:
      - /home/user/edc-my-connector/my-connector.jar:/workspace/my-connector.jar:ro
      - /home/user/edc-my-connector/my-connector-configuration-docker.properties:/workspace/my-connector-configuration-docker.properties:ro
      - /home/user/edc-my-connector/cacerts.jks:/workspace/cacerts.jks:ro
    network_mode: host
    restart: unless-stopped
```

`network_mode: host` is the simplest option: the container shares the VM's
network directly, so `127.0.0.1` inside the container is the VM itself
(essential to reach a Postgres that only listens on localhost).

### If your VM ALREADY has another connector running (two-connector case)

**Don't use `network_mode: host`**: it would clash on every port with the
connector already there (including a fixed internal port, `17171`, used by
the federated catalog extension, which doesn't seem to be configurable).
Instead, use normal *bridge* networking with explicit port mapping, shifting
each port by +10000 (or whatever offset you prefer):

```yaml
services:
  my-connector:
    image: eclipse-temurin:17-jre
    container_name: my-connector
    working_dir: /workspace
    command:
      - java
      - -Djavax.net.ssl.trustStore=/workspace/cacerts.jks
      - -Djavax.net.ssl.trustStorePassword=dataspaceunit
      - -Dedc.fs.config=/workspace/my-connector-configuration-docker.properties
      - -jar
      - /workspace/my-connector.jar
    volumes:
      - /home/user/edc-my-connector/my-connector.jar:/workspace/my-connector.jar:ro
      - /home/user/edc-my-connector/my-connector-configuration-docker.properties:/workspace/my-connector-configuration-docker.properties:ro
      - /home/user/edc-my-connector/cacerts.jks:/workspace/cacerts.jks:ro
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

Note: **inside** the `.properties` the ports stay the normal ones (19191,
etc.); only the outside changes, in the `ports:` mapping. Postgres is no
longer reachable at `127.0.0.1` in this case, so you have to:

```bash
# on the VM, allow Postgres to accept connections from Docker
sudo -u postgres psql -c "ALTER SYSTEM SET listen_addresses = '*';"
echo "host    all    all    172.16.0.0/12    md5" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf
sudo systemctl restart postgresql
```

(`172.16.0.0/12` covers any subnet Docker Compose decides to create: each
`docker compose up` in a new project may use a different subnet, such as
`172.17.0.0/16`, `172.18.0.0/16`, etc.)

---

## Step 7: The shared truststore (`cacerts.jks`)

All services in this dataspace use TLS certificates signed by our own
(self-signed) CA, not a public one. Without this file, the connector fails at
startup with `PKIX path building failed`. Copy it from any Kubernetes
namespace that already has it:

```bash
kubectl -n core-control get secret common-tls-cacerts -o jsonpath='{.data.cacerts\.jks}' | base64 -d > cacerts.jks
scp cacerts.jks user@YOUR_VM:~/edc-my-connector/cacerts.jks
```

The password of this truststore is always `dataspaceunit` (it's already in
the `docker-compose.yml` above, in the `java -Djavax.net.ssl.trustStorePassword=...`
command).

---

## Step 8: Start it

```bash
ssh user@YOUR_VM 'cd ~/edc-my-connector && docker compose up -d'
```

Wait about 10 seconds and look at the logs:

```bash
ssh user@YOUR_VM 'docker logs my-connector --tail 30'
```

Look for the line `Runtime stics-<CONNECTOR_NAME> ready`. If it appears, the
connector started. If not, see the "Common errors" section at the end.

---

## Step 9: Two fixes that are ALWAYS needed after the first start

### 9a. The INESData tables that autocreate doesn't create

The jar includes INESData's own extensions (federated catalog, vocabulary
validator) that need tables the standard `edc.sql.schema.autocreate=true`
**does not create by itself**. Apply them by hand, once, against the
connector's database:

```bash
psql -h <POSTGRES_HOST> -U <DB_USER> -d <DB_NAME> \
  -f adapters/inesdata/sources/inesdata-connector/resources/sql/060_federated-catalog-schema.sql
psql -h <POSTGRES_HOST> -U <DB_USER> -d <DB_NAME> \
  -f adapters/inesdata/sources/inesdata-connector/resources/sql/060_vocabulary-schema.sql
```

If you don't, you'll see log errors such as
`relation "edc_catalog" does not exist` or `relation "edc_vocabulary" does not exist`.

### 9b. The registered participant URL is wrong

Step 3 registers the connector with an "internal" URL that doesn't work from
outside (such as `http://<CONNECTOR_NAME>:19194/protocol`). You have to fix
it by hand in the **registration-service** database (not the connector's:
this one lives in the shared Postgres, VM `stics2test`, `127.0.0.1:5432`,
database `stics_rs`):

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d stics_rs -c "
UPDATE public.edc_participant
SET url = 'https://<MY_PUBLIC_HOSTNAME>/protocol',
    shared_url = 'https://<MY_PUBLIC_HOSTNAME>/shared'
WHERE participant_id = '<CONNECTOR_NAME>';
"
```

After these two fixes, restart the connector:

```bash
ssh user@YOUR_VM 'cd ~/edc-my-connector && docker compose restart'
```

---

## Step 10: The network "bridge", which is the most delicate part

This is where we have made the most mistakes in practice, so read it
carefully. The idea: someone on the internet types `https://my-connector.stics...`
in a browser; that traffic must end up reaching exactly your connector's port,
on your VM.

### 10.0 Find out which machine your DNS REALLY points to

```bash
nslookup <MY_PUBLIC_HOSTNAME> 8.8.8.8
```

It may resolve **directly to your VM's public IP** (simple case, as with the
bavenir VM), or to the **public IP of a different VM** that acts as the
"entry point" for several private machines at once (the case of the
`stics2test` VM, public IP `138.100.15.165`, which actually forwards traffic
to other private VMs). If you don't know, ask; don't assume.

### 10.1 Whatever the case, Kubernetes almost certainly intercepts ports 80/443 before any system nginx

All the VMs in this project run k3s, and k3s **hijacks ports 80/443 of the
whole host** through `iptables` rules (its "ServiceLB"), before any regular
operating system nginx gets to see them. Check it like this on the VM your
DNS really points to:

```bash
sudo iptables -t nat -L -n | grep "dpt:80 \|dpt:443 "
```

If you see a line `DNAT ... to:<pod-ip>`, the suspicion is confirmed: **don't
edit the operating system nginx; edit Kubernetes**.

### 10.2 Create a "manual" Service + Endpoints pointing to your connector

This is a Kubernetes pattern to bring something that is NOT a pod (your
standalone Docker container) into an Ingress's routing. Save this as
`my-bridge.yaml` (adjust namespace, IP, ports):

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: <A_SHORT_NAMESPACE>
---
apiVersion: v1
kind: Service
metadata:
  name: my-connector-external
  namespace: <A_SHORT_NAMESPACE>
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
  name: my-connector-external
  namespace: <A_SHORT_NAMESPACE>
subsets:
  - addresses:
      - ip: <YOUR_VM_IP>
    ports:
      # If you used network_mode: host, the left and right ports match (19191).
      # If you used bridge with a +10000 offset, put the REAL published port here (29191, etc.)
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
  name: my-connector-ingress
  namespace: <A_SHORT_NAMESPACE>
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "false"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "false"
    nginx.ingress.kubernetes.io/proxy-body-size: "800m"
spec:
  ingressClassName: nginx   # or "traefik", depending on that cluster's controller (check with: kubectl get ingressclass)
  tls:
    - hosts: ["<MY_PUBLIC_HOSTNAME>"]
      secretName: pionera-internal-ingress-tls
  rules:
    - host: <MY_PUBLIC_HOSTNAME>
      http:
        paths:
          - { path: /api,        pathType: Prefix, backend: { service: { name: my-connector-external, port: { number: 19191 } } } }
          - { path: /control,    pathType: Prefix, backend: { service: { name: my-connector-external, port: { number: 19192 } } } }
          - { path: /management, pathType: Prefix, backend: { service: { name: my-connector-external, port: { number: 19193 } } } }
          - { path: /protocol,   pathType: Prefix, backend: { service: { name: my-connector-external, port: { number: 19194 } } } }
          - { path: /version,   pathType: Prefix, backend: { service: { name: my-connector-external, port: { number: 19195 } } } }
          - { path: /shared,    pathType: Prefix, backend: { service: { name: my-connector-external, port: { number: 19196 } } } }
          - { path: /public,    pathType: Prefix, backend: { service: { name: my-connector-external, port: { number: 19291 } } } }
```

Apply it **on the cluster of the VM your DNS really points to** (it may not be
the same VM where the connector runs; see the example of
`con-lab.stics.linkeddata.es`, which points to the consumer's VM, not the
common VM):

```bash
kubectl --kubeconfig <KUBECONFIG_OF_THE_RIGHT_CLUSTER> apply -f my-bridge.yaml
```

**Diagnostic tip** if something doesn't add up:
- `curl -k https://your-host/anything` → `404 page not found` without a
  `Server:` header → you reached Kubernetes but there is no rule for that
  host (or you reached the wrong cluster).
- Same `curl` → `503`, with a `Server: nginx/...` header → you got there, but
  the Service has no healthy backend yet (check the Endpoints).
- The request **doesn't even show up** in
  `kubectl -n ingress-nginx logs deploy/ingress-nginx-controller` → it's not
  reaching that cluster at all; reconsider step 10.0.

---

## Step 11: Add your hostname to the shared TLS certificate

The self-signed certificate used by the whole dataspace (`pionera-internal-ingress-tls`)
only covers the hostnames it already knows. You have to tell it explicitly to
include yours, and then force it to be regenerated (by default it reuses the
certificate already stored on disk and doesn't notice there is a new host):

```bash
# from the stics2test VM, with the framework venv:
export PIONERA_VM_INGRESS_TLS_HOSTS="<MY_PUBLIC_HOSTNAME>"

rm -f /home/stics2/Validation-Environment/.local/artifacts/ingress-tls/vm-distributed/stics/tls.crt
rm -f /home/stics2/Validation-Environment/.local/artifacts/ingress-tls/vm-distributed/stics/tls.key
```

Then, in Python (using the `inesdata` adapter, which is the one that manages
the dataspace):

```python
import os, sys
sys.path.insert(0, "/home/stics2/Validation-Environment")
os.chdir("/home/stics2/Validation-Environment")
import main as framework_main
adapter = framework_main.build_adapter("inesdata", topology="vm-distributed")
adapter.infrastructure._sync_vm_ingress_tls("vm-distributed")
```

**Very important**: as soon as this finishes with `secret/... configured` (not
`unchanged`), the certificate **has really changed** (new key), which means
**the `cacerts.jks` of ALL existing connectors (not only the new one) is now
outdated**. You have to copy it again to all of them (Step 7) and run
`docker compose restart` on all of them, or you'll get
`PKIX path building failed` errors on connectors that had been working fine
for weeks.

---

## Step 12: Final check

```bash
curl -k https://<MY_PUBLIC_HOSTNAME>/api/check/health
# Should return HTTP 200

# Wait ~65 seconds (the federated catalog cycle) and look for errors:
sleep 75
ssh user@YOUR_VM 'docker logs my-connector --since 90s 2>&1 | grep -iE "error|exception"'
# If nothing comes out, perfect.
```

If you want to check real interoperability (negotiate a contract and transfer
data with another existing connector), follow
[docs/47_stics_edc_interop_evidence.md](./47_stics_edc_interop_evidence.md):
it has the exact, already verified `curl` commands for that.

---

## Common errors cheat sheet

| Symptom in the log | What it means | How to fix it |
| --- | --- | --- |
| `ValueError: Invalid connector name '...'. Maximum length is 20 characters` | The connector name is too long | Shorten it, 20 characters maximum |
| `Connection to 127.0.0.1:5432 refused` | The container can't see Postgres | If you use `network_mode: host`, check that Postgres listens there. If you use *bridge*, point to the Docker gateway IP (`172.17.0.1` or similar), not `127.0.0.1` |
| `no pg_hba.conf entry for host "172.x.x.x"` | Postgres rejects the container's IP | Add a `host all all 172.16.0.0/12 md5` line to `pg_hba.conf` and set `listen_addresses='*'`, then restart Postgres |
| `relation "edc_catalog" does not exist` / `"edc_vocabulary" does not exist` | INESData's own tables are missing | Apply the two `.sql` files from Step 9a |
| `<name>: Temporary failure in name resolution` / `No address associated with hostname` (in the crawler) | The participant is registered with a URL that doesn't resolve (internal, or DNS not active yet) | If it's the internal URL → apply Step 9b. If DNS isn't active yet → wait, it fixes itself |
| `PKIX path building failed` / `Failed to get keys from .../certs` | The truststore (`cacerts.jks`) is out of date with respect to the current certificate | Copy a fresh `cacerts.jks` (Step 7) to that connector, and to all others if the certificate was just regenerated |
| `curl` returns `404 page not found` without a `Server:` header | You reached Kubernetes but no Ingress recognizes that host (or wrong cluster) | Check Step 10: does the DNS point where you think? Did you create the Ingress on the right cluster? |
| `curl` returns `503` with `Server: nginx/...` | You got there, but the Service has no healthy backend | Check the `Endpoints` (correct IP and ports, the process really listening there) |
| The request doesn't even appear in the `ingress-nginx-controller` logs | It's not reaching that cluster at all | The DNS probably points to a different machine/gateway than you think |
