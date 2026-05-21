from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


COMPONENT_KEY = "semantic-virtualization"
SUITE_NAME = "automap-source"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
AUTOMAP_REPOSITORY = "https://github.com/ProyectoPIONERA/automap"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "adapters" / "inesdata" / "sources" / "automap"

REQUIRED_FILES = {
    "readme": "README.md",
    "pyproject": "pyproject.toml",
    "entrypoint": "main.py",
    "langgraph": "langgraph.json",
    "dockerfile": "Dockerfile",
    "compose": "docker-compose.yml",
    "morph_kgc_patch": "scripts/patch_morph_kgc.sh",
    "workflow": "graph/workflow.py",
    "rml_tools": "tools/rml_tools.py",
    "evaluation_metrics": "evaluation/metrics.py",
}

REQUIRED_DIRECTORIES = {
    "agents": "agents",
    "config": "config",
    "data": "data",
    "evaluation": "evaluation",
    "graph": "graph",
    "tools": "tools",
}

README_CAPABILITY_MARKERS = {
    "langgraph": "langgraph",
    "rml": "rml",
    "yarrrml": "yarrrml",
    "morph_kgc": "morph-kgc",
    "sparql": "sparql",
    "shacl": "shacl",
    "evaluation": "evaluation",
}


def resolve_automap_source_dir(source_dir: str | os.PathLike[str] | None = None) -> Path:
    if source_dir:
        return Path(source_dir).resolve()
    return DEFAULT_SOURCE_DIR.resolve()


def _component_dir(experiment_dir: str | os.PathLike[str] | None) -> Path | None:
    if not experiment_dir:
        return None
    path = Path(experiment_dir) / "components" / COMPONENT_KEY / SUITE_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _git_output(source_dir: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_dir), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _read_text(path: Path, limit: int = 20000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def validate_automap_source(source_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    resolved_source_dir = resolve_automap_source_dir(source_dir)
    assertions: list[str] = []
    required_files: dict[str, dict[str, Any]] = {}
    required_directories: dict[str, dict[str, Any]] = {}

    if not resolved_source_dir.is_dir():
        assertions.append(
            "Automap source repository is not available locally. "
            f"Expected clone at {resolved_source_dir}. Run Level 5 for the INESData adapter to synchronize component sources."
        )
        return {
            "status": "failed",
            "assertions": assertions,
            "source_dir": str(resolved_source_dir),
            "repository": AUTOMAP_REPOSITORY,
            "required_files": required_files,
            "required_directories": required_directories,
        }

    for key, relative_path in REQUIRED_FILES.items():
        path = resolved_source_dir / relative_path
        required_files[key] = {
            "path": str(path),
            "present": path.is_file(),
        }
        if not path.is_file():
            assertions.append(f"Automap source is missing required file: {relative_path}")

    for key, relative_path in REQUIRED_DIRECTORIES.items():
        path = resolved_source_dir / relative_path
        py_files = sorted(item.name for item in path.glob("*.py")) if path.is_dir() else []
        required_directories[key] = {
            "path": str(path),
            "present": path.is_dir(),
            "python_file_count": len(py_files),
        }
        if not path.is_dir():
            assertions.append(f"Automap source is missing required directory: {relative_path}")

    readme_text = _read_text(resolved_source_dir / "README.md").lower()
    detected_capabilities = sorted(
        key for key, marker in README_CAPABILITY_MARKERS.items() if marker in readme_text
    )
    missing_capabilities = sorted(set(README_CAPABILITY_MARKERS) - set(detected_capabilities))
    if missing_capabilities:
        assertions.append(
            "Automap README does not expose expected mapping-generation capabilities: "
            + ", ".join(missing_capabilities)
        )

    pyproject_text = _read_text(resolved_source_dir / "pyproject.toml").lower()
    dependency_markers = sorted(
        marker
        for marker in ["langgraph", "morph-kgc", "rdflib", "pyshacl", "yatter"]
        if marker in pyproject_text
    )
    if "langgraph" not in dependency_markers:
        assertions.append("Automap pyproject.toml does not declare LangGraph-related dependencies")
    if "morph-kgc" not in dependency_markers:
        assertions.append("Automap pyproject.toml does not declare Morph-KGC-related dependencies")

    commit = _git_output(resolved_source_dir, ["rev-parse", "HEAD"])
    remote = _git_output(resolved_source_dir, ["config", "--get", "remote.origin.url"])

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "source_dir": str(resolved_source_dir),
        "repository": AUTOMAP_REPOSITORY,
        "remote": remote,
        "commit": commit,
        "required_files": required_files,
        "required_directories": required_directories,
        "capabilities": {
            "detected_from_readme": detected_capabilities,
            "dependency_markers": dependency_markers,
        },
        "secret_policy": "Environment files and API keys are not read or persisted by this validation.",
        "execution_scope": (
            "Source readiness and traceability only. Automap is included as mapping-generation tooling for "
            "Semantic Virtualization; it is not deployed as a Level 5 runtime service in the current baseline."
        ),
    }


def run_automap_source_validation(
    experiment_dir: str | os.PathLike[str] | None = None,
    *,
    source_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    started_at = datetime.now()
    validation = validate_automap_source(source_dir)
    completed_at = datetime.now()
    if completed_at < started_at:
        completed_at = started_at

    case = {
        "test_case_id": "SV-AUTOMAP-01",
        "description": "Validate local availability of Automap mapping-generation tooling",
        "type": "support",
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "mapping_generation_traceability",
        "mapping_status": "mapped",
        "automation_mode": "offline_source_readiness",
        "execution_mode": "offline_source_readiness",
        "coverage_status": "automated",
        "evaluation": {
            "status": validation["status"],
            "assertions": list(validation.get("assertions") or []),
        },
        "evidence": validation,
        "expected_result": (
            "The framework can trace Semantic Virtualization validation to the Automap repository "
            "as mapping-generation tooling without requiring LLM execution during Level 6."
        ),
    }
    summary = {
        "total": 1,
        "passed": 1 if validation["status"] == "passed" else 0,
        "failed": 1 if validation["status"] == "failed" else 0,
        "skipped": 0,
    }
    report = {
        "component": COMPONENT_KEY,
        "suite": SUITE_NAME,
        "status": validation["status"],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "summary": summary,
        "support_checks": [case],
        "test_cases": [case],
        "artifacts": {},
        "evidence_index": [],
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = component_dir / "semantic_virtualization_automap_source.json"
        report["artifacts"]["report_json"] = str(report_path)
        report["evidence_index"] = [
            {
                "scope": "suite",
                "suite": SUITE_NAME,
                "artifact_name": "report_json",
                "path": str(report_path),
            }
        ]
        _write_json(report_path, report)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Automap source readiness for Semantic Virtualization",
    )
    parser.add_argument("--experiment-dir", help="Experiment directory where evidence artifacts will be written")
    parser.add_argument("--source-dir", default="", help=f"Local clone of {AUTOMAP_REPOSITORY}")
    args = parser.parse_args()

    report = run_automap_source_validation(
        experiment_dir=args.experiment_dir,
        source_dir=args.source_dir or None,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
