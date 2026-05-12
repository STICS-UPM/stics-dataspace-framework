dataspace:
  name: {{ keys.dataspace_name }}
  environment: {{ 'pro' if keys.environment == 'PRO' else 'dev' }}
registration:
  image:
    name:
      ghcr.io/proyectopionera/inesdata-registration-service
    tag:
      20260309-c341c68
services:
  db:
    hostname:
      {{ keys.database_hostname }}
    registration:
      user:
        {{ keys.registration_service_database.user }}
      password:
        "{{ keys.registration_service_database.passwd }}"
      name:
        {{ keys.registration_service_database.name }}
  keycloak:
    # comsrv prefix comes from the Helm release of the common services
    hostname:
      {{ keys.keycloak_hostname }}
    realm:
      {{ keys.dataspace_name }}
    protocol:
      {{ 'https' if keys.environment == 'PRO' else 'http' }}
ingress:
  registration:
    hostname:
      registration-service-{{ keys.dataspace_name }}{{ '.ds.dataspaceunit-project.eu' if keys.environment == 'PRO' else '.dev.ds.dataspaceunit.upm' }}
hostAliases: []
