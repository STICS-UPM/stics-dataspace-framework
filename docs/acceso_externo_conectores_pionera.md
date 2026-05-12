# Acceso externo a los conectores del entorno PIONERA

**Documento técnico para el equipo**  
Fecha: 2026-04-25

---

## Situación actual

El entorno de validación está desplegado en una máquina virtual (VM) con una IP pública, representada aquí como `203.0.113.10`. Dentro de esa VM corre **Minikube**, que es un clúster Kubernetes local. Todos los servicios (conectores, Keycloak, MinIO, etc.) están dentro de Minikube en la red interna `192.168.49.2`.

El problema es que esa red interna **no es accesible desde fuera de la VM**. Los dominios que usan los servicios (`conn-citycouncil-pionera.example.org`, `auth.example.org`, etc.) deben resolverse en DNS hacia la IP pública de la VM.

### Diagrama del estado actual

```
[PC del usuario]                  [VM pública]               [Minikube interno]
     │                            203.0.113.10                192.168.49.2
     │                                  │                           │
     │  DNS: *.example.org              │                           │
     │  → NO RESUELVE ❌                │                           │
     │                                  │                           │
     │  Aunque resolviese:              │                           │
     │──────────:80 ───────────────────▶│  puerto 80 no expuesto ❌ │
     │                                  │                           │
     │  (Solo desde dentro de la VM):   │──────:80 ────────────────▶│ ✅ funciona
```

---

## Qué se necesita para que funcione

Son **dos cambios independientes**, uno técnico y uno administrativo.

---

### Cambio 1 — Abrir el tráfico en la VM (técnico, ~5 minutos)

La VM tiene IP forwarding activado (`ip_forward=1`) y tiene instalado el nginx ingress controller de Kubernetes. Solo falta una regla **iptables DNAT** que redirija el tráfico entrante del puerto 80 hacia Minikube:

```bash
sudo iptables -t nat -A PREROUTING -d 203.0.113.10 -p tcp --dport 80 -j DNAT --to-destination 192.168.49.2:80
sudo iptables -t nat -A POSTROUTING -d 192.168.49.2 -j MASQUERADE
```

**¿Por qué funciona sin tocar el Ingress de Kubernetes?**

El Ingress de Kubernetes (nginx ingress controller) ya está configurado correctamente con todos los hostnames. Cuando llega una petición HTTP, lee la cabecera `Host:` y la enruta al servicio correcto. La regla iptables solo hace que el tráfico llegue a él — el header `Host` se preserva intacto durante el DNAT.

```
[PC usuario]
  → petición HTTP a 203.0.113.10:80
    con cabecera: Host: conn-citycouncil-pionera.example.org

[VM - iptables DNAT]
  → redirige a 192.168.49.2:80
    cabecera Host se mantiene igual ✅

[Minikube - nginx ingress]
  → lee Host: conn-citycouncil-pionera.example.org
  → enruta al pod correcto ✅
```

Para que la regla **persista tras reinicios**, hay que guardarla:

```bash
sudo apt install iptables-persistent -y
sudo netfilter-persistent save
```

---

### Cambio 2 — Registro DNS wildcard (administrativo)

El DNS público del despliegue debe tener un registro raíz como este:

```
example.org    IN  A  203.0.113.10
```

Falta añadir un **único registro wildcard**:

```
*.example.org  IN  A  203.0.113.10
```

Esto resolvería automáticamente **todos** los subdominios:
- `conn-citycouncil-pionera.example.org → 203.0.113.10`
- `conn-company-pionera.example.org → 203.0.113.10`
- `auth.example.org → 203.0.113.10`
- `minio.example.org → 203.0.113.10`
- `registration-service-pionera.example.org → 203.0.113.10`
- (cualquier subdominio futuro también)

**Acción**: solicitar al administrador DNS del despliegue que añada el registro wildcard.

---

## Flujo completo con los dos cambios aplicados

```
[Browser en la red autorizada o VPN]

  1. Escribe: http://conn-citycouncil-pionera.example.org
  
  2. DNS resuelve: 203.0.113.10
     (gracias al wildcard *.example.org)

  3. Browser manda petición HTTP a 203.0.113.10:80
     con cabecera Host: conn-citycouncil-pionera.example.org

  4. VM recibe en :80, iptables redirige a 192.168.49.2:80
     (cabecera Host intacta)

  5. Nginx ingress de Minikube lee la cabecera Host
     → enruta al pod conn-citycouncil-pionera ✅

  6. Usuario ve la interfaz del conector ✅
```

---

## Servicios accesibles (URLs definitivas)

> Accesibles desde cualquier PC en la red autorizada o VPN, sin modificar `/etc/hosts`.

| URL | Servicio |
|-----|----------|
| `https://public.example.org/c/citycouncil/inesdata-connector-interface/` | Interfaz conector City Council |
| `https://public.example.org/c/company/inesdata-connector-interface/` | Interfaz conector Company |
| `https://public.example.org/auth/` | Keycloak (autenticación) |
| `https://public.example.org/auth/admin/pionera/console/` | Consola admin Keycloak |
| `https://public.example.org/s3-console/` | Consola MinIO (almacenamiento) |
| `https://public.example.org/rs-pionera/` | Servicio de registro del dataspace |

### Credenciales de acceso a los conectores

| Conector | Usuario | Contraseña |
|----------|---------|------------|
| City Council | leer de `deployers/<adapter>/deployments/.../credentials-*.json` local | no publicar |
| Company | leer de `deployers/<adapter>/deployments/.../credentials-*.json` local | no publicar |
| Keycloak admin | leer de `deployers/<adapter>/deployer.config` local | no publicar |

---

## Resumen de acciones

| # | Acción | Responsable | Tiempo estimado |
|---|--------|-------------|-----------------|
| 1 | Ejecutar reglas iptables en la VM y hacer persistentes | Administrador VM | 5 minutos |
| 2 | Solicitar al administrador DNS añadir `*.example.org IN A 203.0.113.10` usando los valores reales del despliegue | Equipo del despliegue | 5 min solicitud / días para respuesta |
| 3 | Verificar acceso desde un PC externo a la VM | Cualquiera del equipo | Tras propagación DNS (~24h) |

---

## Nota sobre soluciones alternativas evaluadas

| Solución | Viable | Motivo descarte |
|----------|--------|-----------------|
| SSH tunnel | ✅ pero manual | Requiere configuración en cada PC cliente |
| `/etc/hosts` en cada PC | ✅ pero manual | No escala a todos los usuarios |
| ngrok / Cloudflare Tunnel | ✅ | Cambia las URLs, no usa el dominio público propio |
| **iptables DNAT + DNS wildcard** | ✅ **RECOMENDADO** | Transparente para el usuario, URLs estables |
