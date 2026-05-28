# Preparación de Conectores Externos

## Objetivo

Este documento describe la preparación necesaria para desplegar un dataspace con
topología `vm-distributed` y conectores adicionales en infraestructura externa o
gestionada por terceros. Su propósito es evitar que la persona que opera el
framework tenga que reconstruir datos técnicos desde cero durante un despliegue.

## Alcance Implementado

El framework ya permite preparar, inspeccionar y prevalidar la configuración
local de `vm-distributed` desde el menú interactivo mediante la opción
`W - vm-distributed assistant`.

La implementación actual cubre:

- generación asistida de `deployers/infrastructure/deployer.config`;
- generación asistida de
  `deployers/infrastructure/topologies/vm-distributed.config`;
- generación asistida de `deployers/<adapter>/deployer.config`;
- normalización automática de hostnames comunes (`KC_*`, `KEYCLOAK_*`,
  `MINIO_*`) a partir de `DOMAIN_BASE` cuando están vacíos o siguen usando
  defaults generados, conservando valores personalizados;
- inventario configurable de conectores con `DS_1_CONNECTORS`;
- asignación configurable de conectores a grupos o namespaces mediante
  `DS_1_CONNECTOR_NAMESPACES`;
- pares de validación configurables mediante `DS_1_VALIDATION_PAIRS`;
- modo aditivo de nivel 4 mediante
  `LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive`;
- checklist de preparación al terminar el asistente;
- plan de VMs por rol con SSH directo o vía bastion;
- preflight SSH/HTTP no destructivo y siempre confirmado por la persona
  operadora;
- planificación de entradas de hosts con `hosts --topology vm-distributed
  --dry-run`;
- propagación de variables de branding para la interfaz INESData.

El caso operativo soportado de forma conservadora es un cluster Kubernetes
lógico común para servicios compartidos, dataspace, componentes y conectores.
Ese cluster puede estar distribuido físicamente en varias VMs si el kubeconfig
permite operar todos los namespaces requeridos.

## Límites Actuales

El nivel 4 bloquea de forma segura el despliegue de conectores si
`K3S_KUBECONFIG_COMMON`, `K3S_KUBECONFIG_PROVIDER` y
`K3S_KUBECONFIG_CONSUMER` apuntan a API servers distintos. Esta protección evita
desplegar conectores en clusters externos sin un flujo multi-cluster completo y
validado.

El framework no instala automáticamente k3s por SSH en VMs externas ni abre
reglas de firewall en infraestructura de terceros. Esos pasos deben estar
preparados antes de ejecutar los niveles de despliegue.

La personalización visual de INESData se expone como contrato de configuración.
El nivel 4 local recompila la interfaz del conector con la personalización
configurada y restaura los sources originales al terminar. Variables como
`APP_BRAND_NAME`, `APP_SHOW_MENU_TEXT`, `APP_LOGO_URLS`, `APP_FOOTER_TEXT`,
`APP_PRIMARY_COLOR` y `APP_LOCAL_STORE_LABEL` también quedan propagadas por Helm
para trazabilidad del despliegue.

`InesDataStore` debe mantenerse como tipo técnico en las llamadas de
transferencia. Si se usa `LocalStore`, debe tratarse como etiqueta visual, no
como reemplazo del valor técnico usado por el backend.

## Datos Necesarios Para un Despliegue

Antes de preparar una topología `vm-distributed`, se debe recopilar:

