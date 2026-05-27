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
  branding:
    name:
      {{ (keys.inesdata_brand_name | default('PIONERA', true)) | tojson }}
    theme:
      {{ (keys.inesdata_brand_theme | default('theme-1', true)) | tojson }}
    primaryColor:
      {{ (keys.inesdata_brand_primary_color | default('', true)) | tojson }}
    secondaryColor:
      {{ (keys.inesdata_brand_secondary_color | default('', true)) | tojson }}
    showMenuText:
      {{ (keys.inesdata_brand_show_menu_text | default('true', true)) | tojson }}
    assetBaseUrl:
      {{ (keys.inesdata_brand_asset_base_url | default('/assets/branding', true)) | tojson }}
    logoFiles:
      {{ (keys.inesdata_brand_logo_files | default('', true)) | tojson }}
    logoUrls:
      {{ (keys.inesdata_brand_logo_urls | default('', true)) | tojson }}
    footerLogoFiles:
      {{ (keys.inesdata_brand_footer_logo_files | default('', true)) | tojson }}
    footerLogoUrls:
      {{ (keys.inesdata_brand_footer_logo_urls | default('', true)) | tojson }}
    poweredByText:
      {{ (keys.inesdata_brand_powered_by_text | default('Powered by:', true)) | tojson }}
    poweredByLogoFiles:
      {{ (keys.inesdata_brand_powered_by_logo_files | default('', true)) | tojson }}
    poweredByLogoUrls:
      {{ (keys.inesdata_brand_powered_by_logo_urls | default('', true)) | tojson }}
    footerText:
      {{ (keys.inesdata_brand_footer_text | default('', true)) | tojson }}
    assets:
      {{ (keys.inesdata_brand_assets | default([], true)) | tojson }}
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
