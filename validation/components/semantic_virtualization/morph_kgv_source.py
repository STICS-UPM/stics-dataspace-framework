from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


COMPONENT_KEY = "semantic-virtualization"
SUITE_NAME = "morph-kgv-source"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MORPH_KGV_REPOSITORY = "https://github.com/ProyectoPIONERA/morph-kgv"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "adapters" / "inesdata" / "sources" / "morph-kgv"

REQUIRED_FILES = {
    "readme": "README.md",
    "pyproject": "pyproject.toml",
    "run_query_cli": "run_query.py",
    "endpoint_client": "query_endpoint.py",
    "package_init": "src/morph_kgc/__init__.py",
    "package_cli": "src/morph_kgc/__main__.py",
    "virt_store": "src/morph_kgc/sparql/virt_store.py",
    "sparql_endpoint": "src/morph_kgc/endpoint/sparql_endpoint.py",
    "csv_example_config": "examples/csv/config.ini",
}

README_CAPABILITY_MARKERS = {
    "install": "pip install .",
    "run_query": "run_query.py",
    "config": "config.ini",
    "serve": "morph-kgv serve config.ini",
    "sparql_endpoint": "http://localhost:8000/sparql",
}

PYPROJECT_MARKERS = {
    "console_script": "morph-kgv",
    "package_name": "morph_kgc",
    "rdflib": "rdflib",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "click": "click",
}


def resolve_morph_kgv_source_dir(source_dir: str | os.PathLike[str] | None = None) -> Path:
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


def _read_text(path: Path, limit: int = 30000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def validate_morph_kgv_source(source_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    resolved_source_dir = resolve_morph_kgv_source_dir(source_dir)
    assertions: list[str] = []
    required_files: dict[str, dict[str, Any]] = {}

    if not resolved_source_dir.is_dir():
        assertions.append(
            "morph-kgv source repository is not available locally. "
            f"Expected clone at {resolved_source_dir}. Run Level 5 for the INESData adapter to synchronize component sources."
        )
        return {
            "status": "failed",
            "assertions": assertions,
            "source_dir": str(resolved_source_dir),
            "repository": MORPH_KGV_REPOSITORY,
            "required_files": required_files,
        }

    for key, relative_path in REQUIRED_FILES.items():
        path = resolved_source_dir / relative_path
        required_files[key] = {
            "path": str(path),
            "present": path.is_file(),
        }
        if not path.is_file():
            assertions.append(f"morph-kgv source is missing required file: {relative_path}")

    readme_text = _read_text(resolved_source_dir / "README.md").lower()
    detected_readme_markers = sorted(
        key for key, marker in README_CAPABILITY_MARKERS.items() if marker.lower() in readme_text
    )
    missing_readme_markers = sorted(set(README_CAPABILITY_MARKERS) - set(detected_readme_markers))
    if missing_readme_markers:
        assertions.append(
            "morph-kgv README does not expose expected execution contract markers: "
            + ", ".join(missing_readme_markers)
        )

    pyproject_text = _read_text(resolved_source_dir / "pyproject.toml").lower()
    detected_pyproject_markers = sorted(
        key for key, marker in PYPROJECT_MARKERS.items() if marker.lower() in pyproject_text
    )
    missing_pyproject_markers = sorted(set(PYPROJECT_MARKERS) - set(detected_pyproject_markers))
    if missing_pyproject_markers:
        assertions.append(
            "morph-kgv pyproject.toml does not expose expected package or dependency markers: "
            + ", ".join(missing_pyproject_markers)
        )

    cli_text = _read_text(resolved_source_dir / "src" / "morph_kgc" / "__main__.py").lower()
    if "serve" not in cli_text or "/sparql" not in cli_text or "uvicorn.run" not in cli_text:
        assertions.append("morph-kgv package CLI does not expose the expected SPARQL serve contract")

    run_query_text = _read_text(resolved_source_dir / "run_query.py").lower()
    if "virtstore" not in run_query_text or "graph.query" not in run_query_text:
        assertions.append("morph-kgv run_query.py does not expose the expected VIRTStore query contract")

    example_configs = sorted(str(path.relative_to(resolved_source_dir)) for path in resolved_source_dir.glob("examples/*/config.ini"))
    if not example_configs:
        assertions.append("morph-kgv does not expose example config.ini files")

    commit = _git_output(resolved_source_dir, ["rev-parse", "HEAD"])
    remote = _git_output(resolved_source_dir, ["config", "--get", "remote.origin.url"])

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "source_dir": str(resolved_source_dir),
        "repository": MORPH_KGV_REPOSITORY,
        "remote": remote,
        "commit": commit,
        "required_files": required_files,
        "example_configs": example_configs,
        "capabilities": {
            "readme_markers": detected_readme_markers,
            "pyproject_markers": detected_pyproject_markers,
        },
        "secret_policy": "Environment files, database credentials and API keys are not read or persisted by this validation.",
        "execution_scope": (
            "Source readiness and execution-contract traceability for morph-kgv. "
            "Level 6 validates the repository contract without materializing external databases or requiring secrets."
        ),
    }


def run_morph_kgv_source_validation(
    experiment_dir: str | os.PathLike[str] | None = None,
    *,
    source_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    started_at = datetime.now()
    validation = validate_morph_kgv_source(source_dir)
    completed_at = datetime.now()
    if completed_at < started_at:
        completed_at = started_at

    case = {
        "test_case_id": "SV-MORPH-KGV-01",
        "description": "Validate morph-kgv source readiness and SPARQL endpoint contract",
        "type": "support",
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "virtualization_runtime_traceability",
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
            "The framework can trace Semantic Virtualization validation to morph-kgv as the runtime "
            "that exposes VIRTStore querying and the SPARQL endpoint contract."
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
        report_path = component_dir / "semantic_virtualization_morph_kgv_source.json"
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
        description="Validate morph-kgv source readiness for Semantic Virtualization",
    )
    parser.add_argument("--experiment-dir", help="Experiment directory where evidence artifacts will be written")
    parser.add_argument("--source-dir", default="", help=f"Local clone of {MORPH_KGV_REPOSITORY}")
    args = parser.parse_args()

    report = run_morph_kgv_source_validation(
        experiment_dir=args.experiment_dir,
        source_dir=args.source_dir or None,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
