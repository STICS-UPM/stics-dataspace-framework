# Script: Deploying the Validation Environment
# Goal: Show how an environment is created from scratch

---

## BLOCK 0 — Introduction (1 min)

**Say:**
> "In this video we are going to deploy a validation environment from
> scratch using the framework. We'll look at the configuration assistant
> and levels 1 to 5: infrastructure, common services, dataspace,
> connectors, and components."

---

## BLOCK 1 — The assistant: configuring the environment (3 min)

**Say:**
> "The first step is to configure the environment using the framework's
> interactive assistant."

**Run:**
```bash
python3 main.py
```

**In the main menu:**
- Select the `inesdata` adapter
- Press `W` → opens the VM-DISTRIBUTED ASSISTANT

**Say:**
> "The assistant guides us through defining the VM IPs, the domains, SSH
> access, and the dataspace inventory. Let's go to option 1."

**Press `1`**

**Say while filling it in:**
> "We define the IP of the common services VM, the provider's and the
> consumer's. The base domain all URLs will derive from. SSH access through
> the bastion. And the connectors and components we want to deploy."

**Confirm at the end with Enter**

**Say:**
> "The assistant has generated three local configuration files. Let's take
> a look at them."

**Show:**
```bash
cat deployers/infrastructure/deployer.config
```

**Point out:**
```
VM_COMMON_IP=192.168.122.64       # common services VM — org1
VM_PROVIDER_IP=192.168.122.134    # provider VM — org2
VM_CONSUMER_IP=192.168.122.9      # consumer VM — org3
DOMAIN_BASE=pionera.oeg.fi.upm.es # base domain for all URLs
```

```bash
cat deployers/infrastructure/topologies/vm-distributed.config
```

**Point out:**
```
SSH_BASTION_HOST=orion.dia.fi.upm.es    # SSH bastion
K3S_KUBECONFIG_PROVIDER=~/.kube/pionera20.yaml
K3S_KUBECONFIG_CONSUMER=~/.kube/pionera3.yaml
VM_PROVIDER_PUBLIC_URL=https://org2.pionera.oeg.fi.upm.es
VM_CONSUMER_PUBLIC_URL=https://org3.pionera.oeg.fi.upm.es
```

```bash
cat deployers/inesdata/deployer.config
```

**Point out:**
```
DS_1_NAME=pionera
DS_1_CONNECTORS=org2,org3
COMPONENTS=ontology-hub,ai-model-hub,semantic-virtualization
KEYCLOAK_FRONTEND_URL=https://org1.pionera.oeg.fi.upm.es/auth
MINIO_CONSOLE_PUBLIC_URL=https://org1.pionera.oeg.fi.upm.es/s3-console
COMPONENTS_PUBLIC_BASE_URL=https://org1.pionera.oeg.fi.upm.es
```

**Say:**
> "These three files are local and ignored by git. They fully define the
> environment: where the VMs are, how to access them, which connectors to
> deploy, and which components to enable."

---

## BLOCK 2 — Level 1: Infrastructure preflight (2 min)

**Say:**
> "With the configuration ready, we start the deployment. Level 1 in the
> vm-distributed topology doesn't install anything. It runs read-only
> checks on the cluster: kubectl, helm, nodes, ingress, and storage."

**Run:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 1
```

**Say while it runs:**
> "It checks that kubectl and helm are available, that the cluster
> responds, that there are ready nodes, and that an nginx IngressClass
> exists."

**When it finishes, show:**
```bash
kubectl --kubeconfig ~/.kube/pionera40.yaml get nodes
kubectl --kubeconfig ~/.kube/pionera40.yaml get ingressclass
kubectl --kubeconfig ~/.kube/pionera40.yaml get storageclass
```

---

## BLOCK 3 — Level 2: Common services (3 min)

**Say:**
> "Level 2 deploys the common services: Keycloak for identity, MinIO for
> object storage, PostgreSQL for databases, and Vault for secret
> management."

**Run:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 2
```

