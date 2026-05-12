# Ontology Hub Functional

## Proposito
Suite enfocada en flujos funcionales y de navegacion de Ontology Hub que sean
trazables contra los 27 casos del Excel `Ontology Hub`. La suite usa Playwright
contra la aplicacion real, integrada en el menu de `main.py`, y deja que
fallen los problemas de la aplicacion en lugar de ocultarlos con postprocesos
manuales externos.

## Alcance
- Caso `1`: disponibilidad de la home.
- Caso `2`: login/logout.
- Casos `3` y `4`: registro por URI y por repositorio.
- Caso `5`: visualizacion de detalle y descarga `.n3`.
- Casos `6` a `9`: filtros de catalogo.
- Casos `10` a `14`: edicion, versiones y borrado de ontologias.
- Casos `15` a `18`: agentes, usuarios y promocion.
- Casos `19` a `21`: tags.
- Casos `22` a `24`: Patterns, FOOPS y Themis.
- Casos `25` a `27`: busqueda y filtros de terminos.

## Trazabilidad
- Matriz funcional y correlacion PT5: `docs/11_ontology_hub_validation.md`
- El criterio general de correlacion entre hojas del Excel y automatizacion se documenta en `docs/13_test_cases.md`.
- La numeracion de automatizacion conserva dos ids historicos al inicio:
  `OH-APP-00` cubre el caso `1` del Excel y `OH-APP-01` cubre el caso `2`.

## Carpetas Auxiliares
- `validation/components/ontology_hub/functional/fixtures/`: prerequisitos fijos de la suite, por ejemplo el fichero de `Themis`.
- `validation/components/ontology_hub/functional/generated/`: copias estables de ficheros generados por la app durante la ejecucion.
- `validation/components/ontology_hub/functional/state/`: estado interno compartido entre tests cuando la suite se ejecuta por CLI directa.
- Subcarpetas actuales en `generated/`: `patterns/`, `n3/` y `themis/`.

## Ejecucion desde el menu
```
python3 main.py menu
U - UI Validation
2 - Ontology Hub Tests (Normal/Live/Debug)
> seleccionar modo
2 - Ontology Hub Functional
```

## Integracion con Level 6

`Level 6` ejecuta `Ontology Hub Functional` en modo normal (`headless`) como
suite de validacion por defecto para `ontology-hub`.

La suite `integration/` se conserva intacta para validaciones tecnicas de
integracion y comprobaciones PT5 historicas del framework, pero ya no es la que
se lanza automaticamente desde `Level 6`.

Al ejecutarse desde el menu, `Ontology Hub Functional` usa por defecto una
limpieza `soft` de los datos generados por el framework antes de lanzar la
suite. Esa limpieza intenta borrar usuarios, agentes, vocabularios y tags de
prueba sin reiniciar pods, y despues exige un preflight HTTP sano sobre
`/dataset` y `/edition`.

Si la limpieza selectiva falla o deja la aplicacion en mal estado, el framework
cae automaticamente a `hard reset`. En ese caso reinicia los deployments del
release `<dataspace>-ontology-hub` dentro de `components_namespace`
(por ejemplo `demo-ontology-hub-mongodb`,
`demo-ontology-hub-elasticsearch` y `demo-ontology-hub` en `components`) y
repite la comprobacion HTTP antes de continuar.

Si hace falta cambiar el comportamiento, se puede forzar con:
- `ONTOLOGY_HUB_FUNCTIONAL_RESET_MODE=soft`: intenta limpiar usuarios, agentes, vocabularios y tags sin reiniciar pods.
- `ONTOLOGY_HUB_FUNCTIONAL_RESET_MODE=hard`: reinicia los deployments del release `<dataspace>-ontology-hub` en `components_namespace`.
- `ONTOLOGY_HUB_FUNCTIONAL_RESET_MODE=off`: no limpia ni reinicia antes de lanzar la suite.
- Compatibilidad: se siguen aceptando `ONTOLOGY_HUB_APP_FLOWS_RESET_MODE` y `ONTOLOGY_HUB_APP_FLOWS_GENERATED_DIR` como alias antiguos.

## Ejecucion directa por CLI
Desde `validation/ui`:
```bash
npx playwright test --config ../components/ontology_hub/functional/playwright.config.js
```

Modo visible:
```bash
npx playwright test --config ../components/ontology_hub/functional/playwright.config.js --headed
```

Modo debug:
```bash
PWDEBUG=1 npx playwright test --config ../components/ontology_hub/functional/playwright.config.js --headed --debug
```

