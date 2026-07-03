# 48. Guía Para Dummies: Cómo Montar un Conector EDC Nuevo Desde Cero

## Para quién es esta guía

Para cualquiera que necesite añadir **un conector EDC más** al dataspace `stics`,
sin haber estado en la sesión donde se hizo la primera vez. No asume
conocimiento previo del framework — explica el *por qué* de cada paso, no solo
el comando.

Está basada exactamente en cómo se montaron los 4 conectores que ya existen
hoy (`connector-stics`, `conlab-stics`, `contest-stics`, `contest-bavenir`),
incluyendo los tropiezos reales que tuvimos y cómo se resolvieron.

## Idea general antes de empezar

Un conector EDC en este proyecto **no vive dentro de Kubernetes** (a
diferencia de cómo lo hace el framework "de fábrica"). Vive como un programa
Java normal (`connector.jar`), corriendo dentro de un contenedor Docker, en
la VM que tú elijas. Lo único que sigue viviendo en Kubernetes son los
**servicios comunes** (Keycloak, Vault, MinIO, registration-service),
desplegados en la VM `stics2test` (`192.168.122.2`).

Para que el conector nuevo funcione, necesita 4 cosas:

1. **Una identidad** en el dataspace: un cliente en Keycloak, un par de claves
   en Vault, un bucket en MinIO. Esto lo genera un script que ya tenemos, no
   hay que crearlo a mano.
2. **Una base de datos Postgres** donde guardar sus propios datos (assets,
   contratos, transferencias).
3. **Un fichero de configuración** (`.properties`) que le dice al conector
   cómo llegar a Keycloak/Vault/MinIO/Postgres y qué identidad usar.
4. **Un "puente" de red** para que el mundo exterior (otros conectores,
   navegadores) pueda llegar hasta él vía HTTPS con un nombre público.

Vamos paso a paso.

---

## Paso 0: Decide 3 cosas antes de tocar nada

- **Nombre del conector** (su "participant id" en el dataspace). Regla
  importante: **máximo 20 caracteres**. Si te pasas, el script de
  aprovisionamiento falla con `ValueError: Invalid connector name`. Ejemplo:
  `contest-bavenir` (15 caracteres) en vez de `contest-bavenir-stics` (22,
  demasiado largo).
- **En qué VM va a vivir** (¿una VM nueva, o una que ya tiene otro conector?
  Esto importa mucho, ver el aviso más abajo).
- **Qué hostname público va a tener** (p. ej. `mi-conector.stics.linkeddata.es`).
  Tiene que ser un dominio que **ya resuelva** por DNS hacia la IP pública de
  la VM elegida. Compruébalo así antes de continuar:

  ```bash
  nslookup mi-conector.stics.linkeddata.es 8.8.8.8
  ```

  Si no resuelve, alguien tiene que darlo de alta en el DNS antes de seguir
  (normalmente OEG-UPM para `*.linkeddata.es`, o el proveedor de la VM para
  otros dominios). Puedes preparar todo lo demás mientras tanto, pero no
  podrás verificar el acceso público hasta que el DNS esté activo.

### ⚠️ Aviso importante: comprueba si la VM ya tiene otro conector

Antes de asumir que es una "VM nueva", compruébalo de verdad. Nos pasó que
alguien nos dio una IP como si fuera una máquina distinta, y resultó ser
**la misma VM** donde ya teníamos un conector corriendo (solo que con un
usuario de sistema distinto). Compruébalo así:

```bash
ssh usuario_que_ya_conoces@IP_DE_LA_VM 'hostname; hostname -I; getent passwd usuario_que_te_han_dado_nuevo'
```

Si el `hostname` coincide con una VM que ya conoces, es la misma máquina.
Esto importa porque **dos conectores en la misma VM no pueden usar los mismos
puertos** — hay que usar puertos distintos y red tipo *bridge* de Docker en
vez de `network_mode: host` (lo explico en el Paso 6).

---

## Paso 1: Comprobar que la VM tiene lo necesario

