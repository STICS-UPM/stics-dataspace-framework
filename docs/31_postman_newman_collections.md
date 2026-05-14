# Colecciones Newman y Postman

Este documento describe qué colecciones mantiene el framework, cuáles ejecuta
automáticamente `Level 6` y cuáles pueden importarse manualmente en Postman.

## Colecciones Ejecutadas por el Framework

`Level 6` ejecuta las colecciones de:

```text
validation/core/collections/
```

Secuencia actual:

| Orden | Colección | Propósito |
| --- | --- | --- |
| 1 | `01_environment_health.json` | Salud básica de Keycloak y APIs de conectores |
| 2 | `02_connector_management_api.json` | CRUD de entidades de management del conector |
| 3 | `03_provider_setup.json` | Preparación del asset, policy y contract definition |
| 4 | `04_consumer_catalog.json` | Descubrimiento de catálogo desde consumidor |
| 5 | `05_consumer_negotiation.json` | Negociación de contrato |
| 6 | `06_consumer_transfer.json` | Inicio y verificación de transferencia |

El framework genera un entorno temporal de Newman con las variables calculadas
desde el adapter, el dataspace y los conectores desplegados. Las credenciales
reales no están embebidas en las colecciones.

## Colecciones Importables en Postman

Los ficheros importables manualmente están en:

```text
validation/core/collections/postman/
```

| Fichero | Tipo | Uso |
| --- | --- | --- |
| `00_environment.json` | Environment | Ejemplo INESData/PIONERA |
| `00_environment_edc.json` | Environment | Ejemplo EDC |
| `01_environment_health.json` | Collection | Salud básica |
| `02_connector_management_api.json` | Collection | CRUD management |
| `03_e2e_compact.json` | Collection | Flujo end-to-end compacto |

Los valores `provider_password` y `consumer_password` están marcados como
`secret` y contienen placeholders. Deben rellenarse localmente en Postman o
Newman a partir de los artefactos generados por el despliegue. No deben
versionarse contraseñas reales, tokens, claves de API ni exports de entorno con
credenciales.

## Verificación de Importabilidad

Una comprobación mínima de sintaxis JSON puede ejecutarse con:

```bash
python3 - <<'PY'
import json
from pathlib import Path

for path in sorted(Path("validation/core/collections").rglob("*.json")):
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    info = payload.get("info") if isinstance(payload, dict) else None
    values = payload.get("values") if isinstance(payload, dict) else None
    variable = payload.get("variable") if isinstance(payload, dict) else None
    if info and "item" in payload:
        print(f"collection OK: {path}")
    elif values is not None or variable is not None:
        print(f"environment OK: {path}")
    else:
        raise SystemExit(f"Unrecognized Postman JSON shape: {path}")
PY
```

Esta verificación no ejecuta llamadas HTTP; solo comprueba que los ficheros sean
JSON válidos y tengan forma de colección o entorno Postman.

## Relación con Reportes

Cuando `Level 6` ejecuta Newman, guarda reportes JSON por colección bajo:

```text
experiments/<experiment>/newman_reports/
```

El framework agrega métricas y estados en los artefactos del experimento para
que puedan revisarse desde el visor de reportes documentado en
[40_report_viewer.md](./40_report_viewer.md).
