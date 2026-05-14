# Paso Histórico 6 – Despliegue del Dataspace (infraestructura)

> Nota: este documento forma parte del flujo manual histórico de INESData. No describe los niveles actuales del menú. Para
> operar la versión actual usa [Referencia del menú](../../33_menu_reference.md)
> y [Validación](../../37_validation.md).

### Propósito
Materializar en infraestructura Kubernetes el dataspace definido de forma lógica en el paso histórico 5, desplegando los componentes necesarios para su funcionamiento operativo. Este paso histórico aplica cambios controlados sobre la infraestructura (base de datos y servicios) de forma reproducible y QA-safe, en el contexto de la validación definida en A5.2.

### Ruta
```
pionera-env/
```

### Ejecutar `dataspace-deploy.py` (automatización)
> **Precondiciones técnicas:**
> - El dataspace debe haber sido creado lógicamente en el paso histórico 5.
> - Debe existir el fichero values-demo.yaml en `runtime/workdir/inesdata-deployment/dataspace/step-1/`.
> - Los servicios comunes (PostgreSQL) deben encontrarse operativos conforme al paso histórico 2.

Este script se ejecuta de forma no interactiva, idempotente y QA-safe y:
- verifica la disponibilidad real de PostgreSQL,
- ejecuta un reset controlado de la base de datos del dataspace,
- despliega el `registration-service` mediante Helm (`Step-1`),
- garantiza la existencia y alineación de `ConfigMap` y `Secret` usados por el Deployment,
- fuerza un reinicio controlado del servicio para asegurar la correcta aplicación de la configuración,
- garantiza la inicialización del esquema EDC requerido (`edc_participant`).
```bash
kubectl create namespace demo
python adapters/inesdata/dataspace/dataspace-deploy.py
```

### Verificación
```bash
kubectl get ns demo

kubectl get pods -n demo
```
**Ejemplo de salida esperada**
```text

$ kubectl create namespace demo
namespace/demo created

$ kubectl get ns demo
NAME   STATUS   AGE
demo   Active   10s

NAME                                         READY   STATUS    RESTARTS   AGE
demo-registration-service-xxxxxxxxxx-xxxxx   1/1     Running   0          1m
```
### Criterios de aceptación
- El namespace del dataspace (`demo`) existe y es accesible.
- El pod `demo-registration-service` se encuentra en estado `Running`.
- La base de datos del dataspace ha sido creada y asociada correctamente.
- El Deployment utiliza `ConfigMap` y `Secret` reales del clúster.
- El servicio queda listo para su uso en los pasos históricos posteriores (paso histórico 7 – conectores).

---

⬅️ [Paso anterior: paso histórico 5 – Creación lógica del Dataspace](../step-5/05_step_5_logical_dataspace.md)
➡️ [Siguiente paso: paso histórico 7 – Creación lógica del Conector](../step-7/07_step_7_logical_connector.md)
🏠 [Volver al README principal](../../README.md)
