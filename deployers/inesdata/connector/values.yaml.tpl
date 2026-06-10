# This chart deploys a new connector in the Dataspaceunit platform.
#
{% set topology = keys.topology | default(keys.pionera_topology | default(keys.inesdata_topology | default('local', true), true), true) %}
{% set is_vm_topology = topology in ['vm-single', 'vm-distributed'] %}
connector:
  name: {{ keys.connector_name }}
  dataspace: {{ keys.dataspace_name }}
  environment: {{ 'pro' if keys.environment == 'PRO' else 'dev' }}
  image:
    name: ghcr.io/proyectopionera/inesdata-connector
    tag: 20260309-86a226e
  replicas: 1
  jvmArgs: "{% if keys.environment == 'PRO'%}-Djavax.net.ssl.trustStore=/opt/connector/tls-cacerts/cacerts.jks -Djavax.net.ssl.trustStorePassword=dataspaceunit{% endif %}"
  tlsCacerts:
    enabled: {{ keys.connector_tls_cacerts_enabled | default(false, true) | tojson }}
    secretName: {{ (keys.connector_tls_cacerts_secret_name | default('common-tls-cacerts', true)) | tojson }}
    mountPath: {{ (keys.connector_tls_cacerts_mount_path | default('/opt/connector/tls-cacerts', true)) | tojson }}
  modelExecution:
    edrAttempts: {{ keys.connector_model_execution_edr_attempts | default(90, true) }}
    edrDelayMs: {{ keys.connector_model_execution_edr_delay_ms | default(1000, true) }}
  catalogCache:
    executionPeriodSeconds: {{ keys.connector_catalog_cache_execution_period_seconds | default((60 if keys.environment == 'PRO' or is_vm_topology else 15), true) }}
    participantsPeriodSeconds: {{ keys.connector_participants_cache_execution_period_seconds | default((1800 if keys.environment == 'PRO' or is_vm_topology else 30), true) }}
    partitionNumCrawlers: {{ keys.connector_catalog_cache_partition_num_crawlers | default((1 if is_vm_topology else 2), true) }}
    executionDelaySeconds: {{ keys.connector_catalog_cache_execution_delay_seconds | default((30 if is_vm_topology else 5), true) }}
  configuration:
    configFilePath: /opt/connector/config/connector-configuration.properties
  ingress:
    hostname: {{ keys.connector_name }}.{% if keys.environment == 'PRO' %}ds.dataspaceunit-project.eu{% else %}{{ keys.ds_domain_base | default('pionera.oeg.fi.upm.es') }}{% endif %}
    protocol: {{ 'https' if keys.environment == 'PRO' else 'http' }}
    proxyReadTimeout: {{ keys.connector_ingress_proxy_read_timeout | default('300', true) | tojson }}
    proxySendTimeout: {{ keys.connector_ingress_proxy_send_timeout | default('300', true) | tojson }}
    proxyConnectTimeout: {{ keys.connector_ingress_proxy_connect_timeout | default('30', true) | tojson }}
  minio:
    accesskey: {{ keys.dataspace_name }}/{{ keys.connector_name }}/aws-access-key
    secretkey: {{ keys.dataspace_name }}/{{ keys.connector_name }}/aws-secret-key
  oauth2:
    allowedRole1: connector-admin
    allowedRole2: connector-management
    allowedRole3: connector-user
    client: {{ keys.connector_name }}
    privatekey: {{ keys.dataspace_name }}/{{ keys.connector_name }}/private-key
    publickey: {{ keys.dataspace_name }}/{{ keys.connector_name }}/public-key
    type: code
  transfer:
    privatekey: {{ keys.dataspace_name }}/{{ keys.connector_name }}/private-key
    publickey: {{ keys.dataspace_name }}/{{ keys.connector_name }}/public-key

