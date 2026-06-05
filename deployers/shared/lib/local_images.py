from __future__ import annotations

from deployers.shared.lib.topology import LOCAL_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY


TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}

LEVEL4_DISABLED_VALUES = FALSE_VALUES | {"disabled", "disable"}
LEVEL4_AUTO_VALUES = TRUE_VALUES | {"auto", ""}
LEVEL4_REQUIRED_VALUES = {"required", "require", "strict"}


def parse_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return default


def default_level4_mode(topology: str) -> str:
    return "auto" if str(topology or "").strip() == LOCAL_TOPOLOGY else "disabled"


def is_known_level4_mode(value) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in (LEVEL4_DISABLED_VALUES | LEVEL4_AUTO_VALUES | LEVEL4_REQUIRED_VALUES)


def normalize_level4_mode(value, *, default: str = "auto") -> str:
    raw_value = str(value if value is not None else default).strip().lower()
    if raw_value in LEVEL4_DISABLED_VALUES:
        return "disabled"
    if raw_value in LEVEL4_AUTO_VALUES:
        return "auto"
    if raw_value in LEVEL4_REQUIRED_VALUES:
        return "required"
    return "auto"


def resolve_level4_policy(
    *,
    topology: str,
    mode: str,
    label: str,
    supported_topologies,
    vm_distributed_remote_import_configured: bool,
) -> dict:
    normalized_topology = str(topology or LOCAL_TOPOLOGY).strip() or LOCAL_TOPOLOGY
    normalized_mode = str(mode or "auto").strip().lower() or "auto"
    supported = set(supported_topologies or set())

    if normalized_topology in supported:
        return {
            "topology": normalized_topology,
            "mode": normalized_mode,
            "prepare_local_images": True,
            "allow_local_image_overrides": True,
            "message": "",
            "error": "",
        }

    if normalized_topology == VM_DISTRIBUTED_TOPOLOGY and vm_distributed_remote_import_configured:
        return {
            "topology": normalized_topology,
            "mode": normalized_mode,
            "prepare_local_images": True,
            "allow_local_image_overrides": True,
            "message": (
                f"Preparing {label} local images for vm-distributed through remote k3s image import."
            ),
            "error": "",
        }

    if normalized_mode == "required":
        supported_label = ", ".join(sorted(supported))
        return {
            "topology": normalized_topology,
            "mode": normalized_mode,
            "prepare_local_images": False,
            "allow_local_image_overrides": False,
            "message": "",
            "error": (
                f"{label} local image preparation mode 'required' is only supported in "
                f"topologies {supported_label}, or in vm-distributed when "
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT=true and VM_*_SSH_HOST are configured. "
                f"Configure pullable image references before running Level 4 on topology '{normalized_topology}' "
                "or enable the remote import path."
            ),
        }

    return {
        "topology": normalized_topology,
        "mode": normalized_mode,
        "prepare_local_images": False,
        "allow_local_image_overrides": False,
        "message": (
            f"Skipping {label} local image preparation for topology '{normalized_topology}'. "
            "Using chart-configured image references."
        ),
        "error": "",
    }


def default_level5_auto_build(topology: str) -> bool:
    return str(topology or "").strip() not in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}


def first_config_or_env(config: dict | None, environ: dict | None, *keys: str):
    values = dict(config or {})
    env = dict(environ or {})
    for key in keys:
        if values.get(key) is not None:
            return values.get(key)
    for key in keys:
        if env.get(key) is not None:
            return env.get(key)
    return None


def assume_level5_local_images_available(config: dict | None, environ: dict | None = None) -> bool:
    flag = first_config_or_env(
        config,
        environ,
        "LEVEL5_ASSUME_LOCAL_IMAGES_AVAILABLE",
        "LEVEL6_ASSUME_LOCAL_IMAGES_AVAILABLE",
    )
    return parse_bool(flag, default=False)


def level5_auto_build_enabled(config: dict | None, *, topology: str, environ: dict | None = None) -> bool:
    flag = first_config_or_env(
        config,
        environ,
        "LEVEL5_AUTO_BUILD_LOCAL_IMAGES",
        "LEVEL6_AUTO_BUILD_LOCAL_IMAGES",
    )
    return parse_bool(flag, default=default_level5_auto_build(topology))
