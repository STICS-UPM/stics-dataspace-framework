# Paso Histórico 3 – Post-configuración de Vault y Deployer

> Nota: este documento forma parte del flujo manual histórico de INESData. No describe los niveles actuales del menú. Para
> operar la versión actual usa [Referencia del menú](../../33_menu_reference.md)
> y [Validación](../../37_validation.md).

### Propósito
Garantizar que Vault se encuentra correctamente inicializado y operativo, habilitando la gestión segura de secretos requerida por INESData, y generar la configuración necesaria para que el Deployer pueda interactuar de forma segura y controlada con los servicios comunes. Este paso histórico establece los artefactos y credenciales necesarios para habilitar la creación posterior de dataspaces y conectores durante la ejecución de la validación en A5.2.

### Ruta
```text
pionera-env/
```


> **Precondiciones técnicas:**
> Instalar Vault
```bash
wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg # Ingresar contraseña y confirmar
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list

sudo apt update && sudo apt install vault
```

### Inicialización de Vault (una sola vez)
> - Este paso solo es necesario si Vault no ha sido inicializado previamente en el entorno de pruebas.
> - La inicialización de Vault debe ejecutarse desde el directorio `runtime/workdir/inesdata-deployment/common`, ya que en esta ubicación se genera y gestiona el artefacto `runtime/workdir/inesdata-deployment/common/init-keys-vault.json`, utilizado posteriormente por los scripts de automatización.

1. Ingresar a la carpeta common:
```bash
cd runtime/workdir/inesdata-deployment/common
```
2. El siguiente comando genera el fichero init-keys-vault.json, que contiene las claves necesarias para el proceso de unseal y el acceso inicial a Vault.
```bash
kubectl exec -it common-srvs-vault-0 -n common-srvs -- \
  vault operator init -key-shares=1 -key-threshold=1 -format=json > init-keys-vault.json
```

### Ejecutar `post-common.py` (automatizado)
> **Precondición técnica:**
> Antes de ejecutar el comando automatizado, debe existir un túnel activo hacia Vault, ya que el script interactúa con Vault a través de la dirección local http://127.0.0.1:8200.
```bash
kubectl port-forward common-srvs-vault-0 -n common-srvs 8200:8200
```
Este script realiza de forma no interactiva e idempotente las siguientes acciones:
- Verifica que Vault está accesible.
- Ejecuta el unseal automático si procede.
- Verifica o habilita el Secrets Engine de tipo KV en la ruta secret.
- Genera o ajusta el fichero deployer.config a partir del estado real del clúster.

```bash
cd ../../../..

kubectl exec -it common-srvs-vault-0 -n common-srvs -- \
  vault operator unseal $(jq -r '.unseal_keys_hex[0]' runtime/workdir/inesdata-deployment/common/init-keys-vault.json)

python3 adapters/inesdata/normalize/post-common.py
```

### Verificación
```bash
kubectl exec -it common-srvs-vault-0 -n common-srvs -- vault status
```
**Ejemplo de salida esperada**
```text
$ kubectl exec -it common-srvs-vault-0 -n common-srvs -- vault status
Key             Value
---             -----
Seal Type       shamir
Initialized     true
Sealed          false
Total Shares    1
Threshold       1
Version         1.17.2
Build Date      2024-07-05T15:19:12Z
Storage Type    file
Cluster Name    vault-cluster-3b623214
Cluster ID      26b6afea-6c0f-0db0-0bfc-05ec1d95575d
HA Enabled      false
```
**Criterios de aceptación**
- Vault se encuentra correctamente inicializado y operativo:
  - `Initialized`: true
  - `Sealed`: false
- Existe el fichero `init-keys-vault.json` en la ruta esperada.
- El fichero deployer.config ha sido actualizado correctamente.

**Artefactos generados**
```text
runtime/workdir/inesdata-deployment/common/init-keys-vault.json
runtime/workdir/inesdata-deployment/deployer.config
```

---

⬅️ [Paso anterior: paso histórico 2 – Instalación base de INESData](../step-2/02_step_2_common_services.md)
➡️ [Siguiente paso: paso histórico 4 – Preparación del entorno Deployer](../step-4/04_step_4_deployer_environment.md)
🏠 [Volver al README principal](../../README.md)