Conéctate a la VM y comprueba:

```bash
ssh usuario@IP_DE_LA_VM 'docker --version; docker compose version; java -version'
```

Si falta Docker o Docker Compose, hay que instalarlos antes de seguir (no
cubierto en esta guía, es instalación estándar de Docker Engine en Ubuntu).

---

## Paso 2: Preparar la base de datos Postgres del conector

El conector necesita su propio Postgres para guardar sus assets, contratos y
transferencias (tablas `edc_asset`, `edc_contract_negotiation`, etc.).

### Caso A: la VM ya tiene su propio Postgres local (lo normal)

```bash
ssh usuario@IP_DE_LA_VM 'sudo -u postgres psql' << 'EOF'
DROP DATABASE IF EXISTS <NOMBRE_DB>;
DROP ROLE IF EXISTS <NOMBRE_DB>;
CREATE ROLE <NOMBRE_DB> LOGIN PASSWORD '<CONTRASEÑA_SEGURA>';
CREATE DATABASE <NOMBRE_DB> OWNER <NOMBRE_DB>;
EOF
```

Usa el mismo nombre para el rol y la base de datos, y que coincida con el
nombre del conector (con guiones bajos en vez de guiones si hace falta, p.ej.
`contest_bavenir_stics`).

### Caso B: el conector va a vivir en la MISMA VM que los servicios comunes (`stics2test`)

Sorpresa agradable: en esa VM concreta, el Postgres compartido de Keycloak/
registration-service **ya es accesible directamente en `127.0.0.1:5432`**, sin
necesitar túneles. Y mejor todavía: **el script de aprovisionamiento del Paso 3
ya crea automáticamente una base de datos ahí para el conector** — no hace
falta que crees nada a mano en este caso. Solo tienes que leer el nombre/
usuario/contraseña que el script generó, del fichero `credentials.json`
(ver Paso 3).

---

## Paso 3: Aprovisionar la identidad (Keycloak + Vault + MinIO)

Esto es lo más "mágico" del proceso, pero ya está resuelto: hay una función
del framework que hace exactamente esto por ti, sin necesidad de desplegar
nada en Kubernetes. Guarda este script (ajustando `CONNECTOR_NAME` y
`NAMESPACE`) y ejecútalo **desde la VM `stics2test`** (donde vive el
framework):

```python
# guardar como provision_<nombre>.py y ejecutar con el venv del framework:
# /home/stics2/Validation-Environment/.venv/bin/python3 provision_<nombre>.py
import os
import sys

REPO_ROOT = "/home/stics2/Validation-Environment"
os.chdir(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

CONNECTOR_NAME = "MI-CONECTOR"        # <-- máximo 20 caracteres
DS_NAME = "stics"
NAMESPACE = "MI-NAMESPACE"            # <-- puede ser cualquier palabra corta, p.ej. "contest"

os.environ["PIONERA_DS_1_NAME"] = DS_NAME
os.environ["PIONERA_DS_1_NAMESPACE"] = "core-control"
os.environ["PIONERA_DS_1_CONNECTORS"] = CONNECTOR_NAME
os.environ["PIONERA_DS_1_CONNECTOR_NAMESPACES"] = f"{CONNECTOR_NAME}:{NAMESPACE}"
os.environ["PIONERA_DS_1_REGISTRATION_NAMESPACE"] = "core-control"
os.environ["PIONERA_NAMESPACE_PROFILE"] = "role-aligned"
os.environ["PIONERA_COMMON_SERVICES_NAMESPACE"] = "common-srvs"
os.environ["PIONERA_DOMAIN_BASE"] = "dev.linkeddata.es"
os.environ["PIONERA_DS_DOMAIN_BASE"] = "dev.linkeddata.es"

import main as framework_main  # noqa: E402

print("Construyendo el adapter 'edc' ...")
adapter = framework_main.build_adapter("edc", topology="vm-distributed")

print("Comprobando requisitos (Vault, Postgres, Keycloak) ...")
repo_dir, python_exec = adapter.connectors._prepare_runtime_prerequisites()

print(f"Aprovisionando identidad para '{CONNECTOR_NAME}' ...")
ok = adapter.connectors._prepare_connector_prerequisites(
    CONNECTOR_NAME, DS_NAME, NAMESPACE, repo_dir, python_exec
)
print("RESULTADO:", "OK" if ok else "FALLÓ")

credentials_path = adapter.connectors._connector_credentials_file_path(CONNECTOR_NAME, DS_NAME)
print("Fichero de credenciales:", credentials_path)
```

