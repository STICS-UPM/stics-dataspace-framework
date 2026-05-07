# AI Model Hub Functional Validation

Esta carpeta agrupa las suites funcionales opt-in de `AI Model Hub`.

A diferencia de la primera ola PT5 (`PT5-MH-01` a `PT5-MH-08`), estas suites:

- dependen de fixtures de dominio;
- pueden poblar el dataspace local bajo demanda;
- no se ejecutan por defecto en `Level 6` mientras esten en fase de maduracion.

Primer objetivo funcional previsto:

- `MH-LING-01`: caso linguistico basado en `FLARES-mini`.
- `MH-MOB-01`: caso movilidad basado en `GTFS-Madrid-Bench-mini`,
  automatizado como benchmark determinista opt-in.

Evidencia API complementaria:

- `python3 -m validation.components.ai_model_hub.model_execution_api --flares-mini`
  ejecuta un registro `FLARES-mini` mediante la API del conector y enlaza la
  respuesta con `expected_outputs.json`. Por ahora valida transporte y
  alineacion de fixture; la comparacion semantica de etiquetas FLARES queda
  pendiente de un endpoint de modelo compatible.

Evidencia UI complementaria:

- La suite Playwright `MH-LING-01` valida publicacion, descubrimiento,
  seleccion de oferta, negociacion y vista de contratos para `FLARES-mini`.
- `trace` esta desactivado por defecto para no persistir cabeceras
  `Authorization` en evidencias locales. Si hace falta depurar una ejecucion
  concreta, se puede habilitar temporalmente con `PLAYWRIGHT_TRACE=on`.

Evidencia API movilidad:

- `python3 -m validation.components.ai_model_hub.mobility_benchmarking_api`
  valida `MH-MOB-01` con `GTFS-Madrid-Bench-mini`, comprueba joins
  GTFS-like, ejecuta modelos controlados de estimacion de ruta/ETA y genera
  datos listos para tabla/graficas de benchmarking.
- Tambien puede activarse dentro del runner del componente con
  `AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING=1`.
- La suite no llama un endpoint vivo de inferencia de movilidad ni muta
  INESData; deja esa demo UI como siguiente incremento cuando exista una ruta
  estable.

Evidencia de integracion movilidad:

- `python3 -m validation.components.ai_model_hub.virtualization_traceability`
  valida `INT-VS-AMH-01` como puente de trazabilidad entre el asset `HttpData`
  generado por `Semantic Virtualization` y el fixture `GTFS-Madrid-Bench-mini`
  de `AI Model Hub`.
- Esta evidencia complementa el benchmark funcional y mantiene separada la
  integracion con `Semantic Virtualization`.
