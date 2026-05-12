
# Deploy an Dataspaceunit Platform
# - Deploy common services
#   - Deploy common Helm chart, gerating and/or retrieving secrets

# Deploy a dataspace
# - Configure Keycloak Realm
#   - Create Realm
# - Create portal-backend (strapi) database in Postgres
# - Deploy dataspace Helm chart (portal-backend and frontend)

# Deploy a connector in a dataspace
# - Configure Keycloak Client and users in Realm
# - Create bucket in Minio
# - Create database in POstgres (currently in connector initContainer)
# - Deploy connector Helm chart


# WARNING: Script in draft state

import click
import psycopg2
from psycopg2 import sql
from keycloak import KeycloakAdmin,KeycloakOpenID
from keycloak.exceptions import KeycloakGetError,KeycloakPostError
import json
import os
import requests
import sys
import urllib3
import warnings

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from deployers.infrastructure.lib.config_loader import (
    INFRASTRUCTURE_MANAGED_KEYS,
    load_layered_deployer_config,
)
from deployers.infrastructure.lib.public_hostnames import (
    clean_public_hostname,
    resolved_common_service_hostnames,
)
from deployers.infrastructure.lib.topology import normalize_topology

URL_PRO = '.dataspaceunit-project.eu'
URL_DEV = '.dev.ds.dataspaceunit.upm'


def _vault_capabilities_allow_management(capabilities):
    capability_set = set(capabilities or [])
    if "root" in capability_set or "sudo" in capability_set:
        return True
    return bool({"create", "update"}.intersection(capability_set)) and "deny" not in capability_set


def _vault_capabilities_for_path(payload, path):
    capabilities = payload.get("capabilities")
    if isinstance(capabilities, dict):
        return capabilities.get(path)
    if path in payload:
        return payload.get(path)
    return capabilities