**Qué hace realmente esto, en plata:**

- Crea un cliente OAuth2 en Keycloak (para que el conector se pueda autenticar).
- Genera un par de claves (privada/pública) y las guarda en Vault (para firmar
  tokens de transferencia).
- Crea un bucket en MinIO y le da permisos.
- Registra el conector como "participante" en el registration-service (aunque
  con una URL provisional que **hay que corregir luego**, ver Paso 9).
- Escribe todo lo anterior (menos las claves de Vault en sí, que se quedan en
  Vault) en un fichero JSON:

  ```text
  deployers/edc/deployments/DEV/vm-distributed/stics/connectors/<CONNECTOR_NAME>/credentials.json
  ```

  Ese fichero contiene, entre otras cosas, el **token de Vault** y (si aplica,
  ver Paso 2 Caso B) el nombre/usuario/contraseña de una base de datos ya
  creada. Trátalo como secreto — no lo subas a git (ya está en
  `.gitignore`).

---

## Paso 4: Conseguir el `.jar` del conector

No hace falta compilar nada. El mismo `connector.jar` sirve para cualquier
conector (la identidad se configura por fuera, en el `.properties`). Cópialo
de un conector que ya funcione:

```bash
scp usuario@VM_CON_CONECTOR_EXISTENTE:~/edc-<algo>/connector.jar ~/edc-<mi-conector>/mi-conector.jar
```

(o el nombre de fichero que tenga en ese conector; en nuestro caso se llama
`provider-connector.jar`, `consumer-connector.jar`, etc. — el contenido es
idéntico).

---

## Paso 5: Escribir el fichero `.properties`

Esta es la plantilla completa que ya hemos usado 4 veces. Copia esto,
sustituye los `<CAMPOS>` y guárdalo como `<mi-conector>-configuration-docker.properties`:

