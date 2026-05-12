# 01. Arquitectura del Framework

## Vista simple

El framework actual está organizado para separar tres cosas:

- la orquestación del flujo
- la lógica específica de INESData
- los artefactos de validación

Eso permite mantener estable el núcleo del framework y concentrar la lógica del ecosistema en el adapter.

## Capas principales

### 1. Orquestación

El punto de entrada operativo para el entorno local es `main.py menu`.

Desde ahí se ejecutan los niveles:

- Level 1: cluster
- Level 2: servicios comunes
- Level 3: dataspace
- Level 4: conectores
- Level 5: componentes opcionales
- Level 6: validación

`main.py` es la única entrada operativa del framework. La lógica nueva debe integrarse en `main.py`, `deployers/`, `adapters/`, `framework/` o `validation/`.

## 2. Núcleo reutilizable

La carpeta `framework/` contiene clases reutilizables.

Las más importantes para la validación actual son:

- `framework/validation_engine.py`
- `framework/newman_executor.py`
- `framework/experiment_storage.py`

### ValidationEngine

`ValidationEngine` prepara las variables de entorno para Newman, recorre las parejas proveedor-consumidor y delega la ejecución real a `NewmanExecutor`.

Su responsabilidad es de coordinación, no de conocimiento funcional profundo del ecosistema.

### NewmanExecutor

`NewmanExecutor` ejecuta las colecciones Postman con Newman.

Actualmente hace tres cosas principales:

- carga las colecciones core desde `validation/core/collections/`
- carga scripts compartidos desde `validation/shared/api/`
- añade el script específico de cada colección desde `validation/core/tests/`

## 3. Lógica específica de INESData

La carpeta `adapters/inesdata/` contiene la lógica concreta del proyecto.

Aquí viven:

- despliegue de infraestructura
- despliegue del dataspace
- despliegue de conectores
- despliegue de componentes opcionales
- acceso a configuración y credenciales

Subzonas importantes:

- `adapters/inesdata/infrastructure.py`
- `adapters/inesdata/deployment.py`
- `adapters/inesdata/connectors.py`
- `adapters/inesdata/components.py`
- `adapters/inesdata/sources/`

## 4. Artefactos de despliegue y validación

Tres carpetas son especialmente importantes:

- `deployers/`: deployers, charts, bootstrap y runtime generado por adapter
- `deployers/shared/`: artefactos compartidos por los deployers
- `validation/`: colecciones y scripts de prueba

La regla práctica es esta:

- si integras un servicio API compartido, normalmente trabajarás en `deployers/shared/components/`
- si integras una extensión del conector, normalmente trabajarás en `adapters/inesdata/sources/`

## Qué no debe hacerse

Para integrar un componente no debería ser necesario tocar `framework/`.
