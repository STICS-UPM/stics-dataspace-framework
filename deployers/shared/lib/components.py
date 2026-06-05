from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ComponentContract:
    component: str
    supported_adapters: tuple[str, ...]
    deployable_adapters: tuple[str, ...]
    deployment_strategy: str
    validation_groups: tuple[str, ...]
    edc_required_connector_extensions: tuple[str, ...] = ()


_COMPONENT_ALIASES = {
    "ontology_hub": "ontology-hub",
    "ai_model_hub": "ai-model-hub",
    "semantic_virtualization": "semantic-virtualization",
    "semantic_virtualizer": "semantic-virtualization",
    "virtualizer": "semantic-virtualization",
}


EDC_EXTENSION_ASSET_FILTER = "com.pionera.assetfilter.filter.AssetFilterExtension"
EDC_EXTENSION_CONTRACT_SEQUENCE = "com.pionera.assetfilter.contracts.ContractSequenceExtension"
EDC_EXTENSION_INFERENCE = "com.pionera.assetfilter.infer.InferenceExtension"
EDC_EXTENSION_OBSERVABILITY = "com.pionera.assetfilter.observability.ObservabilityExtension"
EDC_EXTENSION_PROXY = "com.pionera.assetfilter.proxy.CustomProxyDataPlaneExtension"


COMPONENT_CONTRACTS: dict[str, ComponentContract] = {
    "ontology-hub": ComponentContract(
        component="ontology-hub",
        supported_adapters=("inesdata", "edc"),
        deployable_adapters=("inesdata", "edc"),
        deployment_strategy="shared-chart-active-adapter",
        validation_groups=("ontology-hub",),
        edc_required_connector_extensions=(
            EDC_EXTENSION_ASSET_FILTER,
            EDC_EXTENSION_OBSERVABILITY,
        ),
    ),
    "ai-model-hub": ComponentContract(
        component="ai-model-hub",
        supported_adapters=("inesdata", "edc"),
        deployable_adapters=("inesdata", "edc"),
        deployment_strategy="shared-chart-active-adapter",
        validation_groups=("ai-model-hub",),
        edc_required_connector_extensions=(
            EDC_EXTENSION_ASSET_FILTER,
            EDC_EXTENSION_INFERENCE,
            EDC_EXTENSION_OBSERVABILITY,
            EDC_EXTENSION_CONTRACT_SEQUENCE,
        ),
    ),
    "semantic-virtualization": ComponentContract(
        component="semantic-virtualization",
        supported_adapters=("inesdata", "edc"),
        deployable_adapters=("inesdata", "edc"),
        deployment_strategy="shared-chart-active-adapter",
        validation_groups=("semantic-virtualization",),
        edc_required_connector_extensions=(
            EDC_EXTENSION_CONTRACT_SEQUENCE,
            EDC_EXTENSION_PROXY,
            EDC_EXTENSION_OBSERVABILITY,
        ),
    ),
}

COMPONENT_VALIDATION_ORDER = (
    "ontology-hub",
    "ai-model-hub",
    "semantic-virtualization",
)


def component_values_file_candidates(chart_dir: str, ds_name: str, namespace: str) -> list[str]:
    return [
        f"{chart_dir}/values-{ds_name}.yaml",
        f"{chart_dir}/values-{namespace}.yaml",
        f"{chart_dir}/values.yaml",
    ]


def normalize_component_key(component: str | None) -> str:
    normalized = str(component or "").strip().lower().replace("_", "-")
    if not normalized:
        return ""
    return _COMPONENT_ALIASES.get(normalized, normalized)


def get_component_contract(component: str | None) -> ComponentContract | None:
    normalized = normalize_component_key(component)
    if not normalized:
        return None
    return COMPONENT_CONTRACTS.get(normalized)


def strip_url_scheme(host_or_url: str | None) -> str:
    value = str(host_or_url or "").strip().rstrip("/")
    if value.startswith("http://"):
        return value[len("http://"):]
    if value.startswith("https://"):
        return value[len("https://"):]
    return value


def _component_env_key(component: str | None) -> str:
    return normalize_component_key(component).upper().replace("-", "_")


def _component_env_keys(component: str | None) -> list[str]:
    normalized = normalize_component_key(component)
    primary = _component_env_key(normalized)
    keys = [primary] if primary else []
    if normalized == "semantic-virtualization-editor":
        keys.extend([
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR",
            "MAPPING_EDITOR",
        ])
    return list(dict.fromkeys(keys))


