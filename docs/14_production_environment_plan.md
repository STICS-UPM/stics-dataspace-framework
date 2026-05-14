# 14. Entorno Productivo de Validación

El entorno productivo de validación se representa con topologías Kubernetes
distintas al modo local. El modo local usa `Minikube` en la maquina de
desarrollo; `vm-single` usa un Minikube gestionado dentro de la VM para hacer
reproducible el quickstart; y las topologías VM mantienen la misma separación
por niveles del framework.

![PIONERA distributed validation environment](<./pionera_distributed_validation_environment.png>)

## Topologías Soportadas por el Framework

| Topología canonica | Alias visual | Estado actual |
| --- | --- | --- |
| `local` | local | despliegue real habilitado |
| `vm-single` | vm1 | despliegue real habilitado para la ruta base de `inesdata` y `edc` |
| `vm-distributed` | vm3 | planificacion de hosts y perfil de topología |

`vm-distributed` sigue protegido por guardas y `edc` mantiene pendiente `Level 5`
real de componentes. El resto de la ruta ya puede ejecutarse en `vm-single`
sin depender del perfil `local`.

## Interpretacion de `vm-distributed`

Para PIONERA, `vm-distributed` se modela como un único cluster Kubernetes con
tres nodos/VMs y separación de workloads por rol:

| Rol | Workloads |
| --- | --- |
| `common` | servicios comunes, registration service, componentes compartidos |
| `provider` | conector proveedor |
| `consumer` | conector consumidor |

La separación se puede aplicar mediante labels, `nodeSelector`, affinity o
mecanismos equivalentes. Esta decisión mantiene un solo plano de control
Kubernetes y reduce la complejidad operativa inicial.

## Por Qué un Solo Cluster es Adecuado

Un único cluster con tres nodos permite validar:

- distribucion física de workloads;
- comunicacion entre provider, consumer y servicios comunes;
- resolucion DNS/hosts;
- ingress externo;
- identidad, secretos y almacenamiento compartido;
- políticas, contratos, catálogo, negociación y transferencia;
- validaciones de `Level 6` sobre dataspace y componentes.

La descentralización del dataspace se valida en los conectores, las políticas,
la negociación, la transferencia y la separación de roles. No exige tres planos
de control Kubernetes independientes para el primer incremento del entorno de
validación.

## Routing y Endpoints

El modo preferente es `routing_mode=host`: cada servicio relevante tiene su
hostname. Es menos intrusivo para charts y aplicaciones que publicar multiples
servicios bajo prefijos de path.

| Bloque | Ejemplo de endpoint productivo |
| --- | --- |
| Portal público | `https://portal.<dominio-common>` |
| Backend del portal | `https://backend.<dominio-common>` |
| Registration Service | `https://registration-service.<dominio-common>` |
| Keycloak | `https://keycloak.<dominio-common>` |
| MinIO API | `https://minio.<dominio-common>` |
| MinIO Console | `https://console-minio.<dominio-common>` |
| Ontology Hub | `https://ontology-hub.<dominio-common>` |
| AI Model Hub | `https://ai-model-hub.<dominio-common>` |
| Provider | `https://provider.<dominio-provider>` |
| Consumer | `https://consumer.<dominio-consumer>` |

El routing por path queda como modo avanzado para entornos donde no sea posible
obtener hostnames por servicio.

## Variables de Topología

El perfil de topología permite separar direcciones por rol:

| Variable | Uso |
| --- | --- |
| `PIONERA_VM_EXTERNAL_IP` | IP comun para `vm-single` |
| `PIONERA_VM_COMMON_IP` | IP del nodo de servicios comunes |
| `PIONERA_VM_PROVIDER_IP` | IP del nodo provider |
| `PIONERA_VM_CONSUMER_IP` | IP del nodo consumer |

Las entradas de hosts se generan según el rol de cada servicio. En local se usa
`127.0.0.1`; en VM se usan las IPs del perfil.

## Diferencias Frente a Local

| Elemento local | Equivalente productivo |
| --- | --- |
| `Minikube` | Kubernetes real |
| `minikube tunnel` | Ingress/load balancer real |
| `/etc/hosts` local | DNS o hosts gestionados por topología |
| `minikube image load` | Registry de imagenes |
| dominio local fijo | hosts por servicio o por rol |