def validate_vault_management_access(vt_token, vt_url, connector, dataspace):
    vault_url = (vt_url or "").strip().rstrip("/")
    token = (vt_token or "").strip()
    if not vault_url or not token:
        raise click.ClickException(
            "Vault preflight failed: VT_URL/VT_TOKEN are not defined. "
            "Review deployers/infrastructure/deployer.config before creating connectors."
        )

    headers = {"X-Vault-Token": token}
    try:
        response = requests.get(
            f"{vault_url}/v1/auth/token/lookup-self",
            headers=headers,
            timeout=5,
            verify=False,
        )
    except requests.RequestException as exc:
        raise click.ClickException(f"Vault preflight failed: Vault is not reachable ({exc})") from exc

    if response.status_code != 200:
        raise click.ClickException(
            "Vault preflight failed: the configured token is not valid for the running Vault "
            f"(lookup-self HTTP {response.status_code}). Recreate Level 2 common services or "
            "restore the current Vault root token before creating connectors."
        )

    policy_name = f"{connector}-secrets-policy"
    paths = [
        f"sys/policy/{policy_name}",
        f"sys/policies/acl/{policy_name}",
        "auth/token/create",
        f"secret/data/{dataspace}/{connector}/public-key",
    ]
    try:
        response = requests.post(
            f"{vault_url}/v1/sys/capabilities-self",
            headers=headers,
            json={"paths": paths},
            timeout=5,
            verify=False,
        )
    except requests.RequestException as exc:
        raise click.ClickException(f"Vault preflight failed: Vault is not reachable ({exc})") from exc

    if response.status_code != 200:
        raise click.ClickException(
            "Vault preflight failed: could not verify token capabilities "
            f"(HTTP {response.status_code}). Connector bootstrap requires policy, token and "
            "secret creation permissions."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise click.ClickException("Vault preflight failed: invalid capabilities response from Vault") from exc

    for path in paths:
        capabilities = _vault_capabilities_for_path(payload, path)
        if not _vault_capabilities_allow_management(capabilities):
            raise click.ClickException(
                "Vault preflight failed: configured token does not have management "
                f"permissions for '{path}'. Recreate Level 2 common services or restore "
                "the current Vault root token before creating connectors."
            )


def _read_deployer_config_file(path):
    config = {}
    if not os.path.isfile(path):
        return config

    with open(path) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split('=', 1)
            config[name] = value
    return config


def _bootstrap_root_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _active_bootstrap_topology():
    return normalize_topology(os.getenv("PIONERA_TOPOLOGY") or "local")


def load_effective_deployer_config(topology=None):
    """Load shared infrastructure first, then adapter overlay and env overrides."""
    root_dir = _bootstrap_root_dir()
    resolved_topology = normalize_topology(topology or _active_bootstrap_topology())
    return load_layered_deployer_config(
        [
            os.path.abspath(os.path.join(root_dir, "..", "infrastructure", "deployer.config")),
            os.path.join(root_dir, "deployer.config"),
        ],
        protected_keys=INFRASTRUCTURE_MANAGED_KEYS,
        topology=resolved_topology,
    )


@click.group()
@click.option('--pg-user', help='Postgres admin user', default='postgres')
@click.option('--pg-password', help='Postgres admin password', default='aPassword1234')
@click.option('--pg-host', help='Postgres host address', default='localhost')
@click.option('--pg-port', help='Postgres port', default='5432')
@click.option('--kc-user', help='Keycloak admin user', default='admin')
@click.option('--kc-password', help='Keycloak admin password', default='aPassword1234')
@click.option('--kc-url', help='Keycloak server admin API address', default='http://localhost:8080')
@click.option('--kc-internal-url', help='Keycloak internal URL', default='http://comsrv-keycloak.common-services.svc')
@click.option('--vt-token', help='Vault root token', default='rt.0000000000000')
@click.option('--vt-url', help='Vault server address', default='http://localhost:8280')
@click.option('--in_env', help='PRO or DEV environment', default='DEV')
@click.pass_context
def cli(ctx, pg_user, pg_password, pg_host, pg_port, kc_user, kc_password, kc_url, kc_internal_url, vt_token, vt_url, in_env):
    ctx.ensure_object(dict)

    # Load layered configuration. Shared credentials live in
    # deployers/infrastructure while this file keeps adapter-specific values.
    config = load_effective_deployer_config()
    ctx.obj['config'] = config

    # DATABASE
    ctx.obj['pg_user'] = config.get('PG_USER', pg_user)
    ctx.obj['pg_password'] = config.get('PG_PASSWORD', pg_password)
    ctx.obj['pg_host'] = config.get('PG_HOST', pg_host)
    ctx.obj['pg_port'] = config.get('PG_PORT', pg_port)
    # KEYCLOAK
    ctx.obj['kc_user'] = config.get('KC_USER', kc_user)
    ctx.obj['kc_password'] = config.get('KC_PASSWORD', kc_password)
    ctx.obj['kc_url'] = config.get('KC_URL', kc_url)
    ctx.obj['kc_internal_url'] = config.get('KC_INTERNAL_URL', kc_internal_url)

    # HASHICORP VAULT
    ctx.obj['vt_token'] = config.get('VT_TOKEN', vt_token)
    ctx.obj['vt_url'] = config.get('VT_URL', vt_url)
    # ENVIRONMENT
    ctx.obj['in_env'] = config.get('ENVIRONMENT', in_env)

    # Disable SSL warnings
    urllib3.disable_warnings()

    # Suprimir DeprecationWarning
    warnings.filterwarnings("ignore", category=DeprecationWarning)


@cli.group()
def dataspace():
    pass

@dataspace.command()
@click.argument('name')
@click.pass_context
def create(ctx, name):
    click.echo(f'Creating dataspace {name}!')
    # Create passwords file
    create_password_file(name, ctx.obj['in_env'], 'dataspace', name)

    environment = ctx.obj['in_env']

    # Generate RS password and create database
    click.echo(f'- Creating {name} registration-service')
    click.echo(f'  + Creating registration-service database')
    dbname = f'{name.replace("-", "_")}_rs'
    dbuser = f'{name.replace("-", "_")}_rsusr'
    dbpassword = generate_password(16)
    #### DEV PROGRESS
    create_database(ctx.obj['pg_user'], ctx.obj['pg_password'], ctx.obj['pg_host'], ctx.obj['pg_port'], dbname, dbuser, dbpassword)
    register_password(name, ctx.obj['in_env'], 'dataspace', name, 'registration_service_database', {'name': dbname, 'user': dbuser, 'passwd': dbpassword})

    # Generate Public Portal password and create database
    click.echo(f'- Creating {name} Web Portal')
    click.echo(f'  + Creating Web Portal database')
    dbname = f'{name.replace("-", "_")}_wp'
    dbuser = f'{name.replace("-", "_")}_wpusr'
    dbpassword = generate_password(16)
    #### DEV PROGRESS
    create_database(ctx.obj['pg_user'], ctx.obj['pg_password'], ctx.obj['pg_host'], ctx.obj['pg_port'], dbname, dbuser, dbpassword)
    register_password(name, ctx.obj['in_env'], 'dataspace', name, 'web_portal_database', {'name': dbname, 'user': dbuser, 'passwd': dbpassword})

    click.echo(f'  + Creating Web Portal secrets')
    register_password(name, ctx.obj['in_env'], 'dataspace', name, 'web_portal_secrets', {
        'STRAPI_APP_KEYS': '{},{},{},{}'.format(generate_key(16), generate_key(16), generate_key(16), generate_key(16)),
        'STRAPI_ADMIN_JWT_SECRET': generate_key(16),
        'STRAPI_JWT_SECRET': generate_key(16),
        'STRAPI_API_TOKEN_SALT': generate_key(16),
        'STRAPI_TRANSFER_TOKEN_SALT': generate_key(16)})

    # Create keycloak realm and configuration for the new dataspace
    click.echo(f'- Creating {name} Keycloak realm')
    #### DEV PROGRESS
    create_realm(ctx.obj['kc_user'], ctx.obj['kc_password'], ctx.obj['kc_url'], name, name, ctx.obj['kc_internal_url'], environment)

    # Generate Helm values file
    create_dataspace_value_files(name, environment)
    register_password(
        name,
        environment,
        'dataspace',
        name,
        'access_urls',
        build_dataspace_access_urls(name, environment, ctx.obj.get('config', {}))
    )

    click.echo(f'Dataspace {name} created successfuly!')

@dataspace.command()
@click.argument('name')
@click.pass_context
def delete(ctx, name):
    click.echo(f'Deleting dataspace {name}...')
    click.echo(f'- Deleting {name} registration-service database')
    errors = False
    dbname = f'{name.replace("-", "_")}_rs'
    dbuser = f'{name.replace("-", "_")}_rsusr'
    try:
        delete_database(ctx.obj['pg_user'], ctx.obj['pg_password'], ctx.obj['pg_host'], ctx.obj['pg_port'], dbname, dbuser)
    except Exception as e:
        errors = True
        click.echo(f'Failed to delete {name} registration-service database: {str(e)}')

    click.echo(f'- Deleting {name} Web Portal database')
    dbname = f'{name.replace("-", "_")}_wp'
    dbuser = f'{name.replace("-", "_")}_wpusr'
    try:
        delete_database(ctx.obj['pg_user'], ctx.obj['pg_password'], ctx.obj['pg_host'], ctx.obj['pg_port'], dbname, dbuser)
    except Exception as e:
        errors = True
        click.echo(f'Failed to delete {name} Web Portal database: {str(e)}')

    click.echo(f'- Deleting {name} realm')
    try:
        delete_realm(ctx.obj['kc_user'], ctx.obj['kc_password'], ctx.obj['kc_url'], name)
    except Exception as e:
        errors = True
        click.echo(f'Failed to delete {name} realm: {str(e)}')

    if errors:
        click.echo(f'Dataspace {name} deleted with errors')
    else:
        click.echo(f'Dataspace {name} deleted successfuly!')


@cli.group()
def connector():
    pass

@connector.command()
@click.argument('name')
@click.argument('dataspace')
@click.pass_context
def create(ctx, name, dataspace):

    click.echo(f'Creating connector {name} in dataspace {dataspace}')

    environment = ctx.obj['in_env']

    click.echo(f'- Validating {name} vault access')
    validate_vault_management_access(ctx.obj['vt_token'], ctx.obj['vt_url'], name, dataspace)

    # Create passwords file
    create_password_file(dataspace, environment, 'connector', name)

    # Create database
    click.echo(f'- Creating {name} database')
    dbpassword = generate_password(16)
    dbname = name.replace('-', '_')
    create_database(ctx.obj['pg_user'], ctx.obj['pg_password'], ctx.obj['pg_host'], ctx.obj['pg_port'], dbname, dbname, dbpassword)
    register_password(dataspace, environment, 'connector', name, 'database', {'name': dbname, 'user': dbname, 'passwd': dbpassword})

    # Generate certificates
    click.echo(f'- Generating {name} connector certificates')
    certpassword = generate_password(16)
    certs_path = f'deployments/{environment}/{dataspace}/certs'
    create_connector_certificates(name, certpassword, certs_path)
    register_password(dataspace, environment, 'connector', name, 'certificates', {'path': certs_path, 'passwd': certpassword})

    # Create keycloak configuration
    click.echo(f'- Creating {name} keycloak configuration')
    keycloak_openid = KeycloakOpenID(server_url=ctx.obj['kc_url'],
                                   realm_name="master",
                                   client_id='admin-cli',
                                   verify=False)

    try:
        click.echo(f'- Creating {name} keycloak configuration')
        token = keycloak_openid.token(username=ctx.obj['kc_user'], password=ctx.obj['kc_password'])
        access_token = token.get('access_token')
        refresh_token = token.get('refresh_token')
        expires_in = token.get('expires_in')

        token_obj = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_in': expires_in
        }
    except Exception as e:
        click.echo(f"    - Error obtaining token: {e}")
        ctx.exit(1)

    keycloak_admin = KeycloakAdmin(server_url=ctx.obj['kc_url'],
                                   token=token_obj,
                                   realm_name=dataspace,
                                   verify=False)

    create_role(keycloak_admin, name)
    create_group(keycloak_admin, name)
    create_connector_user(keycloak_admin, dataspace, name, environment)

    create_client(keycloak_admin, dataspace, name, environment)

    click.echo(f'- Creating {name} vault secrets')
    create_connector_vault(ctx.obj['vt_token'], ctx.obj['vt_url'], name, dataspace, environment)

    # Create minio policy
    click.echo(f'- Creating {name} minio policy')
    create_minio_policy(name, dataspace, environment)

    # Register connector in registration-service
    click.echo(f'- Adding {name} into registration-service')
    dbname = f'{dataspace.replace("-", "_")}_rs'
    register_connector_database(ctx.obj['pg_user'], ctx.obj['pg_password'], ctx.obj['pg_host'], ctx.obj['pg_port'], dbname, name, dataspace, environment)

    # Generate Helm values file
    create_connector_value_files(dataspace, name, environment)
    register_password(
        dataspace,
        environment,
        'connector',
        name,
        'access_urls',
        build_connector_access_urls(name, dataspace, environment, ctx.obj.get('config', {}))
    )

    click.echo(f'Connector {name} created successfuly!')

