from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS


COMPONENT_KEY = "semantic-virtualization"
SUITE_NAME = "mapping-fixtures"
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
RML_LOGICAL_SOURCE = URIRef("http://semweb.mmlab.be/ns/rml#logicalSource")
RML_SOURCE = URIRef("http://semweb.mmlab.be/ns/rml#source")
RML_REFERENCE_FORMULATION = URIRef("http://semweb.mmlab.be/ns/rml#referenceFormulation")
RML_TRIPLES_MAP = URIRef("http://w3id.org/rml/TriplesMap")
RML_V1_LOGICAL_SOURCE = URIRef("http://w3id.org/rml/logicalSource")
RML_V1_SOURCE = URIRef("http://w3id.org/rml/source")
RML_V1_REFERENCE_FORMULATION = URIRef("http://w3id.org/rml/referenceFormulation")
RML_V1_CLASS = URIRef("http://w3id.org/rml/class")
RML_V1_PREDICATE = URIRef("http://w3id.org/rml/predicate")
RR_TRIPLES_MAP = URIRef("http://www.w3.org/ns/r2rml#TriplesMap")
RR_LOGICAL_TABLE = URIRef("http://www.w3.org/ns/r2rml#logicalTable")
RR_TABLE_NAME = URIRef("http://www.w3.org/ns/r2rml#tableName")
RR_CLASS = URIRef("http://www.w3.org/ns/r2rml#class")
RR_PREDICATE = URIRef("http://www.w3.org/ns/r2rml#predicate")
QL_CSV = URIRef("http://semweb.mmlab.be/ns/ql#CSV")
QL_JSONPATH = URIRef("http://semweb.mmlab.be/ns/ql#JSONPath")

CASE_METADATA: dict[str, dict[str, str]] = {
    "PT5-VS-01": {
        "description": "Configure RML/R2RML mappings over different data sources",
        "dataspace_dimension": "mapping",
        "expected_result": "Representative RML/R2RML mappings are configured for CSV, JSON and relational sources",
    },
    "PT5-VS-03": {
        "description": "Execute a SPARQL query combining multiple sources",
        "dataspace_dimension": "multisource_query",
        "expected_result": "A SPARQL query joins route data and stop data from the virtualized graph",
    },
    "PT5-VS-04": {
        "description": "Execute complex SPARQL queries over virtualized data",
        "dataspace_dimension": "complex_query",
        "expected_result": "A representative SPARQL query with filters and ordering returns the expected result shape",
    },
    "PT5-VS-05": {
        "description": "Validate mappings before execution",
        "dataspace_dimension": "mapping_validation",
        "expected_result": "Valid mappings pass and an intentionally invalid mapping is rejected with diagnostics",
    },
    "PT5-VS-06": {
        "description": "Define mappings using loaded sources and ontologies",
        "dataspace_dimension": "semantic_mapping",
        "expected_result": "Mappings reference existing source data and ontology terms",
    },
    "INT-VS-OH-01": {
        "description": "Reuse Ontology Hub governed ontology artifacts as mapping support",
        "case_group": "cross_component_traceability",
        "validation_type": "integration",
        "dataspace_dimension": "semantic_reuse",
        "automation_mode": "offline_traceability",
        "execution_mode": "offline_traceability",
        "expected_result": "Semantic Virtualization mappings reference ontology terms that can be governed or published through Ontology Hub",
    },
    "PT5-VS-09": {
        "description": "Export mappings in standard formats",
        "dataspace_dimension": "mapping_export",
        "expected_result": "Mappings are exported as parseable Turtle RML/R2RML artifacts",
    },
    "PT5-VS-10": {
        "description": "Evaluate mapping generation methods",
        "dataspace_dimension": "mapping_evaluation",
        "expected_result": "Mapping generation methods are compared using reproducible fixtures and scoring criteria",
    },
}


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


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_rdf(path: Path, *, rdf_format: str | None = None) -> tuple[Graph | None, list[str]]:
    graph = Graph()
    try:
        graph.parse(path, format=rdf_format)
    except Exception as exc:  # rdflib raises several parser-specific exceptions.
        return None, [f"{path.name} is not valid Turtle/RDF: {exc}"]
    return graph, []


def _parse_turtle(path: Path) -> tuple[Graph | None, list[str]]:
    return _parse_rdf(path, rdf_format="turtle")


