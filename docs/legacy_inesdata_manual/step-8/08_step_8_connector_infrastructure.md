# Paso Histórico 8 – Despliegue del Connector (infraestructura)

> Nota: este documento forma parte del flujo manual histórico de INESData. No describe los niveles actuales del menú. Para
> operar la versión actual usa [Referencia del menú](../../33_menu_reference.md)
> y [Validación](../../37_validation.md).

### Propósito
Materializar en infraestructura Kubernetes el connector definido de forma lógica en el paso histórico 7 y permitir su ejecución operativa dentro del dataspace desplegado. Este paso histórico completa la integración instrumental de INESData en el ecosistema PIONERA y valida la interoperabilidad real entre servicios, la resolución DNS cross-namespace y la inicialización efectiva de recursos persistentes.

### Ruta
```text
pionera-env/
```

### Ejecutar `connector-deploy.py` (automatización)
> **Precondiciones técnicas:**
> - El dataspace debe encontrarse desplegado conforme al paso histórico 6.
> - El connector debe haber sido creado lógicamente en el paso histórico 7.
> - Debe existir el fichero `values-<connector>.yaml` normalizado.
> - Los servicios comunes (PostgreSQL, Vault, Keycloak) deben encontrarse operativos.
> - El entorno Deployer debe estar preparado conforme al paso histórico 4.

Este script:
- aplica un parche Helm-safe al chart del connector (resolviendo dependencias estructurales),
- normaliza los valores de configuración requeridos por Helm,
- corrige automáticamente la resolución DNS cross-namespace hacia PostgreSQL,
- despliega el connector mediante `helm upgrade --install`,
- verifica el estado inicial del despliegue y la correcta ejecución de los initContainers.

```text
python adapters/inesdata/connector/connector-deploy.py
```

### Verificación
```text
kubectl get pods -n demo
```

**Ejemplo de salida esperada**
```text
NAME                                         READY   STATUS    RESTARTS   AGE
conn-oeg-demo-xxxxxxxxxx-xxxxx               1/1     Running   0          1m
conn-oeg-demo-interface-xxxxxxxxxx-xxxxx     1/1     Running   0          1m
demo-registration-service-xxxxxxxxxx-xxxxx   1/1     Running   0          19h
```

### Criterios de aceptación
- El connector se encuentra desplegado y en estado Running.
- El `initContainer` del connector se ejecuta correctamente sin errores.
- La base de datos del connector ha sido inicializada.
- La resolución DNS cross-namespace (`*.svc`) es funcional.
- El connector queda operativo dentro del dataspace desplegado.

---

⬅️ [Paso anterior: paso histórico 7 - Creación del Connector (lógica)](../step-7/07_step_7_logical_connector.md) <br>
➡️ [Siguiente paso: paso histórico 9 - Despliegue del Portal Público](../step-9/09_step_9_public_portal.md) </br>
🏠 [Volver al README principal](../../README.md)
