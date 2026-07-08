# STICS Connector Provisioning API

Self-service registration and connector provisioning for the STICS
dataspace, so that adding a new connector no longer requires a UPM operator
to run [`deployment-guide.md`](../deployment-guide.md) by hand for every
client.

## Status

**Increment 1 of 4** (client registration and approval). Connector
provisioning itself is not implemented yet — `POST /v1/connectors`
currently validates the request (name format and uniqueness, DNS already
pointing at the client's VM) and records it, but does not yet call
Keycloak/Vault/MinIO/Kubernetes. See the `TODO` in `app/main.py`.

Planned increments:

1. ✅ Client self-registration with an admin approval gate
2. Connector provisioning for the common case (hostname already covered by
   the shared TLS certificate)
3. TLS certificate regeneration and redistribution, gated behind explicit
   confirmation (this is the one step with blast radius beyond the
   connector being added — see `deployment-guide.md`, Step 11)
4. Containerize and deploy this service itself behind the dataspace's own
   Ingress/TLS

## Why This Exists

Only UPM has SSH access to the STICS common-services VM. Without this API,
every new connector — whether run by UPM or by an external organization —
requires a UPM operator to manually provision identity (Keycloak, Vault,
MinIO, PostgreSQL) and build the Kubernetes bridge described in
`deployment-guide.md`. This API automates that provisioning; the client
still runs Docker Compose on their own machine (this API cannot reach a
client's own infrastructure).

## Running Locally

```bash
cd provisioning-api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PROVISIONING_API_ADMIN_TOKEN=<pick-a-secret> .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8811
```

`PROVISIONING_API_ADMIN_TOKEN` is required — the service refuses to start
without it. It is the single credential used for the `/v1/admin/*`
endpoints and is not tied to any individual client.

## API Overview

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `POST /v1/register` | none | A prospective client submits an email and organization name; receives an API key that is inactive until approved |
| `GET /v1/admin/clients?status=pending` | admin bearer token | List registrations awaiting a decision |
| `POST /v1/admin/clients/{id}/approve` | admin bearer token | Activate a client's API key |
| `POST /v1/admin/clients/{id}/reject` | admin bearer token | Permanently deny a registration |
| `POST /v1/connectors` | client bearer token (approved) | Request a new connector (validated and recorded in this increment; provisioning lands in increment 2) |
| `GET /v1/connectors/{name}/status` | client bearer token (approved) | Check on a previously requested connector |

### Example: End-to-End Registration and Approval

```bash
# 1. Client registers
curl -X POST http://localhost:8811/v1/register \
  -H "Content-Type: application/json" \
  -d '{"email": "ops@example.org", "organization_name": "Example Org"}'
# -> {"client_id": 1, "api_key": "stics_...", "status": "pending", ...}

# 2. A UPM admin reviews and approves
curl -X POST http://localhost:8811/v1/admin/clients/1/approve \
  -H "Authorization: Bearer $PROVISIONING_API_ADMIN_TOKEN"

# 3. The client can now request a connector
curl -X POST http://localhost:8811/v1/connectors \
  -H "Authorization: Bearer stics_..." -H "Content-Type: application/json" \
  -d '{"connector_name": "acme-stics", "public_hostname": "acme.example.org", "target_vm_ip": "203.0.113.10"}'
```

## Design Notes

- `connector_name` is validated against the same 20-character, lowercase,
  alphanumeric-and-hyphens constraint the underlying framework enforces
  (see `deployment-guide.md`, Step 0) — invalid names are rejected before
  anything is provisioned.
- The DNS check in `/v1/connectors` requires `public_hostname` to already
  resolve to the client's declared `target_vm_ip` before proceeding. This
  is deliberate: it is the one precondition this API cannot satisfy on a
  client's behalf (see `dataspace-setup-guide.md`'s note on DNS), so it
  fails fast with a clear message instead of provisioning identity for a
  connector the client cannot yet reach.
- Data lives in a local SQLite file (`data/provisioning.db`, git-ignored).
  This is intentionally simple for the current scale; revisit if this
  service needs to run with multiple replicas.
