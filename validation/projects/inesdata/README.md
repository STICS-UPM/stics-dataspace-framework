# Suites extendidas de INESData

Esta carpeta define la estructura base para añadir validaciones propias a INESData en modo producción sin tocar las pruebas base usadas por PIONERA.

## Qué se reutiliza

- Newman core: `validation/core/collections/`.
- Kafka funcional: suite existente de `Level 6` cuando el target la habilite.
- Playwright core: `validation/ui/`.
- Componentes: `validation/components/`, solo si el target declara componentes.

## Qué se añade aquí

Las pruebas particulares de INESData externo o productivo viven aquí:

```text
validation/projects/inesdata/
  linguistic/
  mobility/
  shared/
```

Cada dominio debe tener:

- `test_cases.yaml`: catálogo funcional de casos;
- `specs/`: pruebas Playwright del dominio;
- `fixtures/`: datos no sensibles necesarios para esas pruebas.

## Reglas

- Las suites de proyecto son opt-in mediante `project_suites` en el target.
- Producción debe empezar en perfil `read-only`.
- No se deben versionar secretos, tokens, usuarios reales ni datos sensibles.
- No se deben modificar fuentes de producto ni suites base para cubrir
  necesidades específicas de INESData externo.

## Evolución para auditoría

El perfil `read-only` es la base segura para conectar el framework con un
INESData productivo y generar evidencias Playwright sin modificar datos reales.
Si una auditoría necesita demostrar flujos de creación, edición o borrado, esos
casos no deben añadirse al perfil `read-only`.

La extensión recomendada es crear un perfil futuro `write-safe`, separado y
explícito, con estas garantías mínimas:

- usar un usuario de validación dedicado y con permisos acotados;
- crear solo datos de prueba identificables por el framework, por ejemplo con
  prefijos `vf-<fecha>-<uuid>`;
- registrar cada entidad creada en un manifiesto de ejecución;
- limpiar únicamente entidades registradas en ese manifiesto y verificadas como
  datos de prueba;
- generar evidencias Playwright igual que en `read-only`, pero dejando claro que
  la suite modifica datos controlados;
- bloquear cualquier borrado genérico o acción destructiva sobre datos no
  creados por la propia ejecución.

Hasta que exista ese perfil, las suites para INESData productivo deben tratarse
como validaciones de solo lectura.

## Ejecución

El menú principal expone la ruta segura:

```bash
python3 main.py
```

Después selecciona `G - Validate target`.

El runner actual solo ejecuta specs Playwright `read-only` habilitados desde el
target. Los ficheros `*.example.*` son plantillas y no se ejecutan.

## Guía rápida para continuar el desarrollo

Trabaja desde la raíz del framework:

```bash
cd Validation-Environment
```

1. Crea el target real local:

```bash
cp validation/targets/inesdata-production.example.yaml \
  validation/targets/inesdata-production.yaml
```

El fichero `validation/targets/inesdata-production.yaml` está ignorado por Git.

2. Edita el target real y completa las URLs/endpoints de INESData.

Mantén las credenciales como nombres de variables, no como valores:

```yaml
auth:
  username_env: INESDATA_PROD_VALIDATION_USER
  password_env: INESDATA_PROD_VALIDATION_PASSWORD
```

3. No escribas credenciales en el target.

En ejecución interactiva, el menú pedirá los valores faltantes por consola y los
mantendrá solo en memoria durante esa ejecución. Si prefieres preparar la sesión
de antemano, también puedes exportarlos en la terminal:

```bash
export INESDATA_PROD_VALIDATION_USER='<usuario-validacion>'
export INESDATA_PROD_VALIDATION_PASSWORD='<password-validacion>'
```

En ambos casos, el framework no escribe esos valores en el target, logs ni
reportes.

4. Crea un spec real a partir de la plantilla:

```bash
cp validation/projects/inesdata/linguistic/specs/linguistic_catalog_smoke.example.ts \
  validation/projects/inesdata/linguistic/specs/inesdata_ling_02_catalog_visible.spec.ts
```

Los ficheros `*.example.*` no se ejecutan. Solo se ejecutan specs reales
`*.spec.ts` o `*.spec.js`.

5. Verifica que la suite esté habilitada en el target:

```yaml
project_suites:
  inesdata:
    linguistic:
      enabled: true
      profile: read-only
```

6. Ejecuta el runner desde el menú:

```bash
python3 main.py
```

Selecciona `G - Validate target`, elige el target y luego
`3 - Run target validation (read-only)`.

Los artefactos Playwright se guardan bajo `experiments/<experiment>/targets/`
con reportes HTML, traces, screenshots y vídeos cuando existan specs reales.

Los specs pueden usar `shared/target-runtime.ts` para leer el target activo:

```typescript
import { portalUrlForDataspace } from "../../shared/target-runtime";

const portalUrl = portalUrlForDataspace("linguistic");
```

La ruta CLI queda como objetivo posterior:

```bash
python3 main.py inesdata validate --target inesdata-production --profile read-only
```
