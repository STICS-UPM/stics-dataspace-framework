import os
from datetime import datetime
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlsplit, urlunsplit

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEPLOYER_CONFIG_PATH = PROJECT_ROOT / "deployers" / "inesdata" / "deployer.config"
CHART_DIR = PROJECT_ROOT / "deployers" / "shared" / "components" / "ontology-hub"
DEFAULT_UI_EXPECT_TIMEOUT_MS = 15000
DEFAULT_UI_ACTION_TIMEOUT_MS = 15000
DEFAULT_UI_NAVIGATION_TIMEOUT_MS = 30000
DEFAULT_UI_READY_TIMEOUT_MS = 30000
DEFAULT_UI_PREFLIGHT_TIMEOUT_SECONDS = 180


def _parse_key_value_file(file_path: Path) -> Dict[str, str]:
    if not file_path.exists():
        return {}

    values: Dict[str, str] = {}
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        separator = line.find("=")
        if separator <= 0:
            continue
        key = line[:separator].strip()
        value = line[separator + 1 :].strip()
        values[key] = value
    return values


def _env_int(environ: Mapping[str, str], key: str, default: int) -> int:
    raw_value = (environ.get(key) or "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _env_bool(environ: Mapping[str, str], key: str, default: bool) -> bool:
    raw_value = (environ.get(key) or "").strip().lower()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return default


def _read_secret_file(file_path: str) -> str:
    candidate = (file_path or "").strip()
    if not candidate:
        return ""

    try:
        return Path(candidate).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _resolve_runtime_value(
    environ: Mapping[str, str],
    deployer_config: Mapping[str, str],
    key: str,
    default: str,
) -> str:
    direct_env = (environ.get(key) or "").strip()
    if direct_env:
        return direct_env

    file_env = _read_secret_file(environ.get(f"{key}_FILE") or "")
    if file_env:
        return file_env

    direct_config = (deployer_config.get(key) or "").strip()
    if direct_config:
        return direct_config

    file_config = _read_secret_file(deployer_config.get(f"{key}_FILE") or "")
    if file_config:
        return file_config

    return default


def _load_yaml_file(file_path: Path) -> Dict[str, Any]:
    if not file_path.exists():
        return {}

    payload = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _chart_values_path(dataspace: str, environ: Mapping[str, str]) -> Path | None:
    explicit = (environ.get("ONTOLOGY_HUB_VALUES_FILE") or "").strip()
    if explicit:
        return Path(explicit)

    candidate = CHART_DIR / f"values-{dataspace}.yaml"
    if candidate.exists():
        return candidate

    fallback = CHART_DIR / "values.yaml"
    return fallback if fallback.exists() else None


def _load_chart_values(dataspace: str, environ: Mapping[str, str]) -> Dict[str, Any]:
    base_path = CHART_DIR / "values.yaml"
    base_values = _load_yaml_file(base_path)
    selected_path = _chart_values_path(dataspace, environ)
    if not selected_path:
        return base_values

    if selected_path.resolve() == base_path.resolve():
        return base_values

    return _deep_merge_dicts(base_values, _load_yaml_file(selected_path))


def _chart_validation_value(chart_values: Mapping[str, Any], *path_parts: str) -> str:
    current: Any = chart_values
    for part in path_parts:
        if not isinstance(current, Mapping):
            return ""
        current = current.get(part)

    if current is None:
        return ""
    return str(current).strip()


def _normalize_repository_uri(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return candidate.rstrip("/")

    path = parsed.path.rstrip("/")
    if parsed.netloc.lower() in {
        "github.com",
        "www.github.com",
        "gitlab.com",
        "www.gitlab.com",
    } and path.lower().endswith(".git"):
        path = path[:-4]

    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)).rstrip("/")


def _first_configured_value(
    environ: Mapping[str, str],
    deployer_config: Mapping[str, str],
    *keys: str,
) -> str:
    for key in keys:
        value = str(environ.get(key) or "").strip()
        if value:
            return value
        value = str(deployer_config.get(key) or "").strip()
        if value:
            return value
    return ""