@connector.command()
@click.argument('name')
@click.argument('dataspace')
@click.pass_context
def delete(ctx, name, dataspace):
    click.echo(f'Deleting dataspace {name}...')

    click.echo(f'- Deleting {name} database')
    dbname = name.replace('-', '_')
    try:
        delete_database(ctx.obj['pg_user'], ctx.obj['pg_password'], ctx.obj['pg_host'], ctx.obj['pg_port'], dbname, dbname)
    except Exception as e:
        click.echo(f'Failed to delete {name} connector database: {str(e)}')

    click.echo(f'- Deleting {name} in keycloak')
    try:
        delete_connector_keycloak(ctx.obj['kc_user'], ctx.obj['kc_password'], ctx.obj['kc_url'], name, dataspace)
    except Exception as e:
        click.echo(f'Failed to delete {name} connector keycloak objects: {str(e)}')

    click.echo(f'Connector {name} deleted successfuly!')

@connector.command()
@click.argument('name')
@click.argument('dataspace')
@click.pass_context
def fix(ctx, name, dataspace):
    # Register connector in registration-service
    dbname = name.replace('-', '_')
    fix_connector_050_database(ctx.obj['pg_user'], ctx.obj['pg_password'], ctx.obj['pg_host'], ctx.obj['pg_port'], dbname)

@connector.command()
@click.argument('name')
@click.argument('dataspace')
@click.pass_context
def renew(ctx, name, dataspace):
    token = update_token_vault(ctx.obj['vt_token'], ctx.obj['vt_url'], name, dataspace)
    check_secrets_vault(token, ctx.obj['vt_url'], name, dataspace)

@connector.command()
@click.argument('name')
@click.argument('dataspace')
@click.pass_context
def minio(ctx, name, dataspace):
    check_minio_bucket(name, dataspace)

@connector.command()
@click.argument('name')
@click.argument('dataspace')
@click.pass_context
def checkdb(ctx, name, dataspace, environment):
    environment = ctx.obj['in_env']
    filename = f'deployments/{environment}/{dataspace}/credentials-connector-{name}.json'

    # Load the JSON file
    with open(filename, 'r') as f:
        credentials = json.load(f)

    # Access the 'database' key in the credentials dictionary
    database_name = credentials['database']['name']
    database_user = credentials['database']['user']
    database_passwd = credentials['database']['passwd']
    check_database_db(database_user, database_passwd, ctx.obj['pg_host'], ctx.obj['pg_port'], database_name)

#######################################
### DATABASE FUNCTIONS
#######################################
import psycopg2

def create_database(pg_user, pg_password, pg_host, pg_port, database, username, password):
    # Connect to the PostgreSQL server
    conn = psycopg2.connect(
            user=pg_user,
            password=pg_password,
            host=pg_host,
            port=pg_port)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s;", (username,))
        if cur.fetchone():
            cur.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN ENCRYPTED PASSWORD %s;").format(sql.Identifier(username)),
                (password,),
            )
        else:
            cur.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN ENCRYPTED PASSWORD %s;").format(sql.Identifier(username)),
                (password,),
            )

        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (database,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(database)))
        cur.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {};").format(
                sql.Identifier(database),
                sql.Identifier(username),
            )
        )
        cur.execute(
            sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {};").format(
                sql.Identifier(database),
                sql.Identifier(username),
            )
        )
    finally:
        if cur is not None:
            cur.close()
        conn.close()