| Dato | Uso en el framework |
| --- | --- |
| Dominio base de servicios comunes | `DOMAIN_BASE` |
| Dominio base del dataspace y conectores | `DS_DOMAIN_BASE` |
| IP o DNS de servicios comunes | `VM_COMMON_IP` |
| IP o DNS del lado provider | `VM_PROVIDER_IP` |
| IP o DNS del lado consumer | `VM_CONSUMER_IP` |
| IP o DNS de componentes | `VM_COMPONENTS_IP` |
| IP o DNS público de ingress | `INGRESS_EXTERNAL_IP` |
| Usuario SSH para sincronizar NGINX remoto | `VM_SSH_USER` |
| kubeconfig de servicios comunes | `K3S_KUBECONFIG_COMMON` |
| kubeconfig del lado provider | `K3S_KUBECONFIG_PROVIDER` |
| kubeconfig del lado consumer | `K3S_KUBECONFIG_CONSUMER` |
| kubeconfig de componentes | `K3S_KUBECONFIG_COMPONENTS` |
| Nombre del dataspace | `DS_1_NAME` |
| Lista de conectores | `DS_1_CONNECTORS` |
| Ubicación de cada conector | `DS_1_CONNECTOR_NAMESPACES` |
| Pares origen/destino para validación | `DS_1_VALIDATION_PAIRS` |
| Modo de acceso SSH | `SSH_ACCESS_MODE` |
| Bastion opcional | `SSH_BASTION_HOST`, `SSH_BASTION_PORT`, `SSH_BASTION_USER` |
| Host/puerto/usuario SSH por rol | `VM_COMMON_SSH_*`, `VM_PROVIDER_SSH_*`, `VM_CONSUMER_SSH_*` |
| Ruta remota del workspace si aplica | `VM_REMOTE_WORKDIR` o `VM_<ROL>_REMOTE_WORKDIR` |
| URLs HTTP internas para preflight | `VM_COMMON_HTTP_URL`, `VM_PROVIDER_HTTP_URL`, `VM_CONSUMER_HTTP_URL` |
| Modo operativo de la topología | `VM_DISTRIBUTED_DEPLOYMENT_MODE` |

También se debe confirmar:

- distribución Ubuntu o Linux compatible;
- acceso SSH administrativo cuando la VM deba prepararse manualmente o cuando el
  framework deba sincronizar NGINX remoto;
- permisos `sudo` para instalación o revisión de k3s;
- conectividad de red entre servicios comunes, conectores y componentes;
- resolución DNS o entradas `/etc/hosts` coherentes con los dominios definidos;
- puertos de ingress y APIs internas permitidos por firewall o VPN.

La configuración versionada debe usar solo placeholders o ejemplos reservados. Los
valores reales de IP, hostnames internos, usuarios, rutas de kubeconfig, tokens,
contraseñas o claves privadas deben quedar en ficheros `.config` locales
ignorados por Git o en variables de entorno del operador.

## Uso del Asistente

Ejecuta:

```bash
python3 main.py menu
```

Después selecciona:

```text
W - vm-distributed assistant
```

Si `vm-distributed` todavía no está activa, `W` cambia a esa topología con
confirmación y abre directamente el wizard de configuración. Con
`vm-distributed` activa, usa la opción `1` para configurar los `.config`, la
opción `2` para revisar el plan de VMs y el preflight estático, la opción `3`
para previsualizar despliegue y hosts, y la opción `4` para ejecutar
comprobaciones SSH/HTTP no destructivas. El asistente solo modifica ficheros
`.config` locales ignorados por Git cuando se usa explícitamente la opción de
configuración.

Al guardar la configuración, el asistente también puede corregir hostnames
comunes derivados de `DOMAIN_BASE`. Solo actualiza `KC_URL`, `KC_INTERNAL_URL`,
`KEYCLOAK_*` y `MINIO_*` si están vacíos o si coinciden con valores generados
por el framework; los valores personalizados se mantienen intactos.

Al finalizar, revisa el checklist impreso. Si aparece `blocked` en el alcance de
nivel 4, significa que se ha configurado un despliegue multi-kubeconfig real.
Ese caso requiere una fase posterior de implementación multi-cluster.

## Conectores Adicionales

Para añadir conectores sin recrear los existentes, configura el inventario y el
modo aditivo:

```ini
DS_1_CONNECTORS=citycouncil,company,partnera
DS_1_CONNECTOR_NAMESPACES=citycouncil:provider,company:consumer,partnera:provider
DS_1_VALIDATION_PAIRS=citycouncil>company,partnera>citycouncil
LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive
```

Los grupos `provider` y `consumer` son ubicaciones operativas del entorno de
validación. No significan que un conector solo pueda actuar como proveedor o
consumidor funcional.

## Branding de INESData

El adapter INESData acepta estas variables en `deployers/inesdata/deployer.config`:

