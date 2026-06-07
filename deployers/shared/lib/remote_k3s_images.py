from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import shlex
import socket


DEFAULT_REMOTE_IMAGE_IMPORT_COMMAND = "sudo -n k3s ctr -n k8s.io images import"
DEFAULT_REMOTE_IMAGE_IMPORT_DIR = "/tmp"
DEFAULT_REMOTE_IMAGE_PRUNE_KEEP = "2"
INTERACTIVE_AUTO = "auto"
INTERACTIVE_ALWAYS = "always"
INTERACTIVE_NEVER = "never"


def parse_bool(value, *, default=False) -> bool:
    if value is None:
        return bool(default)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "disabled", "disable"}:
        return False
    return bool(default)


def image_reference_candidates(image_ref: str) -> list[str]:
    raw_ref = str(image_ref or "").strip()
    if not raw_ref:
        return []

    candidates = [raw_ref]
    ref_name = raw_ref.split("@", 1)[0]
    first_segment = ref_name.split("/", 1)[0]
    if "/" not in ref_name:
        normalized = f"docker.io/library/{raw_ref}"
    elif "." in first_segment or ":" in first_segment or first_segment == "localhost":
        normalized = raw_ref
    else:
        normalized = f"docker.io/{raw_ref}"

    if normalized not in candidates:
        candidates.append(normalized)
    return candidates


@dataclass(frozen=True)
class RemoteK3sImageImportTarget:
    role: str
    host: str
    user: str = ""
    port: str = "22"
    bastion_host: str = ""
    bastion_user: str = ""
    bastion_port: str = "2222"
    identity_file: str = ""
    remote_dir: str = DEFAULT_REMOTE_IMAGE_IMPORT_DIR
    import_command: str = DEFAULT_REMOTE_IMAGE_IMPORT_COMMAND
    allocate_tty: bool = False
    interactive: bool = False
    interactive_mode: str = INTERACTIVE_NEVER
    prune_imported_images: bool = False
    prune_keep: str = DEFAULT_REMOTE_IMAGE_PRUNE_KEEP

    def is_configured(self) -> bool:
        return bool(self.host)

    @property
    def destination(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    @property
    def bastion_destination(self) -> str:
        if not self.bastion_host:
            return ""
        destination = f"{self.bastion_user}@{self.bastion_host}" if self.bastion_user else self.bastion_host
        if self.bastion_port:
            destination = f"{destination}:{self.bastion_port}"
        return destination

    @property
    def bastion_proxy_command(self) -> str:
        if not self.bastion_host or not self.identity_file:
            return ""
        args = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-i",
            self.identity_file,
        ]
        if self.bastion_port:
            args.extend(["-p", str(self.bastion_port)])
        args.extend(["-W", "%h:%p", self.bastion_destination.split(":", 1)[0]])
        return shell_join(args)

    def remote_archive_path(self, local_archive_path: str) -> str:
        filename = os.path.basename(str(local_archive_path or "").strip()) or "pionera-image.tar"
        return f"{self.remote_dir.rstrip('/')}/{filename}"

    def scp_upload_args(self, local_archive_path: str, remote_archive_path: str) -> list[str]:
        args = ["scp"]
        if self.identity_file:
            args.extend(["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-i", self.identity_file])
        if self.port:
            args.extend(["-P", str(self.port)])
        if self.bastion_proxy_command:
            args.extend(["-o", f"ProxyCommand={self.bastion_proxy_command}"])
        elif self.bastion_destination:
            args.extend(["-o", f"ProxyJump={self.bastion_destination}"])
        args.extend([local_archive_path, f"{self.destination}:{remote_archive_path}"])
        return args

    def interactive_import_command(self) -> str:
        return _interactive_sudo_import_command(self.import_command)

    def stdin_password_import_command(self) -> str:
        return _stdin_password_sudo_import_command(self.import_command)

    def allows_interactive_fallback(self) -> bool:
        return self.interactive_mode == INTERACTIVE_AUTO

    def ssh_import_args(
        self,
        remote_archive_path: str,
        *,
        interactive: bool = False,
        sudo_stdin: bool = False,
    ) -> list[str]:
        remote_archive_q = shlex.quote(remote_archive_path)
        if sudo_stdin:
            import_command = self.stdin_password_import_command()
        else:
            import_command = self.interactive_import_command() if interactive else self.import_command
        cleanup_command = f"{import_command} {remote_archive_q}; status=$?; rm -f {remote_archive_q}; exit $status"
        return self.ssh_command_args(cleanup_command, force_tty=interactive)

    def ssh_sudo_probe_args(self) -> list[str]:
        return self.ssh_command_args("sudo -n k3s ctr -n k8s.io images ls -q >/dev/null")

    def ssh_image_check_args(self, image_ref: str, *, sudo_stdin: bool = False) -> list[str]:
        candidates = image_reference_candidates(image_ref)
        if not candidates:
            return self.ssh_command_args("true")
        grep_args = " ".join(f"-e {shlex.quote(candidate)}" for candidate in candidates)
        check_pipeline = f"k3s ctr -n k8s.io images ls -q | grep -Fx {grep_args} >/dev/null"
        sudo_prefix = "sudo -S -p ''" if sudo_stdin else "sudo -n"
        return self.ssh_command_args(f"{sudo_prefix} sh -c {shlex.quote(check_pipeline)}")

    def ssh_command_args(self, command: str, *, force_tty: bool = False) -> list[str]:
        args = ["ssh"]
        if force_tty or self.allocate_tty:
            args.append("-tt")
        if self.identity_file:
            args.extend(["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-i", self.identity_file])
        if self.port:
            args.extend(["-p", str(self.port)])
        if self.bastion_proxy_command:
            args.extend(["-o", f"ProxyCommand={self.bastion_proxy_command}"])
        elif self.bastion_destination:
            args.extend(["-J", self.bastion_destination])
        remote_command = f"sh -c {shlex.quote(str(command or '').strip())}"
        args.extend([self.destination, remote_command])
        return args

    def shell_env(self) -> dict[str, str]:
        return {
            "K3S_REMOTE_IMPORT_HOST": self.host,
            "K3S_REMOTE_IMPORT_USER": self.user,
            "K3S_REMOTE_IMPORT_PORT": self.port,
            "K3S_REMOTE_IMPORT_BASTION_HOST": self.bastion_host,
            "K3S_REMOTE_IMPORT_BASTION_USER": self.bastion_user,
            "K3S_REMOTE_IMPORT_BASTION_PORT": self.bastion_port,
            "K3S_REMOTE_IMPORT_IDENTITY_FILE": self.identity_file,
            "K3S_REMOTE_IMPORT_DIR": self.remote_dir,
            "K3S_IMAGE_IMPORT_COMMAND": self.import_command,
            "K3S_REMOTE_IMPORT_ALLOCATE_TTY": "true" if self.allocate_tty else "false",
            "K3S_REMOTE_IMPORT_INTERACTIVE": self.interactive_mode,
            "K3S_REMOTE_PRUNE_IMPORTED_IMAGES": "true" if self.prune_imported_images else "false",
            "K3S_REMOTE_PRUNE_KEEP": self.prune_keep,
        }

    def render_shell_env_prefix(self) -> str:
        return " ".join(
            f"{key}={shlex.quote(str(value))}"
            for key, value in self.shell_env().items()
            if str(value or "").strip()
        )


