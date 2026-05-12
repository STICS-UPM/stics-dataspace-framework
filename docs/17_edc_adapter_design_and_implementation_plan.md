# 17. Adapter EDC

El adapter `edc` permite ejecutar el framework con conectores EDC genericos sin
reutilizar el runtime de conectores INESData. Mantiene la misma estructura de
niveles y delega en `deployers/edc`.

## Repositorios Fuente

| Elemento | Repositorio |
| --- | --- |
| Runtime del conector EDC | `https://github.com/luciamartinnunez/Connector` |
| Dashboard EDC | `https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard` |

El framework no versiona los repositorios fuente dentro del repo principal. Se
gestionan como fuentes locales bajo `adapters/edc/sources/` y permanecen
ignorados por Git.

## Estructura

```text
adapters/edc/
  adapter.py
  config.py
  connectors.py
  deployment.py
  build/
  scripts/
  sources/
```

```text
deployers/edc/
  connector/
  deployments/
  deployer.py
  deployer.config.example
```

## Fuentes e Imagen Local

El directorio canonico para el runtime del conector es:

```text
adapters/edc/sources/connector/
```

El script de sincronizacion clona o actualiza el repositorio del conector desde
GitHub si el directorio no existe. El script de build construye una imagen local
del runtime EDC y puede cargarla en Minikube.

Variables habituales para ejecutar con una imagen explicita:

```bash
PIONERA_EDC_CONNECTOR_IMAGE_NAME=validation-environment/edc-connector
PIONERA_EDC_CONNECTOR_IMAGE_TAG=adaptertransfer1
```

La ejecucion real de `Level 4` para EDC exige indicar la imagen del conector de
forma explicita para evitar desplegar tags ambiguos u obsoletos.

## Management API

El contrato del adapter se apoya en la Management API de EDC. Las operaciones
usadas por la validacion incluyen:

| Operacion | Endpoint base |
| --- | --- |
| Catalogo | `/management/v3/catalog/request` |
| Assets | `/management/v3/assets` |
| Policies | `/management/v3/policydefinitions` |
| Contract definitions | `/management/v3/contractdefinitions` |
| Negotiations | `/management/v3/contractnegotiations` |
| Transfers | `/management/v3/adaptertransferprocesses` |

`/management/v3/adaptertransferprocesses` actua como alias neutral del adapter
para iniciar transferencias sin acoplar la validacion al nombre INESData.

## Artefactos Runtime

Los artefactos generados por EDC viven en:

```text
deployers/edc/deployments/<ENV>/<dataspace>/
```

Incluyen certificados, credenciales, policies, values de Helm y configuracion
del dashboard/proxy. No deben editarse manualmente ni subirse a Git.

## Aislamiento Frente a INESData

EDC tiene su propio `deployer.py` y su propio arbol runtime. No debe generar
credenciales ni certificados dentro de `deployers/inesdata/deployments`.

Los servicios comunes siguen siendo compartidos, pero los artefactos especificos
del adapter se materializan bajo `deployers/edc`.

## Validacion

`python3 main.py edc validate --topology local` ejecuta:

- Newman sobre los flujos API del dataspace;
- Playwright con `validation/ui/playwright.edc.config.ts`;
- comprobaciones de transferencia y storage;
- persistencia de evidencias en `experiments/`.