| Variable | Propósito |
| --- | --- |
| `INESDATA_BRAND_NAME` | Nombre visible esperado por la interfaz |
| `INESDATA_BRAND_SHOW_MENU_TEXT` | Controla si el nombre textual se muestra junto al logo en el menú lateral |
| `INESDATA_BRAND_THEME` | Tema visual; por defecto `theme-1` |
| `INESDATA_BRAND_PRIMARY_COLOR` | Color primario cuando la imagen lo soporte |
| `INESDATA_BRAND_SECONDARY_COLOR` | Color secundario cuando la imagen lo soporte |
| `INESDATA_BRAND_ASSETS_DIR` | Carpeta del repositorio con assets de branding; por defecto `identity` |
| `INESDATA_BRAND_LOGO_FILES` | Archivos de logo que se empaquetan desde la carpeta de assets |
| `INESDATA_BRAND_LOGO_URLS` | Lista explícita de URLs de logotipos cuando no se quiere derivar desde archivos |
| `INESDATA_BRAND_FOOTER_LOGO_FILES` | Archivos de logos de pie de página que se empaquetan desde la carpeta de assets |
| `INESDATA_BRAND_FOOTER_LOGO_URLS` | Lista explícita de URLs de logos de pie de página |
| `INESDATA_BRAND_FOOTER_TEXT` | Texto de pie de página cuando la imagen lo soporte |
| `INESDATA_BRAND_POWERED_BY_TEXT` | Texto de la sección de tecnología base; por defecto `Powered by:` |
| `INESDATA_BRAND_POWERED_BY_LOGO_FILES` | Archivos de logos para la sección `Powered by` |
| `INESDATA_BRAND_POWERED_BY_LOGO_URLS` | Lista explícita de URLs para la sección `Powered by` |
| `INESDATA_BRAND_CONNECTOR_ASSET_BASE_URL` | Ruta base de assets para la interfaz del conector |
| `INESDATA_BRAND_PORTAL_ASSET_BASE_URL` | Ruta base de assets para el portal |
| `INESDATA_LOCAL_STORE_LABEL` | Etiqueta visual para mostrar `InesDataStore` como un almacén local |

Estas variables son seguras para versionar en `identity/branding.config.example`
cuando no contienen credenciales, tokens ni URLs privadas. La personalización de
un despliegue concreto debe ir en `identity/branding.config`, que está ignorado
por Git.

Los logos de referencia viven en `identity/`. Esa carpeta sirve como fuente
versionable de identidad visual para documentación, reportes y configuración de
branding. Una persona usuaria puede añadir sus propios logos y seleccionar los
archivos desde `INESDATA_BRAND_LOGO_FILES`,
`INESDATA_BRAND_FOOTER_LOGO_FILES` o
`INESDATA_BRAND_POWERED_BY_LOGO_FILES`. El framework monta esos assets en los pods
frontend; si la interfaz necesita URLs externas, se pueden usar las variables
`INESDATA_BRAND_LOGO_URLS`, `INESDATA_BRAND_FOOTER_LOGO_URLS` y
`INESDATA_BRAND_POWERED_BY_LOGO_URLS`.

La configuración base incluida para el cierre de A5.2 establece `PIONERA` como
nombre visible, los colores inferidos del logotipo (`#025B77` y `#2FA0B5`),
logos de proyecto, financiación y grupo en el pie, `Powered by:` como sección
separada con el logo de INESData y `LocalStore` como etiqueta visual de la
opción funcional cuyo valor técnico sigue siendo `InesDataStore`.

## Checklist Antes de Ejecutar Niveles

1. Ejecutar el asistente `W`.
2. Revisar que el preflight no tenga valores faltantes.
3. Ejecutar el plan de hosts en modo seco:

```bash
python3 main.py inesdata hosts --topology vm-distributed --dry-run
```

4. Confirmar que los dominios resuelven desde las VMs implicadas.
5. Confirmar que `kubectl --kubeconfig <ruta> get ns` funciona con los
   kubeconfigs configurados.
6. Ejecutar nivel 1 para validar runtime Kubernetes e ingress.
7. Ejecutar nivel 2 para servicios comunes.
8. Ejecutar nivel 3 para el dataspace.
9. Ejecutar nivel 4 para conectores.
10. Ejecutar nivel 5 para componentes.
11. Ejecutar nivel 6 para evidencia de validación.
