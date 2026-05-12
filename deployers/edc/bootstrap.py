#!/usr/bin/env python3
"""Native bootstrap helper for generic EDC connector prerequisites.

This helper intentionally implements only the connector bootstrap contract that
the EDC adapter needs: create/delete connector credentials, certificates,
Keycloak objects, Vault secrets, MinIO policy files, and registration-service
participants. Helm values are rendered by the adapter itself.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import urllib3

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from deployers.infrastructure.lib.public_hostnames import (  # noqa: E402
    clean_public_hostname,
    resolved_common_service_hostnames,
)
from deployers.infrastructure.lib.config_loader import (  # noqa: E402
    apply_pionera_environment_overrides,
    resolve_deployer_config_layer_paths,
)
from deployers.infrastructure.lib.topology import normalize_topology  # noqa: E402


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def deployment_root() -> Path:
    return Path(__file__).resolve().parent


def read_config_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _default_bootstrap_values() -> dict[str, str]:
    return {
        "ENVIRONMENT": "DEV",
        "PG_HOST": "localhost",
        "PG_PORT": "5432",
        "PG_USER": "postgres",
        "PG_PASSWORD": "aPassword1234",
        "KC_URL": "http://localhost:8080",
        "KC_USER": "admin",
        "KC_PASSWORD": "aPassword1234",
        "VT_URL": "http://localhost:8200",
        "VT_TOKEN": "rt.0000000000000",
    }


def _active_bootstrap_topology() -> str:
    return normalize_topology(os.getenv("PIONERA_TOPOLOGY") or "local")


def load_config(topology: str | None = None) -> dict[str, str]:
    root = project_root()
    resolved_topology = normalize_topology(topology or _active_bootstrap_topology())
    values: dict[str, str] = {}
    # Transitional fallback keeps existing local environments working until the
    # shared infrastructure config is materialized.
    for path in resolve_deployer_config_layer_paths(
        str(root / "deployers" / "inesdata" / "deployer.config"),
        topology=resolved_topology,
    ):
        values.update(read_config_file(Path(path)))
    values.update(_default_bootstrap_values())
    for path in resolve_deployer_config_layer_paths(
        str(root / "deployers" / "infrastructure" / "deployer.config"),
        topology=resolved_topology,
    ):
        values.update(read_config_file(Path(path)))
    for path in resolve_deployer_config_layer_paths(
        str(root / "deployers" / "edc" / "deployer.config"),
        topology=resolved_topology,
    ):
        values.update(read_config_file(Path(path)))
    for path in resolve_deployer_config_layer_paths(
        str(deployment_root() / "deployer.config"),
        topology=resolved_topology,
    ):
        values.update(read_config_file(Path(path)))
    return apply_pionera_environment_overrides(values)


def random_token(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def runtime_dir(environment: str, dataspace: str) -> Path:
    path = deployment_root() / "deployments" / environment / dataspace
    path.mkdir(parents=True, exist_ok=True)
    return path


def credentials_path(environment: str, dataspace: str, source_type: str, name: str) -> Path:
    return runtime_dir(environment, dataspace) / f"credentials-{source_type}-{name}.json"


def write_credentials(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=4), encoding="utf-8")


def read_credentials(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8") or "{}")


def update_credentials(environment: str, dataspace: str, source_type: str, name: str, key: str, value: dict) -> None:
    path = credentials_path(environment, dataspace, source_type, name)
    payload = read_credentials(path)
    payload[key] = value
    write_credentials(path, payload)


def build_connector_access_urls(config: dict[str, str], connector: str, dataspace: str, environment: str) -> dict[str, str]:
    protocol = access_protocol(environment)
    ds_domain = dataspace_domain_base(config, environment)
    connector_base = f"{protocol}://{connector}.{ds_domain}"
    urls = {
        "connector_ingress": connector_base,
        "connector_management_api": f"{connector_base}/management",
        "connector_management_api_v3": f"{connector_base}/management/v3",
        "connector_protocol_api": f"{connector_base}/protocol",
        "connector_default_api": f"{connector_base}/api",
        "connector_control_api": f"{connector_base}/control",
        "minio_bucket": f"{dataspace}-{connector}",
    }
    if as_bool(config.get("EDC_DASHBOARD_ENABLED", "true")):
        dashboard_base_href = normalize_base_href(config.get("EDC_DASHBOARD_BASE_HREF", "/edc-dashboard/"))
        urls["edc_dashboard_login"] = f"{connector_base}{dashboard_base_href}"
        if str(config.get("EDC_DASHBOARD_PROXY_AUTH_MODE", "")).strip().lower() == "oidc-bff":
            urls["edc_dashboard_oidc_login"] = f"{connector_base}/edc-dashboard-api/auth/login"
    urls.update(common_access_urls(config, dataspace, environment))
    return urls


def common_access_urls(config: dict[str, str], dataspace: str, environment: str) -> dict[str, str]:
    protocol = access_protocol(environment)
    resolved_hostnames = resolved_common_service_hostnames(config)
    keycloak_hostname = resolved_hostnames["keycloak_hostname"]
    keycloak_admin_hostname = resolved_hostnames["keycloak_admin_hostname"]
    minio_api_hostname = resolved_hostnames["minio_hostname"]
    minio_console_hostname = resolved_hostnames["minio_console_hostname"]
    return {
        "keycloak_realm": f"{protocol}://{keycloak_hostname}/realms/{dataspace}",
        "keycloak_account": f"{protocol}://{keycloak_hostname}/realms/{dataspace}/account",
        "keycloak_admin_console": f"{protocol}://{keycloak_admin_hostname}/admin/{dataspace}/console/",
        "minio_api": f"{protocol}://{minio_api_hostname}",
        "minio_console": f"{protocol}://{minio_console_hostname}",
    }


def access_protocol(environment: str) -> str:
    return "https" if str(environment or "").strip().upper() == "PRO" else "http"


def dataspace_domain_base(config: dict[str, str], environment: str) -> str:
    if str(environment or "").strip().upper() == "PRO":
        return "ds.dataspaceunit-project.eu"
    configured = str(config.get("DS_DOMAIN_BASE", "")).strip()
    return configured or "dev.ds.dataspaceunit.upm"


def clean_hostname(value: str | None) -> str:
    return clean_public_hostname(value)


def normalize_base_href(value: str | None) -> str:
    base_href = str(value or "/edc-dashboard/").strip() or "/edc-dashboard/"
    if not base_href.startswith("/"):
        base_href = f"/{base_href}"
    if not base_href.endswith("/"):
        base_href = f"{base_href}/"
    return base_href


def as_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def run_psql(config: dict[str, str], sql: str, database: str = "postgres", capture: bool = False) -> str:
    env = os.environ.copy()
    env["PGPASSWORD"] = config.get("PG_PASSWORD", "")
    command = [
        "psql",
        "-h",
        config.get("PG_HOST", "localhost"),
        "-p",
        str(config.get("PG_PORT", "5432")),
        "-U",
        config.get("PG_USER", "postgres"),
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    ]
    result = subprocess.run(
        command,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "psql command failed"
        raise RuntimeError(message)
    return (result.stdout or "").strip()


def create_database(config: dict[str, str], database: str, username: str, password: str) -> None:
    role_sql = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {sql_literal(username)}) THEN
        CREATE ROLE {sql_identifier(username)} LOGIN PASSWORD {sql_literal(password)};
    ELSE
        ALTER ROLE {sql_identifier(username)} WITH LOGIN PASSWORD {sql_literal(password)};
    END IF;
END
$$;
"""
    run_psql(config, role_sql)
    exists = run_psql(
        config,
        f"SELECT 1 FROM pg_database WHERE datname = {sql_literal(database)};",
        capture=True,
    )
    if "1" not in exists:
        run_psql(config, f"CREATE DATABASE {sql_identifier(database)};")
    run_psql(config, f"ALTER DATABASE {sql_identifier(database)} OWNER TO {sql_identifier(username)};")
    run_psql(
        config,
        f"GRANT ALL PRIVILEGES ON DATABASE {sql_identifier(database)} TO {sql_identifier(username)};",
    )