```properties
edc.participant.id=<CONNECTOR_NAME>
edc.runtime.id=stics-<CONNECTOR_NAME>

edc.dsp.callback.address=https://<MI_HOSTNAME_PUBLICO>/protocol

web.http.port=19191
web.http.path=/api
web.http.management.port=19193
web.http.management.path=/management
web.http.protocol.port=19194
web.http.protocol.path=/protocol
web.http.public.port=19291
web.http.public.path=/public
edc.dataplane.api.public.baseurl=https://<MI_HOSTNAME_PUBLICO>/public
edc.dataplane.proxy.public.endpoint=https://<MI_HOSTNAME_PUBLICO>/public
web.http.control.port=19192
web.http.control.path=/control
web.http.version.port=19195
web.http.version.path=/version
web.http.shared.port=19196
web.http.shared.path=/shared

edc.transfer.proxy.token.signer.privatekey.alias=stics/<CONNECTOR_NAME>/private-key
edc.transfer.proxy.token.verifier.publickey.alias=stics/<CONNECTOR_NAME>/public-key

edc.web.rest.cors.enabled=true
edc.web.rest.cors.origins=http://localhost:4200
edc.web.rest.cors.methods=GET,POST,PUT,DELETE,OPTIONS
edc.web.rest.cors.headers=origin, content-type, accept, authorization, x-api-key

edc.vault.hashicorp.url=https://conn-citycouncil-demo.dev.linkeddata.es
edc.vault.hashicorp.token=<VAULT_TOKEN_DE_credentials.json>
edc.edr.vault.path=stics/<CONNECTOR_NAME>/

edc.datasource.default.url=jdbc:postgresql://<HOST_POSTGRES>:5432/<NOMBRE_DB>
edc.datasource.default.user=<USUARIO_DB>
edc.datasource.default.password=<CONTRASEÑA_DB>
edc.datasource.default.pool.maxIdleConnections=10
edc.datasource.default.pool.maxTotalConnections=10
edc.datasource.default.pool.minIdleConnections=5
edc.sql.schema.autocreate=true

# Estos dos NO son claves reales, son "alias" que apuntan a Vault — el conector
# los resuelve él solo en tiempo de ejecución. No hace falta rellenarlos con
# valores reales.
edc.aws.access.key=stics/<CONNECTOR_NAME>/aws-access-key
edc.aws.secret.access.key=stics/<CONNECTOR_NAME>/aws-secret-key
edc.aws.endpoint.override=https://minio.dev.linkeddata.es
edc.aws.region=eu-central-1
edc.aws.bucket.name=stics-<CONNECTOR_NAME>

edc.oauth.token.url=https://auth.dev.linkeddata.es/realms/stics/protocol/openid-connect/token
edc.oauth.provider.audience=https://auth.dev.linkeddata.es/realms/stics
edc.oauth.endpoint.audience=https://auth.dev.linkeddata.es/realms/stics
edc.oauth.provider.jwks.url=https://auth.dev.linkeddata.es/realms/stics/protocol/openid-connect/certs
edc.oauth.certificate.alias=stics/<CONNECTOR_NAME>/public-key
edc.oauth.private.key.alias=stics/<CONNECTOR_NAME>/private-key
edc.oauth.client.id=<CONNECTOR_NAME>
edc.oauth.validation.nbf.leeway=10

edc.api.auth.oauth2.allowedRoles.1.role=connector-admin
edc.api.auth.oauth2.allowedRoles.2.role=connector-management
edc.api.auth.oauth2.allowedRoles.3.role=connector-user

edc.catalog.registration.service.host=https://registration-service-demo.dev.linkeddata.es/api
edc.catalog.cache.execution.period.seconds=60
edc.catalog.cache.partition.num.crawlers=2
edc.catalog.cache.execution.delay.seconds=5
edc.participants.cache.execution.period.seconds=1800
```

**`<HOST_POSTGRES>` depende de dónde está la base de datos respecto al
contenedor** (importante, ver Paso 6):
- Si el contenedor usa `network_mode: host` → `127.0.0.1`.
- Si el contenedor usa red *bridge* con Postgres en el mismo host → la IP de
  la puerta de enlace de Docker (normalmente `172.17.0.1`, compruébalo con
  `docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'`).

---

## Paso 6: El `docker-compose.yml` — la decisión importante

### Si tu VM NO tiene ya otro conector corriendo (caso simple)

```yaml
services:
  mi-conector:
    image: eclipse-temurin:17-jre
    container_name: mi-conector
    working_dir: /workspace
    command:
      - java
      - -Djavax.net.ssl.trustStore=/workspace/cacerts.jks
      - -Djavax.net.ssl.trustStorePassword=dataspaceunit
      - -Dedc.fs.config=/workspace/mi-conector-configuration-docker.properties
      - -jar
      - /workspace/mi-conector.jar
    volumes:
      - /home/usuario/edc-mi-conector/mi-conector.jar:/workspace/mi-conector.jar:ro
      - /home/usuario/edc-mi-conector/mi-conector-configuration-docker.properties:/workspace/mi-conector-configuration-docker.properties:ro
      - /home/usuario/edc-mi-conector/cacerts.jks:/workspace/cacerts.jks:ro
    network_mode: host
    restart: unless-stopped
```

`network_mode: host` es lo más simple: el contenedor comparte la red de la
VM directamente, así que `127.0.0.1` dentro del contenedor es la propia VM
(imprescindible para llegar a un Postgres que solo escucha en localhost).

### Si tu VM YA tiene otro conector corriendo (caso con dos conectores)

