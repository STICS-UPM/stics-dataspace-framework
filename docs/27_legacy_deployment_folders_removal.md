# 27. Carpetas Legacy de Despliegue

La arquitectura nueva usa `deployers/` como ubicacion canonica de artefactos de
despliegue. Las carpetas raiz legacy dejaron de ser fuente activa del framework.

## Carpetas Legacy

```text
inesdata-deployment/
edc-deployment/
```

Estas carpetas no deben ser requeridas por `main.py` ni por los deployers
actuales.

## Ubicacion Actual

| Tipo de artefacto | Ruta actual |
| --- | --- |
| Infraestructura Python | `deployers/infrastructure/lib/` |
| Servicios comunes | `deployers/shared/common/` |
| Registration service compartido | `deployers/shared/dataspace/registration-service/` |
| Componentes compartidos | `deployers/shared/components/` |
| INESData especifico | `deployers/inesdata/` |
| EDC especifico | `deployers/edc/` |
| Runtime generado | `deployers/<adapter>/deployments/<ENV>/<dataspace>/` |

## Reglas

- no crear nuevos artefactos en las carpetas raiz legacy;
- no leer configuracion runtime desde `Validation-Environment/deployer.config`;
- no versionar `deployments/`;
- mantener `deployer.config.example` dentro de cada deployer;
- conservar los secretos solo en ficheros ignorados por Git.

## Compatibilidad

Si una maquina local conserva `inesdata-deployment/` o `edc-deployment/` como
respaldo manual, esas carpetas deben tratarse como estado externo. No forman
parte de la arquitectura activa.

El nombre `inesdata-deployment` solo puede aparecer como referencia historica o
como repositorio externo, no como ruta local requerida por el framework.
