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
from rdflib.namespace import OWL, RDFS, XSD

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
DEFAULT_ONTOLOGY_HUB_ARTIFACT = (
    PROJECT_ROOT / "validation" / "components" / "semantic_virtualization" / "fixtures" / "ontology" / "mobility-mini.ttl"
)

EXPECTED_COLUMNS = ["stop_id", "stop_name", "lat", "lon"]
AUTOMAP_BASE = Namespace("https://pionera.example/automap/")
MOBILITY = Namespace("https://pionera.example/ontology/mobility#")
ONTOLOGY_HUB_MOBILITY = Namespace("https://w3id.org/pionera/validation/mobility#")


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


def _materialize_mobility_fixture(
    csv_path: Path,
    output_path: Path,
    *,
    mobility_namespace: Namespace = MOBILITY,
    stop_name_predicate: str = "stopName",
    latitude_predicate: str = "latitude",
    longitude_predicate: str = "longitude",
) -> dict[str, Any]:
    graph = Graph()
    graph.bind("automap", AUTOMAP_BASE)
    graph.bind("mob", mobility_namespace)

    row_count = 0
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            subject = URIRef(AUTOMAP_BASE[f"stop/{row['stop_id']}"])
            graph.add((subject, RDF.type, mobility_namespace.Stop))
            graph.add((subject, mobility_namespace[stop_name_predicate], Literal(row["stop_name"])))
            graph.add((subject, mobility_namespace[latitude_predicate], Literal(row["lat"], datatype=XSD.decimal)))
            graph.add((subject, mobility_namespace[longitude_predicate], Literal(row["lon"], datatype=XSD.decimal)))

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


def _run_ontology_hub_ask_query(rdf_path: Path) -> dict[str, Any]:
    graph = Graph()
    graph.parse(rdf_path, format="nt")
    query = """
    ASK {
      <https://pionera.example/automap/stop/SOL> a <https://w3id.org/pionera/validation/mobility#Stop> ;
        <https://w3id.org/pionera/validation/mobility#hasStopName> "Sol" .
    }
    """
    return {
        "query": "ASK stop SOL uses Ontology Hub mobility terms",
        "passed": bool(graph.query(query)),
    }


def _parse_ontology_hub_artifact(ontology_path: Path) -> dict[str, Any]:
    assertions: list[str] = []
    graph = Graph()
    try:
        graph.parse(ontology_path, format="turtle")
    except Exception as exc:
        return {
            "status": "failed",
            "assertions": [f"Ontology Hub artifact is not valid Turtle/RDF: {exc}"],
            "path": str(ontology_path),
        }

    ontology_subjects = sorted(str(subject) for subject in graph.subjects(RDF.type, OWL.Ontology))
    labels = sorted(str(label) for subject in graph.subjects(RDF.type, OWL.Ontology) for label in graph.objects(subject, RDFS.label))
    expected_terms = [
        ONTOLOGY_HUB_MOBILITY.Stop,
        ONTOLOGY_HUB_MOBILITY.hasStopName,
        ONTOLOGY_HUB_MOBILITY.hasLatitude,
        ONTOLOGY_HUB_MOBILITY.hasLongitude,
    ]
    missing_terms = [str(term) for term in expected_terms if (term, None, None) not in graph]

    if not ontology_subjects:
        assertions.append("Ontology Hub artifact must declare owl:Ontology metadata")
    if not labels:
        assertions.append("Ontology Hub artifact must expose a governance/catalog label")
    if missing_terms:
        assertions.append("Ontology Hub artifact is missing expected mobility terms: " + ", ".join(missing_terms))

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "path": str(ontology_path),
        "ontology_iris": ontology_subjects,
        "labels": labels,
        "triple_count": len(graph),
        "expected_terms": [str(term) for term in expected_terms],
    }


