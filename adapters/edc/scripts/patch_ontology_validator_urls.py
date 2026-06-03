#!/usr/bin/env python3
"""Patch or restore JenaValidationService Ontology Hub URL mapping for EDC connector builds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deployers.shared.lib.components import (  # noqa: E402
    ontology_validator_patch_context_from_environ,
    ontology_validator_source_paths,
    patch_ontology_validator_source,
    restore_ontology_validator_sources,
    snapshot_ontology_validator_sources,
)


def _load_snapshot(snapshot_path: Path) -> dict[Path, str]:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return {Path(key): value for key, value in payload.items()}


def _write_snapshot(snapshot_path: Path, snapshots: dict[Path, str]) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {str(path): content for path, content in snapshots.items()}
    snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        default=str(REPO_ROOT),
        help="Repository root used to resolve JenaValidationService.java paths.",
    )
    parser.add_argument(
        "--targets",
        default="edc",
        help="Comma-separated adapter targets to patch (default: edc).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--patch", action="store_true", help="Apply external->internal URL patch.")
    group.add_argument("--restore", action="store_true", help="Restore sources from snapshot file.")
    parser.add_argument(
        "--snapshot-out",
        help="Write pre-patch file contents to this JSON path (used with --patch).",
    )
    parser.add_argument(
        "--snapshot",
        help="Snapshot JSON path to restore (used with --restore).",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    targets = tuple(part.strip() for part in args.targets.split(",") if part.strip())

    if args.restore:
        if not args.snapshot:
            print("Ontology validator restore skipped: --snapshot is required.", file=sys.stderr)
            return 1
        snapshot_path = Path(args.snapshot)
        if not snapshot_path.is_file():
            print(f"Ontology validator restore skipped: snapshot not found: {snapshot_path}")
            return 0
        restore_ontology_validator_sources(_load_snapshot(snapshot_path))
        return 0

    context = ontology_validator_patch_context_from_environ()
    if context is None:
        print(
            "Ontology validator URL patch skipped: "
            "PIONERA_ONTOLOGY_PATCH_DATASPACE is not set."
        )
        return 0

    source_paths = ontology_validator_source_paths(project_root, targets=targets)
    if not source_paths:
        print("Ontology validator URL patch skipped: JenaValidationService.java was not found.")
        return 0

    if args.snapshot_out:
        _write_snapshot(Path(args.snapshot_out), snapshot_ontology_validator_sources(source_paths))

    if not patch_ontology_validator_source(context, project_root, targets=targets):
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