def register_connector_database(config: dict[str, str], connector: str, dataspace: str, environment: str) -> None:
    database = f"{dataspace.replace('-', '_')}_rs"
    protocol = (
        f"https://{connector}-{dataspace}.ds.dataspaceunit-project.eu/protocol"
        if environment == "PRO"
        else f"http://{connector}:19194/protocol"
    )
    shared = (
        f"https://{connector}-{dataspace}.ds.dataspaceunit-project.eu/shared"
        if environment == "PRO"
        else f"http://{connector}:19196/shared"
    )
    sql = (
        "DELETE FROM public.edc_participant "
        f"WHERE participant_id = {sql_literal(connector)}; "
        "INSERT INTO public.edc_participant (participant_id, url, created_at, shared_url) "
        f"VALUES ({sql_literal(connector)}, {sql_literal(protocol)}, "
        f"EXTRACT(EPOCH FROM NOW())::BIGINT, {sql_literal(shared)});"
    )
    run_psql(config, sql, database=database)


def generate_certificates(connector: str, password: str, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    private_key = target_dir / f"{connector}-private.key"
    public_cert = target_dir / f"{connector}-public.crt"
    pkcs12 = target_dir / f"{connector}-store.p12"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-out", str(private_key)], check=True)
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-key",
            str(private_key),
            "-out",
            str(public_cert),
            "-days",
            "720",
            "-subj",
            f"/C=ES/ST=CM/L=Madrid/O=UPM/CN={connector}.upm.es",
        ],
        check=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkcs12",
            "-export",
            "-out",
            str(pkcs12),
            "-inkey",
            str(private_key),
            "-in",
            str(public_cert),
            "-password",
            f"pass:{password}",
        ],
        check=True,
    )