def delete_database(pg_user, pg_password, pg_host, pg_port, database, username):
    # Connect to the PostgreSQL server
    conn = psycopg2.connect(
            user=pg_user,
            password=pg_password,
            host=pg_host,
            port=pg_port)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s
              AND pid <> pg_backend_pid();
            """,
            (database,),
        )
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {};").format(sql.Identifier(database)))
        cur.execute(sql.SQL("DROP USER IF EXISTS {};").format(sql.Identifier(username)))
    except Exception as e:
        # Handle other exceptions here
        print(f"An error occurred deleting the database '{database}' and user '{username}': {str(e)}")

    cur.close()
    conn.close()

def connector_participant_urls(config, connector, dataspace, environment):
    if str(environment or "").strip().upper() == "PRO":
        base = f"https://{connector}-{dataspace}.ds.dataspaceunit-project.eu"
        return f"{base}/protocol", f"{base}/shared"

    urls = build_connector_access_urls(connector, dataspace, environment, config)
    return urls["connector_protocol_api"], urls["connector_shared_api"]


def register_connector_database(pg_user, pg_password, pg_host, pg_port, database, connector, dataspace, environment):
    # Connect to the PostgreSQL server
    conn = psycopg2.connect(
            user=pg_user,
            password=pg_password,
            host=pg_host,
            port=pg_port,
            database=database)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    conn_protocol, conn_shared = connector_participant_urls(
        load_effective_deployer_config(),
        connector,
        dataspace,
        environment,
    )
    cur.execute(f"INSERT INTO public.edc_participant (participant_id,url,created_at,shared_url) VALUES ('{connector}','{conn_protocol}',EXTRACT(EPOCH FROM NOW())::BIGINT,'{conn_shared}');")
    cur.close()
    conn.close()

def fix_connector_050_database(pg_user, pg_password, pg_host, pg_port, database):
    # Connect to the PostgreSQL server
    conn = psycopg2.connect(
            user=pg_user,
            password=pg_password,
            host=pg_host,
            port=pg_port,
            database=database)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("ALTER TABLE edc_vocabulary ADD COLUMN connector_id VARCHAR NOT NULL, DROP CONSTRAINT edc_vocabulary_pkey, ADD PRIMARY KEY (id, connector_id);")
    cur.close()
    conn.close()

def check_database_db(pg_user, pg_password, pg_host, pg_port, database):
    # Connect to the PostgreSQL server
    conn = psycopg2.connect(
            user=pg_user,
            password=pg_password,
            host=pg_host,
            port=pg_port,
            database=database)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("SELECT 1;")
    cur.close()
    conn.close()
    print("Connection successful")

#######################################
### KEYS FUNCTIONS
#######################################
import string
import secrets
import base64
def generate_key(length):
    # Generate random bytes
    random_chars = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
    random_bytes = random_chars.encode('utf-8')

    # Convert bytes to Base64 string
    base64_encoded_string = base64.b64encode(random_bytes).decode('utf-8')
    return base64_encoded_string

def generate_minio_key(length):
    # Generate random chars
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))

def generate_password(length):
    special_chars = '!@_^*'
    alphabet = string.ascii_letters + string.digits + special_chars
    while True:
        password = ''.join(secrets.choice(alphabet) for i in range(length))
        if (password[0].isalpha()
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)
                and any(c in special_chars for c in password)):
            break
    return password

def create_password_file(datasource, environment, source_type, name):
    # Generate file name
    filename = f'deployments/{environment}/{datasource}/credentials-{source_type}-{name}.json'
    folder = os.path.dirname(filename)
    os.makedirs(folder, exist_ok=True)

    # Empty credentials object
    credentials = {}

    # Write the credentials to a JSON file
    with open(filename, 'w') as f:
        json.dump(credentials, f)

def register_password(datasource, environment, source_type, name, credential_name, credentials_object):
    # Generate file name
    filename = f'deployments/{environment}/{datasource}/credentials-{source_type}-{name}.json'
    # Open the JSON file and load the data
    with open(filename, 'r+') as f:
        data = json.load(f)

        # Add the new property
        data[credential_name] = credentials_object

        # Move the pointer to the beginning of the file
        f.seek(0)

        # Write the updated data back to the file
        json.dump(data, f, indent=4)

        # Truncate the file to remove any leftover part
        f.truncate()


def get_password_values(datasource, environment, source_type, name):
    # Generate file name
    filename = f'deployments/{environment}/{datasource}/credentials-{source_type}-{name}.json'

    # Open the JSON file and load the data
    data = {}
    with open(filename, 'r') as f:
        data = json.load(f)

    return data
    """
    flattened_data = flatten_json(data)
    print(flattened_data)
    """

def flatten_json(json_obj, parent_key='', sep='-'):
    items = {}
    for k, v in json_obj.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_json(v, new_key, sep=sep))
        else:
            items[new_key] = v
    return items


def build_dataspace_access_urls(dataspace, environment, config):
    protocol = access_protocol(environment)
    ds_domain = dataspace_domain_base(config, environment)
    urls = {
        "public_portal_login": f"{protocol}://{dataspace}.{ds_domain}",
        "public_portal_backend_admin": f"{protocol}://backend-{dataspace}.{ds_domain}/admin",
        "registration_service": f"{protocol}://registration-service-{dataspace}.{ds_domain}",
    }
    urls.update(common_access_urls(dataspace, environment, config))
    return urls


def build_connector_access_urls(connector, dataspace, environment, config, dashboard=False):
    protocol = access_protocol(environment)
    ds_domain = dataspace_domain_base(config, environment)
    connector_base = f"{protocol}://{connector}.{ds_domain}"
    connector_interface_base_href = normalize_base_href(
        config.get("INESDATA_CONNECTOR_INTERFACE_BASE_HREF", "/inesdata-connector-interface/")
    )
    urls = {
        "connector_ingress": connector_base,
        "connector_interface_login": f"{connector_base}{connector_interface_base_href}",
        "connector_management_api": f"{connector_base}/management",
        "connector_protocol_api": f"{connector_base}/protocol",
        "connector_shared_api": f"{connector_base}/shared",
    }
    if dashboard:
        dashboard_base_href = normalize_base_href(config.get("EDC_DASHBOARD_BASE_HREF", "/edc-dashboard/"))
        urls["edc_dashboard_login"] = f"{connector_base}{dashboard_base_href}"
        if str(config.get("EDC_DASHBOARD_PROXY_AUTH_MODE", "")).strip().lower() == "oidc-bff":
            urls["edc_dashboard_oidc_login"] = f"{connector_base}/edc-dashboard-api/auth/login"
    urls.update(common_access_urls(dataspace, environment, config))

    public_hostname = str(config.get("PUBLIC_HOSTNAME", "")).strip()
    if public_hostname:
        # Extract short connector name: conn-citycouncil-demo → citycouncil
        short_name = connector
        if short_name.startswith("conn-"):
            short_name = short_name[len("conn-"):]
        if short_name.endswith("-demo"):
            short_name = short_name[: -len("-demo")]
        base = f"https://{public_hostname}"
        urls["external_connector_interface"] = f"{base}/c/{short_name}/inesdata-connector-interface/"
        urls["external_management_api"] = f"{base}/c/{short_name}/management"
        urls["external_shared_api"] = f"{base}/c/{short_name}/shared"
        urls["external_federated_catalog"] = f"{base}/c/{short_name}/federatedcatalog"
        urls["external_keycloak_realm"] = f"{base}/auth/realms/{dataspace}"
        urls["external_keycloak_admin_console"] = f"{base}/auth/admin/{dataspace}/console/"
        urls["external_minio_console"] = f"{base}/s3-console/"

    return urls


def common_access_urls(dataspace, environment, config):
    protocol = access_protocol(environment)
    resolved_hostnames = resolved_common_service_hostnames(config)
    keycloak_hostname = resolved_hostnames["keycloak_hostname"]
    keycloak_admin_hostname = resolved_hostnames["keycloak_admin_hostname"]
    minio_console_hostname = (
        clean_hostname(config.get("MINIO_CONSOLE_HOSTNAME"))
        or resolved_hostnames["minio_console_hostname"]
    )
    return {
        "keycloak_realm": f"{protocol}://{keycloak_hostname}/realms/{dataspace}",
        "keycloak_account": f"{protocol}://{keycloak_hostname}/realms/{dataspace}/account",
        "keycloak_admin_console": f"{protocol}://{keycloak_admin_hostname}/admin/{dataspace}/console/",
        "minio_console": f"{protocol}://{minio_console_hostname}",
    }


def access_protocol(environment):
    return "https" if str(environment or "").strip().upper() == "PRO" else "http"


def dataspace_domain_base(config, environment):
    if str(environment or "").strip().upper() == "PRO":
        return "ds.dataspaceunit-project.eu"
    configured = str(config.get("DS_DOMAIN_BASE", "")).strip()
    return configured or URL_DEV.lstrip(".")


def dataspace_index(config, dataspace_name, dataspace_namespace=None):
    target_name = str(dataspace_name or "").strip()
    target_namespace = str(dataspace_namespace or "").strip()
    index = 1

    while True:
        configured_name = str(config.get(f"DS_{index}_NAME", "") or "").strip()
        configured_namespace = str(config.get(f"DS_{index}_NAMESPACE", "") or configured_name).strip()
        if not configured_name:
            break
        if target_name and configured_name == target_name:
            return index
        if target_namespace and configured_namespace == target_namespace:
            return index
        index += 1

    return 1


def registration_service_namespace(config, dataspace_name, dataspace_namespace=None):
    resolved_namespace = str(dataspace_namespace or dataspace_name or "").strip() or str(dataspace_name or "").strip()
    index = dataspace_index(config, dataspace_name, dataspace_namespace)
    configured = str(config.get(f"DS_{index}_REGISTRATION_NAMESPACE", "") or "").strip()
    if configured:
        return configured

    profile = str(config.get("NAMESPACE_PROFILE", "compact") or "compact").strip().lower().replace("_", "-")
    if profile in {"role-aligned", "rolealigned", "aligned", "roles"}:
        return f"{dataspace_name}-core"

    return resolved_namespace


def registration_service_internal_hostname(
    config,
    dataspace_name,
    environment,
    *,
    connector_namespace=None,
    dataspace_namespace=None,
):
    if str(environment or "").strip().upper() == "PRO":
        return f"registration-service-{dataspace_name}.ds.dataspaceunit-project.eu"

    index = dataspace_index(config, dataspace_name, dataspace_namespace)
    resolved_dataspace_namespace = (
        str(dataspace_namespace or "").strip()
        or str(config.get(f"DS_{index}_NAMESPACE", "") or "").strip()
        or str(dataspace_name or "").strip()
    )
    resolved_connector_namespace = str(connector_namespace or resolved_dataspace_namespace).strip() or resolved_dataspace_namespace
    resolved_registration_namespace = registration_service_namespace(
        config,
        dataspace_name,
        resolved_dataspace_namespace,
    )
    service_name = f"{dataspace_name}-registration-service"
    if resolved_registration_namespace and resolved_registration_namespace != resolved_connector_namespace:
        return f"{service_name}.{resolved_registration_namespace}.svc.cluster.local:8080"
    return f"{service_name}:8080"


def clean_hostname(value):
    return clean_public_hostname(value)


def normalize_base_href(value):
    base_href = str(value or "/edc-dashboard/").strip() or "/edc-dashboard/"
    if not base_href.startswith("/"):
        base_href = f"/{base_href}"
    if not base_href.endswith("/"):
        base_href = f"{base_href}/"
    return base_href


import subprocess

def create_connector_certificates(name, password, folder):
    # Define command to execute
    command = ['./scripts/generate-cert.sh', name, password, folder]

    # Call the shell script
    subprocess.run(command, check=True)

#######################################
### KEYCLOAK FUNCTIONS
#######################################

def create_realm(username, password, server_url, realm_name, dataspace_name, keycloak_url, environment):
    keycloak_admin = KeycloakAdmin(server_url=server_url,
                                    username=username,
                                    password=password,
                                    realm_name="master",
                                    verify=False)

    # Create the realm if it does not exist
    click.echo(f'  + Creating realm {realm_name}')
    try:
        keycloak_admin.get_realm(realm_name)
    except KeycloakGetError as e:
        if e.response_code == 404:
            keycloak_admin.create_realm(payload={"realm": realm_name, "enabled": True})
    keycloak_admin.change_current_realm(realm_name)

    # Set realm frontendUrl if PUBLIC_HOSTNAME is configured (enables external HTTPS access via nginx proxy)
    config = load_effective_deployer_config()
    public_hostname = str(config.get("PUBLIC_HOSTNAME", "")).strip()
    if public_hostname:
        click.echo(f'  + Setting realm frontendUrl to https://{public_hostname}/auth')
        try:
            realm_rep = keycloak_admin.get_realm(realm_name)
            realm_rep.setdefault("attributes", {})["frontendUrl"] = f"https://{public_hostname}/auth"
            keycloak_admin.update_realm(realm_name, payload=realm_rep)
        except Exception as e:
            click.echo(f'  ! Warning: could not set frontendUrl: {e}')

    # Check if the client scope exists and create it if it doesn't
    click.echo(f'  + Creating scope "dataspaceunit-dataspace-audience"' )
    client_scopes = keycloak_admin.get_client_scopes()
    if not any(scope['name'] == 'dataspaceunit-dataspace-audience' for scope in client_scopes):
        dataspace_audience_payload = {
            "name": "dataspaceunit-dataspace-audience",
            "description": f"Dataspaceunit: Add audience for {dataspace_name} dataspace",
            "protocol": "openid-connect",
            "attributes": {
                "display.on.consent.screen": "false",
                "include.in.token.scope": "false"
            },
            "protocolMappers": [
                {
                    "name": "add-namespace-audience",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "config": {
                        "included.client.audience": "",
                        "included.custom.audience": f"{keycloak_url}/realms/{realm_name}",
                        "id.token.claim": "false",
                        "access.token.claim": "true",
                        "token.introspection.claim": "true"
                    }
                }
            ]
        }
        keycloak_admin.create_client_scope(payload=dataspace_audience_payload)

    click.echo(f'  + Creating scope "dataspaceunit-nbf-claim"' )
    if not any(scope['name'] == 'dataspaceunit-nbf-claim' for scope in client_scopes):
        nbf_claim_payload = {
            "name": "dataspaceunit-nbf-claim",
            "description": "Dataspaceunit: Add nbf required claim",
            "protocol": "openid-connect",
            "attributes": {
                "display.on.consent.screen": "false",
                "include.in.token.scope": "false"
            },
            "protocolMappers": [
                {
                    "name": "add-default-nbf-value",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-hardcoded-claim-mapper",
                    "config": {
                        "claim.name": "nbf",
                        "jsonType.label": "int",
                        "claim.value": "0",
                        "id.token.claim": "false",
                        "access.token.claim": "true",
                        "userinfo.token.claim": "true",
                        "access.token.response.claim": "false",
                        "token.introspection.claim": "true"
                    }
                }
            ]
        }
        keycloak_admin.create_client_scope(payload=nbf_claim_payload)

    # Create default realm roles
    create_role(keycloak_admin, 'connector-user')
    create_role(keycloak_admin, 'connector-admin')
    create_role(keycloak_admin, 'connector-management')
    create_role(keycloak_admin, 'dataspace-admin')

    # Create manager realm group
    create_manager_group(keycloak_admin, realm_name)

    # Create realm manager user
    create_realm_user(keycloak_admin, realm_name, dataspace_name, environment)

    # Create the client if it does not exist
    click.echo(f'  + Creating users client "dataspace-users"' )
    clients = keycloak_admin.get_clients()
    if not any(client['clientId'] == 'dataspace-users' for client in clients):
        new_client = {
            "clientId": "dataspace-users",
            "name": "dataspace-users",
            "description": "Dataspaceunit: Cliente para la identificación de los usuarios del dataspace",
            "alwaysDisplayInConsole": False,
            "redirectUris": ["*"],
            "webOrigins": ["*"],
            "protocol": "openid-connect",
            "enabled": True,
            "publicClient": True,
            "frontchannelLogout": True,
            "attributes": {
                "post.logout.redirect.uris": "+",
                "backchannel.logout.session.required": True
            },
            "defaultClientScopes":["dataspaceunit-dataspace-audience", "dataspaceunit-nbf-claim", "profile", "email", "acr", "web-origins", "roles"]
        }
        keycloak_admin.create_client(payload=new_client)

    # Create keycloak user for strapi backend
    user_name = 'user-strapi-' + realm_name
    user_password = generate_password(16)
    user_id = create_user(keycloak_admin, user_name, user_password)
    register_password(dataspace_name, environment, 'dataspace', realm_name, 'strapi_user', {'user': user_name, 'passwd': user_password})

def delete_realm(username, password, server_url, realm_name):
    keycloak_admin = KeycloakAdmin(server_url=server_url,
                                   username=username,
                                   password=password,
                                   realm_name="master",
                                   verify=False)

    # Create the realm if it does not exist
    click.echo(f'  + Deleting realm {realm_name}')
    try:
        keycloak_admin.get_realm(realm_name)
        keycloak_admin.delete_realm(realm_name=realm_name)
    except KeycloakGetError as e:
        if e.response_code == 404:
            click.echo(f'  + Realm {realm_name} does not exist')
        else:
            click.echo(f'  + ERROR: {e}')

    keycloak_admin.change_current_realm(realm_name)


def create_role(keycloak_admin, role_name):
    try:
        keycloak_admin.get_realm_role(role_name)
        click.echo(f"    + Role {role_name} already exists.")
    except KeycloakGetError as e:
        if e.response_code == 404:
            if role_name =='connector-user' or role_name =='dataspace-admin':
                keycloak_admin.create_realm_role(payload={"name": role_name})
            else:
                attributes = {
                    "connector": [role_name],
                    "connector-type": ["dataspaceunit-connector"]
                }
                keycloak_admin.create_realm_role(payload={"name": role_name, "attributes": attributes})
            click.echo(f"    + Role {role_name} created.")

def create_group(keycloak_admin, group_name):
    try:
        keycloak_admin.get_group_by_path(f'/{group_name}')
        click.echo(f"    + Group {group_name} already exists.")
    except KeycloakGetError as e:
        if e.response_code == 404:
            group_id = keycloak_admin.create_group(payload={"name": group_name})
            click.echo(f"    + Group {group_name} created successfully.")
            role_id = keycloak_admin.get_realm_role(group_name).get('id')
            keycloak_admin.assign_group_realm_roles(group_id=group_id, roles=[{"id": role_id, "name": group_name}])
            click.echo(f"    + Role {group_name} mapped to group {group_name}.")
            connector_user_role_id = keycloak_admin.get_realm_role('connector-user').get('id')
            keycloak_admin.assign_group_realm_roles(group_id=group_id, roles=[{"id": connector_user_role_id, "name": "connector-user"}])
            click.echo(f"    + Role connector-user mapped to group {group_name}.")

def create_manager_group(keycloak_admin, realm_name):
    try:
        group_name = realm_name + '-manager'
        keycloak_admin.get_group_by_path(f'/{group_name}')
        click.echo(f"    + Manager group {group_name} already exists.")
    except KeycloakGetError as e:
        if e.response_code == 404:
            group_id = keycloak_admin.create_group(payload={"name": group_name})
            click.echo(f"    + Manager group {group_name} created successfully.")

            clients = keycloak_admin.get_clients()
            client = next(c for c in clients if c['clientId'] == "realm-management")
            client_id = client['id']

            roles_to_assign = ["view-realm", "view-users", "query-users", "manage-users"]
            available_roles = keycloak_admin.get_client_roles(client_id=client_id)
            roles_to_add = [role for role in available_roles if role['name'] in roles_to_assign]
            keycloak_admin.assign_group_client_roles(client_id=client_id, group_id=group_id, roles=roles_to_add)
            print(f"    + Manager group {group_name} has been asigned the following roles {roles_to_assign}")

def create_client(keycloak_admin, dataspace, client_name, environment):
    clients = keycloak_admin.get_clients()
    client = next((client for client in clients if client['clientId'] == client_name), None)
    default_scopes = ["dataspaceunit-dataspace-audience", "dataspaceunit-nbf-claim", "profile", "email", "acr", "roles"]
    if client is None:
        new_client = {
            "clientId": client_name,
            "name": client_name,
            "description": f"Client for connector {client_name}",
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
                "backchannel.logout.session.required": True
            },
            "defaultClientScopes": default_scopes
        }
        client_id = keycloak_admin.create_client(payload=new_client)
        click.echo(f"    + Client {client_name} created with ID {client_id}.")
    else:
        client_id = client['id']
        click.echo(f"    + Client {client_name} already exists.")
        ensure_client_service_account_enabled(keycloak_admin, client_id, client)

    # Keep existing clients reproducible when connector certificates are regenerated.
    import os
    cert_path = os.path.join(os.path.dirname(__file__), 'deployments', environment, dataspace, 'certs', f'{client_name}-public.crt')
    with open(cert_path, 'rb') as f:
        cert_data = f.read()
    try:
        keycloak_admin.upload_certificate(client_id=client_id, certcont=cert_data)
        click.echo(f"    + Client certificate for {client_name} synchronized from {client_name}-public.crt.")
    except KeycloakPostError as e:
        click.echo(f"Error uploading certificate {e}")
    finally:
        keycloak_admin.connection.add_param_headers("Content-Type", "application/json")

    ensure_client_default_scopes(keycloak_admin, client_id, default_scopes)
    ensure_client_service_account_roles(keycloak_admin, client_id, [client_name, "connector-user"])


def ensure_client_service_account_enabled(keycloak_admin, client_id, client):
    if client.get("serviceAccountsEnabled"):
        return
    payload = dict(client)
    payload["serviceAccountsEnabled"] = True
    keycloak_admin.update_client(client_id=client_id, payload=payload)
    click.echo("    + Client service account enabled.")


def ensure_client_default_scopes(keycloak_admin, client_id, expected_scope_names):
    current_scopes = keycloak_admin.get_client_default_client_scopes(client_id)
    current_names = {scope.get("name") for scope in current_scopes}
    all_scopes = {scope.get("name"): scope for scope in keycloak_admin.get_client_scopes()}

    for scope_name in expected_scope_names:
        if scope_name in current_names:
            continue
        scope = all_scopes.get(scope_name)
        if not scope:
            click.echo(f"    - Client scope {scope_name} not found. Skipping.")
            continue
        keycloak_admin.add_client_default_client_scope(
            client_id=client_id,
            client_scope_id=scope["id"],
            payload={},
        )
        click.echo(f"    + Client default scope {scope_name} mapped.")


def ensure_client_service_account_roles(keycloak_admin, client_id, role_names):
    service_account = keycloak_admin.get_client_service_account_user(client_id)
    current_roles = keycloak_admin.get_realm_roles_of_user(service_account["id"])
    current_role_names = {role.get("name") for role in current_roles}
    roles_to_assign = []

    for role_name in role_names:
        if role_name in current_role_names:
            continue
        roles_to_assign.append(keycloak_admin.get_realm_role(role_name))

    if roles_to_assign:
        keycloak_admin.assign_realm_roles(user_id=service_account["id"], roles=roles_to_assign)
        click.echo(
            "    + Client service account realm roles mapped: "
            + ", ".join(role["name"] for role in roles_to_assign)
        )
    else:
        click.echo("    + Client service account realm roles already mapped.")

def create_realm_user(keycloak_admin, realm, dataspace, environment):
    click.echo(f"    + Creating realm user {realm} ............")
    user_name = realm + '_manager'
    user_password = generate_password(16)
    user_id = create_user(keycloak_admin, user_name, user_password)

    if user_id:
        register_password(dataspace, environment, 'dataspace', realm, 'realm_manager', {'user': user_name, 'passwd': user_password})

        # Assign the role to the user
        roles = keycloak_admin.get_realm_roles()
        dataspace_admin_role = next((role for role in roles if role['name'] == 'dataspace-admin'), None)
        if dataspace_admin_role:
            keycloak_admin.assign_realm_roles(user_id=user_id, roles=[dataspace_admin_role])
            click.echo(f"    + Role dataspace-admin assigned to the user {user_name}.")
        else:
            click.echo("    - Role 'dataspace-admin' doesn't exist.")

        # Assign the manager group to the user
        group_name = realm + '-manager'
        groups = keycloak_admin.get_groups()
        manager_group = next((group for group in groups if group['name'] == group_name), None)
        if manager_group:
            keycloak_admin.group_user_add(user_id=user_id, group_id=manager_group['id'])
            click.echo(f"    + Assigned user {user_name} to group {group_name}.")
        else:
            click.echo(f'    - Group {group_name} does not exist.')

    else:
        click.echo(f"    + User {user_name} already exists.")

def create_connector_user(keycloak_admin, dataspace, connector, environment):
    click.echo(f"    + Creating connector user {connector} ............")
    user_name = 'user-' + connector
    user_password = generate_password(16)
    user_id = create_user(keycloak_admin, user_name, user_password)

    if user_id:
        register_password(dataspace, environment, 'connector', connector, 'connector_user', {'user': user_name, 'passwd': user_password})

        # Assign the connector group to the user
        groups = keycloak_admin.get_groups()
        connector_group = next((group for group in groups if group['name'] == connector), None)
        if connector_group:
            keycloak_admin.group_user_add(user_id=user_id, group_id=connector_group['id'])
            click.echo(f"    + Assigned user {user_name} to group {connector}.")
        else:
            click.echo(f'    - Group {connector} does not exist.')
    else:
        click.echo(f"    - User {user_name} already exists.")

def create_user(keycloak_admin, user_name, user_password):
    click.echo(f"    + Creating {user_name} ............")

    users = keycloak_admin.get_users()
    existing_user = next((user for user in users if user['username'] == user_name), None)
    if not existing_user:
        new_user = {
            "username": user_name,
            "email": user_name + '@dataspaceunit.com',
            "firstName": user_name,
            "lastName": user_name,
            "enabled": True,
            "emailVerified": True,
        }
        user_id = keycloak_admin.create_user(payload=new_user)
        click.echo(f"    + User {user_name} created.")

        keycloak_admin.set_user_password(user_id=user_id, password=user_password, temporary=False)

        return user_id
    else:
        user_id = existing_user['id']
        keycloak_admin.set_user_password(user_id=user_id, password=user_password, temporary=False)
        click.echo(f"    - User {user_name} already exists. Password reset for reproducible credentials.")
        return user_id

def delete_connector_keycloak(username, password, server_url, connector, dataspace):
    # Create keycloak configuration
    keycloak_openid = KeycloakOpenID(server_url=server_url,
                                     realm_name="master",
                                     client_id='admin-cli',
                                     verify=False)

    try:
        token = keycloak_openid.token(username=username, password=password)
        access_token = token.get('access_token')
        refresh_token = token.get('refresh_token')
        expires_in = token.get('expires_in')

        token_obj = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_in': expires_in
        }
    except Exception as e:
        click.echo(f"    - Error obtaining token: {e}")
        return

    keycloak_admin = KeycloakAdmin(server_url=server_url,
                                   token=token_obj,
                                   realm_name=dataspace,
                                   verify=False)
    # DELETE USER
    deleted = False
    user_name = 'user-' + connector
    try:
        users = keycloak_admin.get_users({})
        for user in users:
            if user['username'] == user_name:
                keycloak_admin.delete_user(user_id=user['id'])
                deleted = True

        if deleted:
            click.echo(f'  + User {user_name} deleted')
        else:
            click.echo(f'  - User {user_name} not deleted')
    except Exception as e:
        click.echo(f'  + Error deleting connector user {user_name} with error {e}')

    # DELETE CONNECTOR CLIENT
    try:
        deleted = False
        clients = keycloak_admin.get_clients()
        for client in clients:
            if client['clientId'] == connector:
                keycloak_admin.delete_client(client_id=client['id'])
                deleted = True

        if deleted:
            click.echo(f'  + Client {connector} deleted')
        else:
            click.echo(f'  - Client {connector} not deleted')
    except Exception as e:
        click.echo(f'  + Error deleting connector client {connector} with error {e}')

    # DELETE GROUP
    try:
        deleted = False
        groups = keycloak_admin.get_groups()
        for group in groups:
            if group['name'] == connector:
                keycloak_admin.delete_group(group_id=group['id'])
                deleted = True

        if deleted:
            click.echo(f'  + Group {connector} deleted')
        else:
            click.echo(f'  - Group {connector} not deleted')
    except Exception as e:
        click.echo(f'  + Error deleting connector group {connector} with error {e}')

    # DELETE ROLE
    try:
        deleted = False
        roles = keycloak_admin.get_realm_roles()
        for role in roles:
            if role['name'] == connector:
                keycloak_admin.delete_role_by_id(role_id=role['id'])
                deleted = True

        if deleted:
            click.echo(f'  + Group {connector} deleted')
        else:
            click.echo(f'  - Group {connector} not deleted')
    except Exception as e:
        click.echo(f'  + Error deleting connector role {connector} with error {e}')

#######################################
### HASHICORP VAULT FUNCTIONS
#######################################
import hvac
def create_connector_vault(vt_token, vt_url, connector, dataspace, environment):
    validate_vault_management_access(vt_token, vt_url, connector, dataspace)

    # Connect with Vault
    client = hvac.Client(
        url=vt_url,
        token=vt_token,
        verify=False
    )
    click.echo(f'  + Conectado a vault')

    # Definir la política en HCL
    policy_name = f'{connector}-secrets-policy'
    connector_policy = f"""
