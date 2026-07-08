"""SQLite storage for registered clients and provisioned connectors.

Kept deliberately simple (stdlib sqlite3, no ORM): this service manages a
handful of rows, not a high-throughput dataset.
"""

import hashlib
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "provisioning.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    organization_name TEXT NOT NULL,
    api_key_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    created_at REAL NOT NULL,
    approved_at REAL
);

CREATE TABLE IF NOT EXISTS connectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    connector_name TEXT NOT NULL UNIQUE,
    public_hostname TEXT NOT NULL,
    target_vm_ip TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested',  -- requested | provisioned | failed
    created_at REAL NOT NULL,
    detail TEXT
);
"""


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return "stics_" + secrets.token_urlsafe(32)


def create_client(email: str, organization_name: str) -> tuple[int, str]:
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO clients (email, organization_name, api_key_hash, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (email, organization_name, key_hash, time.time()),
        )
        client_id = cur.lastrowid
    return client_id, raw_key


def get_client_by_api_key(raw_key: str):
    key_hash = hash_api_key(raw_key)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM clients WHERE api_key_hash = ?", (key_hash,)
        ).fetchone()
    return dict(row) if row else None


def get_client_by_email(email: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM clients WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def list_clients(status: str | None = None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM clients WHERE status = ? ORDER BY created_at", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM clients ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def set_client_status(client_id: int, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE clients SET status = ?, approved_at = ? WHERE id = ?",
            (status, time.time() if status == "approved" else None, client_id),
        )


def create_connector_request(client_id: int, connector_name: str, public_hostname: str, target_vm_ip: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO connectors (client_id, connector_name, public_hostname, target_vm_ip, status, created_at) "
            "VALUES (?, ?, ?, ?, 'requested', ?)",
            (client_id, connector_name, public_hostname, target_vm_ip, time.time()),
        )
        connector_id = cur.lastrowid
    return connector_id


def get_connector_by_name(connector_name: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM connectors WHERE connector_name = ?", (connector_name,)
        ).fetchone()
    return dict(row) if row else None


def set_connector_status(connector_name: str, status: str, detail: str = ""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE connectors SET status = ?, detail = ? WHERE connector_name = ?",
            (status, detail, connector_name),
        )


def list_connectors_for_client(client_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM connectors WHERE client_id = ? ORDER BY created_at", (client_id,)
        ).fetchall()
    return [dict(r) for r in rows]