connectorInterface:
  image:
    name: ghcr.io/proyectopionera/inesdata-connector-interface
    tag: 20260309-2e7b345
  branding:
    name: {{ (keys.inesdata_brand_name | default('PIONERA', true)) | tojson }}
    theme: {{ (keys.inesdata_brand_theme | default('theme-1', true)) | tojson }}
    primaryColor: {{ (keys.inesdata_brand_primary_color | default('', true)) | tojson }}
    secondaryColor: {{ (keys.inesdata_brand_secondary_color | default('', true)) | tojson }}
    showMenuText: {{ (keys.inesdata_brand_show_menu_text | default('true', true)) | tojson }}
    assetBaseUrl: {{ (keys.inesdata_brand_asset_base_url | default('/inesdata-connector-interface/assets/branding', true)) | tojson }}
    logoFiles: {{ (keys.inesdata_brand_logo_files | default('', true)) | tojson }}
    logoUrls: {{ (keys.inesdata_brand_logo_urls | default('', true)) | tojson }}
    footerLogoFiles: {{ (keys.inesdata_brand_footer_logo_files | default('', true)) | tojson }}
    footerLogoUrls: {{ (keys.inesdata_brand_footer_logo_urls | default('', true)) | tojson }}
    poweredByText: {{ (keys.inesdata_brand_powered_by_text | default('Powered by:', true)) | tojson }}
    poweredByLogoFiles: {{ (keys.inesdata_brand_powered_by_logo_files | default('', true)) | tojson }}
    poweredByLogoUrls: {{ (keys.inesdata_brand_powered_by_logo_urls | default('', true)) | tojson }}
    footerText: {{ (keys.inesdata_brand_footer_text | default('', true)) | tojson }}
    localStoreLabel: {{ (keys.inesdata_local_store_label | default('InesDataStore', true)) | tojson }}
    assetsConfigMapName: {{ (keys.inesdata_brand_assets_configmap_name | default('', true)) | tojson }}
    assets: {{ (keys.inesdata_brand_assets | default([], true)) | tojson }}
{% set ontology_public_url = keys.ontology_hub_public_url | default('', true) %}
{% if not ontology_public_url and (keys.components_public_base_url | default('', true)) %}
{% set ontology_public_path = keys.ontology_hub_public_path | default('/ontology-hub', true) %}
{% set ontology_public_url = (keys.components_public_base_url.rstrip('/') ~ '/' ~ ontology_public_path.lstrip('/')).rstrip('/') %}
{% endif %}
  ontologyHub:
    url: {{ (ontology_public_url if ontology_public_url else (('https' if keys.environment == 'PRO' else 'http') ~ '://ontology-hub-' ~ keys.dataspace_name ~ '.' ~ ('ds.dataspaceunit-project.eu' if keys.environment == 'PRO' else (keys.ds_domain_base | default('pionera.oeg.fi.upm.es'))))) | tojson }}
  modelObserver:
    strapiUrl: {{ 'https' if keys.environment == 'PRO' else 'http' }}://backend-{{ keys.dataspace_name }}.{% if keys.environment == 'PRO' %}ds.dataspaceunit-project.eu{% else %}{{ keys.ds_domain_base | default('pionera.oeg.fi.upm.es') }}{% endif %}
    proxyTarget: {{ 'https' if keys.environment == 'PRO' else 'http' }}://backend-{{ keys.dataspace_name }}.{% if keys.environment == 'PRO' %}ds.dataspaceunit-project.eu{% else %}{{ keys.ds_domain_base | default('pionera.oeg.fi.upm.es') }}{% endif %}
  oauth2:
    client:
      dataspace-users
    type:
      code
    scope:
      openid profile email

services:
  db:
    # comsrv prefix comes from the Helm release of the common services
    hostname: {{ keys.database_hostname }}
    # credentials for the new Connector DB. `user` will also be used to create the DB
    # and therefore must comply with SQL identifiers restrictions
    name: {{ keys.database.name }}
    user: {{ keys.database.user }}
    password: {{ keys.database.passwd }}
  keycloak:
    # comsrv prefix comes from the Helm release of the common services
    hostname: {{ keys.keycloak_hostname }}
    external: {{ keys.keycloak_hostname }}
    protocol: {{ 'https' if keys.environment == 'PRO' else 'http' }}
  minio:
    # comsrv prefix comes from the Helm release of the common services
    hostname: {{ keys.minio_hostname }}
    bucket: {{ keys.dataspace_name }}-{{ keys.connector_name }}
    protocol: {{ 'https' if keys.environment == 'PRO' else 'http' }}
  registrationService:
    hostname: {% if keys.environment == 'PRO' %}registration-service-{{ keys.dataspace_name }}.ds.dataspaceunit-project.eu{%
                                         else %}{{ keys.registration_service_internal_hostname | default(keys.dataspace_name ~ '-registration-service:8080') }}{% endif %}
    protocol: {{ 'https' if keys.environment == 'PRO' else 'http' }}
  vault:
    url: {{ keys.vault_url }}
    token: {{ keys.vault.token }}
    path: {{ keys.dataspace_name }}/{{ keys.connector_name }}/
hostAliases:
- ip: 192.168.49.2
  hostnames:
  - {{ keys.keycloak_hostname | default('auth.' + (keys.domain_base | default('pionera.oeg.fi.upm.es'))) }}
  - {{ keys.keycloak_admin_hostname | default('admin.auth.' + (keys.domain_base | default('pionera.oeg.fi.upm.es'))) }}
  - {{ keys.minio_hostname | default('minio.' + (keys.domain_base | default('pionera.oeg.fi.upm.es'))) }}
  - {{ keys.minio_console_hostname | default('console.minio-s3.' + (keys.domain_base | default('pionera.oeg.fi.upm.es'))) }}
  - registration-service-{{ keys.dataspace_name }}.{{ keys.ds_domain_base | default('pionera.oeg.fi.upm.es') }}
  - ontology-hub-{{ keys.dataspace_name }}.{{ keys.ds_domain_base | default('pionera.oeg.fi.upm.es') }}
  - ai-model-hub-{{ keys.dataspace_name }}.{{ keys.ds_domain_base | default('pionera.oeg.fi.upm.es') }}
{% for c in (keys.ds_1_connectors | default('')).split(',') %}{% if c.strip() %}  - conn-{{ c.strip() }}-{{ keys.dataspace_name }}.{{ keys.ds_domain_base | default('pionera.oeg.fi.upm.es') }}
{% endif %}{% endfor %}
