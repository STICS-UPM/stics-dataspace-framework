edc.participant.id={{ .Values.connector.name }}
edc.runtime.id={{ .Values.connector.dataspace }}-{{ .Values.connector.name }}
{{- if eq .Values.connector.environment "pro" }}
edc.hostname={{ .Values.connector.ingress.hostname }}
{{- end }}

# External callback address exposed through ingress
{{- if eq .Values.connector.environment "pro" }}
edc.dsp.callback.address=https://{{ .Values.connector.ingress.hostname }}/protocol
{{- else }}
edc.dsp.callback.address=http://{{ .Values.connector.ingress.hostname }}/protocol
{{- end }}

web.http.port=19191
web.http.path=/api
web.http.management.port=19193
web.http.management.path=/management
web.http.protocol.port=19194
web.http.protocol.path=/protocol
web.http.public.port=19291
web.http.public.path=/public
web.http.control.port=19192
web.http.control.path=/control
web.http.version.port=19195
web.http.version.path=/version
web.http.shared.port=19196
web.http.shared.path=/shared

{{- if eq .Values.connector.environment "pro" }}
edc.dataplane.api.public.baseurl=https://{{ .Values.connector.ingress.hostname }}/public
edc.dataplane.proxy.public.endpoint=https://{{ .Values.connector.ingress.hostname }}/public
{{- else }}
edc.dataplane.api.public.baseurl=http://{{ .Values.connector.ingress.hostname }}/public
edc.dataplane.proxy.public.endpoint=http://{{ .Values.connector.ingress.hostname }}/public
{{- end }}

edc.transfer.proxy.token.signer.privatekey.alias={{ .Values.connector.transfer.privatekey }}
edc.transfer.proxy.token.verifier.publickey.alias={{ .Values.connector.transfer.publickey }}

edc.web.rest.cors.enabled=true
edc.web.rest.cors.headers=origin, content-type, accept, authorization, x-api-key

edc.vault.hashicorp.url={{ .Values.services.vault.url }}
edc.vault.hashicorp.token={{ .Values.services.vault.token }}
edc.edr.vault.path={{ .Values.services.vault.path }}

edc.datasource.default.url=jdbc:postgresql://{{ .Values.services.db.hostname }}:5432/{{ .Values.services.db.name }}
edc.datasource.default.user={{ .Values.services.db.user }}
edc.datasource.default.password={{ .Values.services.db.password }}
edc.datasource.default.pool.maxIdleConnections=10
edc.datasource.default.pool.maxTotalConnections=10
edc.datasource.default.pool.minIdleConnections=5
edc.sql.schema.autocreate={{ .Values.connector.sql.schemaAutocreate }}

edc.aws.access.key={{ .Values.connector.minio.accesskey }}
edc.aws.secret.access.key={{ .Values.connector.minio.secretkey }}
{{- $minioUrl := (default (printf "%s://%s" .Values.services.minio.protocol .Values.services.minio.hostname) .Values.services.minio.url) | trimSuffix "/" }}
edc.aws.endpoint.override={{ $minioUrl }}
edc.aws.region=eu-central-1
edc.aws.bucket.name={{ .Values.services.minio.bucket }}

{{- $keycloakUrl := (default (printf "%s://%s" .Values.services.keycloak.protocol .Values.services.keycloak.hostname) .Values.services.keycloak.url) | trimSuffix "/" }}
edc.oauth.token.url={{ $keycloakUrl }}/realms/{{ .Values.connector.dataspace }}/protocol/openid-connect/token
edc.oauth.provider.audience={{ $keycloakUrl }}/realms/{{ .Values.connector.dataspace }}
edc.oauth.endpoint.audience={{ $keycloakUrl }}/realms/{{ .Values.connector.dataspace }}
edc.oauth.provider.jwks.url={{ $keycloakUrl }}/realms/{{ .Values.connector.dataspace }}/protocol/openid-connect/certs
edc.oauth.certificate.alias={{ .Values.connector.oauth2.publickey }}
edc.oauth.private.key.alias={{ .Values.connector.oauth2.privatekey }}
edc.oauth.client.id={{ .Values.connector.oauth2.client }}
edc.oauth.validation.nbf.leeway=10

edc.api.auth.oauth2.allowedRoles.1.role={{ .Values.connector.oauth2.allowedRole1 }}
edc.api.auth.oauth2.allowedRoles.2.role={{ .Values.connector.oauth2.allowedRole2 }}
edc.api.auth.oauth2.allowedRoles.3.role={{ .Values.connector.oauth2.allowedRole3 }}

edc.catalog.registration.service.host={{ .Values.services.registrationService.protocol }}://{{ .Values.services.registrationService.hostname }}/api
edc.catalog.cache.execution.period.seconds=60
edc.catalog.cache.partition.num.crawlers=2
edc.catalog.cache.execution.delay.seconds=5
edc.participants.cache.execution.period.seconds=1800