def remote_k3s_image_import_enabled(config: dict | None) -> bool:
    values = dict(config or {})
    return parse_bool(values.get("VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT"), default=False)


def parse_interactive_mode(value, *, default=INTERACTIVE_NEVER) -> str:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"auto", "fallback", "if-needed", "if_needed", "prompt-if-needed", "prompt_if_needed"}:
        return INTERACTIVE_AUTO
    if normalized in {"1", "true", "yes", "y", "on", "enabled", "enable", "always", "interactive"}:
        return INTERACTIVE_ALWAYS
    if normalized in {"0", "false", "no", "n", "off", "disabled", "disable", "never", "none"}:
        return INTERACTIVE_NEVER
    return default


def _interactive_sudo_import_command(command: str) -> str:
    raw = str(command or "").strip()
    if not raw:
        return raw
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    if parts[:1] != ["sudo"] or "-n" not in parts:
        return raw
    cleaned = [parts[0]]
    removed_noninteractive_flag = False
    for part in parts[1:]:
        if not removed_noninteractive_flag and part == "-n":
            removed_noninteractive_flag = True
            continue
        cleaned.append(part)
        if not part.startswith("-"):
            cleaned.extend(parts[len(cleaned) + (1 if removed_noninteractive_flag else 0):])
            break
    else:
        parts = cleaned
        return shell_join(parts)
    parts = cleaned
    return shell_join(parts)