**No uses `network_mode: host`** — chocaría en todos los puertos con el
conector que ya está ahí (incluido un puerto interno fijo, `17171`, que usa
la extensión de catálogo federado y que no parece configurable). En vez de
eso, usa red *bridge* normal con mapeo de puertos explícito, desplazando cada
puerto en +10000 (o el offset que prefieras):

```yaml
services:
  mi-conector:
    image: eclipse-temurin:17-jre
    container_name: mi-conector
    working_dir: /workspace
    command:
      - java
      - -Djavax.net.ssl.trustStore=/workspace/cacerts.jks
      - -Djavax.net.ssl.trustStorePassword=dataspaceunit
      - -Dedc.fs.config=/workspace/mi-conector-configuration-docker.properties
      - -jar
      - /workspace/mi-conector.jar
    volumes:
      - /home/usuario/edc-mi-conector/mi-conector.jar:/workspace/mi-conector.jar:ro
      - /home/usuario/edc-mi-conector/mi-conector-configuration-docker.properties:/workspace/mi-conector-configuration-docker.properties:ro
      - /home/usuario/edc-mi-conector/cacerts.jks:/workspace/cacerts.jks:ro
    ports:
      - "29191:19191"
      - "29192:19192"
      - "29193:19193"
      - "29194:19194"
      - "29195:19195"
      - "29196:19196"
      - "29291:19291"
      - "27171:17171"
    restart: unless-stopped
```

Fíjate: **dentro** del `.properties` los puertos siguen siendo los normales
(19191 etc.) — solo cambia por fuera, en el mapeo `ports:`. El bridge de
Postgres deja de ser `127.0.0.1` en este caso — tienes que:

```bash
# en la VM, dar permiso a Postgres para aceptar conexiones desde Docker
sudo -u postgres psql -c "ALTER SYSTEM SET listen_addresses = '*';"
echo "host    all    all    172.16.0.0/12    md5" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf
sudo systemctl restart postgresql
```

(`172.16.0.0/12` cubre cualquier subred que Docker Compose decida crear —
cada `docker compose up` en un proyecto nuevo puede usar una subred
distinta, tipo `172.17.0.0/16`, `172.18.0.0/16`, etc.)

---

## Paso 7: El truststore compartido (`cacerts.jks`)

Todos los servicios de este dataspace usan certificados TLS firmados por un
CA propio (autofirmado), no uno público. Sin este fichero, el conector falla
al arrancar con `PKIX path building failed`. Cópialo desde cualquier
namespace de Kubernetes que ya lo tenga:

```bash
kubectl -n core-control get secret common-tls-cacerts -o jsonpath='{.data.cacerts\.jks}' | base64 -d > cacerts.jks
scp cacerts.jks usuario@TU_VM:~/edc-mi-conector/cacerts.jks
```

La contraseña de este truststore es siempre `dataspaceunit` (ya está en el
`.properties` de arriba, en el comando `java -Djavax.net.ssl.trustStorePassword=...`).

---

## Paso 8: Levantarlo

```bash
ssh usuario@TU_VM 'cd ~/edc-mi-conector && docker compose up -d'
```

Espera unos 10 segundos y mira los logs:

```bash
ssh usuario@TU_VM 'docker logs mi-conector --tail 30'
```

Busca la línea `Runtime stics-<CONNECTOR_NAME> ready` — si aparece, el
conector arrancó. Si no, mira la sección de "Errores típicos" al final.

---

## Paso 9: Dos arreglos que SIEMPRE hacen falta después del primer arranque

### 9a. Las tablas de INESData que el autocreate no crea

El jar incluye extensiones propias de INESData (catálogo federado, validador
de vocabulario) que necesitan tablas que el `edc.sql.schema.autocreate=true`
estándar **no crea solo**. Aplícalas a mano, una vez, contra la base de datos
del conector:

