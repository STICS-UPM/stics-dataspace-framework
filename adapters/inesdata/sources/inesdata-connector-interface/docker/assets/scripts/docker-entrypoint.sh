#!/bin/sh

# REQUIRED ENV VARS
#
# - $JWT_WHITELISTED_DOMAINS
# - $API_BASEURL_AUTH
# - $API_BASEURL_TASKS
# - $API_BASEURL_USERS
#

# Remplaza los valores de configuracion en entorno con variables de entorno
if test -f "$ENVIRONMENT_CFG_TPL"; then
    echo "Creando fichero de configuracion desde plantilla con variables de entorno"
    envsubst < $ENVIRONMENT_CFG_TPL > $ENVIRONMENT_CFG_TMP && cp $ENVIRONMENT_CFG_TMP $ENVIRONMENT_CFG && cat $ENVIRONMENT_CFG
    echo "Fichero de configuracion de entorno creado"
else
    echo "No existe fichero plantilla de configuracion en $ENVIRONMENT_CFG_TPL"
fi

if test -z "$APP_BASE_HREF"; then
    export APP_BASE_HREF="/inesdata-connector-interface/"
fi

case "$APP_BASE_HREF" in
    */) ;;
    *) APP_BASE_HREF="${APP_BASE_HREF}/" ;;
esac

INDEX_HTML="${DOCUMENT_ROOT}/index.html"
if test -f "$INDEX_HTML"; then
    echo "Configurando base href de la interfaz: $APP_BASE_HREF"
    APP_BASE_HREF_ESCAPED=$(printf '%s' "$APP_BASE_HREF" | sed 's/[&|]/\\&/g')
    sed -i "s|<base href=\"[^\"]*\">|<base href=\"${APP_BASE_HREF_ESCAPED}\">|" "$INDEX_HTML"
else
    echo "No existe index.html en $INDEX_HTML"
fi

if test -z "$MODEL_OBSERVER_PROXY_TARGET" && test -n "$STRAPI_URL"; then
    export MODEL_OBSERVER_PROXY_TARGET="$STRAPI_URL"
fi

if test -z "$MODEL_OBSERVER_PROXY_TARGET"; then
    echo "MODEL_OBSERVER_PROXY_TARGET not configured; using inert local fallback for Nginx proxy"
    export MODEL_OBSERVER_PROXY_TARGET="http://127.0.0.1:9"
fi

if test -f "$NGINX_DEFAULT_CONF_TPL"; then
    echo "Creando configuracion nginx desde plantilla"
    envsubst '${MODEL_OBSERVER_PROXY_TARGET}' < $NGINX_DEFAULT_CONF_TPL > $NGINX_DEFAULT_CONF
    echo "Configuracion nginx creada"
else
    echo "No existe plantilla nginx en $NGINX_DEFAULT_CONF_TPL"
fi

echo "Iniciando servidor web nginx"
# Execute nginx with same parameters defined in nginx:stable official dockerfile
nginx -g 'daemon off;'
