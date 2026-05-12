# Artefactos Compartidos de Despliegue

Esta carpeta contiene artefactos Helm reutilizables por varios deployers.

Estos artefactos son la fuente compartida por defecto para los deployers. Para
desactivar temporalmente esta resolución compartida se puede establecer:

```bash
PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS=false
```

## Contenido Migrado

- `common/`: chart fuente para servicios comunes.
- `dataspace/registration-service/`: chart fuente del servicio de registro.
- `components/`: charts fuente de componentes opcionales.

## Exclusiones Intencionales

No se copian ni versionan artefactos generados o sensibles:

- `common/charts/`
- `common/init-keys-vault.json`
- `dataspace/registration-service/cacerts.jks`
- `dataspace/registration-service/cert.yaml`
- `dataspace/registration-service/values-*.yaml`
- `components/*/values-*.yaml`

Los ficheros `values-*.yaml` de entorno deben generarse automáticamente durante
el despliegue o permanecer en la ruta legacy hasta completar la migración.

## Valores Runtime

Cuando `PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS=true`, el chart fuente se lee desde
`deployers/shared`. Los valores mutables de servicios comunes se escriben en un
runtime compartido ignorado por Git:

```text
deployers/shared/deployments/<ENV>/common/
```

Los valores mutables específicos de un dataspace se escriben bajo el runtime del
adapter, pero no dentro de una carpeta `shared/` del adapter:

```text
deployers/<adapter>/deployments/<ENV>/<dataspace>/dataspace/registration-service/
```

Ejemplos:

- `deployers/shared/deployments/DEV/common/values.yaml`
- `deployers/inesdata/deployments/DEV/demo/dataspace/registration-service/values-demo.yaml`

Las claves generadas de Vault pertenecen a los servicios comunes compartidos, no
a un deployer concreto. Por eso la copia canónica se mantiene en:

- `deployers/shared/common/init-keys-vault.json`

Estas rutas están ignoradas por Git porque pueden contener configuración
específica del entorno o secretos generados.
