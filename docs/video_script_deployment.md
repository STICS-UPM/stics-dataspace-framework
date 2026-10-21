# Script: Despliegue del Ambiente de Validación
# Objetivo: Enseñar cómo se crea un ambiente desde cero

---

## BLOQUE 0 — Introducción (1 min)

**Decir:**
> "En este vídeo vamos a desplegar un ambiente de validación desde cero
> usando el framework. Veremos el asistente de configuración y los
> niveles del 1 al 5: infraestructura, servicios comunes, dataspace,
> conectores y componentes."

---

## BLOQUE 1 — El asistente: configurar el ambiente (3 min)

**Decir:**
> "El primer paso es configurar el ambiente usando el asistente
> interactivo del framework."

**Ejecutar:**
```bash
python3 main.py
```

**En el menú principal:**
- Seleccionar adaptador `inesdata`
- Pulsar `W` → abre el VM-DISTRIBUTED ASSISTANT

**Decir:**
> "El asistente nos guía para definir las IPs de las VMs, los dominios,
> el acceso SSH y el inventario del dataspace. Vamos a la opción 1."

**Pulsar `1`**

**Decir mientras se rellena:**
> "Definimos la IP de la VM de servicios comunes, la del proveedor
> y la del consumidor. El dominio base del que derivarán todas las URLs.
> El acceso SSH a través del bastión. Y los conectores y componentes
> que queremos desplegar."

**Confirmar al final con Enter**

**Decir:**
> "El asistente ha generado tres ficheros de configuración locales.
> Vamos a verlos."

**Mostrar:**
```bash
cat deployers/infrastructure/deployer.config
```

**Señalar:**
```
VM_COMMON_IP=192.168.122.64       # VM servicios comunes — org1
VM_PROVIDER_IP=192.168.122.134    # VM proveedor — org2
VM_CONSUMER_IP=192.168.122.9      # VM consumidor — org3
DOMAIN_BASE=pionera.oeg.fi.upm.es # dominio base de todas las URLs
```

```bash
cat deployers/infrastructure/topologies/vm-distributed.config
```

**Señalar:**
```
SSH_BASTION_HOST=orion.dia.fi.upm.es    # bastión SSH
K3S_KUBECONFIG_PROVIDER=~/.kube/pionera20.yaml
K3S_KUBECONFIG_CONSUMER=~/.kube/pionera3.yaml
VM_PROVIDER_PUBLIC_URL=https://org2.pionera.oeg.fi.upm.es
VM_CONSUMER_PUBLIC_URL=https://org3.pionera.oeg.fi.upm.es
```

```bash
cat deployers/inesdata/deployer.config
```

**Señalar:**
```
DS_1_NAME=pionera
DS_1_CONNECTORS=org2,org3
COMPONENTS=ontology-hub,ai-model-hub,semantic-virtualization
KEYCLOAK_FRONTEND_URL=https://org1.pionera.oeg.fi.upm.es/auth
MINIO_CONSOLE_PUBLIC_URL=https://org1.pionera.oeg.fi.upm.es/s3-console
COMPONENTS_PUBLIC_BASE_URL=https://org1.pionera.oeg.fi.upm.es
```

**Decir:**
> "Estos tres ficheros son locales e ignorados por git. Definen
> completamente el ambiente: dónde están las VMs, cómo acceder,
> qué conectores desplegar y qué componentes activar."

---

## BLOQUE 2 — Nivel 1: Preflight de infraestructura (2 min)

**Decir:**
> "Con la configuración lista, arrancamos el despliegue. El Nivel 1
> en topología vm-distributed no instala nada. Hace comprobaciones
> de solo lectura sobre el cluster: kubectl, helm, nodos, ingress
> y almacenamiento."

**Ejecutar:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 1
```

**Decir mientras se ejecuta:**
> "Comprueba que kubectl y helm están disponibles, que el cluster
> responde, que hay nodos listos y que existe una IngressClass nginx."

**Cuando termine, mostrar:**
```bash
kubectl --kubeconfig ~/.kube/pionera40.yaml get nodes
kubectl --kubeconfig ~/.kube/pionera40.yaml get ingressclass
kubectl --kubeconfig ~/.kube/pionera40.yaml get storageclass
```

---

## BLOQUE 3 — Nivel 2: Servicios comunes (3 min)

**Decir:**
> "El Nivel 2 despliega los servicios comunes: Keycloak para identidad,
> MinIO para almacenamiento de objetos, PostgreSQL para bases de datos
> y Vault para gestión de secretos."

**Ejecutar:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 2
```