def _ontology_terms(ontology_graph: Graph) -> set[URIRef]:
    return {term for term in ontology_graph.subjects() if isinstance(term, URIRef)}


def _reference_formulation_to_format(reference_formulation: URIRef | None, source_path: str) -> str:
    if reference_formulation == QL_CSV or source_path.lower().endswith(".csv"):
        return "csv"
    if reference_formulation == QL_JSONPATH or source_path.lower().endswith(".json"):
        return "json"
    return "unknown"


def _schema_contains_table(schema_path: Path, table_name: str) -> bool:
    if not schema_path.exists():
        return False
    normalized_schema = schema_path.read_text(encoding="utf-8").lower()
    normalized_table = table_name.lower()
    return (
        f"table {normalized_table}" in normalized_schema
        or f"table if not exists {normalized_table}" in normalized_schema
    )


def _objects_any(graph: Graph, subject: Any, predicates: list[URIRef]) -> list[Any]:
    return [
        item
        for predicate in predicates
        for item in graph.objects(subject, predicate)
    ]


def validate_mapping_artifact(
    mapping_path: str | os.PathLike[str],
    *,
    fixture_dir: str | os.PathLike[str] = DEFAULT_FIXTURE_DIR,
    ontology_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    fixture_root = Path(fixture_dir)
    mapping_file = Path(mapping_path)
    ontology_file = Path(ontology_path) if ontology_path else fixture_root / "ontology" / "mobility-mini.ttl"
    diagnostics: list[str] = []

    graph, parser_errors = _parse_turtle(mapping_file)
    diagnostics.extend(parser_errors)
    ontology_graph, ontology_errors = _parse_turtle(ontology_file)
    diagnostics.extend(ontology_errors)

    if graph is None or ontology_graph is None:
        return {
            "mapping_path": str(mapping_file),
            "status": "failed",
            "assertions": diagnostics,
            "source_references": [],
            "source_formats": [],
            "ontology_terms": [],
            "triples_map_count": 0,
        }

    source_references: list[dict[str, Any]] = []
    source_formats: set[str] = set()

    for logical_source in _objects_any(graph, None, [RML_LOGICAL_SOURCE, RML_V1_LOGICAL_SOURCE]):
        source_value = next(iter(_objects_any(graph, logical_source, [RML_SOURCE, RML_V1_SOURCE])), None)
        reference_formulation = next(
            iter(_objects_any(graph, logical_source, [RML_REFERENCE_FORMULATION, RML_V1_REFERENCE_FORMULATION])),
            None,
        )
        if not isinstance(source_value, Literal):
            diagnostics.append(f"{mapping_file.name} has an RML logical source without literal rml:source")
            continue
        source_path = str(source_value)
        absolute_source_path = fixture_root / source_path
        source_format = _reference_formulation_to_format(
            reference_formulation if isinstance(reference_formulation, URIRef) else None,
            source_path,
        )
        source_formats.add(source_format)
        source_references.append(
            {
                "type": "rml",
                "path": source_path,
                "format": source_format,
                "exists": absolute_source_path.exists(),
            }
        )
        if not absolute_source_path.exists():
            diagnostics.append(f"{mapping_file.name} references missing source file {source_path}")

    schema_path = fixture_root / "sources" / "relational" / "schema.sql"
    for logical_table in graph.objects(None, RR_LOGICAL_TABLE):
        table_name = next(graph.objects(logical_table, RR_TABLE_NAME), None)
        if not isinstance(table_name, Literal):
            diagnostics.append(f"{mapping_file.name} has an R2RML logical table without rr:tableName")
            continue
        source_formats.add("relational")
        table_value = str(table_name)
        table_exists = _schema_contains_table(schema_path, table_value)
        source_references.append(
            {
                "type": "r2rml",
                "table": table_value,
                "format": "relational",
                "exists": table_exists,
            }
        )
        if not table_exists:
            diagnostics.append(f"{mapping_file.name} references table {table_value}, not present in schema.sql")

    if not source_references:
        diagnostics.append(f"{mapping_file.name} does not define an RML logical source or R2RML logical table")

    defined_terms = _ontology_terms(ontology_graph)
    ontology_references = [
        term
        for term in list(graph.objects(None, RR_CLASS))
        + list(graph.objects(None, RML_V1_CLASS))
        + list(graph.objects(None, RR_PREDICATE))
        + list(graph.objects(None, RML_V1_PREDICATE))
        if isinstance(term, URIRef)
    ]
    missing_terms = sorted({str(term) for term in ontology_references if term not in defined_terms})
    if not ontology_references:
        diagnostics.append(f"{mapping_file.name} does not reference ontology classes or predicates")
    for term in missing_terms:
        diagnostics.append(f"{mapping_file.name} references ontology term not loaded in fixture: {term}")

    triples_map_count = len(set(graph.subjects(RDF.type, RR_TRIPLES_MAP)) | set(graph.subjects(RDF.type, RML_TRIPLES_MAP)))
    if triples_map_count == 0:
        diagnostics.append(f"{mapping_file.name} does not declare rr:TriplesMap or rml:TriplesMap")

    return {
        "mapping_path": str(mapping_file),
        "status": "failed" if diagnostics else "passed",
        "assertions": diagnostics,
        "source_references": source_references,
        "source_formats": sorted(source_formats),
        "ontology_terms": sorted({str(term) for term in ontology_references}),
        "triples_map_count": triples_map_count,
        "sha256": _hash_file(mapping_file),
    }


def _case_result(case_id: str, status: str, assertions: list[str], evidence: dict[str, Any]) -> dict[str, Any]:
    metadata = CASE_METADATA[case_id]
    return {
        "test_case_id": case_id,
        "description": metadata["description"],
        "type": "offline_fixture",
        "case_group": metadata.get("case_group", "pt5"),
        "validation_type": metadata.get("validation_type", "functional"),
        "dataspace_dimension": metadata["dataspace_dimension"],
        "mapping_status": "mapped",
        "automation_mode": metadata.get("automation_mode", "offline_fixture"),
        "execution_mode": metadata.get("execution_mode", "offline_fixture"),
        "coverage_status": "automated",
        "evaluation": {
            "status": status,
            "assertions": assertions,
        },
        "evidence": evidence,
        "expected_result": metadata["expected_result"],
    }


def _summarize_cases(executed_cases: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(executed_cases), "passed": 0, "failed": 0, "skipped": 0}
    for case in executed_cases:
        status = str(((case.get("evaluation") or {}).get("status") or "")).lower()
        if status in summary:
            summary[status] += 1
    return summary


def _export_mapping(mapping_path: Path, export_dir: Path | None) -> dict[str, Any]:
    graph, parser_errors = _parse_turtle(mapping_path)
    if graph is None:
        return {
            "source": str(mapping_path),
            "status": "failed",
            "assertions": parser_errors,
        }
    serialized = graph.serialize(format="turtle")
    exported_graph = Graph()
    exported_errors: list[str] = []
    try:
        exported_graph.parse(data=serialized, format="turtle")
    except Exception as exc:
        exported_graph = None
        exported_errors.append(f"Serialized export is not parseable Turtle/RDF: {exc}")

    result = {
        "source": str(mapping_path),
        "format": "text/turtle",
        "status": "failed" if exported_graph is None else "passed",
        "assertions": exported_errors,
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "triple_count": len(exported_graph) if exported_graph is not None else 0,
    }
    if export_dir:
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"{mapping_path.stem}.ttl"
        export_path.write_text(serialized, encoding="utf-8")
        result["path"] = str(export_path)
        result["sha256"] = _hash_file(export_path)
    return result


def execute_sparql_fixture_query(
    query_path: str | os.PathLike[str],
    *,
    graph_path: str | os.PathLike[str] | None = None,
    fixture_dir: str | os.PathLike[str] = DEFAULT_FIXTURE_DIR,
) -> dict[str, Any]:
    fixture_root = Path(fixture_dir)
    query_file = Path(query_path)
    graph_file = Path(graph_path) if graph_path else fixture_root / "expected" / "mobility-virtualized-output.ttl"
    graph, parser_errors = _parse_turtle(graph_file)
    if graph is None:
        return {
            "query_path": str(query_file),
            "graph_path": str(graph_file),
            "status": "failed",
            "assertions": parser_errors,
            "rows": [],
        }

    try:
        query_text = query_file.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "query_path": str(query_file),
            "graph_path": str(graph_file),
            "status": "failed",
            "assertions": [f"Could not read SPARQL query {query_file}: {exc}"],
            "rows": [],
        }

    try:
        result_set = graph.query(query_text)
    except Exception as exc:
        return {
            "query_path": str(query_file),
            "graph_path": str(graph_file),
            "status": "failed",
            "assertions": [f"SPARQL query failed: {exc}"],
            "rows": [],
            "query_sha256": hashlib.sha256(query_text.encode("utf-8")).hexdigest(),
        }

    rows = [
        {str(variable): str(value) for variable, value in row.asdict().items()}
        for row in result_set
    ]
    return {
        "query_path": str(query_file),
        "graph_path": str(graph_file),
        "status": "passed",
        "assertions": [],
        "variables": [str(variable) for variable in getattr(result_set, "vars", [])],
        "rows": rows,
        "row_count": len(rows),
        "query_sha256": hashlib.sha256(query_text.encode("utf-8")).hexdigest(),
        "graph_sha256": _hash_file(graph_file),
    }