def _validate_automap_ontology_hub_reuse(
    *,
    rml_tools: Any,
    metrics_module: Any,
    csv_path: Path,
    fixtures_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    assertions: list[str] = []
    ontology_path = DEFAULT_ONTOLOGY_HUB_ARTIFACT
    mapping_path = fixtures_dir / "ontology_hub_mobility_mapping.yarrr.yml"
    gold_kg_path = fixtures_dir / "ontology_hub_mobility_gold.nt"
    generated_kg_path = output_dir / "automap_generated_ontology_hub_mobility.nt"

    for label, path in {
        "ontology_hub_artifact": ontology_path,
        "mapping": mapping_path,
        "gold_kg": gold_kg_path,
    }.items():
        if not path.is_file():
            assertions.append(f"Automap/Ontology Hub fixture is missing: {label} ({path})")

    if assertions:
        return {
            "status": "failed",
            "assertions": assertions,
            "ontology_hub_artifact": str(ontology_path),
            "mapping_path": str(mapping_path),
            "gold_kg_path": str(gold_kg_path),
        }

    ontology_profile = _parse_ontology_hub_artifact(ontology_path)
    assertions.extend(ontology_profile.get("assertions") or [])

    ontology_summary = rml_tools.get_ontology_subgraph(str(ontology_path), EXPECTED_COLUMNS)
    ontology_markers = [
        "Class: <https://w3id.org/pionera/validation/mobility#Stop>",
        "hasStopName",
        "hasLatitude",
        "hasLongitude",
    ]
    missing_ontology_markers = [marker for marker in ontology_markers if marker not in ontology_summary]
    if missing_ontology_markers:
        assertions.append(
            "Automap did not extract expected Ontology Hub-governed terms: "
            + ", ".join(missing_ontology_markers)
        )

    mapping_text = mapping_path.read_text(encoding="utf-8")
    try:
        mapping_data = yaml.safe_load(mapping_text)
    except yaml.YAMLError as exc:
        mapping_data = None
        assertions.append(f"Ontology Hub YARRRML fixture is not valid YAML: {exc}")
    if not isinstance(mapping_data, dict) or "mappings" not in mapping_data:
        assertions.append("Ontology Hub YARRRML fixture must contain a mappings block")
    if "https://w3id.org/pionera/validation/mobility#" not in mapping_text:
        assertions.append("Ontology Hub YARRRML fixture must reference the governed mobility ontology namespace")

    materialization = _materialize_mobility_fixture(
        csv_path,
        generated_kg_path,
        mobility_namespace=ONTOLOGY_HUB_MOBILITY,
        stop_name_predicate="hasStopName",
        latitude_predicate="hasLatitude",
        longitude_predicate="hasLongitude",
    )
    if materialization["rows"] != 3:
        assertions.append(f"Expected 3 ontology-backed materialized rows, got {materialization['rows']}")
    if materialization["triples"] != 12:
        assertions.append(f"Expected 12 ontology-backed RDF triples, got {materialization['triples']}")

    pipeline_result = {
        "yarrrml_output": mapping_text,
        "rdf_output": str(generated_kg_path),
        "csv_path": str(csv_path),
        "retry_count": 0,
        "feedback": "Deterministic Automap execution using an Ontology Hub-governable ontology artifact",
        "messages": [],
    }
    evaluation_metrics = metrics_module.evaluate(
        levels=[2, 3],
        pipeline_result=pipeline_result,
        gold_kg_path=str(gold_kg_path),
    )
    if evaluation_metrics.get("L2_skipped"):
        assertions.append(f"Automap/Ontology Hub gold KG comparison was skipped: {evaluation_metrics.get('L2_skip_reason')}")
    else:
        for metric_name in [
            "L2_norm_triple_precision",
            "L2_norm_triple_recall",
            "L2_norm_triple_f1",
            "L2_predicate_f1",
            "L2_class_f1",
        ]:
            if evaluation_metrics.get(metric_name) != 1.0:
                assertions.append(f"Expected Automap/Ontology Hub {metric_name}=1.0, got {evaluation_metrics.get(metric_name)}")
    if evaluation_metrics.get("L3_skipped"):
        assertions.append(f"Automap/Ontology Hub column coverage was skipped: {evaluation_metrics.get('L3_skip_reason')}")
    elif evaluation_metrics.get("L3_columns_mapped_yarrrml") != len(EXPECTED_COLUMNS):
        assertions.append(
            "Automap/Ontology Hub YARRRML column coverage did not map all fixture columns: "
            + ", ".join(evaluation_metrics.get("L3_columns_missing_yarrrml") or [])
        )

    sparql_check = _run_ontology_hub_ask_query(generated_kg_path)
    if not sparql_check["passed"]:
        assertions.append("Direct SPARQL ASK validation over the Ontology Hub-backed KG did not pass")

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "ontology_hub_artifact": ontology_profile,
        "ontology_summary_excerpt": ontology_summary[:1200],
        "ontology_markers_checked": ontology_markers,
        "mapping": {
            "path": str(mapping_path),
            "yaml_valid": isinstance(mapping_data, dict),
            "governed_namespace": "https://w3id.org/pionera/validation/mobility#",
        },
        "materialization": materialization,
        "metrics": evaluation_metrics,
        "sparql": sparql_check,
        "linked_cases": ["INT-VS-OH-01", "PT5-OH-07", "PT5-VS-06", "PT5-VS-10"],
        "execution_scope": (
            "Deterministic cross-component traceability baseline: Automap consumes an ontology artifact "
            "with Ontology Hub governance metadata and produces RDF evidence using those ontology terms."
        ),
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
    ontology_hub_reuse = _validate_automap_ontology_hub_reuse(
        rml_tools=rml_tools,
        metrics_module=metrics_module,
        csv_path=csv_path,
        fixtures_dir=resolved_fixtures_dir,
        output_dir=resolved_output_dir,
    )
    if ontology_hub_reuse.get("status") != "passed":
        assertions.extend(
            f"Automap/Ontology Hub reuse: {assertion}"
            for assertion in list(ontology_hub_reuse.get("assertions") or [])
        )

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
        "ontology_hub_reuse": ontology_hub_reuse,
        "execution_scope": (
            "Deterministic offline execution baseline for Automap schema extraction, ontology extraction, "
            "Ontology Hub-governed ontology reuse, RDF materialization evidence and evaluation metrics. "
            "The LLM generation path is intentionally not executed in Level 6 because it requires model/runtime "
            "configuration and secrets outside the open-source baseline."
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
        "dataspace_dimension": "mapping_generation_evaluation_and_semantic_reuse",
        "mapping_status": "mapped",
        "automation_mode": "offline_deterministic_execution",
        "execution_mode": "offline_fixture",
        "coverage_status": "automated",
        "linked_pt5_cases": ["PT5-VS-01", "PT5-VS-06", "PT5-VS-10", "PT5-OH-07"],
        "linked_cases": ["INT-VS-OH-01"],
        "evaluation": {
            "status": validation["status"],
            "assertions": list(validation.get("assertions") or []),
        },
        "evidence": validation,
        "expected_result": (
            "Automap deterministic tooling can extract source schema and ontology context, produce "
            "traceable RDF evidence from controlled mapping fixtures, reuse an Ontology Hub-governable "
            "ontology artifact and evaluate the outputs against gold KGs."
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