def _resolve_release_name(
    environ: Mapping[str, str],
    deployer_config: Mapping[str, str],
    dataspace: str,
) -> str:
    explicit_release = _first_configured_value(
        environ,
        deployer_config,
        "ONTOLOGY_HUB_RELEASE_NAME",
    )
    if explicit_release:
        return explicit_release

    explicit_service = _first_configured_value(
        environ,
        deployer_config,
        "ONTOLOGY_HUB_SELF_HOST_SERVICE_NAME",
        "ONTOLOGY_HUB_SERVICE_NAME",
    )
    if explicit_service:
        return explicit_service

    component_dataspace = _first_configured_value(
        environ,
        deployer_config,
        "ONTOLOGY_HUB_COMPONENT_DATASPACE_NAME",
        "PIONERA_COMPONENT_DATASPACE_NAME",
        "COMPONENT_DATASPACE_NAME",
    )
    if component_dataspace:
        return f"{component_dataspace}-ontology-hub"

    component_dataspace = _shared_component_dataspace_name(environ, deployer_config, dataspace)
    if component_dataspace:
        return f"{component_dataspace}-ontology-hub"

    return f"{dataspace}-ontology-hub"


def _base_dataspace_name(dataspace: str) -> str:
    resolved = str(dataspace or "").strip()
    for suffix in ("-edc", "_edc"):
        if resolved.lower().endswith(suffix):
            return resolved[: -len(suffix)] or resolved
    return resolved


def _shared_component_dataspace_name(
    environ: Mapping[str, str],
    deployer_config: Mapping[str, str],
    dataspace: str,
) -> str:
    adapter = _first_configured_value(environ, deployer_config, "PIONERA_ADAPTER", "UI_ADAPTER").lower()
    if adapter != "edc":
        return ""

    scope = _first_configured_value(environ, deployer_config, "COMPONENTS_RELEASE_SCOPE").lower() or "auto"
    if scope in {"dataspace", "adapter", "per-adapter", "adapter-dataspace"}:
        return ""
    if scope in {"shared", "base", "common", "common-dataspace"}:
        return _base_dataspace_name(dataspace)

    raw_components = (
        _first_configured_value(environ, deployer_config, "COMPONENTS_SHARED_RELEASE_COMPONENTS")
        or "ontology-hub,ai-model-hub,semantic-virtualization"
    ).strip()
    lowered = raw_components.lower()
    if lowered in {"", "none", "false", "no", "0"}:
        return ""
    if lowered in {"*", "all"}:
        return _base_dataspace_name(dataspace)

    configured = {
        token.strip().lower().replace("_", "-")
        for token in raw_components.split(",")
        if token.strip()
    }
    if "ontology-hub" in configured:
        return _base_dataspace_name(dataspace)
    return ""


