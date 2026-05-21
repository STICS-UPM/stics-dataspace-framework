from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import XSD

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from validation.components.semantic_virtualization.automap_source import (
    AUTOMAP_REPOSITORY,
    resolve_automap_source_dir,
)


COMPONENT_KEY = "semantic-virtualization"
SUITE_NAME = "automap-deterministic-execution"
TEST_CASE_ID = "SV-AUTOMAP-02"
DEFAULT_FIXTURES_DIR = PROJECT_ROOT / "validation" / "components" / "semantic_virtualization" / "fixtures" / "automap"

EXPECTED_COLUMNS = ["stop_id", "stop_name", "lat", "lon"]
AUTOMAP_BASE = Namespace("https://pionera.example/automap/")
MOBILITY = Namespace("https://pionera.example/ontology/mobility#")


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


def _load_automap_module(source_dir: Path, relative_path: str, module_name: str):
    module_path = source_dir / relative_path
    if not module_path.is_file():
        raise FileNotFoundError(f"Automap module not found: {relative_path}")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Automap module: {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _materialize_mobility_fixture(csv_path: Path, output_path: Path) -> dict[str, Any]:
    graph = Graph()
    graph.bind("automap", AUTOMAP_BASE)
    graph.bind("mob", MOBILITY)

    row_count = 0
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            subject = URIRef(AUTOMAP_BASE[f"stop/{row['stop_id']}"])
            graph.add((subject, RDF.type, MOBILITY.Stop))
            graph.add((subject, MOBILITY.stopName, Literal(row["stop_name"])))
            graph.add((subject, MOBILITY.latitude, Literal(row["lat"], datatype=XSD.decimal)))
            graph.add((subject, MOBILITY.longitude, Literal(row["lon"], datatype=XSD.decimal)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="NTSerializer always uses UTF-8 encoding.*")
        graph.serialize(destination=str(output_path), format="nt")
    return {
        "rows": row_count,
        "triples": len(graph),
        "output_path": str(output_path),
    }


def _run_direct_ask_query(rdf_path: Path) -> dict[str, Any]:
    graph = Graph()
    graph.parse(rdf_path, format="nt")
    query = """
    ASK {
      <https://pionera.example/automap/stop/SOL> a <https://pionera.example/ontology/mobility#Stop> ;
        <https://pionera.example/ontology/mobility#stopName> "Sol" .
    }
    """
    return {
        "query": "ASK stop SOL has type Stop and label Sol",
        "passed": bool(graph.query(query)),
    }


def validate_automap_deterministic_execution(
    source_dir: str | os.PathLike[str] | None = None,
    *,
    fixtures_dir: str | os.PathLike[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    resolved_source_dir = resolve_automap_source_dir(source_dir)
    resolved_fixtures_dir = Path(fixtures_dir or DEFAULT_FIXTURES_DIR).resolve()
    resolved_output_dir = Path(output_dir or resolved_fixtures_dir).resolve()

    assertions: list[str] = []
    if not resolved_source_dir.is_dir():
        assertions.append(
            "Automap source repository is not available locally. "
            f"Expected clone at {resolved_source_dir}. Run Level 5 for the INESData adapter to synchronize component sources."
        )
    if not resolved_fixtures_dir.is_dir():
        assertions.append(f"Automap deterministic fixtures directory is missing: {resolved_fixtures_dir}")

    fixture_paths = {
        "csv": resolved_fixtures_dir / "mobility_stops.csv",
        "ontology": resolved_fixtures_dir / "mobility_ontology.ttl",
        "mapping": resolved_fixtures_dir / "mobility_mapping.yarrr.yml",
        "gold_kg": resolved_fixtures_dir / "mobility_gold.nt",
    }
    for label, path in fixture_paths.items():
        if not path.is_file():
            assertions.append(f"Automap deterministic fixture is missing: {label} ({path})")

    if assertions:
        return {
            "status": "failed",
            "assertions": assertions,
            "source_dir": str(resolved_source_dir),
            "repository": AUTOMAP_REPOSITORY,
            "fixtures_dir": str(resolved_fixtures_dir),
        }

    try:
        rml_tools = _load_automap_module(resolved_source_dir, "tools/rml_tools.py", "_pionera_automap_rml_tools")
        metrics_module = _load_automap_module(
            resolved_source_dir,
            "evaluation/metrics.py",
            "_pionera_automap_metrics",
        )
    except Exception as exc:
        assertions.append(f"Automap deterministic modules could not be loaded: {type(exc).__name__}: {exc}")
        return {
            "status": "failed",
            "assertions": assertions,
            "source_dir": str(resolved_source_dir),
            "repository": AUTOMAP_REPOSITORY,
            "fixtures_dir": str(resolved_fixtures_dir),
        }

    csv_path = fixture_paths["csv"]
    ontology_path = fixture_paths["ontology"]
    mapping_path = fixture_paths["mapping"]
    gold_kg_path = fixture_paths["gold_kg"]
    generated_kg_path = resolved_output_dir / "automap_generated_mobility.nt"

    schema_info = rml_tools.get_csv_schema(str(csv_path))
    columns = list(schema_info.get("columns") or [])
    if columns != EXPECTED_COLUMNS:
        assertions.append(f"Automap schema extraction returned unexpected columns: {columns}")
    if len(schema_info.get("sample") or []) != 3:
        assertions.append("Automap schema extraction should expose a 3-row sample")

    ontology_summary = rml_tools.get_ontology_subgraph(str(ontology_path), EXPECTED_COLUMNS)
    ontology_markers = ["Class: <https://pionera.example/ontology/mobility#Stop>", "stopName", "latitude", "longitude"]
    missing_ontology_markers = [marker for marker in ontology_markers if marker not in ontology_summary]
    if missing_ontology_markers:
        assertions.append("Automap ontology extraction missed expected markers: " + ", ".join(missing_ontology_markers))

    mapping_text = mapping_path.read_text(encoding="utf-8")
    try:
        mapping_data = yaml.safe_load(mapping_text)
    except yaml.YAMLError as exc:
        mapping_data = None
        assertions.append(f"Deterministic YARRRML fixture is not valid YAML: {exc}")
    if not isinstance(mapping_data, dict) or "mappings" not in mapping_data:
        assertions.append("Deterministic YARRRML fixture must contain a mappings block")

    materialization = _materialize_mobility_fixture(csv_path, generated_kg_path)
    if materialization["rows"] != 3:
        assertions.append(f"Expected 3 materialized fixture rows, got {materialization['rows']}")
    if materialization["triples"] != 12:
        assertions.append(f"Expected 12 materialized RDF triples, got {materialization['triples']}")

    pipeline_result = {
        "yarrrml_output": mapping_text,
        "rdf_output": str(generated_kg_path),
        "csv_path": str(csv_path),
        "retry_count": 0,
        "feedback": "Deterministic Automap execution baseline without LLM generation",
        "messages": [],
    }
    evaluation_metrics = metrics_module.evaluate(
        levels=[2, 3],
        pipeline_result=pipeline_result,
        gold_kg_path=str(gold_kg_path),
    )
    if evaluation_metrics.get("L2_skipped"):
        assertions.append(f"Automap gold KG comparison was skipped: {evaluation_metrics.get('L2_skip_reason')}")
    else:
        for metric_name in [
            "L2_norm_triple_precision",
            "L2_norm_triple_recall",
            "L2_norm_triple_f1",
            "L2_predicate_f1",
            "L2_class_f1",
        ]:
            if evaluation_metrics.get(metric_name) != 1.0:
                assertions.append(f"Expected {metric_name}=1.0, got {evaluation_metrics.get(metric_name)}")
    if evaluation_metrics.get("L3_skipped"):
        assertions.append(f"Automap column coverage was skipped: {evaluation_metrics.get('L3_skip_reason')}")
    elif evaluation_metrics.get("L3_columns_mapped_yarrrml") != len(EXPECTED_COLUMNS):
        assertions.append(
            "Automap YARRRML column coverage did not map all fixture columns: "
            + ", ".join(evaluation_metrics.get("L3_columns_missing_yarrrml") or [])
        )

    sparql_check = _run_direct_ask_query(generated_kg_path)
    if not sparql_check["passed"]:
        assertions.append("Direct SPARQL ASK validation over the generated KG did not pass")

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "source_dir": str(resolved_source_dir),
        "repository": AUTOMAP_REPOSITORY,
        "fixtures_dir": str(resolved_fixtures_dir),
        "generated_kg_path": str(generated_kg_path),
        "schema": {
            "columns": columns,
            "sample_size": len(schema_info.get("sample") or []),
        },
        "ontology": {
            "summary_excerpt": ontology_summary[:1200],
            "markers_checked": ontology_markers,
        },
        "mapping": {
            "path": str(mapping_path),
            "yaml_valid": isinstance(mapping_data, dict),
            "column_references_expected": EXPECTED_COLUMNS,
        },
        "materialization": materialization,
        "metrics": evaluation_metrics,
        "metric_interpretation": (
            "L3_column_coverage_by_yarrrml is the authoritative coverage metric for this fixture. "
            "L3_column_coverage_by_value is diagnostic and can be lower when an identifier column is used "
            "in the subject URI instead of as a literal object."
        ),
        "sparql": sparql_check,
        "execution_scope": (
            "Deterministic offline execution baseline for Automap schema extraction, ontology extraction, "
            "RDF materialization evidence and evaluation metrics. The LLM generation path is intentionally not "
            "executed in Level 6 because it requires model/runtime configuration and secrets outside the open-source baseline."
        ),
        "secret_policy": "No environment files, API keys or remote LLM endpoints are read by this validation.",
    }


def run_automap_deterministic_execution_validation(
    experiment_dir: str | os.PathLike[str] | None = None,
    *,
    source_dir: str | os.PathLike[str] | None = None,
    fixtures_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    started_at = datetime.now()
    component_dir = _component_dir(experiment_dir)
    output_dir = component_dir or Path(os.getcwd())
    validation = validate_automap_deterministic_execution(
        source_dir,
        fixtures_dir=fixtures_dir,
        output_dir=output_dir,
    )
    completed_at = datetime.now()
    if completed_at < started_at:
        completed_at = started_at

    case = {
        "test_case_id": TEST_CASE_ID,
        "description": "Execute a deterministic Automap mapping-generation evaluation baseline",
        "type": "functional",
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "mapping_generation_evaluation",
        "mapping_status": "mapped",
        "automation_mode": "offline_deterministic_execution",
        "execution_mode": "offline_fixture",
        "coverage_status": "automated",
        "linked_pt5_cases": ["PT5-VS-01", "PT5-VS-06", "PT5-VS-10"],
        "evaluation": {
            "status": validation["status"],
            "assertions": list(validation.get("assertions") or []),
        },
        "evidence": validation,
        "expected_result": (
            "Automap deterministic tooling can extract source schema and ontology context, produce "
            "traceable RDF evidence from a controlled mapping fixture and evaluate it against a gold KG."
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
        "test_cases": [case],
        "executed_cases": [case],
        "pt5_case_results": [case],
        "support_checks": [],
        "artifacts": {},
        "evidence_index": [],
    }

    if component_dir:
        report_path = component_dir / "semantic_virtualization_automap_execution.json"
        metrics_path = component_dir / "automap_metrics.json"
        _write_json(report_path, report)
        _write_json(metrics_path, validation.get("metrics") or {})
        report["artifacts"]["report_json"] = str(report_path)
        report["artifacts"]["metrics_json"] = str(metrics_path)
        if validation.get("generated_kg_path"):
            report["artifacts"]["generated_kg"] = validation["generated_kg_path"]
        report["evidence_index"] = [
            {
                "scope": "suite",
                "suite": SUITE_NAME,
                "artifact_name": "report_json",
                "path": str(report_path),
            },
            {
                "scope": "suite",
                "suite": SUITE_NAME,
                "artifact_name": "metrics_json",
                "path": str(metrics_path),
            },
        ]
        if validation.get("generated_kg_path"):
            report["evidence_index"].append(
                {
                    "scope": "case",
                    "suite": SUITE_NAME,
                    "test_case_id": TEST_CASE_ID,
                    "artifact_name": "generated_kg",
                    "path": validation["generated_kg_path"],
                }
            )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic Automap execution validation for Semantic Virtualization",
    )
    parser.add_argument("--experiment-dir", help="Experiment directory where evidence artifacts will be written")
    parser.add_argument("--source-dir", default="", help=f"Local clone of {AUTOMAP_REPOSITORY}")
    parser.add_argument("--fixtures-dir", default="", help="Automap deterministic fixture directory")
    args = parser.parse_args()

    report = run_automap_deterministic_execution_validation(
        experiment_dir=args.experiment_dir,
        source_dir=args.source_dir or None,
        fixtures_dir=args.fixtures_dir or None,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
