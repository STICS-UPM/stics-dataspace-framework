dataspace:
  name: {{ keys.dataspace_name }}
  environment: {{ 'pro' if keys.environment == 'PRO' else 'dev' }}
backend:
  image:
    name:
      ghcr.io/proyectopionera/inesdata-public-portal-backend
    tag:
      20260309-dbfde06
  api:
    token:
      salt:
        {{ keys.web_portal_secrets.STRAPI_API_TOKEN_SALT }}
  app:
    keys:
      {{ keys.web_portal_secrets.STRAPI_APP_KEYS }}
  catalog:
    connector:
      {{ 'https' if keys.environment == 'PRO' else 'http' }}://CHANGEME-conn-NAME-{{ keys.dataspace_name }}{{ '.ds.dataspaceunit-project.eu' if keys.environment == 'PRO' else ':19193' }}
  vocabularies:
    connector:
      {{ 'https' if keys.environment == 'PRO' else 'http' }}://CHANGEME-conn-NAME-{{ keys.dataspace_name }}{{ '.ds.dataspaceunit-project.eu' if keys.environment == 'PRO' else ':19196' }}
  jwt:
    secret:
      core:
        {{ keys.web_portal_secrets.STRAPI_JWT_SECRET }}
      admin:
        {{ keys.web_portal_secrets.STRAPI_ADMIN_JWT_SECRET }}
  oauth2:
    client:
      dataspace-users
    type:
      code
    scope:
      openid profile email
    username:
      {{ keys.strapi_user.user }}
    password:
      {{ keys.strapi_user.passwd }}
frontend:
  image:
    name:
      ghcr.io/proyectopionera/inesdata-public-portal-frontend
    tag:
      20260309-c5e8553
services:
  db:
    hostname:
      {{ keys.database_hostname }}
    portal:
      user:
        {{ keys.web_portal_database.user }}
      password:
        "{{ keys.web_portal_database.passwd }}"
      name:
        {{ keys.web_portal_database.name }}
  keycloak:
    # comsrv prefix comes from the Helm release of the common services
    hostname:
      {{ keys.keycloak_hostname }}
    realm:
      {{ keys.dataspace_name }}
    protocol:
      {{ 'https' if keys.environment == 'PRO' else 'http' }}
    url:
      {{ 'https' if keys.environment == 'PRO' else 'http' }}://{{ keys.keycloak_hostname }}/realms/{{ keys.dataspace_name }}
ingress:
  frontend:
    hostname:
      {{ keys.dataspace_name }}{{ '.ds.dataspaceunit-project.eu' if keys.environment == 'PRO' else '.dev.ds.dataspaceunit.upm' }}
  backend:
    hostname:
      backend-{{ keys.dataspace_name }}{{ '.ds.dataspaceunit-project.eu' if keys.environment == 'PRO' else '.dev.ds.dataspaceunit.upm' }}
  protocol:
    {{ 'https' if keys.environment == 'PRO' else 'http' }}
