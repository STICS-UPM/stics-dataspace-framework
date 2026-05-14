# Paso Histórico 7 – Creación de Conector (lógico)

> Nota: este documento forma parte del flujo manual histórico de INESData. No describe los niveles actuales del menú. Para
> operar la versión actual usa [Referencia del menú](../../33_menu_reference.md)
> y [Validación](../../37_validation.md).

### Propósito
Crear de forma lógica un connector de INESData asociado al dataspace ya desplegado, registrándolo correctamente en el esquema EDC y generando los artefactos de configuración necesarios para su despliegue posterior. Este paso histórico ejecuta operaciones controladas y QA-safe sobre los metadatos y bases de datos de soporte, sin aplicar despliegues Helm ni modificar directamente la infraestructura Kubernetes, en el contexto de la validación definida en A5.2.

### Ruta
```
pionera-env/
```

### Ejecutar `connector-create.py` (automatización)
> **Precondiciones técnicas:**
> - El dataspace debe encontrarse desplegado conforme al paso histórico 6.
> - Debe existir el fichero `values-demo.yaml` del dataspace (`Step-1`).
> - El servicio registration-service debe encontrarse operativo.
> - El esquema EDC (`edc_participant`) debe estar inicializado.
> - El entorno Deployer debe estar preparado conforme al paso histórico 4.

Este script se ejecuta de forma no interactiva, idempotente y QA-safe y:
- verifica las precondiciones del entorno INESData,
- valida la existencia del esquema EDC (`edc_participant`),
- ejecuta una limpieza controlada de bases de datos, roles y registros previos,
- crea lógicamente el connector mediante el Deployer,
- registra el connector en el esquema EDC,
- normaliza los ficheros `values.yaml` generados.
```bash
python adapters/inesdata/connector/connector-create.py
```
### Verificación
> Nota: usa la credencial local generada por el framework para el entorno de
> validación. No publiques contraseñas reales ni salidas de comandos que
> revelen secretos.

```bash
kubectl exec -n common-srvs common-srvs-postgresql-0 -- \
sh -c "PGPASSWORD=<postgres_password> psql -U postgres -d demo_rs -c \"SELECT participant_id FROM public.edc_participant;\""


```
**Ejemplo de salida esperada:**
```bash
 participant_id
----------------
 conn-oeg-demo
(1 row)
```

### Artefactos generados
```text
runtime/workdir/inesdata-deployment/connector/values-conn-oeg-demo.yaml
```
### Criterios de aceptación
- El connector se encuentra registrado en la tabla `public.edc_participant`.
- No existen restos inconsistentes de ejecuciones previas (limpieza QA-safe).
- El fichero `values-conn-oeg-demo.yaml` existe y está normalizado.
- El entorno queda listo para el despliegue del connector en fases posteriores (si aplica).

---

⬅️ [Paso anterior: paso histórico 6 – Despliegue del Dataspace](../step-6/06_step_6_dataspace_infrastructure.md)
➡️ [Siguiente paso: paso histórico 8 – Despliegue del Connector](../step-8/08_step_8_connector_infrastructure.md)
🏠 [Volver al README principal](../../README.md)
