# 19. Playwright por Adapter

La validacion UI esta organizada por adapter para evitar acoplar todos los
portales al comportamiento de INESData.

## Estructura Actual

```text
validation/ui/
  shared/
  core/
  adapters/
    edc/
      components/
      specs/
  playwright.config.ts
  playwright.edc.config.ts
  playwright.ops.config.ts
```

| Configuracion | Uso |
| --- | --- |
| `playwright.config.ts` | suite INESData |
| `playwright.edc.config.ts` | suite EDC |
| `playwright.ops.config.ts` | validaciones operativas como MinIO |

## Principio de Separacion

Las piezas compartidas viven en `shared/` y en la orquestacion comun. Las rutas,
page objects y flujos especificos viven bajo el adapter correspondiente.

Se reutiliza lo que es realmente comun:

- evidencias, screenshots, traces y videos;
- resolucion de runtime provider/consumer;
- login cuando el modo de autenticacion coincide;
- checks de errores gateway y readiness;
- persistencia de resultados en `experiments/`.

Los flujos propios se mantienen separados:

- creacion de assets;
- creacion de policies;
- creacion de contract definitions;
- catalogo;
- negociacion;
- transferencia;
- historial.

## Runtime UI

El runtime de UI describe:

| Campo | Uso |
| --- | --- |
| `adapter` | `inesdata`, `edc` u otro adapter futuro |
| `dataspace` | dataspace activo |
| `provider` | conector proveedor y URLs |
| `consumer` | conector consumidor y URLs |
| `auth.mode` | `keycloak-form`, `oidc-bff` o `none` |
| `routeMap` | rutas disponibles del portal |
| `capabilities` | capacidades visuales soportadas por el portal |

Esto permite que las pruebas fallen por capacidades no disponibles de forma
explicita, no por supuestos heredados de otro portal.

## Autenticacion

| Modo | Uso |
| --- | --- |
| `keycloak-form` | portales que redirigen directamente al formulario Keycloak |
| `oidc-bff` | dashboard EDC con proxy/BFF same-origin |
| `none` | smoke tests sin login |

EDC usa `oidc-bff` por defecto. INESData usa el flujo compatible con su portal.

## Marcado Visual de Interacciones

Las suites conservan helpers para destacar elementos antes de hacer click o
rellenar formularios. Esto facilita seguir el flujo en modo headed, debug y en
videos del reporte.

## Ejecucion

```bash
cd validation/ui
npm run test:inesdata
npm run test:edc
```

Desde el framework, `Level 6` selecciona la configuracion Playwright desde el
perfil de validacion del deployer activo.
