"""Authentication for the two distinct trust levels this API exposes.

Client API keys (issued via /v1/register, activated by an admin) authorize
provisioning actions scoped to that client's own connectors. The admin
credential is a single, separately-configured secret with no client-facing
equivalent — it exists only to approve/reject registrations.
"""

import os
import secrets

from fastapi import Header, HTTPException

from . import db


def _admin_token() -> str:
    token = os.environ.get("PROVISIONING_API_ADMIN_TOKEN", "")
    if not token:
        raise RuntimeError(
            "PROVISIONING_API_ADMIN_TOKEN is not set. Refusing to start without an admin credential."
        )
    return token


def require_admin(authorization: str = Header(default="")):
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing bearer admin token")
    if not secrets.compare_digest(token, _admin_token()):
        raise HTTPException(status_code=403, detail="Invalid admin token")


def require_approved_client(authorization: str = Header(default="")):
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing bearer API key")
    client = db.get_client_by_api_key(token)
    if not client:
        raise HTTPException(status_code=403, detail="Unknown API key")
    if client["status"] != "approved":
        raise HTTPException(status_code=403, detail=f"Client status is '{client['status']}', not approved")
    return client