class KeycloakAdmin:
    def __init__(self, config: dict[str, str], realm: str):
        self.base_url = config.get("KC_URL", "http://localhost:8080").rstrip("/")
        self.realm = realm
        token_response = requests.post(
            f"{self.base_url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": config.get("KC_USER", "admin"),
                "password": config.get("KC_PASSWORD", "aPassword1234"),
            },
            timeout=30,
            verify=False,
        )
        token_response.raise_for_status()
        self.token = token_response.json()["access_token"]

    def request(self, method: str, path: str, allowed_statuses: set[int] | None = None, **kwargs) -> requests.Response:
        allowed_statuses = allowed_statuses or set()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.token}"
        response = requests.request(
            method,
            f"{self.base_url}/admin/realms/{self.realm}{path}",
            headers=headers,
            timeout=30,
            verify=False,
            **kwargs,
        )
        if response.status_code >= 400 and response.status_code not in allowed_statuses:
            raise RuntimeError(f"Keycloak {method} {path} failed with HTTP {response.status_code}: {response.text}")
        return response

    def maybe_get(self, path: str) -> dict | None:
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(
            f"{self.base_url}/admin/realms/{self.realm}{path}",
            headers=headers,
            timeout=30,
            verify=False,
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise RuntimeError(f"Keycloak GET {path} failed with HTTP {response.status_code}: {response.text}")
        return response.json() if response.text else {}

    def ensure_role(self, name: str, connector_role: bool = False) -> dict:
        role = self.maybe_get(f"/roles/{name}")
        if role is None:
            payload: dict[str, object] = {"name": name}
            if connector_role:
                payload["attributes"] = {
                    "connector": [name],
                    "connector-type": ["dataspaceunit-connector"],
                }
            self.request("POST", "/roles", json=payload)
            role = self.maybe_get(f"/roles/{name}")
        if role is None:
            raise RuntimeError(f"Keycloak role was not created: {name}")
        return role

    def find_group(self, name: str) -> dict | None:
        response = self.request("GET", "/groups", params={"search": name})
        for group in response.json():
            if group.get("name") == name:
                return group
        return None

    def ensure_group(self, name: str, roles: list[dict]) -> dict:
        group = self.find_group(name)
        if group is None:
            self.request("POST", "/groups", json={"name": name})
            group = self.find_group(name)
        if group is None:
            raise RuntimeError(f"Keycloak group was not created: {name}")
        self.request(
            "POST",
            f"/groups/{group['id']}/role-mappings/realm",
            json=roles,
            allowed_statuses={409},
        )
        return group

    def ensure_user(self, username: str, password: str, group_id: str) -> None:
        response = self.request("GET", "/users", params={"username": username, "exact": "true"})
        users = response.json()
        if users:
            user_id = users[0]["id"]
        else:
            self.request(
                "POST",
                "/users",
                json={
                    "username": username,
                    "email": f"{username}@dataspaceunit.com",
                    "firstName": username,
                    "lastName": username,
                    "enabled": True,
                    "emailVerified": True,
                },
            )
            users = self.request("GET", "/users", params={"username": username, "exact": "true"}).json()
            if not users:
                raise RuntimeError(f"Keycloak user was not created: {username}")
            user_id = users[0]["id"]
        self.request(
            "PUT",
            f"/users/{user_id}/reset-password",
            json={"type": "password", "value": password, "temporary": False},
        )
        self.request("PUT", f"/users/{user_id}/groups/{group_id}", allowed_statuses={409})

    def ensure_client(self, client_id: str, cert_path: Path) -> None:
        response = self.request("GET", "/clients", params={"clientId": client_id})
        clients = response.json()
        if not clients:
            self.request(
                "POST",
                "/clients",
                json={
                    "clientId": client_id,
                    "name": client_id,
                    "description": f"Client for connector {client_id}",
                    "protocol": "openid-connect",
                    "redirectUris": ["*"],
                    "webOrigins": ["*"],
                    "publicClient": False,
                    "enabled": True,
                    "serviceAccountsEnabled": True,
                    "directAccessGrantsEnabled": True,
                    "clientAuthenticatorType": "client-jwt",
                    "attributes": {
                        "frontchannel.logout": True,
                        "backchannel.logout.session.required": True,
                    },
                    "defaultClientScopes": [
                        "dataspaceunit-dataspace-audience",
                        "dataspaceunit-nbf-claim",
                        "profile",
                        "email",
                        "acr",
                    ],
                },
            )
            clients = self.request("GET", "/clients", params={"clientId": client_id}).json()
        if not clients:
            raise RuntimeError(f"Keycloak client was not created: {client_id}")
        internal_id = clients[0]["id"]
        with cert_path.open("rb") as handle:
            response = requests.post(
                f"{self.base_url}/admin/realms/{self.realm}/clients/{internal_id}/certificates/jwt.credential/upload-certificate",
                headers={"Authorization": f"Bearer {self.token}"},
                data={"keystoreFormat": "Certificate PEM"},
                files={"file": (cert_path.name, handle, "application/x-x509-ca-cert")},
                timeout=30,
                verify=False,
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Keycloak certificate upload failed for {client_id} with HTTP {response.status_code}: {response.text}"
            )

    def delete_connector_objects(self, connector: str) -> None:
        username = f"user-{connector}"
        users = self.request("GET", "/users", params={"username": username, "exact": "true"}).json()
        for user in users:
            self.request("DELETE", f"/users/{user['id']}")
        clients = self.request("GET", "/clients", params={"clientId": connector}).json()
        for client in clients:
            self.request("DELETE", f"/clients/{client['id']}")
        group = self.find_group(connector)
        if group:
            self.request("DELETE", f"/groups/{group['id']}")
        role = self.maybe_get(f"/roles/{connector}")
        if role:
            self.request("DELETE", f"/roles-by-id/{role['id']}")


def configure_keycloak(config: dict[str, str], connector: str, dataspace: str, environment: str) -> None:
    admin = KeycloakAdmin(config, realm=dataspace)
    connector_user_role = admin.ensure_role("connector-user")
    connector_role = admin.ensure_role(connector, connector_role=True)
    group = admin.ensure_group(
        connector,
        [
            {"id": connector_role["id"], "name": connector_role["name"]},
            {"id": connector_user_role["id"], "name": connector_user_role["name"]},
        ],
    )
    username = f"user-{connector}"
    password = random_token(16)
    admin.ensure_user(username, password, group["id"])
    update_credentials(
        environment,
        dataspace,
        "connector",
        connector,
        "connector_user",
        {"user": username, "passwd": password},
    )
    cert_path = runtime_dir(environment, dataspace) / "certs" / f"{connector}-public.crt"
    admin.ensure_client(connector, cert_path)


def configure_vault(config: dict[str, str], connector: str, dataspace: str, environment: str) -> None:
    vault_url = config.get("VT_URL", "http://localhost:8200").rstrip("/")
    token = config.get("VT_TOKEN", "")
    headers = {"X-Vault-Token": token}
    policy_name = f"{connector}-secrets-policy"
    policy = f"""
path "secret/data/{dataspace}/{connector}/*" {{
    capabilities = ["create", "read", "update", "list", "delete"]
}}
"""
    response = requests.put(
        f"{vault_url}/v1/sys/policies/acl/{policy_name}",
        headers=headers,
        json={"policy": policy},
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    response = requests.post(
        f"{vault_url}/v1/auth/token/create",
        headers=headers,
        json={"period": "768h", "policies": [policy_name], "renewable": True},
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    user_token = response.json()["auth"]["client_token"]
    update_credentials(
        environment,
        dataspace,
        "connector",
        connector,
        "vault",
        {"token": user_token, "path": f"secret/data/{dataspace}/{connector}/"},
    )

    cert_dir = runtime_dir(environment, dataspace) / "certs"
    secrets_payload = {
        f"{dataspace}/{connector}/public-key": (cert_dir / f"{connector}-public.crt").read_text(encoding="utf-8"),
        f"{dataspace}/{connector}/private-key": (cert_dir / f"{connector}-private.key").read_text(encoding="utf-8"),
        f"{dataspace}/{connector}/aws-access-key": random_token(16),
        f"{dataspace}/{connector}/aws-secret-key": random_token(40),
    }
    for path, content in secrets_payload.items():
        response = requests.post(
            f"{vault_url}/v1/secret/data/{path}",
            headers=headers,
            json={"data": {"content": content}},
            timeout=30,
            verify=False,
        )
        response.raise_for_status()
    update_credentials(
        environment,
        dataspace,
        "connector",
        connector,
        "minio",
        {
            "access_key": secrets_payload[f"{dataspace}/{connector}/aws-access-key"],
            "secret_key": secrets_payload[f"{dataspace}/{connector}/aws-secret-key"],
            "user": connector,
            "passwd": random_token(16),
        },
    )


def create_minio_policy(connector: str, dataspace: str, environment: str) -> None:
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:*"],
                "Resource": [
                    f"arn:aws:s3:::{dataspace}-{connector}",
                    f"arn:aws:s3:::{dataspace}-{connector}/*",
                ],
            }
        ],
    }
    policy_path = runtime_dir(environment, dataspace) / f"policy-{dataspace}-{connector}.json"
    policy_path.write_text(json.dumps(policy, indent=4), encoding="utf-8")


