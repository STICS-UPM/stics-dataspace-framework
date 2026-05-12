# 26. Componentes Compartidos en EDC

Los charts de componentes viven en `deployers/shared/components` para que no
pertenezcan exclusivamente a INESData.

## Estado Actual

| Adapter | Level 5 componentes | Validacion de componentes |
| --- | --- | --- |
| `inesdata` | habilitado | habilitada si hay componentes |
| `edc` | no habilitado para despliegue real | deshabilitada |

En `deployers/edc/deployer.py`, `deploy_components()` responde sin desplegar
componentes y el `ValidationProfile` mantiene
`component_validation_enabled=False`.

## Componentes Compartidos Disponibles

```text
deployers/shared/components/ontology-hub/
deployers/shared/components/ai-model-hub/
```

Estos charts no deben contener valores runtime, credenciales ni secretos. Los
valores generados deben escribirse por deployer:

```text
deployers/<adapter>/deployments/<ENV>/<dataspace>/components/<component>/
```

## Condiciones Para Activar EDC Level 5

Antes de activar `Level 5` real en EDC, el framework debe asegurar:

- resolucion de hosts de componentes para el dataspace EDC;
- values runtime generados bajo `deployers/edc/deployments`;
- imagenes locales o registry disponible para cada componente;
- validacion smoke de componente;
- ausencia de dependencia del portal INESData;
- perfil de validacion EDC capaz de habilitar componentes solo cuando existan.

## Relacion con el Dashboard EDC

El dashboard EDC es apoyo visual para conectores. No debe absorber
`Ontology Hub` ni `AI Model Hub` hasta que los componentes esten integrados y
validados como servicios independientes.

Los componentes deben exponerse mediante URLs propias y validarse con suites
separadas.

## Limite Actual

El framework ya esta organizado para compartir charts, pero EDC todavia no
despliega `Ontology Hub` ni `AI Model Hub` en `Level 5`. Esta limitacion es
explicita y evita dar un falso verde en validaciones EDC con componentes.
