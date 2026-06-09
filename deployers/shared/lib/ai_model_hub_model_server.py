from __future__ import annotations

from urllib.parse import urlsplit

from deployers.shared.lib.components import public_path_ingress_annotations


DEFAULT_USE_CASES_SOURCE_REPOSITORY = "https://github.com/ProyectoPIONERA/AIModelHub-Use-Cases.git"


def parse_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def model_server_enabled(config: dict | None) -> bool:
    values = dict(config or {})
    flag = values.get("AI_MODEL_HUB_MODEL_SERVER_ENABLED")
    if flag is None:
        flag = values.get("LEVEL5_AI_MODEL_HUB_MODEL_SERVER_ENABLED")
    return parse_bool(flag, default=False)


def normalize_model_server_mode(mode) -> str:
    normalized = str(mode or "").strip().lower().replace("_", "-")
    aliases = {
        "": "mock",
        "fixture": "mock",
        "deterministic": "mock",
        "development-mock": "mock",
        "real": "use-cases",
        "usecases": "use-cases",
        "use-cases": "use-cases",
        "combined-real": "combined",
        "real-combined": "combined",
        "remote": "external",
    }
    return aliases.get(normalized, normalized)


def model_server_mode(config: dict | None) -> tuple[str, str]:
    values = dict(config or {})
    raw_mode = (
        values.get("AI_MODEL_HUB_MODEL_SERVER_MODE")
        or values.get("LEVEL5_AI_MODEL_HUB_MODEL_SERVER_MODE")
        or values.get("MODEL_SERVER_MODE")
        or "mock"
    )
    return normalize_model_server_mode(raw_mode), str(raw_mode)


def source_repository(config: dict | None) -> str:
    values = dict(config or {})
    explicit = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY")
        or values.get("AI_MODEL_HUB_USE_CASE_MODEL_SERVER_REPOSITORY")
        or values.get("AI_MODEL_HUB_REAL_MODEL_SERVER_REPOSITORY")
        or values.get("MODEL_SERVER_SOURCE_REPOSITORY")
        or ""
    ).strip()
    if explicit:
        return explicit
    mode, _raw_mode = model_server_mode(values)
    if mode in {"use-cases", "combined"}:
        return DEFAULT_USE_CASES_SOURCE_REPOSITORY
    return ""


def source_ref(config: dict | None) -> str:
    values = dict(config or {})
    return str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF")
        or values.get("MODEL_SERVER_SOURCE_REF")
        or ""
    ).strip()


def image_ref(config: dict | None) -> str:
    return str((config or {}).get("AI_MODEL_HUB_MODEL_SERVER_IMAGE") or "model-server:latest").strip()


def manifest_path(config: dict | None) -> str:
    values = dict(config or {})
    return str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH")
        or values.get("MODEL_SERVER_MANIFEST_PATH")
        or ""
    ).strip()


def readiness_path(config: dict | None, mode: str) -> str:
    values = dict(config or {})
    explicit = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH")
        or values.get("MODEL_SERVER_READINESS_PATH")
        or ""
    ).strip()
    if explicit:
        return explicit if explicit.startswith("/") else f"/{explicit}"
    if mode in {"use-cases", "combined"}:
        return "/models"
    return "/api/v1/health"


def service_url(namespace) -> str:
    resolved_namespace = str(namespace or "").strip() or "components"
    return f"http://model-server.{resolved_namespace}.svc.cluster.local:8080"


def container_port(config: dict | None) -> int:
    values = dict(config or {})
    raw_value = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT")
        or values.get("MODEL_SERVER_CONTAINER_PORT")
        or "8080"
    ).strip()
    try:
        port = int(raw_value)
    except ValueError:
        port = 8080
    return port if 1 <= port <= 65535 else 8080


def docker_base_image(config: dict | None) -> str:
    values = dict(config or {})
    return str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_DOCKER_BASE_IMAGE")
        or values.get("MODEL_SERVER_DOCKER_BASE_IMAGE")
        or "python:3.10-slim"
    ).strip()


def uvicorn_app(config: dict | None, mode: str) -> str:
    values = dict(config or {})
    explicit = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_UVICORN_APP")
        or values.get("MODEL_SERVER_UVICORN_APP")
        or ""
    ).strip()
    if explicit:
        return explicit
    return "combined_model_server.server:app" if mode == "combined" else "src.server:app"


