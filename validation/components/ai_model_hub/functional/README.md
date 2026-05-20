# AI Model Hub Functional Validation

Esta carpeta agrupa las suites funcionales de `AI Model Hub`.

A diferencia de la primera ola PT5 (`PT5-MH-01` a `PT5-MH-08`), estas suites:

- dependen de datasets de dominio sincronizados en `Level 5`;
- pueden poblar el dataspace local bajo demanda;
- se ejecutan por defecto desde `Level 6` y pueden omitirse temporalmente
  definiendo la variable `AI_MODEL_HUB_ENABLE_*` correspondiente en `false`,
  `0`, `no` o dejándola vacía.

Primer objetivo funcional previsto:

- `MH-LING-01`: caso lingüístico basado en `FLARES`.
- `MH-MOB-01`: caso movilidad basado en `GTFS-Madrid-Bench`,
  automatizado como benchmark determinista.

Evidencia API complementaria:

- `python3 -m validation.components.ai_model_hub.model_execution_api --flares-dataset`
  ejecuta un registro `FLARES` mediante la API del conector y enlaza la
  respuesta con etiquetas esperadas derivadas de la fuente. Por defecto usa
  `/api/v1/nlp/flares-reliability-baseline-a` del `model-server`, por lo que
  valida transporte, alineación de dataset y comparación semántica controlada
  mediante `result.label`.

Evidencia UI complementaria:

- La suite Playwright `MH-LING-01` valida publicación, descubrimiento,
  selección de oferta, negociación y vista de contratos para `FLARES`.
- `trace` está desactivado por defecto para no persistir cabeceras
  `Authorization` en evidencias locales. Si hace falta depurar una ejecución
  concreta, se puede habilitar temporalmente con `PLAYWRIGHT_TRACE=on`.

Evidencia API movilidad:

- `python3 -m validation.components.ai_model_hub.mobility_benchmarking_api`
  valida `MH-MOB-01` con `GTFS-Madrid-Bench`, comprueba joins
  GTFS-like, ejecuta modelos controlados de estimación de ruta/ETA y genera
  datos listos para tabla/gráficas de benchmarking.
- Dentro del runner del componente se ejecuta por defecto; para omitirla en una
  iteración rápida se puede usar `AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING=false`.
- La suite no muta INESData. Los endpoints vivos de movilidad del
  `model-server` quedan disponibles como línea base reemplazable para futuros
  incrementos UI/API.

Evidencia de integración movilidad:

- `python3 -m validation.components.ai_model_hub.virtualization_traceability`
  valida `INT-VS-AMH-01` como puente de trazabilidad entre el asset `HttpData`
  generado por `Semantic Virtualization` y el dataset `GTFS-Madrid-Bench`
  de `AI Model Hub`.
- Esta evidencia complementa el benchmark funcional y mantiene separada la
  integración con `Semantic Virtualization`.
