# Adapters

## Propósito

Los adapters aíslan el comportamiento específico de cada implementación de dataspace.

Los adapters actuales son:

```text
adapters/inesdata/
adapters/edc/
```

Ambos adapters pueden convivir en un mismo cluster local y compartir
`common-srvs`. Para que esa convivencia sea reproducible, cada adapter debe
usar un dataspace y namespace propios. La configuración local de referencia usa
`pionera` para INESData y `pionera-edc` para EDC.

No se debe reutilizar el mismo `DS_1_NAME` o `DS_1_NAMESPACE` entre adapters en
el mismo cluster. Esa reutilización puede mezclar registration-service, bases de
datos, usuarios, hostnames y artefactos de despliegue.

Cada adapter puede aportar:

- operaciones de despliegue;
- descubrimiento de conectores;
- generación de URLs;
- carga de credenciales;
- limpieza de datos;
- configuración específica de validación;
- soporte para construir imágenes locales.

## Adapter INESData

El adapter INESData soporta el despliegue basado en INESData.

Configuración relevante:

```text
deployers/infrastructure/deployer.config
deployers/infrastructure/topologies/<topology>.config
deployers/inesdata/deployer.config
```

En el estado actual del framework, `INESData` no necesita overlays propios de
topología dentro de `deployers/inesdata/`. Su `deployer.config` sigue siendo la
capa del adapter y debe mantenerse centrada en identidad de dataspace,
conectores, componentes y flags funcionales; las diferencias `local`,
`vm-single` y `vm-distributed` pertenecen a la capa compartida de
infraestructura.

Deployer relevante:

```text
deployers/inesdata/deployer.py
```

Los componentes opcionales se configuran en el `deployer.config` del adapter y se despliegan en el nivel 5 cuando están habilitados.

El adapter INESData también puede propagar variables de branding hacia la
interfaz de conectores y el portal. La configuración recomendada vive en
`identity/branding.config.example`. Para un despliegue concreto, copia ese
archivo como `identity/branding.config` y ajusta los valores necesarios:

```ini
INESDATA_BRAND_NAME=PIONERA
INESDATA_BRAND_SHOW_MENU_TEXT=false
INESDATA_BRAND_THEME=theme-1
INESDATA_BRAND_PRIMARY_COLOR=#025B77
INESDATA_BRAND_SECONDARY_COLOR=#2FA0B5
INESDATA_BRAND_ASSETS_DIR=identity
INESDATA_BRAND_LOGO_FILES=pionera-logo.svg
INESDATA_BRAND_LOGO_URLS=
INESDATA_BRAND_FOOTER_LOGO_FILES=pionera-logo.svg,funding-logos.png
INESDATA_BRAND_FOOTER_LOGO_URLS=
INESDATA_BRAND_FOOTER_TEXT=
INESDATA_BRAND_POWERED_BY_TEXT=Powered by:
INESDATA_BRAND_POWERED_BY_LOGO_FILES=
INESDATA_BRAND_POWERED_BY_LOGO_URLS=
INESDATA_BRAND_CONNECTOR_ASSET_BASE_URL=/inesdata-connector-interface/assets/branding
INESDATA_BRAND_PORTAL_ASSET_BASE_URL=/assets/branding
INESDATA_LOCAL_STORE_LABEL=LocalStore
```

En despliegues locales, el nivel 4 recompila la interfaz del conector aplicando
la personalización visual de forma temporal sobre los sources y restaura los
archivos originales al finalizar el build. `INESDATA_BRAND_SHOW_MENU_TEXT=false`
oculta el nombre textual del menú lateral cuando el logo ya incluye la marca.
`InesDataStore` sigue siendo el tipo técnico usado por las APIs de transferencia;
`INESDATA_LOCAL_STORE_LABEL=LocalStore` debe interpretarse como el nombre visual
de esa opción funcional, no como reemplazo del valor técnico.

Los activos visuales versionables viven en `identity/`. Para usar logos propios,
añade archivos a esa carpeta y referencia sus nombres en
`INESDATA_BRAND_LOGO_FILES`, `INESDATA_BRAND_FOOTER_LOGO_FILES` o
`INESDATA_BRAND_POWERED_BY_LOGO_FILES`. El framework
los empaqueta como ConfigMaps de Helm y los monta en los frontends en
`/assets/branding` o en la ruta base configurada para la interfaz del conector.
Si se necesitan URLs externas, se pueden indicar directamente en
`INESDATA_BRAND_LOGO_URLS`, `INESDATA_BRAND_FOOTER_LOGO_URLS` o
`INESDATA_BRAND_POWERED_BY_LOGO_URLS`.

Por compatibilidad, las mismas variables también pueden definirse en
`deployers/inesdata/deployer.config`; si aparecen ahí, sobrescriben la
configuración de `identity/`.

## Adapter EDC

El adapter EDC soporta un despliegue EDC genérico.

Configuración relevante:

```text
deployers/infrastructure/deployer.config
deployers/infrastructure/topologies/<topology>.config
deployers/edc/deployer.config
```

