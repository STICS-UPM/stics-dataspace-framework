# 25. Issues de Validación y Limpieza de Datos

Las suites de validación deben arrancar con datos de prueba trazables y evitar
fallos por saturación o residuos de ejecuciones anteriores.

## Registro de Issues

Los issues de validación se documentan con este formato:

| Campo | Uso |
| --- | --- |
| ID | identificador estable, por ejemplo `ISSUE-VAL-009` |
| Adapter | `inesdata`, `edc` o ambos |
| Estado | abierto, mitigado, corregido |
| Síntoma | que falla |
| Causa | por que falla |
| Impacto | que invalida o ensucia |
| Resolucion | cambio aplicado |
| Evidencia | tests, experimento o comando |

La documentación conserva el patron y las conclusiones técnicas. Los
logs con secretos o rutas locales sensibles no deben publicarse.

## Limpieza Antes de Validar

La limpieza se basa en dos ideas:

- nombres unicos por experimento para datos nuevos;
- limpieza segura de prefijos de prueba conocidos.

Prefijos usados por la suite EDC:

```text
playwright-edc-
playwright-edc-storage-
playwright-edc-policy-
playwright-edc-contract-
```

El core de validación también genera nombres unicos para assets y objetos de
transferencia usando el experimento y el par provider/consumer.

## MinIO y Storage

La validación de storage no debe aprobar solo porque exista un objeto antiguo.
Debe comprobar que el objeto esperado de la ejecución actual aparece como nuevo
o actualizado.

El verificador de storage:

- lee el objeto esperado desde la ejecución Newman;
- compara contra el bucket destino;
- falla con `expected_object_name` si no aparece;
- redacta credenciales antes de persistir evidencias.

## Redaccion de Secretos

Los artefactos de validación no deben contener:

- access keys;
- secret keys;
- passwords;
- bearer tokens;
- certificados privados;
- datos completos de destinos S3.

Los reportes persistidos deben usar `***REDACTED***` para campos sensibles.

## Hosts

La sincronización de hosts es idempotente. Si una entrada ya existe, se registra
como omitida y no se duplica. Esto evita que pruebas repetidas ensucien
`/etc/hosts` o el fichero de hosts configurado.

## Criterio de Fallo

No se deben relajar aserciones para ocultar residuos. Si la suite no puede
demostrar que el dato pertenece a la ejecución actual, el test debe fallar y
dejar evidencia suficiente para depurar.
