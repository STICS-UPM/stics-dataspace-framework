# Arquitectura

El framework despliega y valida entornos de dataspace mediante adapters, deployers y suites de validación.

## Áreas Principales

```text
main.py                         CLI y menú guiado
framework/                      validación, métricas y reportes reutilizables
adapters/                       comportamiento específico de cada adapter
deployers/                      contratos, charts y deployers por adapter
validation/                     validaciones Newman, Playwright y componentes
tests/                          pruebas unitarias Python
experiments/                    salidas generadas por validación y métricas
```

Los artefactos generados en tiempo de ejecución se mantienen fuera de Git siempre que sea posible.

## Vistas de Referencia

- [Entorno local de validación](./getting-started.md#vista-local).
- [Entorno VM distribuido de validación](./deployers-and-topologies.md#interpretación-del-diagrama-vm3).

## Modelo de Ejecución

El framework usa un modelo de seis niveles:

```text
Level 1  preparación del cluster
Level 2  servicios comunes
Level 3  runtime del dataspace
Level 4  conectores
Level 5  componentes opcionales
Level 6  validación
```

`main.py` es la entrada canónica. Soporta menú guiado y comandos directos.

## Responsabilidad del Adapter

Un adapter conoce cómo interactuar con una implementación concreta de dataspace.

Los adapters actuales son:

- `inesdata`;
- `edc`.

Los adapters aportan comportamiento específico como URLs de conectores, credenciales, bootstrap, limpieza de datos y soporte de validación.

## Responsabilidad del Deployer

Un deployer expone el contrato común de despliegue para un adapter.

Los deployers viven en:

```text
deployers/inesdata/
deployers/edc/
```

Las utilidades compartidas de infraestructura viven en:

```text
deployers/infrastructure/lib/
```

Los charts y artefactos compartidos viven en:

```text
deployers/shared/
```

## Responsabilidad de Validación

La validación se centraliza en el nivel 6. Puede ejecutar:

- limpieza previa de datos de prueba;
- colecciones Newman/Postman;
- pruebas UI con Playwright;
- validaciones específicas de componentes;
- recolección de métricas.

El contexto del deployer y el adapter seleccionado determinan qué validaciones se habilitan.
