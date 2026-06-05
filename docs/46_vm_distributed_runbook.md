# Guía Operativa de vm-distributed

## Objetivo

Esta guía convierte la experiencia de despliegue distribuido en un procedimiento
repetible, verificable y apto para compartirse sin exponer datos sensibles del
entorno.

La meta no es que la persona recuerde todos los detalles de red, SSH,
kubeconfig, DNS, Ingress y validación. La meta es que el framework la lleve por
un camino claro, verificable y con poca carga cognitiva.

## Principios Operativos

| Principio | Regla práctica |
| --- | --- |
| Configuración explícita | Los valores reales viven en `.config` locales o variables de entorno, no en `docs/` ni en Git |
| Seguridad de acceso | La autenticación SSH usa una llave dedicada al entorno, nunca una llave privada compartida |
| Preflight antes de desplegar | Primero se comprueba red, SSH, kubeconfig, HTTP e Ingress; después se ejecutan niveles |
| Evidencia auditable | Cada nivel debe dejar salidas verificables y resultados bajo `experiments/` cuando aplique |
| Topologías coherentes | `local`, `vm-single` y `vm-distributed` comparten nombres de niveles, namespaces y contratos de adapter |
| Cambios aditivos cuando proceda | Para añadir conectores a un dataspace vivo se usa reconciliación aditiva |

## Roles de vm-distributed

`vm-distributed` separa el entorno en roles. La implementación admite un cluster
Kubernetes común con varios nodos y también clusters k3s controlados por
kubeconfigs distintos.

| Rol | Responsabilidad |
| --- | --- |
| `common` | Servicios comunes: Keycloak, Vault, PostgreSQL, MinIO y servicios base |
| `provider` | Conectores ubicados en el lado proveedor del entorno de validación |
| `consumer` | Conectores ubicados en el lado consumidor del entorno de validación |
| `components` | Componentes compartidos como Ontology Hub, AI Model Hub y Semantic Virtualization |

Los namespaces canónicos se mantienen estables:

| Namespace | Uso |
| --- | --- |
| `common-srvs` | Servicios comunes |
| `core-control` | Servicios del dataspace |
| `provider` | Conectores del grupo provider |
| `consumer` | Conectores del grupo consumer |
| `components` | Componentes compartidos |

## Flujo Desde Cero

El flujo recomendado para un entorno nuevo es ejecutar los niveles en orden, con
verificaciones entre ellos.

1. Preparar red de la estación operadora.
2. Preparar SSH con una llave dedicada.
3. Preparar kubeconfig dedicado para la topología.
4. Configurar `vm-distributed` con el asistente.
5. Ejecutar preflight estático y remoto.
6. Ejecutar `Level 1`.
7. Ejecutar `Level 2`.
8. Ejecutar `Level 3`.
9. Ejecutar `Level 4`.
10. Ejecutar `Level 5`.
11. Ejecutar `Level 6`.
12. Guardar evidencias y resultados.

## Red y SSH

En Windows con WSL, primero se debe confirmar que WSL ve la misma red o VPN que
Windows. Si Windows alcanza el bastión pero WSL no, habilita networking mirrored
en `%UserProfile%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
firewall=true
```

Después reinicia WSL:

```powershell
wsl --shutdown
```

