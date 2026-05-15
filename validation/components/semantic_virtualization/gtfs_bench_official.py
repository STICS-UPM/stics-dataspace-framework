from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from validation.datasets.manager import dataset_source_candidates, dataset_source_dir


COMPONENT_KEY = "semantic-virtualization"
SUITE_NAME = "gtfs-bench-official-source"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_SOURCE_DIR = dataset_source_dir("gtfs-bench")
DEFAULT_SOURCE_DIR = CANONICAL_SOURCE_DIR
GTFS_BENCH_REPOSITORY = "https://github.com/oeg-upm/gtfs-bench"
RML_LOGICAL_SOURCE = URIRef("http://semweb.mmlab.be/ns/rml#LogicalSource")
RML_SOURCE = URIRef("http://semweb.mmlab.be/ns/rml#source")
RR_TRIPLES_MAP = URIRef("http://www.w3.org/ns/r2rml#TriplesMap")


REQUIRED_FILES = {
    "readme": "README.md",
    "license": "LICENSE",
    "csv_mapping": "mappings/gtfs-csv.rml.ttl",
    "json_mapping": "mappings/gtfs-json.rml.ttl",
    "rdb_mapping": "mappings/gtfs-rdb.r2rml.ttl",
    "ontology": "ontology/gtfs.ttl",
    "simple_query_q1": "queries/simple/q1.rq",
    "full_query_q1": "queries/q1.rq",
}


EXPECTED_CSV_SOURCES = {
    "/data/AGENCY.csv",
    "/data/CALENDAR.csv",
    "/data/CALENDAR_DATES.csv",
    "/data/FEED_INFO.csv",
    "/data/FREQUENCIES.csv",
    "/data/ROUTES.csv",
    "/data/SHAPES.csv",
    "/data/STOPS.csv",
    "/data/STOP_TIMES.csv",
    "/data/TRIPS.csv",
}


def resolve_gtfs_bench_source_dir(source_dir: str | os.PathLike[str] | None = None) -> Path:
    if source_dir:
        return Path(source_dir).resolve()
    for candidate in dataset_source_candidates("gtfs-bench"):
        if candidate.is_dir():
            return candidate.resolve()
    return CANONICAL_SOURCE_DIR.resolve()


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


def _parse_turtle(path: Path) -> tuple[Graph | None, list[str]]:
    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception as exc:
        return None, [f"{path} is not valid Turtle/RDF: {exc}"]
    return graph, []


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


def _count_query_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return len(sorted(item for item in path.glob("*.rq") if item.is_file()))