def evaluate_ontology_hub_mapping_reuse(
    *,
    fixture_dir: str | os.PathLike[str] = DEFAULT_FIXTURE_DIR,
) -> dict[str, Any]:
    fixture_root = Path(fixture_dir)
    turtle_ontology = fixture_root / "ontology" / "mobility-mini.ttl"
    rdfxml_ontology = fixture_root / "ontology" / "mobility-mini.owl"
    assertions: list[str] = []

    turtle_graph, turtle_errors = _parse_turtle(turtle_ontology)
    rdfxml_graph, rdfxml_errors = _parse_rdf(rdfxml_ontology, rdf_format="xml")
    assertions.extend(turtle_errors)
    assertions.extend(rdfxml_errors)

    ontology_subjects: list[URIRef] = []
    classes: list[URIRef] = []
    datatype_properties: list[URIRef] = []
    object_properties: list[URIRef] = []
    ontology_labels: list[str] = []

    if turtle_graph is not None:
        ontology_subjects = [
            subject
            for subject in turtle_graph.subjects(RDF.type, OWL.Ontology)
            if isinstance(subject, URIRef)
        ]
        classes = [
            subject
            for subject in turtle_graph.subjects(RDF.type, OWL.Class)
            if isinstance(subject, URIRef)
        ]
        datatype_properties = [
            subject
            for subject in turtle_graph.subjects(RDF.type, OWL.DatatypeProperty)
            if isinstance(subject, URIRef)
        ]
        object_properties = [
            subject
            for subject in turtle_graph.subjects(RDF.type, OWL.ObjectProperty)
            if isinstance(subject, URIRef)
        ]
        ontology_labels = [
            str(label)
            for subject in ontology_subjects
            for label in turtle_graph.objects(subject, RDFS.label)
        ]

    if not ontology_subjects:
        assertions.append("Expected an owl:Ontology declaration in the reusable ontology artifact")
    if not classes:
        assertions.append("Expected ontology classes to support mapping authoring")
    if not (datatype_properties or object_properties):
        assertions.append("Expected ontology properties to support predicate/object maps")
    if not ontology_labels:
        assertions.append("Expected a human-readable ontology label for governance/catalog evidence")

    valid_mapping_paths = sorted(
        path for path in (fixture_root / "mappings").glob("*.ttl")
        if not path.name.startswith("invalid_")
    )
    mapping_validations = [
        validate_mapping_artifact(path, fixture_dir=fixture_root, ontology_path=turtle_ontology)
        for path in valid_mapping_paths
    ]
    assertions.extend(
        assertion
        for result in mapping_validations
        for assertion in result.get("assertions", [])
    )

    if not mapping_validations:
        assertions.append("Expected at least one mapping fixture to validate ontology reuse")
    if any(not result.get("ontology_terms") for result in mapping_validations):
        assertions.append("Expected every valid mapping fixture to reference reusable ontology terms")

    referenced_terms = sorted(
        {
            term
            for result in mapping_validations
            for term in result.get("ontology_terms", [])
        }
    )
    if len(referenced_terms) < 2:
        assertions.append("Expected mappings to reuse at least two ontology terms")

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "ontology_artifacts": {
            "turtle": str(turtle_ontology),
            "rdfxml": str(rdfxml_ontology),
            "turtle_parseable": turtle_graph is not None,
            "rdfxml_parseable": rdfxml_graph is not None,
        },
        "ontology_profile": {
            "ontology_iris": sorted(str(subject) for subject in ontology_subjects),
            "labels": ontology_labels,
            "class_count": len(classes),
            "datatype_property_count": len(datatype_properties),
            "object_property_count": len(object_properties),
        },
        "mapping_count": len(mapping_validations),
        "referenced_ontology_terms": referenced_terms,
        "mapping_validations": mapping_validations,
        "linked_cases": ["PT5-VS-06", "PT5-OH-07"],
    }