La llave SSH debe ser dedicada al entorno VM:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_<entorno> -C "<entorno>-<usuario>"
```

El preflight usa `BatchMode=yes`, así que la autenticación debe funcionar sin
pedir contraseña interactiva:

```bash
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519_<entorno> -p <puerto-bastion> <usuario>@<bastion> hostname
ssh -o BatchMode=yes -i ~/.ssh/id_ed25519_<entorno> -J <usuario>@<bastion>:<puerto-bastion> <usuario>@<vm-common> hostname
```

## Kubeconfig Dedicado

Para no mezclar `local`, `vm-single` y `vm-distributed`, usa un kubeconfig
dedicado para esta topología.

Si la API de k3s solo es accesible desde la VM remota, abre un túnel SSH:

```bash
ssh -N -L 127.0.0.1:<puerto-local>:127.0.0.1:6443 -J <usuario>@<bastion>:<puerto-bastion> <usuario>@<vm-common>
```

El kubeconfig local debe apuntar a ese puerto:

```yaml
server: https://127.0.0.1:<puerto-local>
```

Verifica:

```bash
kubectl --kubeconfig <ruta-kubeconfig-vm-distributed> get nodes
kubectl --kubeconfig <ruta-kubeconfig-vm-distributed> get ns
```

## Configuración con el Asistente

Abre el menú:

```bash
python3 main.py menu
```

Después:

```text
T - Select topology
3 - vm-distributed
W - vm-distributed assistant
```

Usa:

| Opción | Uso |
| --- | --- |
| `1` | Crear o actualizar `.config` locales |
| `2` | Ver topología y preflight estático |
| `3` | Previsualizar despliegue y hosts |
| `4` | Ejecutar preflight SSH/HTTP no destructivo |

Si no sabes qué valor poner en un campo del asistente, escribe `?`.

## Acceso Público

El patrón recomendado es exponer cada VM mediante un dominio público o URL
estable gestionada por la organización.

Ejemplo conceptual:

| Rol | URL pública |
| --- | --- |
| `common` | `https://org1.<dominio>` |
| `provider` | `https://org2.<dominio>` |
| `consumer` | `https://org3.<dominio>` |

En la VM común, los servicios conviven por rutas:

```ini
VM_COMMON_PUBLIC_URL=https://org1.<dominio-comun>
VM_PROVIDER_PUBLIC_URL=https://org2.<dominio-dataspace>
VM_CONSUMER_PUBLIC_URL=https://org3.<dominio-dataspace>
KEYCLOAK_FRONTEND_URL=https://org1.<dominio-comun>/auth
MINIO_CONSOLE_PUBLIC_URL=https://org1.<dominio-comun>/s3-console
COMPONENTS_PUBLIC_BASE_URL=https://org1.<dominio-comun>
COMPONENTS_PUBLIC_PATH_REWRITE=true
```

Si estas URLs se dejan vacías, el framework infiere valores por defecto a
partir de `DOMAIN_BASE` y `DS_DOMAIN_BASE`: `org1` para servicios comunes,
`org2` para el conector proveedor y `org3` para el conector consumidor. Esos
nombres son una convención, no una obligación.

La regla práctica es:

1. Una URL completa configurada explícitamente tiene prioridad.
2. Si no hay URL explícita, se usa la convención `org1/org2/org3`.
3. Si una organización usa otros dominios, subdominios o rutas de proxy, debe
   configurar la URL completa correspondiente.

Con esa configuración, los componentes se publican como:

| Componente | URL pública |
| --- | --- |
| `ontology-hub` | `https://org1.<dominio-comun>/ontology-hub` |
| `ai-model-hub` | `https://org1.<dominio-comun>/ai-model-hub` |
| `semantic-virtualization` | `https://org1.<dominio-comun>/semantic-virtualization` |

El editor gráfico de Semantic Virtualization está basado en Streamlit y usa
WebSocket. En el entorno PIONERA distribuido se publica mediante un dominio
dedicado para evitar los problemas habituales de proxy inverso por subruta:

```ini
SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL=https://streamlit.pionera.linkeddata.es
SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_EXPOSURE_MODE=host-port
SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST_PORT=5678
```

Con ese patrón, el servicio interno sigue viviendo en la VM de servicios comunes
y componentes, pero el acceso público al editor no depende de
`/semantic-virtualization-editor`.

Si un frontend carga HTML pero falla al cargar JavaScript, CSS o rutas internas,
el problema suele ser de base path del componente. En ese caso se debe configurar
el base path de la imagen o usar dominios dedicados para ese componente.

Ejemplo con dominios personalizados por servicio:

