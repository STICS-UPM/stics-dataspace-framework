# 14. Entorno Productivo de Validacion

El entorno productivo de validacion se representa con topologias Kubernetes
distintas al modo local. El modo local usa `Minikube` en la maquina de
desarrollo; `vm-single` usa un Minikube gestionado dentro de la VM para hacer
reproducible el quickstart; y las topologias VM mantienen la misma separacion
por niveles del framework.

![PIONERA production validation environment](<./pionera production validation environment.png>)

## Topologias Soportadas por el Framework

| Topologia canonica | Alias visual | Estado actual |
| --- | --- | --- |
| `local` | local | despliegue real habilitado |
| `vm-single` | vm1 | despliegue real habilitado para la ruta base de `inesdata` y `edc` |
| `vm-distributed` | vm3 | planificacion de hosts y perfil de topologia |

`vm-distributed` sigue protegido por guardas y `edc` mantiene pendiente `Level 5`
real de componentes. El resto de la ruta ya puede ejecutarse en `vm-single`
sin depender del perfil `local`.

## Interpretacion de `vm-distributed`

Para PIONERA, `vm-distributed` se modela como un unico cluster Kubernetes con
tres nodos/VMs y separacion de workloads por rol:

| Rol | Workloads |
| --- | --- |
| `common` | servicios comunes, registration service, componentes compartidos |
| `provider` | conector proveedor |
| `consumer` | conector consumidor |

La separacion se puede aplicar mediante labels, `nodeSelector`, affinity o
mecanismos equivalentes. Esta decision mantiene un solo plano de control
Kubernetes y reduce la complejidad operativa inicial.

## Por Que un Solo Cluster es Adecuado

Un unico cluster con tres nodos permite validar:

- distribucion fisica de workloads;
- comunicacion entre provider, consumer y servicios comunes;
- resolucion DNS/hosts;
- ingress externo;
- identidad, secretos y almacenamiento compartido;
- politicas, contratos, catalogo, negociacion y transferencia;
- validaciones de `Level 6` sobre dataspace y componentes.

La descentralizacion del dataspace se valida en los conectores, las politicas,
la negociacion, la transferencia y la separacion de roles. No exige tres planos
de control Kubernetes independientes para el primer incremento del entorno de
validacion.

## Routing y Endpoints

El modo preferente es `routing_mode=host`: cada servicio relevante tiene su
hostname. Es menos intrusivo para charts y aplicaciones que publicar multiples
servicios bajo prefijos de path.

| Bloque | Ejemplo de endpoint productivo |
| --- | --- |
| Portal publico | `https://portal.<dominio-common>` |
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

## Variables de Topologia

El perfil de topologia permite separar direcciones por rol:

| Variable | Uso |
| --- | --- |
| `PIONERA_VM_EXTERNAL_IP` | IP comun para `vm-single` |
| `PIONERA_VM_COMMON_IP` | IP del nodo de servicios comunes |
| `PIONERA_VM_PROVIDER_IP` | IP del nodo provider |
| `PIONERA_VM_CONSUMER_IP` | IP del nodo consumer |

Las entradas de hosts se generan segun el rol de cada servicio. En local se usa
`127.0.0.1`; en VM se usan las IPs del perfil.

## Diferencias Frente a Local

| Elemento local | Equivalente productivo |
| --- | --- |
| `Minikube` | Kubernetes real |
| `minikube tunnel` | Ingress/load balancer real |
| `/etc/hosts` local | DNS o hosts gestionados por topologia |
| `minikube image load` | Registry de imagenes |
| dominio local fijo | hosts por servicio o por rol |
