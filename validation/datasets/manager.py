from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_SOURCE_ROOT = PROJECT_ROOT / "validation" / "datasets" / "sources"

CommandRunner = Callable[[list[str], Path | None], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class DatasetSource:
    key: str
    display_name: str
    repository: str
    directory_name: str
    components: tuple[str, ...]
    required_paths: tuple[str, ...] = ()
    legacy_dirs: tuple[Path, ...] = ()


DATASET_SOURCES: dict[str, DatasetSource] = {
    "flares-dataset": DatasetSource(
        key="flares-dataset",
        display_name="FLARES",
        repository="https://github.com/rsepulveda911112/Flares-dataset",
        directory_name="flares-dataset",
        components=("ai-model-hub",),
        required_paths=(
            "5w1h_subtask_2_trial.json",
            "5w1h_subtarea_2_test.json",
        ),
    ),
    "gtfs-bench": DatasetSource(
        key="gtfs-bench",
        display_name="GTFS-Madrid-Bench",
        repository="https://github.com/oeg-upm/gtfs-bench",
        directory_name="gtfs-bench",
        components=("ai-model-hub", "semantic-virtualization"),
        required_paths=(
            "README.md",
            "LICENSE",
            "mappings/gtfs-csv.rml.ttl",
            "ontology/gtfs.ttl",
            "queries/simple/q1.rq",
            "queries/q1.rq",
        ),
    ),
}


def _normalize_component(component: str | None) -> str:
    return str(component or "").strip().lower().replace("_", "-")


def _project_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except Exception:
        return str(path)


def dataset_source_dir(key: str, *, source_root: str | os.PathLike[str] | None = None) -> Path:
    spec = DATASET_SOURCES[key]
    root = Path(source_root or os.getenv("PIONERA_DATASET_SOURCE_ROOT") or DATASET_SOURCE_ROOT)
    return root / spec.directory_name


def dataset_source_candidates(
    key: str,
    *,
    source_root: str | os.PathLike[str] | None = None,
) -> list[Path]:
    spec = DATASET_SOURCES[key]
    candidates = [dataset_source_dir(key, source_root=source_root)]
    candidates.extend(spec.legacy_dirs)
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(candidate)
    return unique


def required_datasets_for_components(components: Iterable[str] | None) -> list[DatasetSource]:
    normalized_components = {_normalize_component(component) for component in list(components or [])}
    selected: list[DatasetSource] = []
    for spec in DATASET_SOURCES.values():
        if normalized_components.intersection(spec.components):
            selected.append(spec)
    return selected


def _run_command(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _git_output(path: Path, args: list[str], runner: CommandRunner | None = None) -> str:
    command = ["git", "-C", str(path), *args]
    try:
        result = (runner or _run_command)(command, None)
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _metadata_for_path(spec: DatasetSource, path: Path, runner: CommandRunner | None = None) -> dict[str, Any]:
    missing = [relative for relative in spec.required_paths if not (path / relative).is_file()]
    return {
        "key": spec.key,
        "name": spec.display_name,
        "repository": spec.repository,
        "path": str(path),
        "relative_path": _project_path(path),
        "commit": _git_output(path, ["rev-parse", "HEAD"], runner),
        "remote": _git_output(path, ["config", "--get", "remote.origin.url"], runner),
        "required_paths": list(spec.required_paths),
        "missing_required_paths": missing,
    }


def _clone_dataset(
    spec: DatasetSource,
    target_dir: Path,
    runner: CommandRunner | None = None,
) -> tuple[bool, str]:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "clone", "--depth", "1", spec.repository, str(target_dir)]
    try:
        result = (runner or _run_command)(command, None)
    except Exception as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "git clone failed").strip()
    return True, ""


def sync_dataset_source(
    spec: DatasetSource,
    *,
    source_root: str | os.PathLike[str] | None = None,
    strict: bool = False,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    canonical_dir = dataset_source_dir(spec.key, source_root=source_root)
    legacy_available = [path for path in spec.legacy_dirs if path.is_dir()]
    notes: list[str] = []

    if canonical_dir.is_dir():
        metadata = _metadata_for_path(spec, canonical_dir, runner)
        status = "passed" if not metadata["missing_required_paths"] else ("failed" if strict else "warning")
        if metadata["missing_required_paths"]:
            notes.append("Required dataset files are missing from the canonical clone.")
        return {
            **metadata,
            "status": status,
            "source_mode": "canonical",
            "cloned": False,
            "notes": notes,
        }

    if legacy_available:
        legacy_dir = legacy_available[0]
        metadata = _metadata_for_path(spec, legacy_dir, runner)
        status = "passed" if not metadata["missing_required_paths"] else ("failed" if strict else "warning")
        notes.append(
            "Using legacy dataset source location; future synchronizations use validation/datasets/sources/."
        )
        if metadata["missing_required_paths"]:
            notes.append("Required dataset files are missing from the legacy clone.")
        return {
            **metadata,
            "status": status,
            "source_mode": "legacy",
            "canonical_path": str(canonical_dir),
            "canonical_relative_path": _project_path(canonical_dir),
            "cloned": False,
            "notes": notes,
        }

    cloned, error = _clone_dataset(spec, canonical_dir, runner)
    if not cloned:
        status = "failed" if strict else "warning"
        return {
            "key": spec.key,
            "name": spec.display_name,
            "repository": spec.repository,
            "path": str(canonical_dir),
            "relative_path": _project_path(canonical_dir),
            "status": status,
            "source_mode": "missing",
            "cloned": False,
            "required_paths": list(spec.required_paths),
            "missing_required_paths": list(spec.required_paths),
            "error": error,
            "notes": ["Dataset repository could not be cloned during Level 5."],
        }

    metadata = _metadata_for_path(spec, canonical_dir, runner)
    status = "passed" if not metadata["missing_required_paths"] else ("failed" if strict else "warning")
    if metadata["missing_required_paths"]:
        notes.append("Dataset repository was cloned, but required validation files are missing.")
    return {
        **metadata,
        "status": status,
        "source_mode": "canonical",
        "cloned": True,
        "notes": notes,
    }


def sync_level5_dataset_sources(
    components: Iterable[str] | None,
    *,
    source_root: str | os.PathLike[str] | None = None,
    strict: bool = False,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    specs = required_datasets_for_components(components)
    if not specs:
        return {
            "status": "not-applicable",
            "datasets": [],
            "source_root": _project_path(Path(source_root or os.getenv("PIONERA_DATASET_SOURCE_ROOT") or DATASET_SOURCE_ROOT)),
        }

    datasets = [
        sync_dataset_source(spec, source_root=source_root, strict=strict, runner=runner)
        for spec in specs
    ]
    failed = [item for item in datasets if item.get("status") == "failed"]
    warnings = [item for item in datasets if item.get("status") == "warning"]
    if failed:
        status = "failed"
    elif warnings:
        status = "warning"
    else:
        status = "passed"
    return {
        "status": status,
        "strict": bool(strict),
        "source_root": _project_path(Path(source_root or os.getenv("PIONERA_DATASET_SOURCE_ROOT") or DATASET_SOURCE_ROOT)),
        "datasets": datasets,
    }
