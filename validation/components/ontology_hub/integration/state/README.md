# Integration State

Esta carpeta guarda el estado interno persistido por la suite `Ontology Hub Integration` cuando se ejecuta directamente por CLI.

Archivo principal:
- `ontology-hub-bootstrap.json`: resultado del bootstrap reutilizable de la suite PT5 integrada.

Reglas:
- no contiene artefactos de la aplicacion; solo estado interno de coordinacion
- por defecto deja de escribirse en `validation/ui/`
- se puede sobrescribir con `ONTOLOGY_HUB_INTEGRATION_STATE_FILE`
- compatibilidad: `ONTOLOGY_HUB_BOOTSTRAP_STATE_FILE` se sigue aceptando como alias antiguo
