#!/bin/bash

# Comprobar que se han proporcionado los argumentos necesarios
if [ "$#" -ne 3 ]; then
    echo "Uso: $0 CONNECTOR_NAME PASS DESTINATION_FOLDER"
    exit 1
fi

# Asignar argumentos a variables
CONNECTOR_NAME=$1
PASS=$2
FOLDER=$3

# Crear la carpeta donde almacenar los certs del nuevo conector si no existe
mkdir -p ${FOLDER}

# Generar clave privada
openssl genpkey -algorithm RSA \
                -out ${FOLDER}/${CONNECTOR_NAME}-private.key

# Generar certificado auto-firmado
openssl req -new -x509 \
            -key ${FOLDER}/${CONNECTOR_NAME}-private.key \
            -out ${FOLDER}/${CONNECTOR_NAME}-public.crt \
            -days 720 \
            -subj "/C=ES/ST=CM/L=Madrid/O=UPM/CN=${CONNECTOR_NAME}.upm.es"

# Almacenar la clave privada y el certificado en un archivo PKCS12
openssl pkcs12 -export \
               -out ${FOLDER}/${CONNECTOR_NAME}-store.p12 \
               -inkey ${FOLDER}/${CONNECTOR_NAME}-private.key \
               -in ${FOLDER}/${CONNECTOR_NAME}-public.crt \
               -password pass:${PASS}