def create_connector(args: argparse.Namespace) -> int:
    config = load_config()
    environment = config.get("ENVIRONMENT", "DEV").strip().upper() or "DEV"
    connector = args.name
    dataspace = args.dataspace

    print(f"Creating EDC connector prerequisites for {connector} in dataspace {dataspace}")
    creds_path = credentials_path(environment, dataspace, "connector", connector)
    write_credentials(creds_path, {})

    database_password = random_token(16)
    database_name = connector.replace("-", "_")
    print(f"- Creating database credentials for {connector}")
    create_database(config, database_name, database_name, database_password)
    update_credentials(
        environment,
        dataspace,
        "connector",
        connector,
        "database",
        {"name": database_name, "user": database_name, "passwd": database_password},
    )

    print(f"- Generating certificates for {connector}")
    certificate_password = random_token(16)
    cert_dir = runtime_dir(environment, dataspace) / "certs"
    generate_certificates(connector, certificate_password, cert_dir)
    update_credentials(
        environment,
        dataspace,
        "connector",
        connector,
        "certificates",
        {"path": str(cert_dir.relative_to(project_root())), "passwd": certificate_password},
    )

    print(f"- Configuring Keycloak objects for {connector}")
    configure_keycloak(config, connector, dataspace, environment)

    print(f"- Configuring Vault secrets for {connector}")
    configure_vault(config, connector, dataspace, environment)

    print(f"- Writing MinIO policy for {connector}")
    create_minio_policy(connector, dataspace, environment)

    print(f"- Registering participant for {connector}")
    register_connector_database(config, connector, dataspace, environment)

    update_credentials(
        environment,
        dataspace,
        "connector",
        connector,
        "access_urls",
        build_connector_access_urls(config, connector, dataspace, environment),
    )

    print(f"EDC connector prerequisites created for {connector}")
    return 0


def delete_connector(args: argparse.Namespace) -> int:
    config = load_config()
    connector = args.name
    dataspace = args.dataspace
    print(f"Deleting EDC connector prerequisites for {connector} in dataspace {dataspace}")
    try:
        KeycloakAdmin(config, realm=dataspace).delete_connector_objects(connector)
    except Exception as exc:  # best effort, cleanup continues in the adapter
        print(f"Warning: Keycloak cleanup did not complete for {connector}: {exc}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Native EDC deployment helper")
    subparsers = parser.add_subparsers(dest="resource", required=True)

    connector_parser = subparsers.add_parser("connector")
    connector_subparsers = connector_parser.add_subparsers(dest="action", required=True)

    create_parser = connector_subparsers.add_parser("create")
    create_parser.add_argument("name")
    create_parser.add_argument("dataspace")
    create_parser.set_defaults(func=create_connector)

    delete_parser = connector_subparsers.add_parser("delete")
    delete_parser.add_argument("name")
    delete_parser.add_argument("dataspace")
    delete_parser.set_defaults(func=delete_connector)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
