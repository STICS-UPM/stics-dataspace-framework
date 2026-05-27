# Identity Assets

Esta carpeta contiene activos visuales para documentación, reportes y
configuración de branding del framework.

## Uso General

La carpeta es parametrizable. Una persona usuaria puede añadir o reemplazar
logos propios y seleccionarlos desde `identity/branding.config` sin modificar
plantillas Helm ni código fuente de las interfaces.

Recomendaciones:

- usar nombres sin espacios ni tildes;
- preferir SVG o PNG optimizados;
- mantener el total de assets seleccionados por debajo de 900 KiB;
- no incluir metadatos locales del sistema operativo;
- no incluir archivos antiguos si no forman parte de la identidad vigente.

## Uso en Branding

El framework propaga variables de branding para INESData mediante Helm. La
configuración base versionada vive en `identity/branding.config.example`. Para
personalizar un despliegue local, copia ese archivo como `identity/branding.config`
y ajusta los valores necesarios. `identity/branding.config` está ignorado por Git.

```ini
INESDATA_BRAND_NAME=PIONERA
INESDATA_BRAND_SHOW_MENU_TEXT=false
INESDATA_BRAND_THEME=theme-1
INESDATA_BRAND_PRIMARY_COLOR=#025B77
INESDATA_BRAND_SECONDARY_COLOR=#2FA0B5
INESDATA_BRAND_ASSETS_DIR=identity
INESDATA_BRAND_LOGO_FILES=pionera-logo.svg
INESDATA_BRAND_LOGO_URLS=
INESDATA_BRAND_FOOTER_LOGO_FILES=pionera-logo.svg,funding-logos.png,oeg.png
INESDATA_BRAND_FOOTER_LOGO_URLS=
INESDATA_BRAND_FOOTER_TEXT=
INESDATA_BRAND_POWERED_BY_TEXT=Powered by:
INESDATA_BRAND_POWERED_BY_LOGO_FILES=inesdta.png
INESDATA_BRAND_POWERED_BY_LOGO_URLS=
INESDATA_BRAND_CONNECTOR_ASSET_BASE_URL=/inesdata-connector-interface/assets/branding
INESDATA_BRAND_PORTAL_ASSET_BASE_URL=/assets/branding
INESDATA_LOCAL_STORE_LABEL=LocalStore
```

`INESDATA_BRAND_LOGO_FILES`, `INESDATA_BRAND_FOOTER_LOGO_FILES` y
`INESDATA_BRAND_POWERED_BY_LOGO_FILES` indican qué archivos de
`INESDATA_BRAND_ASSETS_DIR` se empaquetan como assets de Helm. El framework los
monta en los frontends y genera URLs internas usando
`INESDATA_BRAND_CONNECTOR_ASSET_BASE_URL` o `INESDATA_BRAND_PORTAL_ASSET_BASE_URL`.

`INESDATA_BRAND_SHOW_MENU_TEXT` controla si el nombre textual se muestra junto al
logo en el menú lateral del conector. Usa `false` cuando el logo ya incluya el
nombre de la marca, y `true` cuando el logo sea solo un símbolo.

Si se define `INESDATA_BRAND_LOGO_URLS` o `INESDATA_BRAND_FOOTER_LOGO_URLS`, el
framework usa esas URLs explícitas en lugar de derivarlas desde los archivos.
Lo mismo aplica a `INESDATA_BRAND_POWERED_BY_LOGO_URLS`.

`INESDATA_LOCAL_STORE_LABEL` es una etiqueta visual. El valor técnico de las
transferencias debe seguir siendo `InesDataStore` mientras el backend lo requiera.
Esto permite mostrar `LocalStore` en la interfaz sin cambiar la funcionalidad
subyacente de INESData.

`deployers/inesdata/deployer.config` todavía puede sobrescribir estas variables
por compatibilidad, pero la ubicación recomendada para personalización visual es
`identity/branding.config`.
