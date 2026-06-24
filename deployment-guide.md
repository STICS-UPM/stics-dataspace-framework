# STICS Dataspace Framework Deployment Guide

This guide describes the deployment procedure for the STICS Dataspace Framework and its associated connectors on a freshly provisioned virtual machine.

## Contents

* Prerequisites
* Software Installation
* Kubernetes Installation
* Framework Setup
* Configuration
* Deployment Process
* Vault Management
* Validation
* Troubleshooting

---

# Prerequisites

## Hardware Requirements

### Minimum

* 4 vCPUs
* 8 GB RAM
* 80 GB storage

### Recommended

* 6+ vCPUs
* 16 GB RAM
* 120+ GB SSD

## Operating System

* Ubuntu Server 24.04 LTS (64-bit)

## Network Requirements

The target machine must provide:

* Internet access
* DNS resolution
* External access to HTTP/HTTPS services
* Connectivity to required dataspace components

---

# Software Installation

Update the operating system:

```bash
sudo apt update && sudo apt upgrade -y
```

Install required packages:

```bash
sudo apt install -y \
git \
curl \
wget \
unzip \
python3 \
python3-venv \
python3-pip \
docker.io \
postgresql-client \
nodejs \
npm \
jq
```

---

# Kubernetes Installation

## Install kubectl

```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"

chmod +x kubectl

sudo mv kubectl /usr/local/bin/
```

Verify installation:

```bash
kubectl version --client
```

---

## Install Helm

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

Verify installation:

```bash
helm version
```

---

## Install K3s

```bash
curl -sfL https://get.k3s.io | sh -
```

Configure Kubernetes access:

```bash
sudo chmod 644 /etc/rancher/k3s/k3s.yaml

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
```

Verify cluster status:

```bash
kubectl get nodes
```

Expected output:

```text
NAME       STATUS   ROLES                  AGE
localhost  Ready    control-plane,master
```

---

# Framework Setup

## Clone the Repository

```bash
cd ~

git clone https://github.com/STICS-UPM/stics-dataspace-framework.git

cd stics-dataspace-framework
```

---

## Create a Python Virtual Environment

```bash
python3 -m venv .venv

source .venv/bin/activate

pip install --upgrade pip
```

Install dependencies:

```bash
pip install -r requirements.txt
```

> **Note**
>
> If a different dependency file is used in your deployment branch, update the command accordingly.

---

# DNS Configuration

The framework requires valid domain configuration.

Typical values are:

```text
DOMAIN_BASE=stics.bavenir.eu
DS_DOMAIN_BASE=stics.bavenir.eu
```

If DNS records are not available during testing, temporary entries may be added to:

```bash
/etc/hosts
```

---

# Framework Configuration

Edit:

```bash
deployers/inesdata/deployer.config
```

Required configuration:

```properties
PROFILE_TOPOLOGY=vm-distributed
PROFILE_ADAPTER=inesdata

ENVIRONMENT_NAME=stics

DOMAIN_BASE=stics.bavenir.eu
DS_DOMAIN_BASE=stics.bavenir.eu

VT_URL=http://<vault-host>:8200

VT_TOKEN=<vault-root-token>
```

Additional deployment-specific variables may be required depending on the environment.

---

# Pre-Deployment Validation

Run the framework validation tool:

```bash
python3 main.py doctor
```

Expected status:

```text
ready
```

or

```text
ready_with_warnings
```

No mandatory configuration values should be reported as missing.

---

# Deployment Process

All deployment levels are executed from:

```bash
cd ~/stics-dataspace-framework

source .venv/bin/activate

python3 main.py inesdata
```

The deployment is divided into four sequential levels.

> **Important**
>
> Levels must be executed in order:
>
> Level 1 → Level 2 → Level 3 → Level 4

---

## Level 1 – Environment Preparation

Select:

```text
1
```

Confirm:

```text
Run Level 1? (y/N): y
```

Responsibilities:

* Environment validation
* Dependency checks
* Configuration verification

---

## Level 2 – Common Services Deployment

Select:

```text
2
```

Confirm:

```text
Run Level 2? (y/N): y
```

This level deploys:

