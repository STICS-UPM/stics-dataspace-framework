# 21. Arquitectura `deployers/`, Roles y Level 5

La arquitectura actual separa deployers especificos, artefactos compartidos e
infraestructura Python del framework.

## Estructura

```text
deployers/
  infrastructure/
    lib/
  shared/
    common/
    dataspace/
    components/
  inesdata/
    connector/
    dataspace/
    deployer.py
    deployer.config.example
  edc/
    connector/
    deployer.py
    deployer.config.example
```

## Responsabilidades

| Carpeta | Responsabilidad |
| --- | --- |
| `deployers/infrastructure/lib` | API Python estable: contratos, hosts, topologia, orquestacion |
| `deployers/shared` | charts y artefactos reutilizables |
| `deployers/inesdata` | artefactos y deployer especificos de INESData |
| `deployers/edc` | artefactos y deployer especificos de EDC |

`deployers/shared/lib` se conserva como capa de compatibilidad, pero el codigo
nuevo debe importar desde `deployers.infrastructure.lib`.

## Roles de Namespace

El framework no debe depender de nombres fijos. Usa roles:

| Rol | Uso |
| --- | --- |
| `common` | servicios comunes |
| `dataspace` | registration service, portal y conectores |
| `components` | componentes opcionales |
| `provider` | conector proveedor |
| `consumer` | conector consumidor |

En local varios roles pueden compartir namespace. En VM pueden mapearse a nodos
o namespaces distintos.

## Level 5

`Level 5` despliega componentes opcionales. En INESData, el flujo esta activo y
usa los charts compartidos de:

```text
deployers/shared/components/ontology-hub/
deployers/shared/components/ai-model-hub/
```

El perfil de validacion activa validaciones de componentes cuando
`context.components` no esta vacio.

En EDC, la arquitectura ya permite compartir componentes, pero el despliegue
real de `Level 5` para componentes EDC no esta habilitado todavia.

## Artefactos Generados

Los charts fuente viven en `deployers/shared`; los values runtime y secretos se
materializan por deployer:

```text
deployers/<adapter>/deployments/<ENV>/<dataspace>/
```

Esto permite reproducibilidad sin ensuciar carpetas compartidas ni versionar
credenciales.