def _stdin_password_sudo_import_command(command: str) -> str:
    raw = str(command or "").strip()
    if not raw:
        return raw
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    if parts[:1] != ["sudo"]:
        return raw

    cleaned = ["sudo"]
    if "-S" not in parts[1:]:
        cleaned.append("-S")
    if "-p" not in parts[1:]:
        cleaned.extend(["-p", ""])
    removed_noninteractive_flag = False
    for part in parts[1:]:
        if not removed_noninteractive_flag and part == "-n":
            removed_noninteractive_flag = True
            continue
        cleaned.append(part)
    return shell_join(cleaned)


def remote_k3s_image_import_target(config: dict | None, role: str = "common") -> RemoteK3sImageImportTarget | None:
    values = dict(config or {})
    if not remote_k3s_image_import_enabled(values):
        return None

    normalized_role = str(role or "common").strip().lower() or "common"
    role_key = normalized_role.upper().replace("-", "_")
    fallback_ip = ""
    if normalized_role == "components":
        host = _first_config_value(
            values,
            "VM_COMPONENTS_SSH_HOST",
            "VM_COMMON_SSH_HOST",
            "VM_COMPONENTS_IP",
            "VM_COMMON_IP",
        )
        fallback_ip = _first_config_value(values, "VM_COMPONENTS_IP", "VM_COMMON_IP")
        user = _first_config_value(values, "VM_COMPONENTS_SSH_USER", "VM_COMMON_SSH_USER", "VM_SSH_USER")
        port = _first_config_value(values, "VM_COMPONENTS_SSH_PORT", "VM_COMMON_SSH_PORT") or "22"
    else:
        host = _first_config_value(values, f"VM_{role_key}_SSH_HOST", f"VM_{role_key}_IP")
        fallback_ip = _first_config_value(values, f"VM_{role_key}_IP")
        user = _first_config_value(values, f"VM_{role_key}_SSH_USER", "VM_SSH_USER")
        port = _first_config_value(values, f"VM_{role_key}_SSH_PORT") or "22"

    if not user:
        user = _first_config_value(values, "SSH_BASTION_USER")

    if not host:
        return None

    role_access_mode = _role_specific_config_value(values, normalized_role, "SSH_ACCESS_MODE")
    access_mode = str(role_access_mode or values.get("SSH_ACCESS_MODE") or "").strip().lower()
    if (
        not role_access_mode
        and _normalized_vm_distributed_execution_host(values) == "common-services"
        and _vm_distributed_common_vm_direct_ssh_enabled(values)
        and access_mode in {"", "bastion"}
    ):
        access_mode = "direct"
    if access_mode == "direct":
        host = _direct_access_host(host, fallback_ip)
    bastion_host = ""
    bastion_user = ""
    bastion_port = ""
    if access_mode == "bastion" or (not access_mode and str(values.get("SSH_BASTION_HOST") or "").strip()):
        bastion_host = _role_specific_config_value(
            values,
            normalized_role,
            "SSH_BASTION_HOST",
        ) or _first_config_value(values, "SSH_BASTION_HOST")
        bastion_user = _role_specific_config_value(
            values,
            normalized_role,
            "SSH_BASTION_USER",
        ) or _first_config_value(values, "SSH_BASTION_USER")
        bastion_port = (
            _role_specific_config_value(values, normalized_role, "SSH_BASTION_PORT")
            or _first_config_value(values, "SSH_BASTION_PORT")
            or "2222"
        )

    interactive_mode = parse_interactive_mode(values.get("VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE"))
    import_command = (
        _first_config_value(values, "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND", "K3S_IMAGE_IMPORT_COMMAND")
        or DEFAULT_REMOTE_IMAGE_IMPORT_COMMAND
    )
    if interactive_mode == INTERACTIVE_ALWAYS:
        import_command = _interactive_sudo_import_command(import_command)
    interactive = interactive_mode in {INTERACTIVE_ALWAYS, INTERACTIVE_AUTO}

    return RemoteK3sImageImportTarget(
        role=normalized_role,
        host=host,
        user=user,
        port=port,
        bastion_host=bastion_host,
        bastion_user=bastion_user,
        bastion_port=bastion_port,
        identity_file=_first_config_value(
            values,
            f"VM_{role_key}_SSH_IDENTITY_FILE",
            "VM_COMPONENTS_SSH_IDENTITY_FILE" if normalized_role == "components" else "",
            "VM_COMMON_SSH_IDENTITY_FILE" if normalized_role == "components" else "",
            "SSH_IDENTITY_FILE",
            "VM_DISTRIBUTED_SSH_IDENTITY_FILE",
        ),
        remote_dir=_first_config_value(values, "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR") or DEFAULT_REMOTE_IMAGE_IMPORT_DIR,
        import_command=import_command,
        allocate_tty=parse_bool(
            values.get("VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY"),
            default=interactive_mode == INTERACTIVE_ALWAYS,
        ),
        interactive=interactive,
        interactive_mode=interactive_mode,
        prune_imported_images=parse_bool(values.get("VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE"), default=False),
        prune_keep=(
            _first_config_value(
                values,
                "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP",
                "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP_COUNT",
            )
            or DEFAULT_REMOTE_IMAGE_PRUNE_KEEP
        ),
    )