```bash
psql -h <HOST_POSTGRES> -U <USUARIO_DB> -d <NOMBRE_DB> \
  -f adapters/inesdata/sources/inesdata-connector/resources/sql/060_federated-catalog-schema.sql
psql -h <HOST_POSTGRES> -U <USUARIO_DB> -d <NOMBRE_DB> \
  -f adapters/inesdata/sources/inesdata-connector/resources/sql/060_vocabulary-schema.sql
```

Si no lo haces, verás errores en el log tipo
`relation "edc_catalog" does not exist` o `relation "edc_vocabulary" does not exist`.

### 9b. La URL del participante registrada está mal

El Paso 3 registra el conector con una URL "interna" que no sirve desde fuera
(tipo `http://<CONNECTOR_NAME>:19194/protocol`). Hay que corregirla a mano en
la base de datos del **registration-service** (no la del conector — esta vive
en el Postgres compartido, VM `stics2test`, `127.0.0.1:5432`, base de datos
`stics_rs`):

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d stics_rs -c "
UPDATE public.edc_participant
SET url = 'https://<MI_HOSTNAME_PUBLICO>/protocol',
    shared_url = 'https://<MI_HOSTNAME_PUBLICO>/shared'
WHERE participant_id = '<CONNECTOR_NAME>';
"
```

Después de estos dos arreglos, reinicia el conector:

```bash
ssh usuario@TU_VM 'cd ~/edc-mi-conector && docker compose restart'
```

---

## Paso 10: El "puente" de red — la parte más delicada

Aquí es donde más nos hemos equivocado en la práctica, así que léelo con
calma. La idea: alguien en internet escribe `https://mi-conector.stics...` en
el navegador; ese tráfico tiene que acabar llegando exactamente al puerto de
tu conector, en tu VM.

### 10.0 Averigua a qué máquina apunta REALMENTE tu DNS

```bash
nslookup <MI_HOSTNAME_PUBLICO> 8.8.8.8
```

Puede que resuelva **directamente a la IP pública de tu VM** (caso simple,
como pasa con la VM de bavenir), o que resuelva a la **IP pública de otra VM
distinta** que hace de "puerta de entrada" para varias máquinas privadas a la
vez (caso de la VM `stics2test`, IP pública `138.100.15.165`, que en
realidad reenvía tráfico hacia otras VMs privadas). Si no lo sabes, pregunta
— no lo asumas.

### 10.1 Sea cual sea el caso, casi seguro que Kubernetes intercepta el puerto 80/443 antes que cualquier nginx del sistema

Todas las VMs de este proyecto corren k3s, y k3s **secuestra los puertos
80/443 del host entero** mediante reglas de `iptables` (su "ServiceLB"),
antes de que cualquier nginx normal del sistema operativo llegue a verlos.
Compruébalo así en la VM donde tu DNS apunta de verdad:

```bash
sudo iptables -t nat -L -n | grep "dpt:80 \|dpt:443 "
```

Si ves una línea `DNAT ... to:<ip-de-un-pod>`, confirma la sospecha: **no
edites nginx del sistema operativo, edita Kubernetes**.

### 10.2 Crea un Service + Endpoints "manual" apuntando a tu conector

Esto es un patrón de Kubernetes para meter algo que NO es un pod (tu
contenedor Docker suelto) dentro del sistema de rutas de un Ingress. Guarda
esto como `mi-puente.yaml` (ajusta namespace, IP, puertos):

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: <UN_NAMESPACE_CORTO>
---
apiVersion: v1
kind: Service
metadata:
  name: mi-conector-external
  namespace: <UN_NAMESPACE_CORTO>
spec:
  ports:
    - { name: "19191", port: 19191, protocol: TCP }
    - { name: "19192", port: 19192, protocol: TCP }
    - { name: "19193", port: 19193, protocol: TCP }
    - { name: "19194", port: 19194, protocol: TCP }
    - { name: "19195", port: 19195, protocol: TCP }
    - { name: "19196", port: 19196, protocol: TCP }
    - { name: "19291", port: 19291, protocol: TCP }
---
apiVersion: v1
kind: Endpoints
metadata:
  name: mi-conector-external
  namespace: <UN_NAMESPACE_CORTO>
