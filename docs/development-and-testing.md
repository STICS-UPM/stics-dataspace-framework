# Desarrollo y Testing

## Flujo Seguro de Desarrollo

Trabaja con cambios pequeños y valídalos con pruebas focalizadas antes de ejecutar suites amplias.

Loop recomendado:

```bash
python3 -m unittest tests.test_main_cli
python3 -m unittest tests.test_deployer_shared_contracts
python3 -m unittest tests.test_deployer_shared_hosts_manager
```

Para cambios UI, ejecuta la suite Playwright relevante desde `validation/ui/`.

## Probar Imágenes Locales

Usa `L - Build and Deploy Local Images` cuando modifiques fuentes bajo
`adapters/<adapter>/sources/` y quieras probarlas en el cluster local.

Comportamiento esperado:

- en `Level 4 local`, INESData prepara automáticamente `inesdata-connector` e
  `inesdata-connector-interface` antes de crear conectores;
- las recetas registradas construyen la imagen desde una fuente concreta;
- las imágenes se cargan en Minikube cuando la receta lo requiere;
- `Ontology Hub` y `AI Model Hub` reinician su deployment si ya están
  desplegados;
- si el deployment no existe, la imagen queda preparada y el componente debe
  desplegarse con `Level 5`;
- para cambios en conectores INESData, el script de build recompila el runtime
  Java cuando falta el artefacto o detecta cambios locales.
- las opciones rápidas de INESData en `L` hacen redeploy preservando datos:
  reutilizan los valores existentes de Helm y no recrean credenciales ni
  servicios comunes.
- las opciones rápidas de EDC en `L` construyen/cargan imágenes locales del
  conector y/o dashboard, y reinician deployments EDC existentes sin recrear
  datos.
- el `Level 4` de EDC también prepara las imágenes locales necesarias en modo
  `auto`, antes del despliegue Helm, salvo que se hayan definido overrides
  explícitos o se desactive con `PIONERA_EDC_LOCAL_IMAGES_MODE=disabled`.

Modos disponibles para `Level 4 local`:

- `INESDATA_LOCAL_IMAGES_MODE=auto`: valor por defecto; usa fuentes locales si
  existen y omite el paso si faltan.
- `INESDATA_LOCAL_IMAGES_MODE=required`: falla si no puede preparar las imágenes
  locales.
- `INESDATA_LOCAL_IMAGES_MODE=disabled`: usa las imágenes configuradas en los
  valores Helm.

Después de cargar una imagen local, valida con una prueba focalizada antes de
ejecutar toda la suite. Para el conector INESData, el flujo E2E recomendado es:

```bash
cd validation/ui
UI_ADAPTER=inesdata npx playwright test core/05-e2e-transfer-flow.spec.ts --config=playwright.config.ts --workers=1
```

## Extender Deployers

La lógica compartida de deployers pertenece a:

```text
deployers/infrastructure/lib/
```

El comportamiento específico de un adapter pertenece a:

```text
deployers/<adapter>/
adapters/<adapter>/
```

Evita añadir comportamiento específico de un adapter en helpers compartidos si no está parametrizado explícitamente.

## Extender Topologías

La resolución de topología está centralizada en:

```text
deployers/infrastructure/lib/topology.py
deployers/shared/lib/topology.py
```

El contexto del deployer debe describir:

- nombre de topología;
- dirección por defecto;
- direcciones por rol;
- IP externa de ingress;
- modo de routing.

La ejecución real de una topología solo debe habilitarse después de implementar y probar sus preflights.

## Extender Validaciones

Las nuevas validaciones deben seguir este orden:

1. Añadir checks API cuando sea posible.
2. Añadir checks UI solo para comportamiento visible.
3. Añadir limpieza de datos generados.
4. Guardar artefactos en `experiments/`.
5. Añadir pruebas focalizadas de orquestación y configuración.

Para pruebas específicas de un INESData externo o productivo, no modifiques las
suites base. Crea suites opt-in bajo `validation/projects/inesdata/` y actívalas
desde el target correspondiente, como se describe en
[Validación de INESData externo](./29_inesdata_external_validation_targets.md).

## Ficheros Generados y Sensibles

No subas:

- `deployer.config` locales;
- despliegues generados;
- salidas de experimentos;
- reportes Playwright;
- repositorios fuente locales bajo carpetas ignoradas;
- contexto interno de desarrollo.

Usa `.gitignore` como fuente de verdad antes de preparar commits.

## Suites Amplias

Algunas suites legacy amplias pueden requerir servicios externos o suposiciones antiguas. Para desarrollo diario, prioriza pruebas focalizadas del área modificada y amplía cobertura cuando el entorno esté preparado.
