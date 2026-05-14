# Paso Histórico 4 – Preparación del entorno Deployer

> Nota: este documento forma parte del flujo manual histórico de INESData. No describe los niveles actuales del menú. Para
> operar la versión actual usa [Referencia del menú](../../33_menu_reference.md)
> y [Validación](../../37_validation.md).

### Propósito
Preparar un entorno de ejecución local, aislado y reproducible que permita al Deployer de INESData interactuar de forma controlada con los servicios comunes ya desplegados. Este paso histórico habilita la ejecución de operaciones lógicas sobre INESData (creación de dataspaces y generación de artefactos) sin modificar directamente la infraestructura Kubernetes, en el contexto de la validación definida en A5.2.

### Ruta
```text
runtime/workdir/inesdata-deployment/
```
### Preparación del entorno Python (una sola vez)
Este entorno virtual aísla el deployer de dependencias y evita interferencias con el sistema anfitrión.
```bash
sudo apt install python3.10-venv
python3.10 -m venv venv
source venv/bin/activate
cd runtime/workdir/inesdata-deployment/

pip install -r requirements.txt
```
### Precondiciones técnicas (túneles requeridos)
Durante la ejecución de este paso histórico (y de los pasos lógicos históricos posteriores), deben mantenerse activos los siguientes túneles hacia los servicios comunes:
```bash
kubectl port-forward common-srvs-postgresql-0 -n common-srvs 5432:5432 &
kubectl port-forward common-srvs-vault-0 -n common-srvs 8200:8200 &
kubectl port-forward common-srvs-keycloak-0 -n common-srvs 8080:8080 &
```
Estos túneles exponen interfaces locales necesarias para que el Deployer interactúe con los servicios comunes sin exponerlos fuera del clúster.

### Verificación
```bash
source venv/bin/activate
python3 deployer.py --help
```
**Ejemplo de salida esperada**
```bash
(venv) user@host:
Usage: deployer.py [OPTIONS] COMMAND [ARGS]...
...
```

**Criterios de aceptación**
- El entorno virtual Python está activo y funcional.
- El Deployer responde correctamente a comandos básicos (`--help`).
- Los túneles a los servicios comunes permanecen activos.
- El entorno queda listo para ejecutar operaciones lógicas de INESData en los pasos históricos posteriores.

---

⬅️ [Paso anterior: paso histórico 3 – Post-configuración de Vault y Deployer](../step-3/03_step_3_vault_deployer.md)
➡️ [Siguiente paso: paso histórico 5 – Creación lógica del Dataspace](../step-5/05_step_5_logical_dataspace.md)
🏠 [Volver al README principal](../../README.md)