```ini
KEYCLOAK_FRONTEND_URL=https://login.<dominio-comun>
MINIO_CONSOLE_PUBLIC_URL=https://objetos.<dominio-comun>
ONTOLOGY_HUB_PUBLIC_URL=https://ontologias.<dominio-componentes>
AI_MODEL_HUB_PUBLIC_URL=https://modelos.<dominio-componentes>
SEMANTIC_VIRTUALIZATION_PUBLIC_URL=https://virtualizacion.<dominio-componentes>
```

## Acceso SSH e Idempotencia

La topología distribuida debe usar una llave dedicada del entorno de validación,
no una llave personal reutilizada. La clave privada permanece en el host que
ejecuta el framework y solo se instala la clave pública en las VMs destino.

Configuración conceptual:

```ini
SSH_ACCESS_MODE=direct
SSH_IDENTITY_FILE=<ruta-a-llave-dedicada>
VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE=manual
VM_DISTRIBUTED_EXECUTION_HOST=external
VM_COMMON_SSH_HOST=<host-common>
VM_COMMON_SSH_USER=<usuario-operador>
VM_PROVIDER_SSH_HOST=<host-provider>
VM_PROVIDER_SSH_USER=<usuario-operador>
VM_CONSUMER_SSH_HOST=<host-consumer>
VM_CONSUMER_SSH_USER=<usuario-operador>
```

El bootstrap SSH debe ser idempotente:

- no regenera una llave si ya existe;
- no duplica entradas de `authorized_keys`;
- verifica acceso con `BatchMode=yes`;
- no guarda llaves privadas, contraseñas ni kubeconfigs en ficheros
  versionados.

Antes de tocar VMs reales, valida que el framework sabe crear una llave SSH
nueva desde cero:

```bash
python3 main.py inesdata ssh-access self-test --topology vm-distributed
```

Esta prueba crea una llave temporal, comprueba que la clave pública corresponde
a la privada, valida permisos seguros, repite la creación para comprobar
idempotencia y borra los ficheros temporales. No usa tus llaves actuales, no se
conecta a las VMs y no modifica `authorized_keys`.

Para revisar el plan sin tocar las VMs:

```bash
python3 main.py inesdata ssh-access plan --topology vm-distributed
```

El comando ya no muestra una lista larga de comandos como primera opción.
Muestra la guía interactiva recomendada y explica por qué existe: la preparación
SSH pide contraseñas una sola vez cuando la clave aún no está instalada y debe
ejecutarse desde la máquina correcta. La guía interactiva acompaña al operador
paso a paso, pregunta antes de ejecutar cada comando y nunca guarda contraseñas.

Con `VM_DISTRIBUTED_EXECUTION_HOST=external`, ejecuta la guía desde la misma
terminal donde ejecutas el framework, por ejemplo WSL o la estación de operación.
No se ejecuta dentro de las VMs destino. Con
`VM_DISTRIBUTED_EXECUTION_HOST=common-services`, ejecútala desde la VM de
servicios comunes cuando el workspace remoto esté preparado.

Para iniciar la guía interactiva:

```bash
python3 main.py inesdata ssh-access assistant --topology vm-distributed
```

Úsala leyendo cada paso, respondiendo afirmativamente solo cuando estés listo y
escribiendo contraseñas únicamente cuando lo solicite el prompt de SSH. Después
de instalar la clave pública, la verificación y los siguientes despliegues deben
funcionar sin pedir contraseña.

La guía detecta automáticamente si se está ejecutando desde WSL, desde la VM de
servicios comunes o desde otra terminal de operación. La ruta SSH no se pregunta:
se lee desde los ficheros de configuración. Si la configuración define bastión,
la guía lo usa; si define conexión directa, usa conexión directa. Solo pregunta
por la ubicación cuando lo detectado no encaja con la configuración, y muestra el
progreso de preguntas como `Question 1/N`.

