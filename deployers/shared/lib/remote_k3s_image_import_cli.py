#!/usr/bin/env python3
"""Import a locally saved image archive into a remote k3s runtime.

The shell build scripts use this helper when they build images on the operator
machine but the target Kubernetes runtime lives in a remote VM.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from remote_k3s_images import (
    DEFAULT_REMOTE_IMAGE_IMPORT_COMMAND,
    DEFAULT_REMOTE_IMAGE_IMPORT_DIR,
    INTERACTIVE_ALWAYS,
    INTERACTIVE_AUTO,
    INTERACTIVE_NEVER,
    RemoteK3sImageImportTarget,
    parse_bool,
    parse_interactive_mode,
)


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _remote_sudo_password() -> str:
    for name in ("K3S_REMOTE_IMPORT_SUDO_PASSWORD", "PIONERA_REMOTE_SUDO_PASSWORD", "PIONERA_SUDO_PASSWORD"):
        value = os.getenv(name)
        if value:
            return str(value)
    return ""


def _target_from_environment() -> RemoteK3sImageImportTarget | None:
    host = _env("K3S_REMOTE_IMPORT_HOST")
    if not host:
        return None

    interactive_mode = parse_interactive_mode(
        _env("K3S_REMOTE_IMPORT_INTERACTIVE"),
        default=INTERACTIVE_NEVER,
    )
    return RemoteK3sImageImportTarget(
        role=_env("K3S_REMOTE_IMPORT_ROLE", "common") or "common",
        host=host,
        user=_env("K3S_REMOTE_IMPORT_USER"),
        port=_env("K3S_REMOTE_IMPORT_PORT", "22") or "22",
        bastion_host=_env("K3S_REMOTE_IMPORT_BASTION_HOST"),
        bastion_user=_env("K3S_REMOTE_IMPORT_BASTION_USER"),
        bastion_port=_env("K3S_REMOTE_IMPORT_BASTION_PORT", "2222") or "2222",
        identity_file=_env("K3S_REMOTE_IMPORT_IDENTITY_FILE"),
        remote_dir=_env("K3S_REMOTE_IMPORT_DIR", DEFAULT_REMOTE_IMAGE_IMPORT_DIR)
        or DEFAULT_REMOTE_IMAGE_IMPORT_DIR,
        import_command=_env("K3S_IMAGE_IMPORT_COMMAND", DEFAULT_REMOTE_IMAGE_IMPORT_COMMAND)
        or DEFAULT_REMOTE_IMAGE_IMPORT_COMMAND,
        allocate_tty=parse_bool(
            _env("K3S_REMOTE_IMPORT_ALLOCATE_TTY"),
            default=interactive_mode == INTERACTIVE_ALWAYS,
        ),
        interactive=interactive_mode in {INTERACTIVE_ALWAYS, INTERACTIVE_AUTO},
        interactive_mode=interactive_mode,
        prune_imported_images=False,
        known_hosts_strategy=_env("K3S_REMOTE_IMPORT_KNOWN_HOSTS_STRATEGY"),
    )


def _run(args: list[str], *, input_text: str | None = None) -> int:
    return subprocess.run(args, input=input_text, text=input_text is not None, check=False).returncode


def _remote_image_present(target: RemoteK3sImageImportTarget, image_ref: str) -> bool:
    if not str(image_ref or "").strip():
        return True

    sudo_password = _remote_sudo_password()
    if sudo_password:
        return (
            _run(
                target.ssh_image_check_args(image_ref, sudo_stdin=True),
                input_text=f"{sudo_password}\n",
            )
            == 0
        )

    probe_status = _run(target.ssh_image_check_args(image_ref))
    if probe_status == 0:
        return True

    return False


def _import_archive_once(target: RemoteK3sImageImportTarget, archive: str) -> int:
    remote_archive = target.remote_archive_path(archive)
    upload_status = _run(target.scp_upload_args(archive, remote_archive))
    if upload_status != 0:
        return upload_status

    if target.interactive_mode == INTERACTIVE_AUTO:
        sudo_password = _remote_sudo_password()
        if sudo_password:
            print(
                "Remote k3s image import needs sudo password; using configured batch sudo secret.",
                flush=True,
            )
            return _run(
                target.ssh_import_args(remote_archive, sudo_stdin=True),
                input_text=f"{sudo_password}\n",
            )

        probe_status = _run(target.ssh_sudo_probe_args())
        if probe_status == 0:
            return _run(target.ssh_import_args(remote_archive))

        print(
            "Remote k3s image import needs sudo password; retrying with an interactive prompt.",
            flush=True,
        )
        return _run(target.ssh_import_args(remote_archive, interactive=True))

    return _run(
        target.ssh_import_args(
            remote_archive,
            interactive=target.interactive_mode == INTERACTIVE_ALWAYS,
        )
    )


def import_archive(archive: str, image_ref: str = "") -> int:
    target = _target_from_environment()
    if not target:
        print("K3S_REMOTE_IMPORT_HOST is not configured", file=sys.stderr)
        return 2

    max_attempts = 2 if str(image_ref or "").strip() else 1
    for attempt in range(1, max_attempts + 1):
        import_status = _import_archive_once(target, archive)
        if import_status != 0:
            return import_status
        if _remote_image_present(target, image_ref):
            return 0
        if attempt < max_attempts:
            print(
                f"Remote k3s image import did not expose '{image_ref}' in containerd; retrying once.",
                flush=True,
            )

    print(
        f"Remote k3s image import completed, but '{image_ref}' was not found in containerd.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", help="Local Docker image archive")
    parser.add_argument("--archive", dest="archive_option", help="Local Docker image archive")
    parser.add_argument("--image", default="", help="Image reference, currently informational")
    args = parser.parse_args(argv)

    archive = args.archive_option or args.archive
    if not archive:
        parser.error("archive is required")

    return import_archive(archive, image_ref=args.image)


if __name__ == "__main__":
    raise SystemExit(main())
