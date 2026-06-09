# This chart deploys the PIONERA benchmark EDC connector for the Validation-Environment.
#
connector:
  name: {{ keys.connector_name }}
  dataspace: {{ keys.dataspace_name }}
  environment: {{ 'pro' if keys.environment == 'PRO' else 'dev' }}
  image:
    name: ghcr.io/proyectopionera/edc-connector
    tag: latest
    pullPolicy: IfNotPresent
  replicas: 1
  tlsCacerts:
    enabled: {{ keys.connector_tls_cacerts_enabled | default((keys.environment == 'PRO'), true) | tojson }}
    secretName: {{ (keys.connector_tls_cacerts_secret_name | default('common-tls-cacerts', true)) | tojson }}
    mountPath: {{ (keys.connector_tls_cacerts_mount_path | default('/opt/connector/tls-cacerts', true)) | tojson }}
  jvmArgs: "{% if keys.connector_tls_cacerts_enabled | default((keys.environment == 'PRO'), true) %}-Djavax.net.ssl.trustStore={{ keys.connector_tls_cacerts_mount_path | default('/opt/connector/tls-cacerts', true) }}/cacerts.jks -Djavax.net.ssl.trustStorePassword={{ keys.connector_tls_cacerts_password | default('dataspaceunit', true) }}{% endif %}"
  configuration:
    configFilePath: /opt/connector/config/connector-configuration.properties
  sql:
    schemaAutocreate: {{ keys.edc_sql_schema_autocreate | default(true) }}
  inference:
    edrAttempts: {{ keys.edc_inference_edr_attempts | default(40) }}
    edrDelayMs: {{ keys.edc_inference_edr_delay_ms | default(1000) }}
  ingress:
    hostname: {{ keys.connector_name }}.{% if keys.environment == 'PRO' %}ds.dataspaceunit-project.eu{% else %}{{ keys.ds_domain_base }}{% endif %}
    protocol: {{ 'https' if keys.environment == 'PRO' else 'http' }}
  public:
    protocolUrl: {{ (keys.connector_public_protocol_url | default('', true)) | tojson }}
    publicUrl: {{ (keys.connector_public_public_url | default('', true)) | tojson }}
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
  transfer:
    privatekey: {{ keys.dataspace_name }}/{{ keys.connector_name }}/private-key
    publickey: {{ keys.dataspace_name }}/{{ keys.connector_name }}/public-key
  keys:
    createSecret: false
    existingSecret: ""
  ontologyHub:
    externalBase: ""
    internalBase: ""
    internalFallback: http://ontology-hub:3333
    internalClusterLocalFallback: ""

dashboard:
  enabled: {{ keys.edc_dashboard_enabled | default(false) }}
  replicas: 1
  baseHref: /edc-dashboard/
  image:
    name: {{ keys.edc_dashboard_image_name | default('validation-environment/edc-dashboard') }}
    tag: {{ keys.edc_dashboard_image_tag | default('latest') }}
    pullPolicy: IfNotPresent
  proxy:
    enabled: {{ keys.edc_dashboard_enabled | default(false) }}
    port: 8080
    image:
      name: {{ keys.edc_dashboard_proxy_image_name | default('validation-environment/edc-dashboard-proxy') }}
      tag: {{ keys.edc_dashboard_proxy_image_tag | default('latest') }}
      pullPolicy: {{ keys.edc_dashboard_proxy_image_pull_policy | default('IfNotPresent') }}
    config:
      authMode: {{ keys.edc_dashboard_proxy_auth_mode | default('service-account') }}
      clientId: dataspace-users
      tokenUrl: ""
      connectors: []
    auth:
      connectors: []
  runtime:
    appConfig:
      appTitle: EDC Dashboard
      healthCheckIntervalSeconds: 30
      enableUserConfig: false
      # Populated at deploy time by adapters/edc/connectors.py (includes Ontologies). Do not leave empty.
      menuItems:
        - text: Home
          materialSymbol: home_app_logo
          routerPath: home
          divider: true
        - text: Ontologies
          materialSymbol: account_tree
          routerPath: ontologies
    connectorConfig: []
    baseHref: /edc-dashboard/

services:
  db:
    hostname: {{ keys.database_hostname }}
    port: {{ keys.database_port | default(5432) }}
    name: {{ keys.database.name }}
    user: {{ keys.database.user }}
    password: {{ keys.database.passwd }}
  keycloak:
    hostname: {{ keys.keycloak_hostname }}
    external: {{ keys.keycloak_hostname }}
    protocol: {{ 'https' if keys.environment == 'PRO' else 'http' }}
  minio:
    hostname: {{ keys.minio_hostname }}
    bucket: {{ keys.dataspace_name }}-{{ keys.connector_name }}
    protocol: {{ 'https' if keys.environment == 'PRO' else 'http' }}
  registrationService:
    hostname: {% if keys.environment == 'PRO' %}registration-service-{{ keys.dataspace_name }}.ds.dataspaceunit-project.eu{% else %}{{ keys.registration_service_internal_hostname | default(keys.dataspace_name ~ '-registration-service:8080') }}{% endif %}
    protocol: {{ 'https' if keys.environment == 'PRO' else 'http' }}
  vault:
    url: {{ keys.vault_url }}
    token: {{ keys.vault.token }}
    path: {{ keys.dataspace_name }}/{{ keys.connector_name }}/

hostAliases:
- ip: "192.168.49.2"
  hostnames:
  - "auth.dev.ed.dataspaceunit.upm"
  - "admin.auth.dev.ed.dataspaceunit.upm"
  - "minio.dev.ed.dataspaceunit.upm"
  - "console.minio-s3.dev.ed.dataspaceunit.upm"
  - "registration-service-{{ keys.dataspace_name }}.{{ keys.ds_domain_base }}"