## Supuestos
- El frontend de Ontology Hub esta accesible en `ONTOLOGY_HUB_BASE_URL`.
- Las credenciales admin configuradas son validas.
- El despliegue permite llegar a las rutas publicas y de edicion.
- La limpieza por defecto asume que los datos generados por la suite se pueden
  identificar por sus nombres y borrarse a traves de la propia UI de edicion.
- El modo `hard` sigue disponible como fallback si el estado del entorno queda
  inconsistente o si el cleanup selectivo no es suficiente.
- Cuando un flujo depende de FOOPS, Themis o Patterns, un error en esos servicios se considera fallo de la aplicacion o de su integracion, no un skip del test.

## Variables clave
- `ONTOLOGY_HUB_BASE_URL`
- `ONTOLOGY_HUB_ADMIN_EMAIL`
- `ONTOLOGY_HUB_ADMIN_PASSWORD`
- `ONTOLOGY_HUB_EXPECTED_VOCAB`
- `ONTOLOGY_HUB_EXPECTED_TITLE`
- `ONTOLOGY_HUB_EXPECTED_QUERY`
- `ONTOLOGY_HUB_EXPECTED_LABEL`
- `ONTOLOGY_HUB_EXPECTED_PRIMARY_TAG`
- `ONTOLOGY_HUB_UI_WORKERS`
- `ONTOLOGY_HUB_THEMIS_TEST_FILE`
- `ONTOLOGY_HUB_FUNCTIONAL_GENERATED_DIR`
- `ONTOLOGY_HUB_FUNCTIONAL_STATE_DIR`
- `ONTOLOGY_HUB_FUNCTIONAL_RESET_MODE`
- `PLAYWRIGHT_OUTPUT_DIR`
- `PLAYWRIGHT_HTML_REPORT_DIR`
- `PLAYWRIGHT_BLOB_REPORT_DIR`
- `PLAYWRIGHT_JSON_REPORT_FILE`

## Normalizaciones Importantes
- Caso `3` y caso `4`: los pasos manuales `docker ps`, `docker exec`, `cd setup` y `bash lovInitialization.sh` no se consideran parte del test. La app debe completar internamente la publicacion.
- Caso `15`: los pasos `15` y `23-26` del Excel no se consideran parte del test. Si la activacion del usuario o la propagacion de permisos requieren Atlas/Docker manual, el test falla y eso se atribuye a la app.
- Caso `24`: la automatizacion sigue el flujo corregido del Excel desde `/dataset`: abre un circulo del grafico, intenta lanzar `Themis` desde el panel derecho visible y, si ese acceso queda oculto, cae al tab `Themis` sin cambiar el resto del flujo. Luego cambia a `User Tests`, sube `test_cases.txt` y descarga el resultado. El fichero se puede indicar con `ONTOLOGY_HUB_THEMIS_TEST_FILE` o dejarlo en `validation/components/ontology_hub/functional/fixtures/themis/test_cases.txt`.
- Casos `12` a `14`: si Ontology Hub devuelve un `502/503` transitorio tras editar o borrar versiones, la automatizacion espera la recuperacion del area `edition`, verifica el estado final de la version y solo entonces continua con los siguientes casos. Si la recuperacion no llega o el estado final no coincide, el test sigue fallando.

## Pendientes Reales
- La suite ya modela los 27 casos del Excel, pero no se han verificado en bloque todos los caminos destructivos sobre este despliegue concreto.
- Algunos casos pueden fallar por comportamiento real de la aplicacion o por diferencias del entorno de demo respecto al Excel historico. Esa trazabilidad queda reflejada en `docs/11_ontology_hub_validation.md`.
- Tras `OH-APP-16`, `OH-APP-17` puede quedar bloqueado por comportamiento de la propia UI de edicion: en ejecuciones anteriores `/edition/users` devolvia `500`, y en `vm-single` `2026-04-30 14:00:47` la pagina de edicion carga pero no expone el enlace `+ USER`/`/edition/signup` esperado para completar la promocion.
- `OH-APP-08` y `OH-APP-09` pueden seguir fallando aunque el vocabulario mantenga `tags = Services` e idiomas `en/es` en la vista de edicion. En el despliegue actual, el catalogo publico sigue publicando las facetas `Tag` y `Language` como `N/A`, por lo que la incidencia apunta al indexado o a la agregacion del catalogo, no al selector del test.
- En sondeos previos de `vm-single`, `OH-APP-14` pudo reiniciar el pod despues de editar y borrar versiones. La causa observada fue un `ENOENT` no capturado en `versions.js` al hacer `unlink` de un `.n3` versionado ausente. El chart del framework monta `/app/versions` para reducir desincronizaciones tras reinicios; en el experimento `2026-04-30 14:00:47`, `OH-APP-14` ya no se reproduce.