def _assert_expected_rows(
    query_result: dict[str, Any],
    *,
    expected_pairs: set[tuple[str, str]],
) -> list[str]:
    assertions = list(query_result.get("assertions") or [])
    actual_pairs = {
        (row.get("routeName"), row.get("stopName"))
        for row in query_result.get("rows", [])
    }
    missing_pairs = sorted(expected_pairs - actual_pairs)
    if missing_pairs:
        assertions.append(f"Expected SPARQL rows were not returned: {missing_pairs}")
    if not query_result.get("rows"):
        assertions.append("SPARQL query returned no rows")
    return assertions


def load_generation_methods_catalog(
    *,
    fixture_dir: str | os.PathLike[str] = DEFAULT_FIXTURE_DIR,
) -> dict[str, Any]:
    catalog_path = Path(fixture_dir) / "mapping-generation-methods.json"
    with catalog_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _score_generation_method(
    validation_result: dict[str, Any],
    *,
    expected_source_format: str | None,
    criteria: dict[str, int],
) -> tuple[int, list[str], dict[str, bool]]:
    assertions = list(validation_result.get("assertions") or [])
    source_references = validation_result.get("source_references") or []
    source_formats = set(validation_result.get("source_formats") or [])
    checks = {
        "parseable_mapping": validation_result.get("triples_map_count", 0) > 0,
        "source_resolved": bool(source_references) and all(item.get("exists") for item in source_references),
        "ontology_terms_resolved": bool(validation_result.get("ontology_terms")) and not assertions,
        "triples_map_present": validation_result.get("triples_map_count", 0) > 0,
        "expected_source_format": bool(expected_source_format) and expected_source_format in source_formats,
    }
    if expected_source_format and expected_source_format not in source_formats:
        assertions.append(f"Expected source format {expected_source_format}, got {sorted(source_formats)}")

    score = sum(int(criteria.get(name, 0)) for name, passed in checks.items() if passed)
    return score, assertions, checks