* PostgreSQL
* MinIO
* Keycloak
* Vault
* Shared infrastructure services

Namespace:

```text
common-srvs
```

Validate:

```bash
kubectl get pods -n common-srvs
```

Expected Vault initialization logs:

```text
Configuring Vault...
Vault status: initialized=True, sealed=False
Checking KV engine...
KV v2 engine already enabled
```

---

## Level 3 – Dataspace Core Deployment

Select:

```text
3
```

Confirm:

```text
Run Level 3? (y/N): y
```

This level deploys:

* Registration Service
* Strapi Backend
* Dataspace Portal Backend
* Dataspace Portal Frontend
* Ingress resources

Validate:

```bash
kubectl get pods -n core-control
```

All pods should reach the `Running` state.

---

## Level 4 – Connector Deployment

Select:

```text
4
```

Confirm:

```text
Run Level 4? (y/N): y
```

This level deploys:

* Provider Connector
* Consumer Connector
* Connector secrets
* Runtime services

Expected Vault paths:

```text
secret/data/stics/conn-connector-stics/public-key

secret/data/stics/conn-connector-stics/private-key
```

---

# Vault Management

## Expected Behaviour

Vault should be automatically:

* Deployed
* Initialized
* Unsealed
* Configured with KV v2 storage

Manual intervention should only be required in recovery scenarios.

---

## Manual Recovery

Delete Vault resources:

```bash
kubectl delete pvc -n common-srvs data-common-srvs-vault-0

kubectl delete pod -n common-srvs common-srvs-vault-0 \
--force \
--grace-period=0
```

Initialize Vault:

```bash
kubectl exec -it -n common-srvs common-srvs-vault-0 -- \
vault operator init \
-key-shares=1 \
-key-threshold=1 \
-format=json \
-tls-skip-verify
```

Unseal Vault:

```bash
kubectl exec -it -n common-srvs common-srvs-vault-0 -- \
vault operator unseal \
-tls-skip-verify <UNSEAL_KEY>
```

Enable KV v2:

```bash
kubectl exec -it -n common-srvs common-srvs-vault-0 -- \
vault secrets enable \
-path=secret \
kv-v2
```

Update `VT_TOKEN` with the newly generated root token and re-run deployment levels if necessary.

---

# Validation

## Infrastructure Validation

Verify cluster resources:

```bash
kubectl get pods -A
```

Check Vault:

```bash
kubectl exec -it -n common-srvs common-srvs-vault-0 -- \
vault status -tls-skip-verify
```

List namespaces:

```bash
kubectl get ns
```

Check connector pods:

```bash
kubectl get pods -n <connector-namespace>
```

---

## Functional Validation

Verify the complete dataspace workflow:

1. Access Keycloak.
2. Access the Dataspace Portal.
3. Register a participant.
4. Publish an asset.
5. Discover the asset from another participant.
6. Execute a data transfer.
7. Confirm successful transfer completion.

---

# Troubleshooting

## Missing DOMAIN_BASE or DS_DOMAIN_BASE

Symptoms:

* Vault configuration is skipped.
* Deployment partially succeeds.

Resolution:

* Update `deployer.config`.
* Re-run Levels 2–4.

---

## Vault PVC Out of Sync

Symptoms:

* Vault initialization failures.
* Inconsistent Vault state.

Resolution:

* Delete the Vault PVC.
* Reinitialize Vault.
* Update `VT_TOKEN`.
* Re-run deployment levels.

---

## Missing KV v2 Engine

Symptoms:

```text
hvac.exceptions.InvalidPath
```

Resolution:

```bash
vault secrets enable -path=secret kv-v2
```

---

## Connector Deployment Failure

Symptoms:

* Connector pods crash.
* Secret retrieval errors.

Resolution:

* Verify Vault status.
* Verify KV v2 availability.
* Verify connector secrets.
* Verify `VT_TOKEN` configuration.

---

# Main Components

The STICS Dataspace Framework deployment includes:

* PostgreSQL
* MinIO
* Keycloak
* Vault
* Registration Service
* Strapi
* Dataspace Portal
* Provider Connector
* Consumer Connector