def _first_config_value(config: dict[str, Any], keys: list[str], suffixes: tuple[str, ...]) -> str:
    for key in keys:
        for suffix in suffixes:
            value = str(config.get(f"{key}{suffix}") or "").strip()
            if value:
                return value
    return ""


def _host_from_host_or_url(host_or_url: str | None) -> str:
    value = str(host_or_url or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value if "://" in value else f"http://{value}")
    return str(parsed.netloc or parsed.path.split("/", 1)[0]).strip()


def _path_from_host_or_url(host_or_url: str | None) -> str:
    value = str(host_or_url or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value if "://" in value else f"http://{value}")
    return _normalize_public_path(parsed.path)


def _normalize_public_path(path: str | None) -> str:
    value = str(path or "").strip()
    if not value or value == "/":
        return ""
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/")


def configured_component_public_path(
    component: str | None,
    deployer_config: dict[str, Any] | None,
) -> str:
    normalized = normalize_component_key(component)
    if not normalized:
        return ""

    config = dict(deployer_config or {})
    env_keys = _component_env_keys(normalized)
    explicit_path = _first_config_value(config, env_keys, ("_PUBLIC_PATH", "_PATH"))
    if explicit_path:
        return _normalize_public_path(explicit_path)

    explicit_url = _first_config_value(config, env_keys, ("_PUBLIC_URL", "_URL"))
    if explicit_url:
        return _path_from_host_or_url(explicit_url)

    if _component_public_base_url(normalized, config):
        return f"/{normalized}"

    return ""


def configured_component_public_url(
    component: str | None,
    deployer_config: dict[str, Any] | None,
    *,
    dataspace_name: str = "",
) -> str:
    normalized = normalize_component_key(component)
    if not normalized:
        return ""

    config = dict(deployer_config or {})
    env_keys = _component_env_keys(normalized)
    explicit_url = _first_config_value(config, env_keys, ("_PUBLIC_URL", "_URL"))
    if explicit_url:
        return explicit_url.rstrip("/")

    public_path = configured_component_public_path(normalized, config)
    public_base_url = _component_public_base_url(normalized, config)
    if public_base_url:
        return f"{public_base_url}{public_path}"

    host = configured_component_host(
        normalized,
        config,
        dataspace_name=dataspace_name,
    )
    if host and public_path:
        return f"{host}{public_path}"
    return ""


def normalize_url(raw_url: str | None, default_scheme: str = "http") -> str:
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"{default_scheme}://{value}"


def configured_component_host(
    component: str | None,
    deployer_config: dict[str, Any] | None,
    *,
    dataspace_name: str = "",
) -> str:
    normalized = normalize_component_key(component)
    if not normalized:
        return ""

    config = dict(deployer_config or {})
    env_keys = _component_env_keys(normalized)
    explicit = (
        _first_config_value(config, env_keys, ("_HOST", "_HOSTNAME", "_PUBLIC_URL", "_URL"))
        or _component_public_base_url(normalized, config)
    )
    explicit_host = _host_from_host_or_url(explicit)
    if explicit_host:
        return explicit_host

    if normalized in {"ontology-hub", "ai-model-hub", "semantic-virtualization"}:
        ds_domain = str(config.get("DS_DOMAIN_BASE") or "").strip()
        ds_name = str(dataspace_name or "").strip()
        if ds_domain and ds_name:
            return f"{normalized}-{ds_name}.{ds_domain}"

    return ""


def _component_public_base_url(normalized_component: str, config: dict[str, Any]) -> str:
    env_key = normalized_component.upper().replace("-", "_")
    return str(
        config.get(f"{env_key}_PUBLIC_BASE_URL")
        or config.get("COMPONENTS_PUBLIC_BASE_URL")
        or config.get("VM_SINGLE_PUBLIC_URL")
        or config.get("VM_SINGLE_HTTP_URL")
        or config.get("VM_COMMON_PUBLIC_URL")
        or ""
    ).strip().rstrip("/")


def infer_component_hostname(
    component: str | None,
    values: dict[str, Any] | None,
    deployer_config: dict[str, Any] | None,
    *,
    dataspace_name: str = "",
) -> str | None:
    normalized = normalize_component_key(component)
    if not normalized:
        return None

    configured_host = configured_component_host(
        normalized,
        deployer_config,
        dataspace_name=dataspace_name,
    )
    if configured_host:
        return configured_host

    payload = dict(values or {})
    ingress = payload.get("ingress") or {}
    if not bool(ingress.get("enabled")):
        return None

    host = str(ingress.get("host") or "").strip()
    if host:
        return host

    ds_name = str(dataspace_name or "").strip()
    ds_domain = str((deployer_config or {}).get("DS_DOMAIN_BASE") or "").strip()
    if ds_name and ds_domain:
        return f"{normalized}-{ds_name}.{ds_domain}"

    return None