def evaluate_mapping_generation_methods(
    *,
    fixture_dir: str | os.PathLike[str] = DEFAULT_FIXTURE_DIR,
) -> dict[str, Any]:
    fixture_root = Path(fixture_dir)
    catalog = load_generation_methods_catalog(fixture_dir=fixture_root)
    criteria = {
        str(name): int(weight)
        for name, weight in (catalog.get("criteria") or {}).items()
    }
    method_results: list[dict[str, Any]] = []

    for method in catalog.get("methods") or []:
        mapping_relative_path = str(method.get("mapping") or "")
        mapping_path = fixture_root / mapping_relative_path
        validation_result = validate_mapping_artifact(mapping_path, fixture_dir=fixture_root)
        expected_source_format = method.get("expected_source_format")
        score, assertions, checks = _score_generation_method(
            validation_result,
            expected_source_format=str(expected_source_format) if expected_source_format else None,
            criteria=criteria,
        )
        expected_min_score = int(method.get("expected_min_score") or 0)
        if score < expected_min_score:
            assertions.append(f"Expected minimum score {expected_min_score}, got {score}")

        method_results.append(
            {
                "method_id": method.get("id"),
                "name": method.get("name"),
                "approach": method.get("approach"),
                "mapping": mapping_relative_path,
                "expected_source_format": expected_source_format,
                "expected_min_score": expected_min_score,
                "score": score,
                "status": "passed" if not assertions else "failed",
                "checks": checks,
                "assertions": assertions,
                "validation": validation_result,
            }
        )

    method_count = len(method_results)
    passed_methods = [method for method in method_results if method.get("status") == "passed"]
    approach_count = len({method.get("approach") for method in method_results if method.get("approach")})
    assertions: list[str] = []
    if method_count < 2:
        assertions.append("Expected at least two mapping generation methods to compare")
    if approach_count < 2:
        assertions.append("Expected at least two generation approaches to compare")
    if len(passed_methods) < 2:
        assertions.append("Expected at least two mapping generation methods to pass evaluation")

    failing_method_ids = [str(method.get("method_id")) for method in method_results if method.get("status") != "passed"]
    if failing_method_ids:
        assertions.append(f"Mapping generation methods failed evaluation: {failing_method_ids}")

    ranked_methods = sorted(
        method_results,
        key=lambda item: (-int(item.get("score") or 0), str(item.get("method_id") or "")),
    )
    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "catalog_version": catalog.get("version"),
        "criteria": criteria,
        "method_count": method_count,
        "approach_count": approach_count,
        "passed_method_count": len(passed_methods),
        "ranked_methods": [
            {
                "method_id": method.get("method_id"),
                "approach": method.get("approach"),
                "score": method.get("score"),
                "status": method.get("status"),
            }
            for method in ranked_methods
        ],
        "methods": method_results,
    }


