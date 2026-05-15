# 26. Componentes Compartidos en EDC

Los charts de componentes viven en `deployers/shared/components` para que no
pertenezcan exclusivamente a INESData.

## Estado Actual

| Adapter | Level 5 componentes | Validación de componentes |
| --- | --- | --- |
| `inesdata` | habilitado | habilitada si hay componentes |
| `edc` | habilitado con guarda de extensiones del conector | habilitada si hay componentes |

En `deployers/edc/deployer.py`, `deploy_components()` reutiliza el adaptador
compartido de componentes. Antes de desplegar, verifica que el conector EDC
tenga registradas las extensiones que requiere cada componente configurado.
Si falta alguna extensión, `Level 5` falla temprano con un mensaje explícito
para evitar validaciones con un conector incompleto.

## Componentes Compartidos Disponibles

```text
deployers/shared/components/ontology-hub/
deployers/shared/components/ai-model-hub/
deployers/shared/components/semantic-virtualization/
```

Estos charts no deben contener valores runtime, credenciales ni secretos. Los
valores generados deben escribirse por deployer:

```text
deployers/<adapter>/deployments/<ENV>/<dataspace>/components/<component>/
```

## Extensiones Requeridas en EDC

Cada componente puede requerir cambios propios en el conector mediante
extensiones. La activación de `Level 5` para EDC considera esas dependencias:

| Componente | Extensiones EDC requeridas |
| --- | --- |
| `ontology-hub` | `AssetFilterExtension`, `ObservabilityExtension` |
| `ai-model-hub` | `AssetFilterExtension`, `InferenceExtension`, `ObservabilityExtension`, `ContractSequenceExtension` |
| `semantic-virtualization` | `ContractSequenceExtension`, `CustomProxyDataPlaneExtension`, `ObservabilityExtension` |

La comprobación lee el registro `ServiceExtension` de `final-connector`, que es
el runtime empaquetado por defecto en `adapters/edc/scripts/build_image.sh`. Si
se actualiza el conector, ese registro de extensiones debe mantenerse
sincronizado antes de ejecutar `Level 4` y `Level 5`.

## Condiciones Operativas

Para desplegar componentes en EDC, el framework debe asegurar:

- resolución de hosts de componentes para el dataspace EDC;
- values runtime generados bajo `deployers/edc/deployments`;
- imágenes locales o registry disponible para cada componente;
- validación smoke de componente;
- ausencia de dependencia del portal INESData;
- perfil de validación EDC capaz de habilitar componentes solo cuando existan.

## Relación con el Dashboard EDC

El dashboard EDC es apoyo visual para conectores. No debe absorber
`Ontology Hub`, `AI Model Hub` ni `Semantic Virtualization`. Estos componentes
se integran y validan como servicios independientes.

Los componentes deben exponerse mediante URLs propias y validarse con suites
separadas.

## Límite Actual

`Level 5` de EDC depende de que el conector usado por `Level 4` incluya las
extensiones esperadas. Si el árbol local del conector no contiene esas
extensiones registradas, el framework bloquea el despliegue de componentes
hasta que el conector se actualice o reconstruya.
