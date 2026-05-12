# Functional State

Esta carpeta guarda el estado interno compartido entre tests de `Ontology Hub Functional` cuando la suite se ejecuta directamente por CLI.

Ejemplos:
- vocabulario creado en `Excel-03`
- vocabulario creado en `Excel-04`
- version creada en `Excel-11`
- identidad creada en `Excel-15`

Reglas:
- no contiene artefactos de la aplicacion; solo coordinacion interna de la suite
- cuando la suite se ejecuta desde `main.py menu`, este estado se redirige al directorio del experimento actual
- por entorno se puede sobrescribir con `ONTOLOGY_HUB_FUNCTIONAL_STATE_DIR`
- compatibilidad: `ONTOLOGY_HUB_APP_FLOWS_STATE_DIR` se acepta como alias antiguo