subsets:
  - addresses:
      - ip: <IP_DE_TU_VM>
    ports:
      # Si usaste network_mode: host, los puertos de la izquierda y derecha coinciden (19191).
      # Si usaste bridge con offset +10000, pon aquí el puerto REAL publicado (29191, etc.)
      - { name: "19191", port: 19191, protocol: TCP }
      - { name: "19192", port: 19192, protocol: TCP }
      - { name: "19193", port: 19193, protocol: TCP }
      - { name: "19194", port: 19194, protocol: TCP }
      - { name: "19195", port: 19195, protocol: TCP }
      - { name: "19196", port: 19196, protocol: TCP }
      - { name: "19291", port: 19291, protocol: TCP }
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mi-conector-ingress
  namespace: <UN_NAMESPACE_CORTO>
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "false"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "false"
    nginx.ingress.kubernetes.io/proxy-body-size: "800m"
spec:
  ingressClassName: nginx   # o "traefik", según qué controlador use ese cluster (comprueba con: kubectl get ingressclass)
  tls:
    - hosts: ["<MI_HOSTNAME_PUBLICO>"]
      secretName: pionera-internal-ingress-tls
  rules:
    - host: <MI_HOSTNAME_PUBLICO>
      http:
        paths:
          - { path: /api,        pathType: Prefix, backend: { service: { name: mi-conector-external, port: { number: 19191 } } } }
          - { path: /control,    pathType: Prefix, backend: { service: { name: mi-conector-external, port: { number: 19192 } } } }
          - { path: /management, pathType: Prefix, backend: { service: { name: mi-conector-external, port: { number: 19193 } } } }
          - { path: /protocol,   pathType: Prefix, backend: { service: { name: mi-conector-external, port: { number: 19194 } } } }
          - { path: /version,   pathType: Prefix, backend: { service: { name: mi-conector-external, port: { number: 19195 } } } }
          - { path: /shared,    pathType: Prefix, backend: { service: { name: mi-conector-external, port: { number: 19196 } } } }
          - { path: /public,    pathType: Prefix, backend: { service: { name: mi-conector-external, port: { number: 19291 } } } }
```

Aplícalo **en el cluster de la VM donde tu DNS apunta de verdad** (puede que
no sea la misma VM donde corre el conector — ver el ejemplo de
`con-lab.stics.linkeddata.es`, que apunta a la VM del consumer, no a la VM
común):

```bash
kubectl --kubeconfig <KUBECONFIG_DEL_CLUSTER_CORRECTO> apply -f mi-puente.yaml
```

**Truco de diagnóstico** si algo no cuadra:
- `curl -k https://tu-host/lo-que-sea` → `404 page not found` sin cabecera
  `Server:` → llegaste a Kubernetes pero no hay ninguna regla para ese host
  (o llegaste al cluster equivocado).
- Mismo `curl` → `503`, con cabecera `Server: nginx/...` → llegaste bien,
  pero el Service no tiene un backend sano todavía (revisa el Endpoints).
- La petición **ni siquiera aparece** en
  `kubectl -n ingress-nginx logs deploy/ingress-nginx-controller` → no está
  llegando a ese cluster en absoluto — reconsidera el paso 10.0.

---

## Paso 11: Añadir tu hostname al certificado TLS compartido

El certificado autofirmado que usa todo el dataspace (`pionera-internal-ingress-tls`)
solo cubre los hostnames que ya conoce. Hay que decirle explícitamente que
incluya el tuyo, y luego forzar que se regenere (por defecto reutiliza el
certificado ya guardado en disco, ni se entera de que hay un host nuevo):

```bash
# desde la VM stics2test, con el venv del framework:
export PIONERA_VM_INGRESS_TLS_HOSTS="<MI_HOSTNAME_PUBLICO>"

rm -f /home/stics2/Validation-Environment/.local/artifacts/ingress-tls/vm-distributed/stics/tls.crt
rm -f /home/stics2/Validation-Environment/.local/artifacts/ingress-tls/vm-distributed/stics/tls.key
```

