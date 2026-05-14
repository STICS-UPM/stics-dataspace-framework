# Paso Histórico 0 – Prerrequisitos del sistema (manual)

> Nota: este documento forma parte del flujo manual histórico de INESData. No describe los niveles actuales del menú. Para
> operar la versión actual usa [Referencia del menú](../../33_menu_reference.md)
> y [Validación](../../37_validation.md).

> **Precondiciones técnicas:**
> - La ejecución de este flujo se realiza desde una terminal WSL.
> - El entorno de validación asume que Docker Desktop de Windows está configurado para utilizar el motor WSL 2. Otras opciones de configuración de Docker Desktop no son relevantes para la ejecución de este flujo.
> - Antes de reproducir este flujo, eliminar la carpeta `runtime` de la raíz, si existe.

### Propósito
Preparar el sistema anfitrión. No automatizado por diseño, ya que depende del entorno local.

### Instalación de herramientas (si aplica)

> Este bloque solo es necesario si las herramientas no están instaladas.
> En Windows 10 habilitar WSL:
>   1. Abrir PowerShell como administrador y ejecutar `wsl --install`.
>   2. Abrir CMD y ejecutar `wsl`
>   3. Instalar una distribución Ubuntu reciente. Ejemplo: wsl --install -d Ubuntu-22.04
>   4. Se puede elegir por defecto para evitar que arranque con la incluida en Docker. Ejemplo: `wsl --set-default Ubuntu-22.04`

**Minikube (Linux / WSL):**
```bash
curl -LO https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube && rm minikube-linux-amd64
```
**Helm (Linux / WSL):**
```bash
sudo snap install helm --classic
```

### Verificación
```bash
docker ps
kubectl --help
helm version
python3 --version
```

**Ejemplo de salida esperada**
```text
$ docker ps
CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES

$ kubectl --help
kubectl controls the Kubernetes cluster manager.
Find more information at: https://kubernetes.io/docs/reference/kubectl/

$ helm version
version.BuildInfo{Version:"v3.x.x", GitCommit:"...", GitTreeState:"clean", GoVersion:"go1.xx.x"}

$ python3 --version
Python 3.10.x
```

**Criterio de aceptación**
Todos los comandos responden sin error.

---

➡️ [Siguiente paso: paso histórico 1 – Creación del clúster Kubernetes local](../step-1/01_step_1_minikube.md)
🏠 [Volver al README principal](../../README.md)
