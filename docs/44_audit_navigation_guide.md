# Guía de Navegación para Auditoría

Este documento orienta la revisión pública del Validation Environment. Su
objetivo es ayudar a identificar qué documentación representa el estado actual
del framework, dónde se encuentra la evidencia técnica y qué material se
conserva solo como trazabilidad histórica.

## Alcance Vigente

El framework permite desplegar y validar entornos PIONERA con adapters de
INESData y EDC. La documentación vigente cubre:

- topologías `local`, `vm-single` y modelo de alineamiento para `vm-distributed`;
- namespaces canónicos comunes a todas las topologías;
- ejecución por menú y CLI mediante `main.py`;
- validación de `Level 6` con Newman/Postman, Kafka, componentes compartidos,
  Playwright cuando aplica, métricas y reportes;
- evidencias generadas por ejecución bajo `experiments/`;
- colecciones importables de Postman y ejecución automatizada con Newman.

## Fuera de Alcance

La documentación no debe contener contraseñas reales, tokens, claves de
API, rutas privadas de una máquina, IP privadas de una instalación concreta ni
exports de entornos con credenciales. Los ejemplos usan placeholders o nombres
de variables.

Los logs y artefactos generados por ejecución se tratan como evidencia local de
cada experimento y no forman parte del contenido estable de `docs/`.

## Orden de Lectura Sugerido

1. [README](./README.md): índice principal de la documentación.
2. [30 Estado actual del framework](./30_framework_current_state.md): resumen
   vigente de niveles, topologías, adapters y namespaces.
3. [34 Arquitectura](./34_architecture.md): componentes del repositorio y
   responsabilidades.
4. [35 Deployers y topologías](./35_deployers_and_topologies.md): reglas de
   despliegue, overlays, namespaces y alineamiento de `vm-distributed`.
5. [46 Guía operativa de vm-distributed](./46_vm_distributed_runbook.md):
   procedimiento de operación, preflight, niveles, conectores adicionales y
   evidencia para auditoría.
6. [37 Validación](./37_validation.md): alcance de `Level 6`, validaciones,
   reportes y salida de consola.
7. [31 Colecciones Newman y Postman](./31_postman_newman_collections.md):
   colecciones ejecutables e importables.
8. [40 Visor de reportes](./40_report_viewer.md): revisión local de resultados.
9. [39 Troubleshooting](./39_troubleshooting.md): diagnóstico de fallos
   frecuentes.

## Mapa de Evidencia

| Evidencia | Ubicación | Comentario |
| --- | --- | --- |
| Configuración de ejemplo | `deployers/**/**/*.config.example` | Plantillas versionables sin secretos reales |
| Colecciones Newman | `validation/core/collections/` | Base ejecutada por la validación automatizada |
| Colecciones Postman | `validation/core/collections/postman/` | Archivos importables para revisión manual |
| Resultados de ejecución | `experiments/<experimento>/` | Evidencia generada localmente por cada ejecución |
| Reportes visuales | `main.py report-viewer` | Interfaz local para consultar experimentos |
| Pruebas automatizadas | `tests/` | Cobertura técnica del framework |
| Diagramas públicos | `docs/*.png` | Vista local y distribuida del entorno |
| Guía operativa distribuida | `docs/46_vm_distributed_runbook.md` | Procedimiento estable para operar y auditar `vm-distributed` |
| Reporte consolidado A5.2/E5.2 | `docs/E5.2_Resultados_Validacion_Componentes.xlsx` | Matriz de resultados, evidencias y checklist de apoyo UNE 0087 |
| Alineación UNE 0087 | `experiments/<experimento>/une_0087_alignment.*` | Artefacto de apoyo no certificante generado desde evidencias del experimento |

## Namespaces Canónicos

Todas las topologías deben alinearse con los mismos namespaces funcionales:

| Namespace | Responsabilidad |
| --- | --- |
| `common-srvs` | Servicios comunes de infraestructura |
| `core-control` | Servicios core de control |
| `provider` | Conector y servicios del proveedor |
| `consumer` | Conector y servicios del consumidor |
| `components` | Componentes compartidos y auxiliares |

## Estado de Topologías

`local` y `vm-single` son las topologías principales de trabajo actual. La
topología `vm-distributed` debe mantenerse alineada con la rama remota `main`,
especialmente en namespaces, contratos de deployer, Level 5 y validación de
Level 6.

## Trazabilidad Histórica

Los documentos `00` a `29` explican decisiones, diseño y evolución técnica. Se
mantienen navegables para auditoría, pero la fuente operativa actual es la
documentación vigente enlazada en la ruta de lectura.

La carpeta
[flujo manual histórico de INESData](./legacy_inesdata_manual/00_historical_inesdata_manual_flow.md)
conserva material legacy del flujo manual anterior. Para ejecutar el framework
actual deben usarse [33 Referencia del menú](./33_menu_reference.md),
[35 Deployers y topologías](./35_deployers_and_topologies.md) y
[37 Validación](./37_validation.md).

Para revisar específicamente la topología distribuida, usa
[46 Guía operativa de vm-distributed](./46_vm_distributed_runbook.md) después de
[35 Deployers y topologías](./35_deployers_and_topologies.md).