def image_pull_policy(image_reference, config: dict | None) -> str:
    values = dict(config or {})
    explicit = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_IMAGE_PULL_POLICY")
        or values.get("MODEL_SERVER_IMAGE_PULL_POLICY")
        or ""
    ).strip()
    if explicit in {"Always", "IfNotPresent", "Never"}:
        return explicit
    normalized_image = str(image_reference or "").strip().lower()
    if normalized_image.endswith(":local") or normalized_image.endswith(":latest") or normalized_image.startswith("local/"):
        return "Never"
    return "IfNotPresent"


def copy_excludes(config: dict | None) -> list[str]:
    values = dict(config or {})
    raw_value = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_COPY_EXCLUDES")
        or values.get("MODEL_SERVER_COPY_EXCLUDES")
        or ""
    ).strip()
    excludes = [
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".venv",
        "venv",
        "node_modules",
    ]
    for token in raw_value.replace(";", ",").split(","):
        value = token.strip()
        if value and value not in excludes:
            excludes.append(value)
    return excludes


def connector_base_url(namespace, config: dict | None) -> str:
    values = dict(config or {})
    explicit = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL")
        or values.get("MODEL_SERVER_CONNECTOR_BASE_URL")
        or values.get("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL")
        or values.get("MODEL_SERVER_CONNECTOR_URL")
        or ""
    ).strip()
    if explicit:
        return explicit.rstrip("/")
    return service_url(namespace)


def public_url(config: dict | None) -> str:
    values = dict(config or {})
    explicit = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL")
        or values.get("MODEL_SERVER_PUBLIC_URL")
        or ""
    ).strip()
    if explicit:
        return explicit.rstrip("/")

    public_base = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL")
        or values.get("COMPONENTS_PUBLIC_BASE_URL")
        or ""
    ).strip().rstrip("/")
    if not public_base:
        return ""
    public_path = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH")
        or values.get("MODEL_SERVER_PUBLIC_PATH")
        or "/model-server"
    ).strip()
    if not public_path.startswith("/"):
        public_path = f"/{public_path}"
    return f"{public_base}{public_path.rstrip('/')}"


def public_ingress(namespace, config: dict | None, *, topology: str = "vm-distributed") -> dict | None:
    resolved_public_url = public_url(config)
    if not resolved_public_url:
        return None
    parsed = urlsplit(resolved_public_url if "://" in resolved_public_url else f"http://{resolved_public_url}")
    host = str(parsed.netloc or parsed.path.split("/", 1)[0]).strip()
    path = str(parsed.path or "").strip().rstrip("/")
    if not host or not path:
        return None

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": "model-server-public-path",
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "validation-environment",
                "app.kubernetes.io/part-of": str(topology or "vm-distributed").strip() or "vm-distributed",
                "app.kubernetes.io/component": "model-server",
            },
            "annotations": public_path_ingress_annotations(rewrite_enabled=True),
        },
        "spec": {
            "ingressClassName": "nginx",
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": f"{path}(/|$)(.*)",
                                "pathType": "ImplementationSpecific",
                                "backend": {
                                    "service": {
                                        "name": "model-server",
                                        "port": {"number": 8080},
                                    }
                                },
                            }
                        ]
                    },
                }
            ],
        },
    }


def generated_manifest(namespace, image_reference, mode: str, config: dict | None) -> str:
    resolved_container_port = container_port(config)
    resolved_readiness_path = readiness_path(config, mode)
    resolved_image_pull_policy = image_pull_policy(image_reference, config)
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: model-server
  namespace: {namespace}
  labels:
    app: model-server
    app.kubernetes.io/name: model-server
    app.kubernetes.io/component: ai-model-hub-model-server
    app.kubernetes.io/managed-by: validation-environment
    app.kubernetes.io/mode: {mode}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: model-server
  template:
    metadata:
      labels:
        app: model-server
        app.kubernetes.io/name: model-server
        app.kubernetes.io/component: ai-model-hub-model-server
        app.kubernetes.io/mode: {mode}
    spec:
      containers:
        - name: model-server
          image: {image_reference}
          imagePullPolicy: {resolved_image_pull_policy}
          ports:
            - name: http
              containerPort: {resolved_container_port}
          readinessProbe:
            httpGet:
              path: {resolved_readiness_path}
              port: http
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 24
          livenessProbe:
            httpGet:
              path: {resolved_readiness_path}
              port: http
            initialDelaySeconds: 30
            periodSeconds: 15
            timeoutSeconds: 3
            failureThreshold: 8
---
apiVersion: v1
kind: Service
metadata:
  name: model-server
  namespace: {namespace}
  labels:
    app: model-server
    app.kubernetes.io/name: model-server
    app.kubernetes.io/component: ai-model-hub-model-server
    app.kubernetes.io/managed-by: validation-environment
spec:
  selector:
    app: model-server
  ports:
    - name: http
      port: 8080
      targetPort: http
"""