def shell_join(args: list[str]) -> str:
    return " ".join(shlex.quote(str(arg)) for arg in args)


def _direct_access_host(host: str, fallback_ip: str = "") -> str:
    normalized_host = str(host or "").strip()
    normalized_fallback = str(fallback_ip or "").strip()
    if not normalized_host or not normalized_fallback or normalized_host == normalized_fallback:
        return normalized_host
    if _looks_like_ip_address(normalized_host):
        return normalized_host
    if _resolve_host_addresses(normalized_host):
        return normalized_host
    return normalized_fallback


def _normalized_vm_distributed_execution_host(values: dict) -> str:
    raw_value = str(values.get("VM_DISTRIBUTED_EXECUTION_HOST") or "external").strip().lower().replace("_", "-")
    aliases = {
        "local": "external",
        "operator": "external",
        "orchestrator": "external",
        "common": "common-services",
        "common-vm": "common-services",
        "common-services-vm": "common-services",
        "detect": "auto",
        "detected": "auto",
    }
    normalized = aliases.get(raw_value, raw_value)
    if normalized == "auto":
        return "common-services" if _vm_distributed_running_on_common_services(values) else "external"
    return normalized


def _vm_distributed_common_vm_direct_ssh_enabled(values: dict) -> bool:
    return parse_bool(values.get("VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH"), default=True)


def _vm_distributed_running_on_common_services(values: dict) -> bool:
    target_values = {
        _first_config_value(values, "VM_COMMON_IP"),
        _first_config_value(values, "VM_COMMON_SSH_HOST"),
        _first_config_value(values, "VM_EXTERNAL_IP"),
    }
    target_values = {str(value or "").strip() for value in target_values if str(value or "").strip()}
    if not target_values:
        return False

    aliases = _local_host_aliases()
    if any(value.lower() in aliases for value in target_values):
        return True

    local_addresses = _local_host_addresses()
    explicit_target_addresses = {value for value in target_values if _looks_like_ip_address(value)}
    if explicit_target_addresses:
        return bool(local_addresses.intersection(explicit_target_addresses))

    target_addresses = set()
    for value in target_values:
        target_addresses.update(_resolve_host_addresses(value))
    return bool(local_addresses.intersection(target_addresses))


def _local_host_aliases() -> set[str]:
    aliases = {"localhost", "127.0.0.1"}
    for value in (socket.gethostname(), socket.getfqdn()):
        normalized = str(value or "").strip().lower()
        if normalized:
            aliases.add(normalized)
            aliases.add(normalized.split(".", 1)[0])
    return {alias for alias in aliases if alias}


def _local_host_addresses() -> set[str]:
    addresses = {"127.0.0.1", "::1"}
    for host in _local_host_aliases():
        addresses.update(_resolve_host_addresses(host))
    return addresses


def _resolve_host_addresses(host: str) -> set[str]:
    normalized = str(host or "").strip()
    if not normalized:
        return set()
    if _looks_like_ip_address(normalized):
        return {normalized}

    addresses = set()
    try:
        for item in socket.getaddrinfo(normalized, None):
            address = item[4][0]
            if address:
                addresses.add(address)
    except OSError:
        return set()
    return addresses


def _looks_like_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return True


def _role_specific_config_value(values: dict, role: str, suffix: str) -> str:
    normalized_role = str(role or "").strip().upper().replace("-", "_")
    suffix = str(suffix or "").strip().upper()
    if not normalized_role or not suffix:
        return ""
    keys = []
    if normalized_role == "COMPONENTS":
        keys.extend([f"VM_COMPONENTS_{suffix}", f"VM_COMMON_{suffix}"])
    else:
        keys.append(f"VM_{normalized_role}_{suffix}")
    return _first_config_value(values, *keys)


def _first_config_value(values: dict, *keys: str) -> str:
    for key in keys:
        value = str(values.get(key) or "").strip()
        if value:
            return value
    return ""
