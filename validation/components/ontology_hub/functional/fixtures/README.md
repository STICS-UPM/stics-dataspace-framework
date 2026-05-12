# Functional Fixtures

Esta carpeta guarda prerrequisitos fijos de la suite `Ontology Hub Functional` que no deben inventarse durante la ejecucion.

Estructura actual:

- `themis/test_cases.txt`: fichero base para `Excel-24 / OH-APP-24`.

Regla de uso:

- Cada flujo que necesite ficheros externos debe guardarlos aqui, en una subcarpeta propia por funcionalidad.
- Si un test necesita sobrescribir la ruta por entorno, debe seguir aceptando una variable explicita, pero usar esta carpeta como ubicacion por defecto dentro del framework.