path "secret/data/{dataspace}/{connector}/*" {{
    capabilities = ["create", "read", "update", "list", "delete"]
}}
"""
    # Crear la política en Vault
    client.sys.create_or_update_policy(
        name=policy_name,
        policy=connector_policy
    )
    click.echo(f'  + Policy {policy_name} created')

    # Crear un token para el usuario con un TTL extendido y que sea renovable
    token = client.auth.token.create(
        period="768h",
        policies=[f'{policy_name}'],
        renewable=True
    )
    user_token = token['auth']['client_token']

    click.echo(f'  + Token retrieved')
    register_password(dataspace, environment, 'connector', connector, 'vault', {'token': user_token, 'path': f'secret/data/{dataspace}/{connector}/'})

    # Create secrets with connector certificates
    # Read the content of the file
    cert_path = os.path.join(os.path.dirname(__file__), 'deployments', environment, dataspace, 'certs', f'{connector}-public.crt')
    with open(cert_path, 'rb') as file:
        file_content = file.read()
    client.secrets.kv.v2.create_or_update_secret(
        path=f"{dataspace}/{connector}/public-key",
        secret={"content": file_content.decode('utf-8')}
    )

    cert_path = os.path.join(os.path.dirname(__file__), 'deployments', environment, dataspace, 'certs', f'{connector}-private.key')
    with open(cert_path, 'rb') as file:
        file_content = file.read()
    client.secrets.kv.v2.create_or_update_secret(
        path=f"{dataspace}/{connector}/private-key",
        secret={"content": file_content.decode('utf-8')}
    )

    # Create MinIO secret
    access_key = generate_minio_key(16)
    client.secrets.kv.v2.create_or_update_secret(
        path=f"{dataspace}/{connector}/aws-access-key",
        secret={"content": access_key}
    )

    secret_key = generate_minio_key(40)
    client.secrets.kv.v2.create_or_update_secret(
        path=f"{dataspace}/{connector}/aws-secret-key",
        secret={"content": secret_key}
    )
    register_password(dataspace, environment, 'connector', connector, 'minio', {'access_key': access_key, 'secret_key': secret_key, 'user': connector, 'passwd': generate_minio_key(16)})

def update_token_vault(vt_token, vt_url, connector, dataspace):

    # Connect with Vault
    client = hvac.Client(
        url=vt_url,
        token=vt_token,
        verify=False
    )
    click.echo(f'Conectado a vault')

    # Definir la política en HCL
    policy_name = f'{connector}-secrets-policy'

    # Crear un token para el usuario con un TTL extendido y que sea renovable
    token = client.auth.token.create(
        period="768h",
        policies=[f'{policy_name}'],
        renewable=True
    )
    click.echo('  + TOKEN DATA:')
    click.echo(token)
    click.echo('  +++')

    user_token = token['auth']['client_token']
    click.echo(f'  + Token retrieved {user_token}')

    return user_token

def check_secrets_vault(vt_token, vt_url, connector, dataspace):
    # Connect with Vault
    client = hvac.Client(
        url=vt_url,
        token=vt_token,
        verify=False
    )
    click.echo(f'Conectado a vault')

    # Check the token's life
    token_info = client.auth.token.lookup_self()
    click.echo(f'Token info: {token_info}')

    accesskey = f'{dataspace}/{connector}/aws-access-key'
    secretkey = f'{dataspace}/{connector}/aws-secret-key'
    publickey = f'{dataspace}/{connector}/public-key'
    privatekey = f'{dataspace}/{connector}/private-key'

    # Obtiene el secreto 'devtech/secret/key'
    secret = client.secrets.kv.v2.read_secret_version(path=accesskey)
    click.echo(f'  + Secret {accesskey}:')
    click.echo(secret)
    secret = client.secrets.kv.v2.read_secret_version(path=secretkey)
    click.echo(f'  + Secret {secretkey}:')
    click.echo(secret)
    secret = client.secrets.kv.v2.read_secret_version(path=publickey)
    click.echo(f'  + Secret {publickey}:')
    click.echo(secret)
    secret = client.secrets.kv.v2.read_secret_version(path=privatekey)
    click.echo(f'  + Secret {privatekey}:')
    click.echo(secret)

#######################################
### MINIO FUNCTIONS
#######################################
def create_minio_policy(connector, dataspace, environment):
    minio_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:*"
                ],
                "Resource": [
                    f"arn:aws:s3:::{dataspace}-{connector}",
                    f"arn:aws:s3:::{dataspace}-{connector}/*"
                ]
            }
        ]
    }

    # Generate file name
    filename = f'deployments/{environment}/{dataspace}/policy-{dataspace}-{connector}.json'
    # Write the policy to the file
    with open(filename, 'w') as f:
        # Write the updated data back to the file
        json.dump(minio_policy, f, indent=4)

    click.echo(f'  + Generated MinIO Policy')


from minio import Minio
def check_minio_bucket(connector, dataspace):
    # Crea un cliente de MinIO
    client = Minio(
        "localhost:9000",
        access_key="nTt7cykfyHm6mqSx",
        secret_key="zxAkwIcWYllbfBTXwiG0ZBKtJaVmPy3IhTsrdzGy",
        secure=False,
    )
    click.echo(f'  + Conencted to MinIO ')

    # Nombre del bucket
    bucket_name = f'{dataspace}-{connector}'

    # Make 'asiatrip' bucket if not exist.
    click.echo(f"Checking '{bucket_name}'")
    found = client.bucket_exists(bucket_name)
    if not found:
        click.echo(f"Bucket '{bucket_name}' not exist")
    else:
        click.echo(f"Bucket '{bucket_name}' already exists")

    # Obtiene todos los objetos en el bucket
    objects = client.list_objects(bucket_name)
    click.echo(f'  + Objects ')
    # Imprime los nombres de los objetos
    for obj in objects:
        click.echo(obj.object_name)

#######################################
#######################################
### JINJA FUNCTIONS
#######################################
#######################################
from jinja2 import Environment, FileSystemLoader
def create_dataspace_value_files(name, environment):
    ## Se carga el fichero de datos del espacio de datos
    keys = get_password_values(name, environment, 'dataspace', name)
    keys['dataspace_name'] = name

    for key_name, value in load_effective_deployer_config().items():
        keys[key_name.lower()] = value

    # Generate registration-service values file
    #   registration-service
    env = Environment(loader=FileSystemLoader('dataspace/registration-service'))
    template = env.get_template('values.yaml.tpl')

    # Render the template with the values from the 'keys' variable
    output = template.render(keys=keys)

    # Write the rendered template to a new file
    output_path = f'dataspace/registration-service/values-{name}.yaml'
    with open(output_path, 'w') as f:
        f.write(output)

    click.echo(f'Generated values file: {output_path}')

    # Generate public-portal values file
    #   public-portal
    env = Environment(loader=FileSystemLoader('dataspace/public-portal'))
    template = env.get_template('values.yaml.tpl')

    # Render the template with the values from the 'keys' variable
    output = template.render(keys=keys)

    # Write the rendered template to a new file
    output_path = f'dataspace/public-portal/values-{name}.yaml'
    with open(output_path, 'w') as f:
        f.write(output)

    click.echo(f'Generated values file: {output_path}')

def create_connector_value_files(dataspace_name, connector_name, environment):
    ## Se carga el fichero de datos del conector
    keys = get_password_values(dataspace_name, environment, 'connector', connector_name)
    keys['dataspace_name'] = dataspace_name
    keys['connector_name'] = connector_name

    config = load_effective_deployer_config()
    keys['registration_service_internal_hostname'] = registration_service_internal_hostname(
        config,
        dataspace_name,
        environment,
    )

    for key_name, value in config.items():
        keys[key_name.lower()] = value

    # Generate connector values file
    env = Environment(loader=FileSystemLoader('connector'))
    template = env.get_template('values.yaml.tpl')

    # Render the template with the values from the 'keys' variable
    output = template.render(keys=keys)

    # Write the rendered template to a new file
    output_path = f'connector/values-{connector_name}.yaml'
    with open(output_path, 'w') as f:
        f.write(output)

    click.echo(f'Generated values file: {output_path}')


#######################################
#######################################
### MAIN FUNCTION
#######################################
#######################################
if __name__ == '__main__':
    cli()