def validate_gtfs_bench_official_source(
    source_dir: str | os.PathLike[str] | None = None,
    *,
    auto_clone: bool = False,
) -> dict[str, Any]:
    resolved_source_dir = resolve_gtfs_bench_source_dir(source_dir)
    assertions: list[str] = []
    required_paths: dict[str, str] = {}

    if not resolved_source_dir.is_dir():
        if auto_clone:
            resolved_source_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", GTFS_BENCH_REPOSITORY, str(resolved_source_dir)],
                    check=True,
                )
            except Exception as exc:
                assertions.append(f"Could not auto-clone GTFS-Madrid-Bench source repository: {exc}")
            else:
                return validate_gtfs_bench_official_source(resolved_source_dir, auto_clone=False)

        assertions.append(
            "GTFS-Madrid-Bench source repository is not available locally. "
            f"Expected clone at {resolved_source_dir}."
        )
        return {
            "status": "failed",
            "assertions": assertions,
            "source_dir": str(resolved_source_dir),
            "repository": GTFS_BENCH_REPOSITORY,
            "required_paths": required_paths,
        }

    missing = []
    for key, relative_path in REQUIRED_FILES.items():
        path = resolved_source_dir / relative_path
        required_paths[key] = str(path)
        if not path.is_file():
            missing.append(relative_path)
    if missing:
        assertions.append(f"GTFS-Madrid-Bench source is missing required files: {', '.join(missing)}")

    ontology_result: dict[str, Any] = {}
    ontology_path = resolved_source_dir / REQUIRED_FILES["ontology"]
    if ontology_path.is_file():
        ontology_graph, errors = _parse_turtle(ontology_path)
        assertions.extend(errors)
        ontology_result = {
            "path": str(ontology_path),
            "triple_count": len(ontology_graph) if ontology_graph is not None else 0,
        }
        if ontology_graph is not None and len(ontology_graph) == 0:
            assertions.append("GTFS ontology parsed but contains no triples")

    mapping_result: dict[str, Any] = {}
    mapping_path = resolved_source_dir / REQUIRED_FILES["csv_mapping"]
    if mapping_path.is_file():
        mapping_graph, errors = _parse_turtle(mapping_path)
        assertions.extend(errors)
        triples_map_count = 0
        source_values: set[str] = set()
        logical_source_count = 0
        if mapping_graph is not None:
            triples_map_count = len(list(mapping_graph.subjects(RDF.type, RR_TRIPLES_MAP)))
            logical_source_count = len(list(mapping_graph.subjects(RDF.type, RML_LOGICAL_SOURCE)))
            source_values = {str(value) for value in mapping_graph.objects(None, RML_SOURCE)}

        missing_sources = sorted(EXPECTED_CSV_SOURCES - source_values)
        if triples_map_count == 0:
            assertions.append("Official GTFS CSV mapping does not declare rr:TriplesMap resources")
        if logical_source_count == 0:
            assertions.append("Official GTFS CSV mapping does not declare RML logical sources")
        if missing_sources:
            assertions.append(f"Official GTFS CSV mapping is missing expected source references: {missing_sources}")

        mapping_result = {
            "path": str(mapping_path),
            "triples_map_count": triples_map_count,
            "logical_source_count": logical_source_count,
            "source_count": len(source_values),
            "expected_csv_sources": sorted(EXPECTED_CSV_SOURCES),
            "detected_sources": sorted(source_values),
        }

    simple_query_count = _count_query_files(resolved_source_dir / "queries" / "simple")
    full_query_count = _count_query_files(resolved_source_dir / "queries")
    if simple_query_count < 11:
        assertions.append(f"Expected at least 11 simple SPARQL queries, found {simple_query_count}")
    if full_query_count < 18:
        assertions.append(f"Expected at least 18 full SPARQL queries, found {full_query_count}")

    commit = _git_output(resolved_source_dir, ["rev-parse", "HEAD"])
    remote = _git_output(resolved_source_dir, ["config", "--get", "remote.origin.url"])

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "source_dir": str(resolved_source_dir),
        "repository": GTFS_BENCH_REPOSITORY,
        "remote": remote,
        "commit": commit,
        "license": "Apache-2.0",
        "required_paths": required_paths,
        "ontology": ontology_result,
        "csv_mapping": mapping_result,
        "queries": {
            "simple_query_count": simple_query_count,
            "full_query_count": full_query_count,
        },
        "execution_scope": (
            "Source readiness only. Dataset generation with the official Docker generator "
            "is kept as an explicit maintenance activity outside Level 6 because it requires network/Docker-style dependencies."
        ),
    }


def run_gtfs_bench_official_source_validation(
    experiment_dir: str | os.PathLike[str] | None = None,
    *,
    source_dir: str | os.PathLike[str] | None = None,
    auto_clone: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now()
    validation = validate_gtfs_bench_official_source(source_dir, auto_clone=auto_clone)
    completed_at = datetime.now()
    if completed_at < started_at:
        completed_at = started_at

    case = {
        "test_case_id": "SV-GTFS-BENCH-01",
        "description": "Validate local availability of official GTFS-Madrid-Bench resources",
        "type": "support",
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "official_dataset_traceability",
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
            "The framework can trace Semantic Virtualization validation to the official "
            "GTFS-Madrid-Bench repository resources before running heavier generated datasets."
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
        report_path = component_dir / "semantic_virtualization_gtfs_bench_official_source.json"
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
        description="Validate official GTFS-Madrid-Bench source readiness for Semantic Virtualization",
    )
    parser.add_argument("--experiment-dir", help="Experiment directory where evidence artifacts will be written")
    parser.add_argument("--source-dir", default="", help="Local clone of https://github.com/oeg-upm/gtfs-bench")
    parser.add_argument(
        "--auto-clone",
        action="store_true",
        help="Clone the official repository if the local source directory is missing",
    )
    args = parser.parse_args()

    report = run_gtfs_bench_official_source_validation(
        experiment_dir=args.experiment_dir,
        source_dir=args.source_dir or None,
        auto_clone=args.auto_clone,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
