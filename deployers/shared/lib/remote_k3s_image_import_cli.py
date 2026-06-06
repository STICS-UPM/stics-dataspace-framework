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
    )


def _run(args: list[str]) -> int:
    return subprocess.run(args, check=False).returncode


def import_archive(archive: str) -> int:
    target = _target_from_environment()
    if not target:
        print("K3S_REMOTE_IMPORT_HOST is not configured", file=sys.stderr)
        return 2

    remote_archive = target.remote_archive_path(archive)
    upload_status = _run(target.scp_upload_args(archive, remote_archive))
    if upload_status != 0:
        return upload_status

    if target.interactive_mode == INTERACTIVE_AUTO:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", help="Local Docker image archive")
    parser.add_argument("--archive", dest="archive_option", help="Local Docker image archive")
    parser.add_argument("--image", default="", help="Image reference, currently informational")
    args = parser.parse_args(argv)

    archive = args.archive_option or args.archive
    if not archive:
        parser.error("archive is required")

    return import_archive(archive)


if __name__ == "__main__":
    raise SystemExit(main())