Antes de la primera pregunta, la guía muestra solo un resumen compacto: topología,
llave dedicada, ubicación detectada, ruta SSH configurada y número de preguntas.

Si la guía detecta que se está ejecutando dentro de una VM configurada y la ruta
SSH usa bastión, no continúa en silencio. Lo marca como una situación que debe
revisarse, porque la VM tendría que poder llegar al bastión y el bastión tendría
que poder volver a las VMs destino.

Para obtener el plan completo en JSON, útil para automatización o auditoría:

```bash
python3 main.py inesdata ssh-access plan --topology vm-distributed --json
```

Para reconciliar explícitamente el acceso SSH dedicado:

```bash
python3 main.py inesdata ssh-access reconcile --topology vm-distributed
```

`reconcile` crea o reutiliza la llave dedicada local y añade su clave pública a
`authorized_keys` en las VMs configuradas. Si no existe una ruta de acceso
inicial aprobada, el comando falla sin insistir y muestra el siguiente paso
mínimo.

Cuando el framework se ejecute desde la VM común, usa:

```ini
VM_DISTRIBUTED_EXECUTION_HOST=common-services
VM_COMMON_REMOTE_WORKDIR=<ruta-remota-del-framework>
```

En ese modo, la VM común actúa como host de ejecución y debe poder llegar por
SSH a las VMs donde viven los conectores.

## Ejecución de Niveles

| Nivel | Qué valida o despliega | Punto de control |
| --- | --- | --- |
| `Level 1` | Acceso al cluster, runtime e Ingress | `kubectl get nodes` y preflight correcto |
| `Level 2` | Servicios comunes | Pods de `common-srvs` listos |
| `Level 3` | Dataspace y servicios core | Pods de `core-control` listos |
| `Level 4` | Conectores | Conectores en `provider` y `consumer` listos |
| `Level 5` | Componentes | Componentes en `components` y rutas públicas listas |
| `Level 6` | Validación | Reportes bajo `experiments/` |

Para una instalación nueva, usa reconciliación completa en Level 4:

```ini
LEVEL4_CONNECTOR_RECONCILIATION_MODE=full
```

Para añadir conectores a un dataspace vivo, usa reconciliación aditiva.

## Añadir Conectores a un Dataspace Existente

Este es el flujo recomendado para cumplir el caso pedido por el supervisor:
añadir conectores a espacios de datos que ya tienen conectores desplegados.

La forma guiada es usar el menú principal:

```bash
python3 main.py menu
```

Después selecciona:

```text
J - Add connector to existing dataspace
```

El asistente pide el nombre corto del conector, su ubicación y el par de
validación opcional. Antes de escribir ficheros, muestra un plan. Si el operador
confirma, actualiza el inventario, cambia `Level 4` a modo aditivo y ofrece
ejecutar `Level 4` en ese momento.

El resultado equivalente en configuración es:

Ejemplo:

```ini
DS_1_CONNECTORS=org2,org3,partnera
DS_1_CONNECTOR_NAMESPACES=org2:provider,org3:consumer,partnera:provider
DS_1_VALIDATION_PAIRS=org2>org3,partnera>org2
LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive
```

También revisa el plan manualmente con:

```bash
python3 main.py inesdata deploy --topology vm-distributed --dry-run
```

En modo aditivo, los conectores sanos se preservan y el framework añade los que
faltan.

Para generar evidencia de instalación limpia, vuelve a usar `full` en un entorno
controlado o en una reconstrucción completa.

## Componentes y Desarrollo

`Level 5` despliega componentes compartidos. En `vm-distributed`, las imágenes
de componentes deben llegar al runtime Kubernetes remoto. Hay dos estrategias
recomendadas:

| Estrategia | Cuándo usarla |
| --- | --- |
| Registry de equipo | Ruta preferida para CI/CD y despliegues compartidos |
| Importación remota a k3s | Útil para validación controlada desde una estación de trabajo |

La importación remota se activa con:

