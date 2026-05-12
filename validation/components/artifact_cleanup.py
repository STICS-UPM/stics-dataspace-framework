from pathlib import Path
from typing import Mapping


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def cleanup_empty_experiment_artifact_dirs(
    artifact_paths: Mapping[str, str],
    *,
    experiments_root: str | Path,
) -> None:
    """Remove empty artifact directories under experiments, deepest first."""
    root = Path(experiments_root).resolve()
    candidates: set[Path] = set()

    for key in ("output_dir", "html_report_dir", "blob_report_dir", "base_dir"):
        path = artifact_paths.get(key)
        if path:
            candidates.add(Path(path))

    base_dir = artifact_paths.get("base_dir")
    if base_dir:
        for parent in Path(base_dir).parents:
            if parent.resolve() == root:
                break
            candidates.add(parent)

    for path in sorted(candidates, key=lambda item: len(item.parts), reverse=True):
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved == root or not _is_relative_to(resolved, root):
            continue
        try:
            path.rmdir()
        except OSError:
            pass
