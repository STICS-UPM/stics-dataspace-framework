# 29. Validación de INESData Externo

## Estado

Este documento define la guía objetivo para validar un INESData externo o
productivo con `Level 6`. La implementación debe hacerse de forma incremental y
sin cambiar el comportamiento actual de `local`, `vm-single` ni
`vm-distributed`.

## Cuándo Usar Este Modo

Usa un target externo cuando el entorno ya existe y el framework solo debe
validarlo.

No lo uses para desplegar PIONERA. Para eso siguen existiendo las topologías:

- `local`;
- `vm-single`;
- `vm-distributed`.

La regla principal es:

```text
Topology = entorno que el framework despliega.
Validation target = entorno externo que el framework solo valida.
```

## Configuración del Target

La configuración recomendada para INESData externo debe vivir bajo:

```text
validation/targets/
```

El repositorio debe incluir solo ejemplos:

```text
validation/targets/inesdata-production.example.yaml
```

El fichero real no debe subirse a Git:

```text
validation/targets/inesdata-production.yaml
```

La carpeta `validation/targets/` incluye un `.gitignore` específico para
permitir versionar documentación y ejemplos `*.example.yaml`, pero bloquear
targets reales por defecto.

Las credenciales deben resolverse por variables de entorno, por el mecanismo de
secretos aprobado por INESData o por prompt interactivo seguro. No deben
escribirse en el YAML.

En el menú interactivo, si faltan variables declaradas como `*_env`, el
framework pide esos valores por consola y los mantiene solo en memoria durante
la ejecución.

Ejemplo base:

```yaml
name: inesdata-production
project: inesdata
mode: validation-only
environment: production

safety:
  default_profile: read-only
  allow_write_tests: false
  allow_destructive_tests: false
  redact_artifacts: true

auth:
  keycloak_url: https://auth.example.org
  realm: inesdata
  client_id: validation-framework
  username_env: INESDATA_PROD_VALIDATION_USER
  password_env: INESDATA_PROD_VALIDATION_PASSWORD

dataspaces:
  - name: linguistic
    public_portal_url: https://linguistic.example.org
    connectors:
      - name: provider-linguistic
        role: provider
        portal_url: https://provider-linguistic.example.org
        management_api_url: https://provider-linguistic-api.example.org
      - name: consumer-linguistic
        role: consumer
        portal_url: https://consumer-linguistic.example.org
        management_api_url: https://consumer-linguistic-api.example.org

suites:
  newman_core:
    enabled: true
    profile: read-only
  playwright_core:
    enabled: true
    profile: smoke
  kafka_edc:
    enabled: false

components: {}

project_suites:
  inesdata:
    linguistic:
      enabled: true
      profile: read-only
    mobility:
      enabled: false
```

Si no quieres validar componentes como `ontology-hub` o `ai-model-hub`, basta
con no declararlos o dejar `components: {}`.

## Credenciales y Secretos

El YAML del target debe declarar como encontrar cada secreto, no el valor del
secreto.

Resolucion recomendada:

1. El framework busca las variables declaradas en `username_env`,
   `password_env` u otros campos equivalentes.
2. Si existe un secret manager configurado, intenta resolver el secreto ahi.
3. Si la ejecucion es interactiva y falta un secreto, lo pide por consola.
4. Si la ejecucion no es interactiva y falta un secreto, falla antes de ejecutar
   pruebas.

La contraseña debe pedirse en modo oculto. El valor solo debe vivir en memoria
durante la ejecucion.

El framework no debe escribir secretos en:

- `validation/targets/*.yaml`;
- `deployer.config`;
- `context/`;
- `docs/`;
- `experiments/`;
- logs;
- reportes Newman o Playwright.

Para CI o ejecuciones programadas, usa variables de entorno o el secret manager
aprobado. En ese modo el framework no debe quedarse esperando entrada por
consola.

## Seguridad por Defecto

Un target productivo debe ejecutarse en modo seguro:

- `Levels 1-5` deshabilitados;
- limpieza previa deshabilitada;
- Kafka o transferencias con escritura deshabilitadas salvo aprobación expresa;
- pruebas destructivas deshabilitadas;
- reportes con secretos redactados;
- pruebas de escritura solo con confirmación explícita y datos aislados.

La primera versión de un target productivo debe ser `read-only`. Las pruebas
que creen, editen o borren datos deben añadirse después como perfil opt-in.

## Dónde Crear Pruebas Extendidas

Las pruebas solicitadas específicamente por INESData no deben modificar las
suites base actuales. Deben añadirse como suites de proyecto:

```text
validation/
  core/
  ui/
  components/
  projects/
    inesdata/
      linguistic/
        test_cases.yaml
        specs/
        fixtures/
      mobility/
        test_cases.yaml
        specs/
        fixtures/
      shared/
        fixtures/
        helpers/
```

La estructura base versionada incluye:

- `validation/projects/inesdata/project_suites.yaml`;
- `validation/projects/inesdata/linguistic/test_cases.yaml`;
- `validation/projects/inesdata/mobility/test_cases.yaml`;
- READMEs por dominio, `fixtures/` y `specs/`;
- un ejemplo Playwright no ejecutable por defecto en
  `validation/projects/inesdata/linguistic/specs/linguistic_catalog_smoke.example.ts`.

Uso de cada carpeta:

- `validation/core/`: pruebas comunes del dataspace.
- `validation/ui/`: pruebas UI core actuales por adapter.
- `validation/components/`: componentes como `ontology-hub` o `ai-model-hub`.
- `validation/projects/inesdata/`: validaciones propias de INESData externo.
- `validation/projects/inesdata/shared/`: helpers y fixtures reutilizables por
  dominios INESData.

Regla de separación:

```text
Las pruebas base protegen el framework.
Las pruebas de proyecto cubren necesidades particulares de INESData.
```

## Cómo Crear una Prueba Playwright Extendida

1. Crea una carpeta de dominio bajo `validation/projects/inesdata/`.
2. Añade un `test_cases.yaml` con el identificador funcional, objetivo,
   precondiciones y perfil de seguridad.
3. Añade el spec Playwright bajo `specs/`.
4. Usa fixtures del target en lugar de URLs hardcodeadas.
5. Guarda evidencias en el directorio de experimento.
6. Marca la prueba como `read-only`, `write-safe` o `destructive`.
7. Activa la suite desde `project_suites` en el YAML del target.

Ejemplo de catálogo:

```yaml
cases:
  - id: INESDATA-LING-01
    title: Catalogo linguistico visible
    profile: read-only
    suite: linguistic
    type: playwright
    objective: Verificar que el usuario puede abrir el espacio linguistico y ver el catalogo publicado.
```

Ejemplo conceptual de spec:

```javascript
import { test, expect } from '@playwright/test';

test('INESDATA-LING-01: linguistic catalog is visible', async ({ page }) => {
  const portalUrl = process.env.INESDATA_LINGUISTIC_PORTAL_URL;
  test.skip(!portalUrl, 'Missing INESDATA_LINGUISTIC_PORTAL_URL');

  await page.goto(portalUrl);
  await expect(page.getByRole('heading', { name: /catalog/i })).toBeVisible();
});
```

Cuando se implemente el resolvedor de targets, estas variables deben provenir
del YAML del target y no requerir configuración manual repetitiva.

## Activación desde el Target

Una suite extendida solo debe ejecutarse si aparece activada:

```yaml
project_suites:
  inesdata:
    linguistic:
      enabled: true
      profile: read-only
```

Si la suite no aparece o `enabled` es `false`, `Level 6` debe omitirla.

## Flujo de Uso Objetivo

Flujo por menú:

```text
python3 main.py menu
-> G - Validate target
-> Select validation target
-> Show target validation plan
```

En el estado actual, `G - Validate target` incluye un runner mínimo seguro:

- carga targets de `validation/targets/`;
- muestra el plan de suites;
- informa secretos requeridos sin imprimir valores;
- no ejecuta limpieza ni borra datos;
- no ejecuta escrituras;
- ejecuta únicamente specs Playwright `read-only` explícitamente habilitados en
  `project_suites`;
- ignora plantillas `*.example.*` y termina como `skipped` si no existen specs
  reales.

Flujo CLI previsto:

```bash
python3 main.py inesdata validate --target inesdata-production --profile read-only
```

Esta ruta CLI queda como fase posterior. La base versionada actualmente prioriza
el menú `G - Validate target`, porque es el flujo principal de uso del
framework.

El framework debe mostrar claramente:

```text
Project: inesdata
Target: inesdata-production
Mode: validation-only / read-only
Levels 1-5: disabled for external target
Level 6: enabled
Cleanup: disabled
Writes: disabled
```

## Criterios de Aceptación

Este modo estará listo cuando:

- `Level 6` pueda leer un target externo sin resolver topología PIONERA;
- `Levels 1-5` queden bloqueados para targets externos;
- las suites base actuales sigan funcionando sin cambios;
- los componentes no declarados no se ejecuten;
- las suites de proyecto se ejecuten solo si el target las activa;
- los secretos faltantes se pidan por consola solo en modo interactivo;
- las ejecuciones no interactivas fallen si faltan secretos obligatorios;
- los reportes no expongan secretos;
- exista al menos una prueba extendida `read-only` de ejemplo.
