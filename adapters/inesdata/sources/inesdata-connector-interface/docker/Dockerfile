# node base image
FROM node:18.16-alpine as builder

# working directory
WORKDIR /app

ENV NG_CLI_ANALYTICS=false \
    npm_config_audit=false \
    npm_config_fund=false \
    npm_config_update_notifier=false \
    CI=true

# install dependencies first to keep the expensive layer stable
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund --no-update-notifier

# copy only the files required by the Angular production build
COPY angular.json ./
COPY tsconfig.json tsconfig.app.json ./
COPY src ./src
COPY docker ./docker

# build without production source maps to reduce memory pressure in WSL
RUN NODE_OPTIONS=--max_old_space_size=1536 npm run build -- --configuration production --source-map=false

# nginx base image
FROM nginx:alpine

ENV NGINX_HOME=/usr/share/nginx
RUN mkdir ${NGINX_HOME}/html/connector-interface
RUN chmod 755 ${NGINX_HOME}/html/connector-interface
ENV DOCUMENT_ROOT=${NGINX_HOME}/html/connector-interface

# copy static contents of project to nginx html
COPY --from=builder /app/dist/inesdata-connector-interface ${DOCUMENT_ROOT}

COPY ./docker/assets/scripts/docker-entrypoint.sh ${NGINX_HOME}

ENV ENVIRONMENT_CFG=${DOCUMENT_ROOT}/assets/config/app.config.json \
    ENVIRONMENT_CFG_TPL=${DOCUMENT_ROOT}/assets/config/app.config.template.json \
    ENVIRONMENT_CFG_TMP=/tmp/app.config.temp.json \
    NGINX_DEFAULT_CONF=/etc/nginx/conf.d/default.conf \
    NGINX_DEFAULT_CONF_TPL=/etc/nginx/conf.d/default.conf.template

# Copia fichero plantilla de configuracion de entorno y otorga permiso de escritura al mismo
COPY ./src/assets/config/app.config.template.json ${ENVIRONMENT_CFG_TPL}
COPY ./src/assets/config/app.config.template.json ${ENVIRONMENT_CFG}

# Se setean permisos
RUN chmod ug+w ${ENVIRONMENT_CFG} \
    && chmod ug+x ${NGINX_HOME}/docker-entrypoint.sh

## Nginx default configuration
COPY ./docker/default.conf ${NGINX_DEFAULT_CONF_TPL}

EXPOSE 8080

# Script entrypoint del contenedor
ENTRYPOINT [ "sh", "-c", "${NGINX_HOME}/docker-entrypoint.sh"]
