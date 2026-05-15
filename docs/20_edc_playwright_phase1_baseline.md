# 20. Baseline Playwright EDC

La suite Playwright de EDC valida el dashboard EDC desplegado en `Level 4` y se
ejecuta con una configuración separada de INESData.

## Ruta

```text
validation/ui/adapters/edc/
```

## Specs Actuales

| Spec | Proposito |
| --- | --- |
| `01-login-readiness.spec.ts` | login OIDC BFF y disponibilidad del portal |
| `02-navigation-smoke.spec.ts` | navegacion provider/consumer |
| `03-consumer-negotiation.spec.ts` | catálogo y negociación desde consumer |
| `03-provider-setup.spec.ts` | creacion de asset desde provider |
| `03b-provider-policy-create.spec.ts` | creacion de policy desde provider |
| `03c-provider-contract-definition-create.spec.ts` | creacion de contract definition |
| `04-consumer-transfer.spec.ts` | inicio de transferencia y visibilidad en historial |
| `05-consumer-transfer-storage.spec.ts` | objeto transferido visible en MinIO consumer |

## Diferencias Frente a INESData

| Area | INESData | EDC |
| --- | --- | --- |
| Portal | interfaz INESData | dashboard EDC |
| Auth | flujo del portal INESData | `oidc-bff` |
| Asset UI | subida de fichero del portal INESData | asset `HttpData` |
| Transfer | flujo propio INESData | Management API EDC y destino S3 |
| Configuración | `playwright.inesdata.config.ts` | `playwright.edc.config.ts` |

La suite EDC es analoga a INESData en intencion, pero no replica exactamente los
mismos formularios porque el dashboard EDC expone capacidades distintas.

## Bootstrap y Datos de Prueba

Los tests usan nombres de prueba trazables, por ejemplo prefijos:

```text
playwright-edc-
playwright-edc-storage-
playwright-edc-policy-
playwright-edc-contract-
```

La validación de storage usa nombres unicos por ejecución para evitar falsos
fallos por objetos residuales en MinIO.

## Ejecución Manual

```bash
cd validation/ui
UI_ADAPTER=edc \
UI_DATASPACE=pionera-edc \
UI_PROVIDER_CONNECTOR=conn-citycounciledc-pionera-edc \
UI_CONSUMER_CONNECTOR=conn-companyedc-pionera-edc \
npm run test:edc
```

## Resultado Esperado

En un entorno EDC local sano, la suite debe completar los `8` specs y dejar el
HTML report bajo el experimento generado por `Level 6`.