Y luego, en Python (usando el adapter `inesdata`, que es el que gestiona el
dataspace):

```python
import os, sys
sys.path.insert(0, "/home/stics2/Validation-Environment")
os.chdir("/home/stics2/Validation-Environment")
import main as framework_main
adapter = framework_main.build_adapter("inesdata", topology="vm-distributed")
adapter.infrastructure._sync_vm_ingress_tls("vm-distributed")
```

**Muy importante**: en cuanto esto termine con `secret/... configured` (no
`unchanged`), el certificado **cambió de verdad** (nueva clave), lo que
significa que **el `cacerts.jks` de TODOS los conectores existentes (no solo
el nuevo) queda obsoleto**. Hay que volver a copiarlo a todos (Paso 7) y
reiniciar todos los `docker compose restart`, o te encontrarás errores
`PKIX path building failed` en conectores que llevaban semanas funcionando
bien.

---

## Paso 12: Verificación final

```bash
curl -k https://<MI_HOSTNAME_PUBLICO>/api/check/health
# Debería dar HTTP 200

# Espera ~65 segundos (el ciclo del catálogo federado) y mira si hay errores:
sleep 75
ssh usuario@TU_VM 'docker logs mi-conector --since 90s 2>&1 | grep -iE "error|exception"'
# Si no sale nada, perfecto.
```

Si quieres comprobar interoperabilidad real (negociar un contrato y
transferir datos con otro conector ya existente), sigue
[docs/47_stics_edc_interop_evidence.md](./47_stics_edc_interop_evidence.md) —
tiene los `curl` exactos para eso, ya verificados.

---

## Chuleta de errores típicos

| Síntoma en el log | Qué significa | Cómo se arregla |
| --- | --- | --- |
| `ValueError: Invalid connector name '...'. Maximum length is 20 characters` | El nombre del conector es demasiado largo | Acórtalo, máx. 20 caracteres |
| `Connection to 127.0.0.1:5432 refused` | El contenedor no puede ver el Postgres | Si usas `network_mode: host`, revisa que Postgres escuche ahí. Si usas *bridge*, apunta a la IP de la puerta de enlace de Docker (`172.17.0.1` o similar), no a `127.0.0.1` |
| `no pg_hba.conf entry for host "172.x.x.x"` | Postgres rechaza la IP del contenedor | Añade una línea `host all all 172.16.0.0/12 md5` a `pg_hba.conf` y `listen_addresses='*'`, reinicia Postgres |
| `relation "edc_catalog" does not exist` / `"edc_vocabulary" does not exist` | Faltan las tablas propias de INESData | Aplica los dos `.sql` del Paso 9a |
| `<nombre>: Temporary failure in name resolution` / `No address associated with hostname` (en el crawler) | El participante está registrado con una URL que no resuelve (interna, o el DNS aún no está activo) | Si es la URL interna → arregla el Paso 9b. Si es que el DNS aún no está activo → espera, se soluciona solo |
| `PKIX path building failed` / `Failed to get keys from .../certs` | El truststore (`cacerts.jks`) está desactualizado respecto al certificado actual | Vuelve a copiar `cacerts.jks` fresco (Paso 7) a ese conector — y a todos los demás si el certificado se acaba de regenerar |
| `curl` da `404 page not found` sin cabecera `Server:` | Llegaste a Kubernetes pero ningún Ingress reconoce ese host (o cluster equivocado) | Revisa Paso 10: ¿el DNS apunta donde crees? ¿Creaste el Ingress en el cluster correcto? |
| `curl` da `503` con `Server: nginx/...` | Llegaste bien, pero el Service no tiene backend sano | Revisa el `Endpoints` (IP y puertos correctos, el proceso realmente escuchando ahí) |
| La petición no aparece ni en los logs de `ingress-nginx-controller` | No está llegando a ese cluster en absoluto | El DNS probablemente apunta a otra máquina/gateway distinto del que crees |
