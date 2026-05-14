# Paso Histórico 9 -- Despliegue del Portal Público (infraestructura)

> Nota: este documento forma parte del flujo manual histórico de INESData. No describe los niveles actuales del menú. Para
> operar la versión actual usa [Referencia del menú](../../33_menu_reference.md)
> y [Validación](../../37_validation.md).

### Propósito

Desplegar el Portal Público del dataspace en Kubernetes como interfaz de acceso del dataspace dentro de INESData. Este paso histórico confirma que el Portal se integra correctamente con la base de datos, el Connector EDC y el sistema de autenticación (Keycloak), y que el despliegue es estable y reproducible conforme a A5.2.


### Ruta

``` text
pionera-env/
```

### Ejecutar `portal-create.py` (fase lógica)

> **Precondiciones técnicas:**
> - El dataspace y el connector deben estar desplegados y operativos.
> - Los servicios comunes (PostgreSQL, Vault y Keycloak) deben estar en ejecución.
> - El fichero values-demo.yaml debe existir en dataspace/step-2/.
> - El entorno Deployer debe estar configurado (paso histórico 4).
> - Abrir un túnel y mantenerlo activo durante la validación:
``` bash
minikube tunnel
```

Este script:
- verifica la existencia del connector activo
- normaliza automáticamente `values-demo.yaml`
- corrige la resolución FQDN hacia PostgreSQL
- elimina valores `CHANGEME`
- genera backup automático del fichero de configuración
- garantiza la existencia de un alias DNS `ExternalName` para PostgreSQL en el namespace `demo`.

``` text
python3 adapters/inesdata/portal/portal-create.py
```

### Ejecutar `portal-deploy.py` (automatización de despliegue)

Este script:
- ejecuta `helm upgrade --install` del chart del Portal
- espera de forma controlada la disponibilidad de pods
- detecta estados `CrashLoopBackOff`
- valida la correcta inicialización del backend
- genera evidencia técnica en `runtime/`

``` text
python3 adapters/inesdata/portal/portal-deploy.py
```

### Verificación

``` text
kubectl get pods -n demo

# Verificación por ingress:

# - Frontend
curl -I http://demo.dev.ds.inesdata.upm

# - Backend (panel administrativo)
curl -I http://backend-demo.dev.ds.inesdata.upm/admin


```

**Ejemplo de salida esperada**

``` text
NAME                                           READY   STATUS    RESTARTS   AGE
conn-oeg-demo-xxxxxxxxxx-xxxxx                  1/1     Running   0          5m
conn-oeg-demo-interface-xxxxxxxxxx-xxxxx        1/1     Running   0          5m
demo-public-portal-backend-xxxxxxxxxx-xxxxx     1/1     Running   0          2m
demo-public-portal-frontend-xxxxxxxxxx-xxxxx    1/1     Running   0          2m
demo-registration-service-xxxxxxxxxx-xxxxx      1/1     Running   0          1h

HTTP/1.1 200 OK
HTTP/1.1 200 OK

```

### Criterios de aceptación

-   El backend y el frontend del Portal se encuentran en estado Running.
-   El backend del Portal inicia correctamente y establece conexión con PostgreSQL.
-   La resolución DNS cross-namespace es operativa.
-   El despliegue Helm es reproducible.
-   El acceso HTTP responde con código `200 OK` en:
    - Frontend: http://demo.dev.ds.inesdata.upm
    - Backend: http://backend-demo.dev.ds.inesdata.upm/admin

> **Nota:**
> La configuración funcional del Portal (creación del usuario administrador y habilitación de permisos en Strapi) se aborda en el paso histórico 10.

---

⬅️ [Paso anterior: paso histórico 8 - Despliegue del Connector (infraestructura)](../step-8/08_step_8_connector_infrastructure.md) </br>
🏠 [Volver al README principal](../../README.md)