En el estado actual del framework, `EDC` tampoco necesita overlays propios de
topología dentro de `deployers/edc/`. Su `deployer.config` debe seguir siendo
topología-agnóstico y describir solo el dataspace, sus conectores y flags
específicas del adapter. Si en el futuro aparece una divergencia real por
topología, esa necesidad debe justificarse antes de añadir
`deployers/edc/topologies/`.

Deployer relevante:

```text
deployers/edc/deployer.py
```

`Level 3` de EDC reutiliza de forma transitoria la lógica compartida de
bootstrap del dataspace base, pero lee la configuración de
`deployers/edc/deployer.config`. Por tanto, el dataspace EDC sigue siendo
aislado:

```text
DS_1_NAME=pionera-edc
DS_1_NAMESPACE=edc-control
NAMESPACE_PROFILE=role-aligned
DS_1_REGISTRATION_NAMESPACE=edc-control
DS_1_PROVIDER_NAMESPACE=edc-provider
DS_1_CONSUMER_NAMESPACE=edc-consumer
DS_1_CONNECTORS=citycounciledc,companyedc
```

Para más de dos conectores, el adapter acepta el mismo patrón que INESData:
`DS_1_CONNECTORS` define el inventario, `DS_1_CONNECTOR_NAMESPACES` asigna cada
conector a un namespace o grupo de despliegue, y `DS_1_VALIDATION_PAIRS` define
los pares que se usarán en las validaciones. Los namespaces `edc-provider` y
`edc-consumer` son grupos operativos del entorno de pruebas, no roles funcionales
exclusivos del conector.

Si `DS_1_CONNECTOR_NAMESPACES` y `DS_1_VALIDATION_PAIRS` se dejan vacías en el
`deployer.config`, el framework mantiene el despliegue base: primer conector
como origen de validación, segundo conector como destino de validación y
ubicación derivada de los namespaces configurados para el adapter. Para controlar
un despliegue con más conectores, usa el formato:

```ini
DS_1_CONNECTOR_NAMESPACES=citycounciledc:edc-provider,companyedc:edc-consumer,partneredc:edc-provider
DS_1_VALIDATION_PAIRS=citycounciledc>companyedc,partneredc>citycounciledc
```

El modo `LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive` permite añadir
conectores nuevos preservando conectores existentes que ya están sanos. El modo
por defecto es `full`, que mantiene la reconciliación limpia usada por las
validaciones de cierre.

El comportamiento operativo de `Level 3` debe ser equivalente al de INESData:
ejecuta el bootstrap del dataspace del adapter activo aunque el namespace ya
exista. Después de `Level 3`, ejecuta `Level 4` para desplegar o actualizar los
conectores EDC.

El adapter EDC puede construir o usar una imagen de conector configurada. En topología `local`, si no se han definido overrides, Level 4 prepara automáticamente la imagen local desde `adapters/edc/sources/connector`, la carga en Minikube y usa `validation-environment/edc-connector:local` para esa ejecución. Esta preparación vive también dentro del adapter EDC, de modo que funciona tanto desde el menú por niveles como desde llamadas directas del adapter.

Si `EDC_DASHBOARD_ENABLED=true`, Level 4 también prepara y carga en Minikube las imágenes locales del dashboard y del proxy:

```text
validation-environment/edc-dashboard:latest
validation-environment/edc-dashboard-proxy:latest
```

En topologías VM, o cuando se quiera usar una imagen publicada en un registry, se deben definir overrides explícitos para evitar desplegar una imagen por defecto no verificada.

Variables comunes de override:

```text
PIONERA_EDC_CONNECTOR_IMAGE_NAME
PIONERA_EDC_CONNECTOR_IMAGE_TAG
```

Variables opcionales para cambiar la imagen local automática:

```text
PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_NAME
PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_TAG
```

Variables opcionales para cambiar las imágenes del dashboard:

```text
PIONERA_EDC_DASHBOARD_IMAGE_NAME
PIONERA_EDC_DASHBOARD_IMAGE_TAG
PIONERA_EDC_DASHBOARD_PROXY_IMAGE_NAME
PIONERA_EDC_DASHBOARD_PROXY_IMAGE_TAG
```

La preparación local puede desactivarse con `PIONERA_EDC_LOCAL_IMAGES_MODE=disabled` o hacerse estricta con `PIONERA_EDC_LOCAL_IMAGES_MODE=required`. El valor por defecto es `auto`. Si se desactiva la preparación local, debe existir un override explícito de imagen del conector EDC.

El dashboard EDC es opcional y sirve como apoyo visual para validación UI. Las validaciones API con Newman siguen siendo el mecanismo principal de validación end-to-end.

En el menú interactivo, el adapter EDC incluye una comprobación previa de
hostnames antes de ejecutar niveles `3-6` en topología `local`. Si faltan
entradas, el usuario puede aplicar solo las ausentes antes de continuar; si no
lo confirma, el nivel se cancela para evitar fallos posteriores menos claros.

## Añadir un Adapter

Para añadir otro adapter:

1. Crear `adapters/<name>/`.
2. Crear `deployers/<name>/`.
3. Implementar un deployer con el contrato compartido.
4. Registrar adapter y deployer en `main.py`.
5. Definir el perfil de validación por defecto.
6. Añadir pruebas unitarias focalizadas.
7. Añadir documentación solo cuando el comportamiento sea estable.
