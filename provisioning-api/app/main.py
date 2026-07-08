"""STICS connector provisioning API.

Increment 1 (this file, current scope): client self-registration with an
admin approval gate, and request validation/bookkeeping for connector
requests. Increment 2 will wire /v1/connectors into the framework's actual
provisioning functions (Keycloak/Vault/MinIO/Postgres/Kubernetes bridge) —
see the TODO in `request_connector` below. Until then, that endpoint
validates and records the request but does not provision anything.
"""

import socket

from fastapi import Depends, FastAPI, HTTPException

from . import db
from .auth import require_admin, require_approved_client
from .models import (
    ClientSummary,
    ConnectorRequest,
    ConnectorStatus,
    RegisterRequest,
    RegisterResponse,
)

app = FastAPI(title="STICS Connector Provisioning API", version="0.1.0")


@app.on_event("startup")
def _startup():
    db.init_db()


@app.post("/v1/register", response_model=RegisterResponse)
def register(payload: RegisterRequest):
    if db.get_client_by_email(payload.email):
        raise HTTPException(status_code=409, detail="This email is already registered")
    client_id, api_key = db.create_client(payload.email, payload.organization_name)
    return RegisterResponse(
        client_id=client_id,
        api_key=api_key,
        status="pending",
        message=(
            "Registration received. Save this API key now — it is not shown again. "
            "It will not work until a STICS administrator approves your account."
        ),
    )


@app.get("/v1/admin/clients", response_model=list[ClientSummary])
def list_clients(status: str | None = None, _admin=Depends(require_admin)):
    return db.list_clients(status=status)


@app.post("/v1/admin/clients/{client_id}/approve")
def approve_client(client_id: int, _admin=Depends(require_admin)):
    db.set_client_status(client_id, "approved")
    return {"client_id": client_id, "status": "approved"}


@app.post("/v1/admin/clients/{client_id}/reject")
def reject_client(client_id: int, _admin=Depends(require_admin)):
    db.set_client_status(client_id, "rejected")
    return {"client_id": client_id, "status": "rejected"}


def _hostname_resolves_to(hostname: str, expected_ip: str) -> bool:
    try:
        resolved = socket.gethostbyname(hostname)
    except socket.gaierror:
        return False
    return resolved == expected_ip


@app.post("/v1/connectors", response_model=ConnectorStatus)
def request_connector(payload: ConnectorRequest, client=Depends(require_approved_client)):
    if db.get_connector_by_name(payload.connector_name):
        raise HTTPException(status_code=409, detail="This connector_name is already taken")

    if not _hostname_resolves_to(payload.public_hostname, payload.target_vm_ip):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{payload.public_hostname} does not currently resolve to {payload.target_vm_ip}. "
                "Create the DNS record first, then retry."
            ),
        )

    db.create_connector_request(
        client["id"], payload.connector_name, payload.public_hostname, payload.target_vm_ip
    )

    # TODO (increment 2): call into the framework's provisioning functions:
    #   - Keycloak client, Vault key pair, MinIO bucket + scoped policy, registration-service entry
    #   - Postgres database (only if target_vm_ip is a UPM-managed VM we hold SSH access to)
    #   - Check whether public_hostname is already covered by the shared TLS certificate's SAN list;
    #     if not, and payload.confirm_tls_regeneration is not True, return 409 asking for confirmation
    #     instead of proceeding (this is the step with blast radius beyond this one connector)
    #   - Build the Kubernetes Service/Endpoints/Ingress bridge pointing at target_vm_ip
    #   - Assemble and return the deployable bundle (.properties, docker-compose.yml,
    #     credentials.json, cacerts.jks) instead of just recording the request
    db.set_connector_status(payload.connector_name, "requested", detail="Provisioning not yet implemented (increment 2)")

    return ConnectorStatus(
        connector_name=payload.connector_name,
        public_hostname=payload.public_hostname,
        status="requested",
        detail="Recorded. Provisioning itself is not implemented yet.",
    )


@app.get("/v1/connectors/{connector_name}/status", response_model=ConnectorStatus)
def connector_status(connector_name: str, client=Depends(require_approved_client)):
    row = db.get_connector_by_name(connector_name)
    if not row or row["client_id"] != client["id"]:
        raise HTTPException(status_code=404, detail="Unknown connector_name for this client")
    return ConnectorStatus(
        connector_name=row["connector_name"],
        public_hostname=row["public_hostname"],
        status=row["status"],
        detail=row["detail"] or "",
    )