def resolve_component_release_name(
    component: str | None,
    *,
    dataspace_name: str = "",
    registration_service_release_name: str = "",
    public_portal_release_name: str = "",
) -> str:
    normalized = normalize_component_key(component)
    ds_name = str(dataspace_name or "").strip()
    if not normalized:
        return ds_name
    if normalized == "registration-service" and registration_service_release_name:
        return str(registration_service_release_name).strip()
    if normalized == "public-portal":
        if public_portal_release_name:
            return str(public_portal_release_name).strip()
        if ds_name:
            return f"{ds_name}-dataspace-pp"
    if ds_name:
        return f"{ds_name}-{normalized}"
    return normalized


def configured_optional_components(config: dict[str, Any] | None) -> list[str]:
    raw = str((config or {}).get("COMPONENTS", "") or "").strip()
    if not raw:
        return []

    components: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        normalized = normalize_component_key(token)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        components.append(normalized)
    return components


def components_for_adapter(
    config: dict[str, Any] | None,
    adapter: str,
    *,
    deployable_only: bool = True,
) -> list[str]:
    adapter_name = str(adapter or "").strip().lower()
    resolved: list[str] = []
    for component in configured_optional_components(config):
        contract = get_component_contract(component)
        if contract is None:
            continue
        adapters = contract.deployable_adapters if deployable_only else contract.supported_adapters
        if adapter_name in adapters:
            resolved.append(component)
    return resolved


def component_validation_groups(components: list[str] | tuple[str, ...] | None) -> list[str]:
    groups: list[str] = []
    seen: set[str] = set()
    for component in list(components or []):
        contract = get_component_contract(component)
        if contract is None:
            continue
        for group in contract.validation_groups:
            if group in seen:
                continue
            seen.add(group)
            groups.append(group)
    ordered_groups = [group for group in COMPONENT_VALIDATION_ORDER if group in seen]
    ordered_groups.extend(group for group in groups if group not in COMPONENT_VALIDATION_ORDER)
    return ordered_groups


def required_connector_extensions_for_adapter(
    components: list[str] | tuple[str, ...] | None,
    adapter: str,
) -> list[str]:
    adapter_name = str(adapter or "").strip().lower()
    required: list[str] = []
    seen: set[str] = set()
    for component in list(components or []):
        contract = get_component_contract(component)
        if contract is None:
            continue
        extensions = contract.edc_required_connector_extensions if adapter_name == "edc" else ()
        for extension in extensions:
            if extension in seen:
                continue
            seen.add(extension)
            required.append(extension)
    return required


def summarize_components_for_adapter(config: dict[str, Any] | None, adapter: str) -> dict[str, list[str]]:
    adapter_name = str(adapter or "").strip().lower()
    configured = configured_optional_components(config)
    deployable: list[str] = []
    pending_support: list[str] = []
    unsupported: list[str] = []
    unknown: list[str] = []

    for component in configured:
        contract = get_component_contract(component)
        if contract is None:
            unknown.append(component)
            continue
        if adapter_name in contract.deployable_adapters:
            deployable.append(component)
            continue
        if adapter_name in contract.supported_adapters:
            pending_support.append(component)
            continue
        unsupported.append(component)

    return {
        "configured": configured,
        "deployable": deployable,
        "pending_support": pending_support,
        "unsupported": unsupported,
        "unknown": unknown,
    }