def resolve_ontology_hub_runtime(
    *,
    base_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    current_env = environ or os.environ
    deployer_config = _parse_key_value_file(DEPLOYER_CONFIG_PATH)

    dataspace = (current_env.get("UI_DATASPACE") or deployer_config.get("DS_1_NAME") or "demo").strip()
    chart_values = _load_chart_values(dataspace, current_env)
    ds_domain = (
        current_env.get("UI_DS_DOMAIN")
        or deployer_config.get("DS_DOMAIN_BASE")
        or "dev.ds.dataspaceunit.upm"
    ).strip()
    resolved_base_url = (
        base_url
        or current_env.get("ONTOLOGY_HUB_BASE_URL")
        or f"http://ontology-hub-{dataspace}.{ds_domain}"
    ).rstrip("/")

    explicit_creation_uri = (
        current_env.get("ONTOLOGY_HUB_CREATION_URI")
        or _chart_validation_value(chart_values, "validation", "ui", "creationUri")
        or ""
    ).strip()
    explicit_creation_repo = (
        current_env.get("ONTOLOGY_HUB_CREATION_REPOSITORY_URI")
        or _chart_validation_value(chart_values, "validation", "ui", "creationRepositoryUri")
        or ""
    ).strip()
    explicit_creation_prefix = (
        current_env.get("ONTOLOGY_HUB_CREATION_PREFIX")
        or _chart_validation_value(chart_values, "validation", "ui", "creationPrefix")
        or ""
    ).strip()
    explicit_version_creation_uri = (
        current_env.get("ONTOLOGY_HUB_VERSION_CREATION_URI")
        or _chart_validation_value(chart_values, "validation", "ui", "versionCreationUri")
        or ""
    ).strip()
    explicit_version_creation_namespace = (
        current_env.get("ONTOLOGY_HUB_VERSION_CREATION_NAMESPACE")
        or _chart_validation_value(chart_values, "validation", "ui", "versionCreationNamespace")
        or ""
    ).strip()

    runtime = {
        "dataspace": dataspace,
        "dsDomain": ds_domain,
        "baseUrl": resolved_base_url,
        "componentsNamespace": (
            current_env.get("ONTOLOGY_HUB_COMPONENTS_NAMESPACE")
            or deployer_config.get("COMPONENTS_NAMESPACE")
            or "components"
        ).strip(),
        "releaseName": _resolve_release_name(current_env, deployer_config, dataspace),
        "selfHostServiceName": _first_configured_value(
            current_env,
            deployer_config,
            "ONTOLOGY_HUB_SELF_HOST_SERVICE_NAME",
            "ONTOLOGY_HUB_SERVICE_NAME",
        ),
        "selfHostServiceNamespace": _first_configured_value(
            current_env,
            deployer_config,
            "ONTOLOGY_HUB_SELF_HOST_NAMESPACE",
            "ONTOLOGY_HUB_SERVICE_NAMESPACE",
            "COMPONENTS_NAMESPACE",
        ),
        "selfHostServicePort": _first_configured_value(
            current_env,
            deployer_config,
            "ONTOLOGY_HUB_SELF_HOST_SERVICE_PORT",
            "ONTOLOGY_HUB_SELF_HOST_PORT",
            "ONTOLOGY_HUB_SERVICE_PORT",
        ),
        "internalBaseUrl": (
            current_env.get("ONTOLOGY_HUB_INTERNAL_BASE_URL")
            or f"http://127.0.0.1:{_chart_validation_value(chart_values, 'service', 'port') or '3333'}"
        ).rstrip("/"),
        "adminEmail": _resolve_runtime_value(
            current_env,
            {
                "ONTOLOGY_HUB_ADMIN_EMAIL": _chart_validation_value(
                    chart_values,
                    "validation",
                    "ui",
                    "adminEmail",
                ),
                "ONTOLOGY_HUB_ADMIN_EMAIL_FILE": _chart_validation_value(
                    chart_values,
                    "validation",
                    "ui",
                    "adminEmailFile",
                ),
            },
            "ONTOLOGY_HUB_ADMIN_EMAIL",
            "admin@gmail.com",
        ),
        "adminPassword": _resolve_runtime_value(
            current_env,
            {
                "ONTOLOGY_HUB_ADMIN_PASSWORD": _chart_validation_value(
                    chart_values,
                    "validation",
                    "ui",
                    "adminPassword",
                ),
                "ONTOLOGY_HUB_ADMIN_PASSWORD_FILE": _chart_validation_value(
                    chart_values,
                    "validation",
                    "ui",
                    "adminPasswordFile",
                ),
            },
            "ONTOLOGY_HUB_ADMIN_PASSWORD",
            "admin1234",
        ),
        "expectedVocabularyPrefix": current_env.get("ONTOLOGY_HUB_EXPECTED_VOCAB") or "saref4grid",
        "expectedVocabularyTitle": current_env.get("ONTOLOGY_HUB_EXPECTED_TITLE") or "SAREF4GRID",
        "expectedSearchTerm": current_env.get("ONTOLOGY_HUB_EXPECTED_QUERY") or "Person",
        "expectedLabel": current_env.get("ONTOLOGY_HUB_EXPECTED_LABEL") or "Person",
        "expectedClassUri": current_env.get("ONTOLOGY_HUB_EXPECTED_CLASS_URI") or "http://schema.org/Person",
        "expectedSparqlResourceUri": (
            current_env.get("ONTOLOGY_HUB_EXPECTED_SPARQL_RESOURCE_URI")
            or _chart_validation_value(chart_values, "validation", "integration", "sparqlResourceUri")
            or explicit_creation_uri
            or "https://saref.etsi.org/saref4grid/v2.1.1/"
        ),
        "expectedClassPrefixedName": current_env.get("ONTOLOGY_HUB_EXPECTED_CLASS_PREFIXED_NAME")
        or "saref4grid:Person",
        "expectedPrimaryTag": current_env.get("ONTOLOGY_HUB_EXPECTED_PRIMARY_TAG") or "Services",
        "expectedSecondaryTag": current_env.get("ONTOLOGY_HUB_EXPECTED_SECONDARY_TAG") or "Environment",
        "previousVersionDate": current_env.get("ONTOLOGY_HUB_PREVIOUS_VERSION_DATE") or "2025-01-15",
        "latestVersionDate": current_env.get("ONTOLOGY_HUB_LATEST_VERSION_DATE") or "2026-03-22",
        "creationUri": explicit_creation_uri or "https://saref.etsi.org/saref4grid/v2.1.1/",
        "versionCreationUri": explicit_version_creation_uri or "https://saref.etsi.org/saref4city/v1.1.2/",
        "versionCreationNamespace": explicit_version_creation_namespace or "https://saref.etsi.org/saref4city/",
        "creationRepositoryUri": _normalize_repository_uri(explicit_creation_repo),
        "creationNamespace": current_env.get("ONTOLOGY_HUB_CREATION_NAMESPACE")
        or _chart_validation_value(chart_values, "validation", "ui", "creationNamespace")
        or "https://saref.etsi.org/saref4grid/",
        "creationPrefix": explicit_creation_prefix or "saref4grid",
        "creationTitle": current_env.get("ONTOLOGY_HUB_CREATION_TITLE")
        or _chart_validation_value(chart_values, "validation", "ui", "creationTitle")
        or "SAREF4GRID Vocabulary",
        "creationDescription": current_env.get("ONTOLOGY_HUB_CREATION_DESCRIPTION")
        or _chart_validation_value(chart_values, "validation", "ui", "creationDescription")
        or "Vocabulary created through the Ontology Hub Playwright validation flow.",
        "creationPrimaryLanguage": current_env.get("ONTOLOGY_HUB_CREATION_PRIMARY_LANGUAGE")
        or _chart_validation_value(chart_values, "validation", "ui", "creationPrimaryLanguage")
        or "en",
        "creationSecondaryLanguage": current_env.get("ONTOLOGY_HUB_CREATION_SECONDARY_LANGUAGE")
        or _chart_validation_value(chart_values, "validation", "ui", "creationSecondaryLanguage")
        or "es",
        "creationTag": current_env.get("ONTOLOGY_HUB_CREATION_TAG")
        or _chart_validation_value(chart_values, "validation", "ui", "creationTag")
        or "Services",
        "creationReview": current_env.get("ONTOLOGY_HUB_CREATION_REVIEW")
        or _chart_validation_value(chart_values, "validation", "ui", "creationReview")
        or "Validated through the Playwright ontology flow.",
        "listingSearchTerm": current_env.get("ONTOLOGY_HUB_LISTING_QUERY")
        or _chart_validation_value(chart_values, "validation", "ui", "listingSearchTerm")
        or "saref4grid",
        "uiWorkers": _env_int(current_env, "ONTOLOGY_HUB_UI_WORKERS", 1),
        "uiExpectTimeoutMs": _env_int(
            current_env,
            "ONTOLOGY_HUB_UI_EXPECT_TIMEOUT_MS",
            DEFAULT_UI_EXPECT_TIMEOUT_MS,
        ),
        "uiActionTimeoutMs": _env_int(
            current_env,
            "ONTOLOGY_HUB_UI_ACTION_TIMEOUT_MS",
            DEFAULT_UI_ACTION_TIMEOUT_MS,
        ),
        "uiNavigationTimeoutMs": _env_int(
            current_env,
            "ONTOLOGY_HUB_UI_NAVIGATION_TIMEOUT_MS",
            DEFAULT_UI_NAVIGATION_TIMEOUT_MS,
        ),
        "uiReadyTimeoutMs": _env_int(
            current_env,
            "ONTOLOGY_HUB_UI_READY_TIMEOUT_MS",
            DEFAULT_UI_READY_TIMEOUT_MS,
        ),
        "strictPreflight": _env_bool(current_env, "ONTOLOGY_HUB_UI_STRICT_PREFLIGHT", False),
        "prepareSparqlStore": _env_bool(current_env, "ONTOLOGY_HUB_PREPARE_SPARQL_STORE", True),
        "preflightTimeout": _env_int(
            current_env,
            "ONTOLOGY_HUB_UI_PREFLIGHT_TIMEOUT",
            DEFAULT_UI_PREFLIGHT_TIMEOUT_SECONDS,
        ),
    }

    if (
        not explicit_creation_uri
        and not explicit_creation_repo
        and not explicit_creation_prefix
        and runtime["creationPrefix"] == runtime["expectedVocabularyPrefix"]
    ):
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        runtime["creationPrefix"] = f"{runtime['expectedVocabularyPrefix']}-fw-{timestamp}"
        runtime["creationTitle"] = f"{runtime['creationTitle']} ({runtime['creationPrefix']})"
        runtime["creationUri"] = ""
        runtime["creationRepositoryUri"] = _normalize_repository_uri(
            "https://github.com/ProyectoPIONERA/Ontology-Development-Repository-Example.git"
        )

    return runtime
