# 03. Guía de Integración para Desarrolladores

## Regla principal

Para integrar un componente en este proyecto, los cambios deben concentrarse en estas zonas:

### Los desarrolladores SÍ deben modificar

- `deployers/shared/components/`
- `adapters/inesdata/sources/`
- `deployers/inesdata/deployer.config` cuando haga falta activar componentes o definir endpoints

### Los desarrolladores NO deben modificar

- `validation/`
- `framework/`

## Dos formas de integrar un componente

### 1. Integración vía API

Usa esta opción cuando el componente funciona como servicio independiente.

Ejemplos típicos:

- un servicio REST
- un servicio semántico
- un servicio con endpoint de health y API propia

### 2. Integración como extensión del conector

Usa esta opción cuando el componente amplía el runtime del conector o su interfaz.

Ejemplos típicos:

- extensiones dentro de `inesdata-connector`
- cambios en la interfaz del conector
- cambios en portal frontend o backend asociados a la extensión

## Integración vía API

### Dónde trabajar

- `deployers/shared/components/<component>/`

Hoy el ejemplo real existente es:

- `deployers/shared/components/ontology-hub/`

### Checklist paso a paso

1. Crear o ajustar el chart Helm del componente en `deployers/shared/components/<component>/`.
2. Asegurar que existe `Chart.yaml`.
3. Añadir un `values.yaml` usable en entorno local.
4. Definir puertos, servicios, ingress y endpoint de health.
5. Comprobar que el componente puede desplegarse dentro del namespace `components`.
6. Configurar `COMPONENTS` en `deployers/inesdata/deployer.config` para que `Level 5` lo despliegue.
7. Ejecutar `Level 5` y verificar que el servicio queda disponible.

### Resultado esperado

Al terminar, el componente debe poder desplegarse como servicio adicional sin tocar la lógica de validación.

## Integración como extensión del conector

### Dónde trabajar

- `adapters/inesdata/sources/inesdata-connector/extensions/`
- `adapters/inesdata/sources/inesdata-connector/`
- `adapters/inesdata/sources/inesdata-connector-interface/`
- `adapters/inesdata/sources/inesdata-public-portal-frontend/`
- `adapters/inesdata/sources/inesdata-public-portal-backend/`

No todos estos directorios son obligatorios para todos los componentes. Depende de si la extensión afecta al backend del conector, a la interfaz o al portal.

### Checklist paso a paso

1. Implementar la extensión en el código fuente correspondiente dentro de `adapters/inesdata/sources/`.
2. Registrar la extensión en el proceso de build si el runtime del conector lo necesita.
3. Ajustar la imagen o el despliegue del conector si la extensión cambia el artefacto final.
4. Si hay cambios de interfaz, actualizarlos en `inesdata-connector-interface/`.
5. Si hay cambios de portal, actualizarlos en `inesdata-public-portal-frontend/` o `inesdata-public-portal-backend/`.
6. Desplegar de nuevo niveles 3 y 4 para comprobar que el conector sigue estable.
7. Validar funcionalmente el comportamiento del conector antes de pedir cambios en la capa de validación.

### Resultado esperado

Al terminar, la capacidad nueva debe formar parte del runtime del conector sin exigir cambios directos en `validation/`.

## Qué ocurre con la validación

La validación es una responsabilidad del framework.

Eso significa:

- el desarrollador entrega el componente integrado
- el framework decide cómo y cuándo se añaden pruebas en `validation/core/` o `validation/components/`