def build_component_preview(
    *,
    configured: list[str] | tuple[str, ...] | None,
    deployable: list[str] | tuple[str, ...] | None,
    pending_support: list[str] | tuple[str, ...] | None,
    unsupported: list[str] | tuple[str, ...] | None,
    unknown: list[str] | tuple[str, ...] | None,
    inferred_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    configured_values = [str(value or "").strip() for value in (configured or []) if str(value or "").strip()]
    deployable_values = [str(value or "").strip() for value in (deployable or []) if str(value or "").strip()]
    pending_values = [str(value or "").strip() for value in (pending_support or []) if str(value or "").strip()]
    unsupported_values = [str(value or "").strip() for value in (unsupported or []) if str(value or "").strip()]
    unknown_values = [str(value or "").strip() for value in (unknown or []) if str(value or "").strip()]
    urls = dict(inferred_urls or {})

    if not configured_values:
        return {
            "status": "not-applicable",
            "action": "skip",
            "components": [],
            "configured": [],
            "deployable": [],
            "pending_support": [],
            "unsupported": [],
            "unknown": [],
        }

    component_entries: list[dict[str, Any]] = []
    deployable_set = set(deployable_values)
    pending_set = set(pending_values)
    unsupported_set = set(unsupported_values)
    for component in configured_values:
        if component in deployable_set:
            component_status = "planned"
        elif component in pending_set:
            component_status = "pending-support"
        elif component in unsupported_set:
            component_status = "unsupported"
        else:
            component_status = "unknown"
        component_entries.append(
            {
                "name": component,
                "url": urls.get(component),
                "status": component_status,
            }
        )

    if deployable_values:
        status = "planned"
        action = "deploy_components"
    elif pending_values:
        status = "pending-support"
        action = "skip"
    elif unsupported_values or unknown_values:
        status = "unsupported"
        action = "skip"
    else:
        status = "not-applicable"
        action = "skip"

    return {
        "status": status,
        "action": action,
        "components": component_entries,
        "configured": configured_values,
        "deployable": deployable_values,
        "pending_support": pending_values,
        "unsupported": unsupported_values,
        "unknown": unknown_values,
    }


_ONTOLOGY_VALIDATOR_SOURCE_PARTS = (
    "adapters",
    "inesdata",
    "sources",
    "inesdata-connector",
    "extensions",
    "ontology-validator",
    "src",
    "main",
    "java",
    "org",
    "upm",
    "inesdata",
    "validator",
    "services",
    "impl",
    "JenaValidationService.java",
)

_EDC_ONTOLOGY_VALIDATOR_SOURCE_PARTS = (
    "adapters",
    "edc",
    "sources",
    "connector",
    "extensions",
    "edc-rdf-validator",
    "src",
    "main",
    "java",
    "org",
    "eclipse",
    "edc",
    "validation",
    "rdf",
    "services",
    "impl",
    "JenaValidationService.java",
)

_ONTOLOGY_VALIDATOR_SOURCE_PARTS_BY_TARGET = {
    "inesdata": _ONTOLOGY_VALIDATOR_SOURCE_PARTS,
    "edc": _EDC_ONTOLOGY_VALIDATOR_SOURCE_PARTS,
}


def _repo_root_candidates(project_root: str | Path | None) -> list[Path]:
    candidates: list[Path] = []
    if project_root:
        root = Path(project_root).resolve()
        candidates.extend([root, root.parent, root.parent.parent])
        if root.name == "inesdata" and root.parent.name == "deployers":
            candidates.insert(0, root.parent.parent)
    else:
        candidates.append(Path(__file__).resolve().parents[3])

    resolved: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        resolved.append(candidate)
    return resolved


def ontology_validator_source_paths(
    project_root: str | Path | None,
    *,
    targets: tuple[str, ...] = ("inesdata", "edc"),
) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        relative_parts = _ONTOLOGY_VALIDATOR_SOURCE_PARTS_BY_TARGET.get(target)
        if relative_parts is None:
            continue
        relative_path = Path(*relative_parts)
        for root in _repo_root_candidates(project_root):
            candidate = (root / relative_path).resolve()
            if candidate.exists() and candidate not in seen:
                seen.add(candidate)
                resolved.append(candidate)
    return resolved


def ontology_validator_source_path(project_root: str | Path | None) -> Path | None:
    paths = ontology_validator_source_paths(project_root)
    return paths[0] if paths else None


def snapshot_ontology_validator_sources(paths: list[Path]) -> dict[Path, str]:
    snapshots: dict[Path, str] = {}
    for path in paths:
        if path.exists():
            snapshots[path] = path.read_text(encoding="utf-8")
    return snapshots


def restore_ontology_validator_sources(snapshots: dict[Path, str]) -> None:
    for path, content in snapshots.items():
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current != content:
                path.write_text(content, encoding="utf-8", newline="\n")
                print(f"Ontology validator source restored: {path}")


def ontology_validator_url_mapping(context: Any) -> dict[str, str]:
    config = dict(getattr(context, "config", {}) or {})
    dataspace_name = str(
        getattr(context, "dataspace_name", "")
        or config.get("DS_1_NAME")
        or config.get("DATASPACE_NAME")
        or ""
    ).strip()
    if not dataspace_name:
        return {}

    external_host = configured_component_host(
        "ontology-hub",
        config,
        dataspace_name=dataspace_name,
    )
    if not external_host:
        return {}

    raw_url = str(
        config.get("ONTOLOGY_HUB_URL")
        or config.get("ONTOLOGY_HUB_HOST")
        or config.get("ONTOLOGY_HUB_HOSTNAME")
        or ""
    ).strip()
    protocol = "https" if raw_url.startswith("https://") else "http"
    namespace_roles = getattr(context, "namespace_roles", None)
    components_namespace = str(
        getattr(namespace_roles, "components_namespace", "")
        or config.get("COMPONENTS_NAMESPACE")
        or "components"
    ).strip() or "components"
    release_name = resolve_component_release_name("ontology-hub", dataspace_name=dataspace_name)

    internal_base_url = normalize_url(config.get("ONTOLOGY_HUB_INTERNAL_BASE_URL") or "")
    internal_url = (
        internal_base_url
        if internal_base_url
        else f"http://{release_name}.{components_namespace}.svc.cluster.local:3333"
    )

    return {
        "external_url": f"{protocol}://{external_host}",
        "internal_url": internal_url,
    }


def _patch_jena_validation_service_file(source_path: Path, mapping: dict[str, str]) -> bool:
    content = source_path.read_text(encoding="utf-8")
    pattern = r'(return\s+url\.replace\(")([^"]*)(",\s*")([^"]*)("\);)'

    def replace(match: re.Match[str]) -> str:
        return (
            f"{match.group(1)}{mapping['external_url']}"
            f"{match.group(3)}{mapping['internal_url']}{match.group(5)}"
        )

    updated, replacements = re.subn(pattern, replace, content, count=1)
    if replacements == 0:
        print(
            "Ontology validator URL patch skipped: expected url.replace(...) pattern was not found "
            f"in {source_path}."
        )
        return False

    if updated != content:
        source_path.write_text(updated, encoding="utf-8", newline="\n")
        print(
            "Ontology validator URL patch applied: "
            f"{mapping['external_url']} -> {mapping['internal_url']} ({source_path.name})"
        )
    else:
        print(
            "Ontology validator URL patch already up to date: "
            f"{mapping['external_url']} -> {mapping['internal_url']} ({source_path.name})"
        )
    return True


def patch_ontology_validator_source(
    context: Any,
    project_root: str | Path | None,
    *,
    targets: tuple[str, ...] = ("inesdata", "edc"),
) -> bool:
    mapping = ontology_validator_url_mapping(context)
    if not mapping:
        print("Ontology validator URL patch skipped: Ontology Hub endpoint could not be resolved.")
        return False

    source_paths = ontology_validator_source_paths(project_root, targets=targets)
    if not source_paths:
        print("Ontology validator URL patch skipped: JenaValidationService.java was not found.")
        return False

    patched_any = False
    for source_path in source_paths:
        if _patch_jena_validation_service_file(source_path, mapping):
            patched_any = True
    return patched_any


def ontology_validator_patch_context_from_environ() -> Any | None:
    import os
    from types import SimpleNamespace

    dataspace_name = str(os.environ.get("PIONERA_ONTOLOGY_PATCH_DATASPACE") or "").strip()
    if not dataspace_name:
        return None

    config = {
        "DS_DOMAIN_BASE": str(os.environ.get("PIONERA_ONTOLOGY_PATCH_DS_DOMAIN_BASE") or "").strip(),
        "COMPONENTS_NAMESPACE": str(
            os.environ.get("PIONERA_ONTOLOGY_PATCH_COMPONENTS_NAMESPACE") or ""
        ).strip(),
        "ONTOLOGY_HUB_URL": str(os.environ.get("PIONERA_ONTOLOGY_PATCH_ONTOLOGY_HUB_URL") or "").strip(),
        "ONTOLOGY_HUB_HOST": str(os.environ.get("PIONERA_ONTOLOGY_PATCH_ONTOLOGY_HUB_HOST") or "").strip(),
        "ONTOLOGY_HUB_HOSTNAME": str(
            os.environ.get("PIONERA_ONTOLOGY_PATCH_ONTOLOGY_HUB_HOSTNAME") or ""
        ).strip(),
    }
    components_namespace = config["COMPONENTS_NAMESPACE"] or "components"
    return SimpleNamespace(
        dataspace_name=dataspace_name,
        config=config,
        namespace_roles=SimpleNamespace(components_namespace=components_namespace),
    )