**Say while it runs:**
> "It syncs the configuration, builds the Helm dependencies, deploys the
> chart, and waits until all services are up. At the end it configures
> Vault automatically."

**When it finishes:**
```bash
kubectl --kubeconfig ~/.kube/pionera40.yaml get pods -n common-srvs
```

**Open the browser:**
- `https://org1.pionera.oeg.fi.upm.es/auth` → Keycloak
- `https://org1.pionera.oeg.fi.upm.es/s3-console` → MinIO Console

---

## BLOCK 4 — Level 3: Dataspace (2 min)

**Say:**
> "Level 3 creates the dataspace. It deploys the registration-service and
> registers the dataspace in Keycloak and PostgreSQL."

**Run:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 3
```

**When it finishes:**
```bash
kubectl --kubeconfig ~/.kube/pionera40.yaml get pods -n core-control
```

**Say:**
> "The registration-service manages the dataspace participants and the
> access policies."

---

## BLOCK 5 — Level 4: Connectors (4 min)

**Say:**
> "Level 4 deploys the INESData connectors. We have two: org2 on the
> provider VM and org3 on the consumer VM. The framework generates unique
> credentials for each one in Keycloak, Vault, and PostgreSQL, builds the
> Docker image, transfers it to the corresponding VM, and deploys it with
> Helm."

**Run:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 4
```

**When it finishes:**
```bash
kubectl --kubeconfig ~/.kube/pionera20.yaml get pods -n provider
kubectl --kubeconfig ~/.kube/pionera3.yaml get pods -n consumer
```

**Show the credentials file:**
```bash
cat deployers/inesdata/deployments/DEV/pionera/credentials-connector-conn-org2-pionera.json
```

**Point out:**
```json
"connector_user": { "user": "...", "passwd": "..." },
"vault":          { "token": "...", "path": "..." },
"minio":          { "access_key": "...", "secret_key": "..." },
"public_access_urls": {
    "connector_interface_login": "https://org2.pionera.oeg.fi.upm.es/inesdata-connector-interface/"
}
```

**Say:**
> "The framework stores the generated credentials in this JSON file. It is
> the reference point for accessing the connector APIs."

**Open the browser:**
- `https://org2.pionera.oeg.fi.upm.es/inesdata-connector-interface/`
- `https://org3.pionera.oeg.fi.upm.es/inesdata-connector-interface/`

---

## BLOCK 6 — Level 5: Components (3 min)

**Say:**
> "Level 5 deploys the optional dataspace components: Ontology Hub, AI
> Model Hub, and Semantic Virtualization. They are all exposed on org1
> under path-based routes."

**Run:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 5
```

**When it finishes:**
```bash
kubectl --kubeconfig ~/.kube/pionera40.yaml get pods -n components
```

**Open the browser:**
- `https://org1.pionera.oeg.fi.upm.es/ontology-hub`
- `https://org1.pionera.oeg.fi.upm.es/ai-model-hub`
- `https://org1.pionera.oeg.fi.upm.es/semantic-virtualization`

---

## BLOCK 7 — Wrap-up: domain parameterization (1 min)

**Show again:**
```bash
grep -E "DOMAIN_BASE|VM_.*PUBLIC_URL|COMPONENTS_PUBLIC_BASE" deployers/infrastructure/deployer.config
grep -E "DOMAIN_BASE|VM_.*PUBLIC_URL|COMPONENTS_PUBLIC_BASE" deployers/infrastructure/topologies/vm-distributed.config
```

**Say:**
> "Everything we've seen (the Keycloak, MinIO, connector, and component
> URLs) derives from the base domain and the IPs configured at the
> beginning. To deploy the same environment on other infrastructure, just
> change these values in the assistant and repeat the levels."

---

## ESTIMATED LENGTH: 20-25 minutes

## NOTES BEFORE RECORDING

- Empty the 3 deployer.config files before recording so the assistant has
  something visible to configure
- Level 2 can take 5-8 min to start Keycloak; plan a cut or record in real
  time
- The credentials in the JSON change with every deploy; this is normal,
  mention it in the video
- Have the browser preconfigured with the URLs before recording