```ini
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT=true
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND=sudo -n k3s ctr -n k8s.io images import
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY=false
SSH_IDENTITY_FILE=<ruta-a-llave-dedicada>
```

La opción `sudo -n` evita esperas por contraseña interactiva. Si esa comprobación
falla, usa un registry accesible por el clúster o configura un permiso
no interactivo y acotado para importar imágenes en k3s.

Para una validación manual desde una terminal real, habilita el modo interactivo:

```ini
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE=true
VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY=true
```

En ese modo el framework asigna una pseudo-terminal SSH y permite escribir la
contraseña de `sudo` en el momento de importar la imagen. Este modo es útil para
desbloquear una validación manual, pero no debe usarse como base de CI/CD.

Para desarrollar componentes, el contrato deseado es:

- imagen configurable por `.config`;
- chart Helm con valores versionables;
- endpoints públicos declarados por configuración;
- pruebas de Level 6 registradas bajo `validation/components/`;
- evidencias generadas bajo `experiments/`.

## Experimentos con Cargas Grandes

Para experimentos con datasets o modelos grandes, se debe registrar antes:

- tamaño estimado de datasets;
- tamaño estimado de modelos;
- número de ejecuciones;
- si se requiere GPU o CPU;
- si los resultados deben conservarse tras la validación.

Antes de ejecutar Level 5 o Level 6 con cargas grandes, se debe revisar la
capacidad de disco:

```bash
df -h
docker system df
kubectl --kubeconfig <kubeconfig> get pvc -A
```

## Evidencia para Auditoría

Para una ejecución auditable, conserva:

| Evidencia | Ubicación recomendada |
| --- | --- |
| Configuración sin secretos | anexo operativo sanitizado |
| Plan de hosts y URLs | salida de `hosts --dry-run` |
| Preflight estático | salida de `W -> 2` |
| Preflight remoto | salida de `W -> 4` |
| Estado Kubernetes por nivel | salidas de `kubectl get` |
| Resultado de niveles | log de consola |
| Resultados de validación | `experiments/<experimento>/` |
| Incidencias y mitigaciones | documento de traspaso sanitizado |

No guardar contraseñas, tokens, claves privadas, cookies ni kubeconfigs reales en
documentación versionada.

## Automatización Prioritaria

Para reducir carga cognitiva, las siguientes mejoras deberían priorizarse:

| Mejora | Beneficio |
| --- | --- |
| Generador guiado de llave SSH dedicada | Evita reutilizar llaves personales y reduce errores de permisos |
| Gestor de túneles SSH para kubeconfig | Evita abrir terminales manuales para la API de k3s |
| Asistente de kubeconfig dedicado | Separa `local`, `vm-single` y `vm-distributed` |
| Preflight de disco y PVCs | Detecta falta de capacidad antes de Level 5 y Level 6 |
| Flujo “añadir conector” | Cambia config, previsualiza y ejecuta Level 4 aditivo de forma guiada |
| Paquete de evidencia | Genera un resumen sanitizado para auditoría |
| Validador de rutas públicas | Prueba Keycloak, MinIO, conectores y componentes desde la estación operadora |
| Plantilla de componente | Facilita añadir charts, imágenes, configuración y pruebas |

## Checklist Corta

Antes de desplegar:

```text
[ ] WSL o estación operadora ve la VPN/red requerida
[ ] SSH por bastión funciona con BatchMode=yes
[ ] kubeconfig dedicado responde a kubectl get nodes
[ ] W -> 2 no muestra valores faltantes
[ ] W -> 3 muestra hosts y namespaces esperados
[ ] W -> 4 pasa o documenta claramente qué comprobación HTTP no aplica
[ ] Hay capacidad de disco suficiente para componentes, datasets y modelos
[ ] Level 4 usa full para instalación nueva o additive para añadir conectores
[ ] Las URLs públicas esperadas están definidas en la topología
[ ] Level 6 generará evidencia bajo experiments/
```