**Decir mientras se ejecuta:**
> "Sincroniza la configuración, construye las dependencias Helm,
> despliega el chart y espera a que todos los servicios estén
> operativos. Al final configura Vault automáticamente."

**Cuando termine:**
```bash
kubectl --kubeconfig ~/.kube/pionera40.yaml get pods -n common-srvs
```

**Abrir navegador:**
- `https://org1.pionera.oeg.fi.upm.es/auth` → Keycloak
- `https://org1.pionera.oeg.fi.upm.es/s3-console` → MinIO Console

---

## BLOQUE 4 — Nivel 3: Dataspace (2 min)

**Decir:**
> "El Nivel 3 crea el dataspace. Despliega el registration-service
> y registra el dataspace en Keycloak y PostgreSQL."

**Ejecutar:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 3
```

**Cuando termine:**
```bash
kubectl --kubeconfig ~/.kube/pionera40.yaml get pods -n core-control
```

**Decir:**
> "El registration-service gestiona los participantes del dataspace
> y las políticas de acceso."

---

## BLOQUE 5 — Nivel 4: Conectores (4 min)

**Decir:**
> "El Nivel 4 despliega los conectores INESData. Tenemos dos:
> org2 en la VM proveedora y org3 en la VM consumidora.
> El framework genera credenciales únicas para cada uno en
> Keycloak, Vault y PostgreSQL, construye la imagen Docker,
> la transfiere a la VM correspondiente y la despliega con Helm."

**Ejecutar:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 4
```

**Cuando termine:**
```bash
kubectl --kubeconfig ~/.kube/pionera20.yaml get pods -n provider
kubectl --kubeconfig ~/.kube/pionera3.yaml get pods -n consumer
```

**Mostrar fichero de credenciales:**
```bash
cat deployers/inesdata/deployments/DEV/pionera/credentials-connector-conn-org2-pionera.json
```

**Señalar:**
```json
"connector_user": { "user": "...", "passwd": "..." },
"vault":          { "token": "...", "path": "..." },
"minio":          { "access_key": "...", "secret_key": "..." },
"public_access_urls": {
    "connector_interface_login": "https://org2.pionera.oeg.fi.upm.es/inesdata-connector-interface/"
}
```

**Decir:**
> "El framework guarda las credenciales generadas en este fichero JSON.
> Es el punto de referencia para acceder a las APIs del conector."

**Abrir navegador:**
- `https://org2.pionera.oeg.fi.upm.es/inesdata-connector-interface/`
- `https://org3.pionera.oeg.fi.upm.es/inesdata-connector-interface/`

---

## BLOQUE 6 — Nivel 5: Componentes (3 min)

**Decir:**
> "El Nivel 5 despliega los componentes opcionales del dataspace:
> Ontology Hub, AI Model Hub y Semantic Virtualization.
> Todos se exponen en org1 bajo rutas de path."

**Ejecutar:**
```bash
python3 main.py inesdata deploy --topology vm-distributed --level 5
```

**Cuando termine:**
```bash
kubectl --kubeconfig ~/.kube/pionera40.yaml get pods -n components
```

**Abrir navegador:**
- `https://org1.pionera.oeg.fi.upm.es/ontology-hub`
- `https://org1.pionera.oeg.fi.upm.es/ai-model-hub`
- `https://org1.pionera.oeg.fi.upm.es/semantic-virtualization`

---

## BLOQUE 7 — Cierre: parametrización de dominios (1 min)

**Volver a mostrar:**
```bash
grep -E "DOMAIN_BASE|VM_.*PUBLIC_URL|COMPONENTS_PUBLIC_BASE" deployers/infrastructure/deployer.config
grep -E "DOMAIN_BASE|VM_.*PUBLIC_URL|COMPONENTS_PUBLIC_BASE" deployers/infrastructure/topologies/vm-distributed.config
```

**Decir:**
> "Todo lo que hemos visto — URLs de Keycloak, MinIO, conectores
> y componentes — deriva del dominio base y las IPs configuradas
> al principio. Para desplegar el mismo ambiente en otra
> infraestructura basta con cambiar estos valores en el asistente
> y repetir los niveles."

---

## DURACIÓN ESTIMADA: 20-25 minutos

## NOTAS PREVIAS AL RODAJE

- Vaciar los 3 deployer.config antes de grabar para que el asistente
  tenga algo visible que configurar
- El Nivel 2 puede tardar 5-8 min en arrancar Keycloak — prever corte
  o grabar en tiempo real
- Las credenciales del JSON cambiarán con cada deploy — es normal,
  mencionarlo en el vídeo
- Tener el navegador preconfigurado con las URLs antes de grabar