def run_semantic_virtualization_mapping_validation(
    experiment_dir: str | os.PathLike[str] | None = None,
    *,
    fixture_dir: str | os.PathLike[str] = DEFAULT_FIXTURE_DIR,
) -> dict[str, Any]:
    started_at_dt = datetime.now()
    fixture_root = Path(fixture_dir)
    component_dir = _component_dir(experiment_dir)
    artifacts: dict[str, str] = {}

    valid_mapping_paths = sorted(
        path for path in (fixture_root / "mappings").glob("*.ttl")
        if not path.name.startswith("invalid_")
    )
    invalid_mapping_paths = sorted((fixture_root / "mappings").glob("invalid_*.ttl"))
    valid_results = [
        validate_mapping_artifact(path, fixture_dir=fixture_root)
        for path in valid_mapping_paths
    ]
    invalid_results = [
        validate_mapping_artifact(path, fixture_dir=fixture_root)
        for path in invalid_mapping_paths
    ]

    all_source_formats = sorted(
        {
            source_format
            for result in valid_results
            for source_format in result.get("source_formats", [])
        }
    )
    valid_assertions = [
        assertion
        for result in valid_results
        for assertion in result.get("assertions", [])
    ]
    invalid_diagnostics = [
        assertion
        for result in invalid_results
        for assertion in result.get("assertions", [])
    ]

    expected_route_stop_pairs = {("C4", "Atocha"), ("ML4", "Parla Centro")}
    multisource_query_result = execute_sparql_fixture_query(
        fixture_root / "queries" / "multisource_routes_stops.rq",
        fixture_dir=fixture_root,
    )
    multisource_assertions = _assert_expected_rows(
        multisource_query_result,
        expected_pairs=expected_route_stop_pairs,
    )
    complex_query_result = execute_sparql_fixture_query(
        fixture_root / "queries" / "complex_mobility_query.rq",
        fixture_dir=fixture_root,
    )
    complex_assertions = _assert_expected_rows(
        complex_query_result,
        expected_pairs=expected_route_stop_pairs,
    )
    ontology_hub_reuse = evaluate_ontology_hub_mapping_reuse(fixture_dir=fixture_root)
    generation_evaluation = evaluate_mapping_generation_methods(fixture_dir=fixture_root)

    cases = [
        _case_result(
            "PT5-VS-01",
            "passed"
            if len(valid_results) >= 3 and {"csv", "json", "relational"}.issubset(all_source_formats)
            else "failed",
            [] if len(valid_results) >= 3 and {"csv", "json", "relational"}.issubset(all_source_formats)
            else ["Expected RML/R2RML fixtures for CSV, JSON and relational sources"],
            {
                "valid_mapping_count": len(valid_results),
                "source_formats": all_source_formats,
                "mapping_paths": [str(path) for path in valid_mapping_paths],
            },
        ),
        _case_result(
            "PT5-VS-03",
            "passed" if not multisource_assertions else "failed",
            multisource_assertions,
            {
                "query_result": multisource_query_result,
                "linked_fixture_sources": ["sources/json/routes.json", "sources/csv/stops.csv"],
            },
        ),
        _case_result(
            "PT5-VS-04",
            "passed" if not complex_assertions else "failed",
            complex_assertions,
            {
                "query_result": complex_query_result,
                "query_features": ["FILTER", "ORDER BY", "IRI join"],
            },
        ),
        _case_result(
            "PT5-VS-05",
            "passed" if not valid_assertions and invalid_results and invalid_diagnostics else "failed",
            valid_assertions
            if valid_assertions
            else ([] if invalid_results and invalid_diagnostics else ["Expected an invalid mapping fixture to be rejected"]),
            {
                "valid_mappings": valid_results,
                "invalid_mappings": invalid_results,
            },
        ),
        _case_result(
            "PT5-VS-06",
            "passed"
            if not valid_assertions and all(result.get("ontology_terms") for result in valid_results)
            else "failed",
            valid_assertions
            if valid_assertions
            else (
                [] if all(result.get("ontology_terms") for result in valid_results)
                else ["Expected all valid mappings to reference ontology terms"]
            ),
            {
                "ontology_path": str(fixture_root / "ontology" / "mobility-mini.ttl"),
                "valid_mappings": valid_results,
            },
        ),
        _case_result(
            "INT-VS-OH-01",
            "passed" if ontology_hub_reuse.get("status") == "passed" else "failed",
            list(ontology_hub_reuse.get("assertions") or []),
            {
                "ontology_hub_reuse": ontology_hub_reuse,
            },
        ),
    ]

    export_dir = component_dir / "exports" if component_dir else None
    exported_mappings = [_export_mapping(path, export_dir) for path in valid_mapping_paths]
    for exported in exported_mappings:
        if exported.get("path"):
            artifact_key = f"exported-{Path(str(exported['path'])).name}"
            artifacts[artifact_key] = str(exported["path"])

    export_assertions = [
        assertion
        for exported in exported_mappings
        if exported.get("status") != "passed"
        for assertion in exported.get("assertions", [])
    ]
    export_count_ok = len(exported_mappings) == len(valid_mapping_paths)
    cases.append(
        _case_result(
            "PT5-VS-09",
            "passed" if export_count_ok and not export_assertions else "failed",
            export_assertions
            if export_assertions
            else ([] if export_count_ok else ["Expected standard mapping artifacts to be exported"]),
            {
                "exported_mappings": exported_mappings,
                "export_format": "text/turtle",
            },
        )
    )
    cases.append(
        _case_result(
            "PT5-VS-10",
            "passed" if generation_evaluation.get("status") == "passed" else "failed",
            list(generation_evaluation.get("assertions") or []),
            {
                "generation_evaluation": generation_evaluation,
            },
        )
    )

    summary = _summarize_cases(cases)
    completed_at_dt = datetime.now()
    if completed_at_dt < started_at_dt:
        completed_at_dt = started_at_dt
    report = {
        "component": COMPONENT_KEY,
        "suite": SUITE_NAME,
        "status": "passed" if summary["failed"] == 0 else "failed",
        "started_at": started_at_dt.isoformat(),
        "completed_at": completed_at_dt.isoformat(),
        "summary": summary,
        "test_cases": cases,
        "fixtures": {
            "fixture_dir": str(fixture_root),
            "valid_mapping_paths": [str(path) for path in valid_mapping_paths],
            "invalid_mapping_paths": [str(path) for path in invalid_mapping_paths],
        },
        "artifacts": artifacts,
    }

    if component_dir:
        report_path = component_dir / "semantic_virtualization_mapping_validation.json"
        _write_json(report_path, report)
        artifacts["report_json"] = str(report_path)
        report["evidence_index"] = [
            {
                "scope": "suite",
                "suite": SUITE_NAME,
                "artifact_name": "report_json",
                "path": str(report_path),
            },
            *[
                {
                    "scope": "case",
                    "suite": SUITE_NAME,
                    "test_case_id": "PT5-VS-09",
                    "artifact_name": key,
                    "path": path,
                }
                for key, path in sorted(artifacts.items())
                if key.startswith("exported-")
            ],
        ]
        _write_json(report_path, report)
    else:
        report["evidence_index"] = []

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Semantic Virtualization mapping fixtures for A5.2")
    parser.add_argument("--experiment-dir", help="Experiment directory where evidence artifacts will be written")
    parser.add_argument("--fixture-dir", default=str(DEFAULT_FIXTURE_DIR), help="Semantic Virtualization fixture directory")
    args = parser.parse_args()

    result = run_semantic_virtualization_mapping_validation(
        experiment_dir=args.experiment_dir,
        fixture_dir=args.fixture_dir,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
