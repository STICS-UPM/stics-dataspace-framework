# 18. Portal EDC y Validacion UI

El portal EDC se despliega como apoyo visual de cada conector EDC. Forma parte
de `Level 4`, igual que la interfaz de conector en INESData, y no sustituye las
validaciones Newman ni las comprobaciones API.

## Ruta Publica

El dashboard EDC se publica bajo el host del conector:

```text
http://conn-<connector>-<dataspace>.dev.ds.dataspaceunit.upm/edc-dashboard/
```

Esta ruta evita colisiones con:

- `/management`;
- `/management/v3`;
- `/protocol`;
- rutas internas del runtime del conector.

## Configuracion Runtime

La configuracion generada del dashboard queda bajo:

```text
deployers/edc/deployments/<ENV>/<dataspace>/dashboard/<connector>/
```

Archivos habituales:

| Fichero | Uso |
| --- | --- |
| `app-config.json` | titulo, menu y parametros visuales |
| `edc-connector-config.json` | URLs del conector consumidas por el dashboard |
| `APP_BASE_HREF.txt` | base path `/edc-dashboard/` |

El dashboard recibe la URL base `/management`, aunque la validacion del
framework use `/management/v3`, porque ese es el contrato esperado por el
dashboard EDC.

## Autenticacion

El modo local actual usa `oidc-bff`:

- el navegador no recibe tokens tecnicos del conector;
- el proxy mantiene la sesion mediante cookies `HttpOnly`;
- el dashboard llama a rutas same-origin;
- el proxy reenvia hacia la Management API.

Ante un error de callback, el portal vuelve a `/edc-dashboard/` con un evento de
error controlado. La suite Playwright detecta ese estado y falla con una causa
visible en lugar de quedarse bloqueada.

## Papel en Validacion

El portal es una superficie visual para:

- login;
- navegacion de provider y consumer;
- creacion visual de assets, policies y contract definitions;
- catalogo;
- negociacion;
- transferencia;
- historial de transferencias.

El baseline oficial sigue siendo:

1. Management API disponible;
2. flujo API `catalog -> negotiation -> transfer`;
3. transferencia validada contra MinIO;
4. dashboard disponible como apoyo visual y superficie Playwright.

## Relacion con Playwright

La suite EDC vive separada de INESData:

```text
validation/ui/playwright.edc.config.ts
validation/ui/adapters/edc/
```

La autenticacion usa el flujo `oidc-bff` y los page objects del dashboard EDC.
Esto evita forzar al portal EDC a comportarse como la interfaz INESData.
