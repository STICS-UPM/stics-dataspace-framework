from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, XSD

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from validation.components.semantic_virtualization.gtfs_bench_dataset import (  # noqa: E402
    EXPECTED_CSV_FILES,
    GTFS_HEADERS,
    build_gtfs_bench_official_sample,
    validate_gtfs_bench_official_dataset_sample,
    write_gtfs_bench_runtime_sample_csvs,
)


COMPONENT_KEY = "semantic-virtualization"
SUITE_NAME = "gtfs-bench-official-materialization"

GTFS = Namespace("http://vocab.gtfs.org/terms#")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
SCHEMA = Namespace("http://schema.org/")
BASE = "http://transport.linkeddata.es/madrid"


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


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _literal(value: str | None, datatype: URIRef | None = None) -> Literal | None:
    if value is None or value == "":
        return None
    return Literal(value, datatype=datatype) if datatype is not None else Literal(value)


def _add_literal(graph: Graph, subject: URIRef, predicate: URIRef, value: str | None, datatype: URIRef | None = None) -> None:
    literal = _literal(value, datatype)
    if literal is not None:
        graph.add((subject, predicate, literal))


def _iri_part(value: str) -> str:
    return quote(str(value), safe="")


def _shape_uri(shape_id: str) -> URIRef:
    return URIRef(f"{BASE}/metro/shape/{_iri_part(shape_id)}")


def _shape_point_uri(shape_id: str, sequence: str) -> URIRef:
    return URIRef(f"{BASE}/metro/shape_point/{_iri_part(shape_id)}-{_iri_part(sequence)}")


def _agency_uri(agency_id: str) -> URIRef:
    return URIRef(f"{BASE}/agency/{_iri_part(agency_id)}")


def _route_uri(route_id: str) -> URIRef:
    return URIRef(f"{BASE}/metro/routes/{_iri_part(route_id)}")


def _service_uri(service_id: str) -> URIRef:
    return URIRef(f"{BASE}/metro/services/{_iri_part(service_id)}")


def _trip_uri(trip_id: str) -> URIRef:
    return URIRef(f"{BASE}/metro/trips/{_iri_part(trip_id)}")


def _stop_uri(stop_id: str) -> URIRef:
    return URIRef(f"{BASE}/metro/stops/{_iri_part(stop_id)}")


def _stop_time_uri(row: dict[str, str]) -> URIRef:
    return URIRef(
        f"{BASE}/metro/stoptimes/{_iri_part(row['trip_id'])}-{_iri_part(row['stop_id'])}-{_iri_part(row['arrival_time'])}"
    )


def _frequency_uri(row: dict[str, str]) -> URIRef:
    return URIRef(f"{BASE}/metro/frequency/{_iri_part(row['trip_id'])}-{_iri_part(row['start_time'])}")


def _calendar_rule_uri(service_id: str) -> URIRef:
    return URIRef(f"{BASE}/metro/calendar_rules/{_iri_part(service_id)}")


def _calendar_date_rule_uri(row: dict[str, str]) -> URIRef:
    return URIRef(f"{BASE}/metro/calendar_date_rule/{_iri_part(row['service_id'])}-{_iri_part(row['date'])}")


def _feed_uri(feed_publisher_name: str) -> URIRef:
    return URIRef(f"{BASE}/metro/feed/{_iri_part(feed_publisher_name)}")


def adapt_official_csv_mapping(
    *,
    source_dir: str | os.PathLike[str] | None = None,
    sample_csv_dir: str | os.PathLike[str] | None = None,
    output_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    try:
        sample = build_gtfs_bench_official_sample(source_dir)
    except Exception as exc:
        return {
            "status": "failed",
            "assertions": [str(exc)],
            "mapping_path": "",
            "adapted_mapping_path": str(output_path) if output_path else "",
            "source_rewrites": {},
        }

    mapping_path = Path(sample["required_paths"]["mapping"])
    csv_root = Path(sample_csv_dir) if sample_csv_dir else None
    assertions: list[str] = []
    adapted_text = ""

    if not mapping_path.is_file():
        return {
            "status": "failed",
            "assertions": [f"Official CSV mapping reference is missing: {mapping_path}"],
            "mapping_path": str(mapping_path),
            "adapted_mapping_path": str(output_path) if output_path else "",
            "source_rewrites": {},
        }

    adapted_text = mapping_path.read_text(encoding="utf-8")
    source_rewrites: dict[str, str] = {}
    for csv_file in EXPECTED_CSV_FILES:
        original = f"/data/{csv_file}"
        adapted = f"{csv_root.name}/{csv_file}" if csv_root else f"runtime-sample-csv/{csv_file}"
        source_rewrites[original] = adapted
        adapted_text = adapted_text.replace(original, adapted)
        if csv_root and not (csv_root / csv_file).is_file():
            assertions.append(f"Adapted mapping source does not resolve in runtime sample: {adapted}")

    graph = Graph()
    try:
        graph.parse(data=adapted_text, format="turtle")
    except Exception as exc:
        assertions.append(f"Adapted mapping is not parseable Turtle/RDF: {exc}")

    adapted_mapping_path = Path(output_path) if output_path else None
    if adapted_mapping_path is not None:
        adapted_mapping_path.parent.mkdir(parents=True, exist_ok=True)
        adapted_mapping_path.write_text(adapted_text, encoding="utf-8")

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "mapping_path": str(mapping_path),
        "adapted_mapping_path": str(adapted_mapping_path) if adapted_mapping_path else "",
        "source_rewrites": source_rewrites,
        "triples_map_count": len(list(graph.subjects(RDF.type, URIRef("http://www.w3.org/ns/r2rml#TriplesMap")))),
        "adapted_mapping_sha256": _hash_text(adapted_text),
    }


def materialize_gtfs_bench_official_graph(
    *,
    source_dir: str | os.PathLike[str] | None = None,
    sample: dict[str, Any] | None = None,
) -> tuple[Graph, dict[str, Any]]:
    resolved_sample = sample or build_gtfs_bench_official_sample(source_dir)
    rows = {
        table: [
            {key: "" if value is None else str(value) for key, value in row.items()}
            for row in list((resolved_sample.get("tables") or {}).get(table) or [])
        ]
        for table in GTFS_HEADERS
    }
    graph = Graph()
    graph.bind("gtfs", GTFS)
    graph.bind("geo", GEO)
    graph.bind("foaf", FOAF)
    graph.bind("dct", DCTERMS)
    graph.bind("schema", SCHEMA)

    for row in rows["AGENCY"]:
        subject = _agency_uri(row["agency_id"])
        graph.add((subject, RDF.type, GTFS.Agency))
        _add_literal(graph, subject, FOAF.name, row.get("agency_name"))
        _add_literal(graph, subject, DCTERMS.language, row.get("agency_lang"))
        _add_literal(graph, subject, GTFS.timeZone, row.get("agency_timezone"))
        _add_literal(graph, subject, FOAF.phone, row.get("agency_phone"))

    for row in rows["ROUTES"]:
        subject = _route_uri(row["route_id"])
        graph.add((subject, RDF.type, GTFS.Route))
        graph.add((subject, GTFS.agency, _agency_uri(row["agency_id"])))
        _add_literal(graph, subject, GTFS.shortName, row.get("route_short_name"))
        _add_literal(graph, subject, GTFS.longName, row.get("route_long_name"))
        _add_literal(graph, subject, DCTERMS.description, row.get("route_desc"))
        _add_literal(graph, subject, GTFS.color, row.get("route_color"))
        _add_literal(graph, subject, GTFS.textColor, row.get("route_text_color"))

    for row in rows["CALENDAR"]:
        service = _service_uri(row["service_id"])
        calendar_rule = _calendar_rule_uri(row["service_id"])
        graph.add((service, RDF.type, GTFS.Service))
        graph.add((service, GTFS.serviceRule, calendar_rule))
        graph.add((calendar_rule, RDF.type, GTFS.CalendarRule))
        for field in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
            _add_literal(graph, calendar_rule, GTFS[field], row.get(field), XSD.boolean)
        _add_literal(graph, calendar_rule, SCHEMA.startDate, row.get("start_date"), XSD.date)
        _add_literal(graph, calendar_rule, SCHEMA.endDate, row.get("end_date"), XSD.date)

    for row in rows["CALENDAR_DATES"]:
        service = _service_uri(row["service_id"])
        calendar_date_rule = _calendar_date_rule_uri(row)
        graph.add((service, RDF.type, GTFS.Service))
        graph.add((service, GTFS.serviceRule, calendar_date_rule))
        graph.add((calendar_date_rule, RDF.type, GTFS.CalendarDateRule))
        _add_literal(graph, calendar_date_rule, DCTERMS.date, row.get("date"), XSD.date)
        _add_literal(graph, calendar_date_rule, GTFS.dateAddition, row.get("exception_type"), XSD.boolean)

    for row in rows["FEED_INFO"]:
        subject = _feed_uri(row["feed_publisher_name"])
        graph.add((subject, RDF.type, GTFS.Feed))
        _add_literal(graph, subject, DCTERMS.publisher, row.get("feed_publisher_name"))
        _add_literal(graph, subject, DCTERMS.language, row.get("feed_lang"))
        _add_literal(graph, subject, SCHEMA.startDate, row.get("feed_start_date"), XSD.date)
        _add_literal(graph, subject, SCHEMA.endDate, row.get("feed_end_date"), XSD.date)
        _add_literal(graph, subject, SCHEMA.version, row.get("feed_version"))

    for row in rows["SHAPES"]:
        shape = _shape_uri(row["shape_id"])
        shape_point = _shape_point_uri(row["shape_id"], row["shape_pt_sequence"])
        graph.add((shape, RDF.type, GTFS.Shape))
        graph.add((shape, GTFS.shapePoint, shape_point))
        graph.add((shape_point, RDF.type, GTFS.ShapePoint))
        _add_literal(graph, shape_point, GEO.lat, row.get("shape_pt_lat"), XSD.double)
        _add_literal(graph, shape_point, GEO.long, row.get("shape_pt_lon"), XSD.double)
        _add_literal(graph, shape_point, GTFS.pointSequence, row.get("shape_pt_sequence"))
        _add_literal(graph, shape_point, GTFS.distanceTraveled, row.get("shape_dist_traveled"), XSD.double)

    for row in rows["STOPS"]:
        subject = _stop_uri(row["stop_id"])
        graph.add((subject, RDF.type, GTFS.Stop))
        _add_literal(graph, subject, GTFS.code, row.get("stop_code"))
        _add_literal(graph, subject, DCTERMS.identifier, row.get("stop_id"))
        _add_literal(graph, subject, FOAF.name, row.get("stop_name"))
        _add_literal(graph, subject, DCTERMS.description, row.get("stop_desc"))
        _add_literal(graph, subject, GEO.lat, row.get("stop_lat"), XSD.double)
        _add_literal(graph, subject, GEO.long, row.get("stop_lon"), XSD.double)
        _add_literal(graph, subject, GTFS.zone, row.get("zone_id"))
        _add_literal(graph, subject, GTFS.timeZone, row.get("stop_timezone"))
        if row.get("parent_station"):
            graph.add((subject, GTFS.parentStation, _stop_uri(row["parent_station"])))

    for row in rows["TRIPS"]:
        subject = _trip_uri(row["trip_id"])
        graph.add((subject, RDF.type, GTFS.Trip))
        graph.add((subject, GTFS.route, _route_uri(row["route_id"])))
        graph.add((subject, GTFS.service, _service_uri(row["service_id"])))
        graph.add((subject, GTFS.shape, _shape_uri(row["shape_id"])))
        _add_literal(graph, subject, GTFS.headsign, row.get("trip_headsign"))
        _add_literal(graph, subject, GTFS.shortName, row.get("trip_short_name"))
        _add_literal(graph, subject, GTFS.direction, row.get("direction_id"), XSD.integer)

    for row in rows["STOP_TIMES"]:
        subject = _stop_time_uri(row)
        graph.add((subject, RDF.type, GTFS.StopTime))
        graph.add((subject, GTFS.trip, _trip_uri(row["trip_id"])))
        graph.add((subject, GTFS.stop, _stop_uri(row["stop_id"])))
        _add_literal(graph, subject, GTFS.arrivalTime, row.get("arrival_time"))
        _add_literal(graph, subject, GTFS.departureTime, row.get("departure_time"))
        _add_literal(graph, subject, GTFS.stopSequence, row.get("stop_sequence"), XSD.integer)
        _add_literal(graph, subject, GTFS.headsign, row.get("stop_headsign"))
        _add_literal(graph, subject, GTFS.distanceTraveled, row.get("shape_dist_traveled"), XSD.double)

    for row in rows["FREQUENCIES"]:
        subject = _frequency_uri(row)
        graph.add((subject, RDF.type, GTFS.Frequency))
        graph.add((subject, GTFS.trip, _trip_uri(row["trip_id"])))
        _add_literal(graph, subject, GTFS.startTime, row.get("start_time"))
        _add_literal(graph, subject, GTFS.endTime, row.get("end_time"))
        _add_literal(graph, subject, GTFS.headwaySeconds, row.get("headway_secs"), XSD.integer)

    summary = {
        "table_row_counts": {table: len(table_rows) for table, table_rows in rows.items()},
        "triple_count": len(graph),
        "shape_count": len(set(graph.subjects(RDF.type, GTFS.Shape))),
        "shape_point_count": len(set(graph.subjects(RDF.type, GTFS.ShapePoint))),
        "trip_count": len(set(graph.subjects(RDF.type, GTFS.Trip))),
        "stop_time_count": len(set(graph.subjects(RDF.type, GTFS.StopTime))),
        "stop_count": len(set(graph.subjects(RDF.type, GTFS.Stop))),
    }
    return graph, summary


def _query_graph(graph: Graph, query_path: Path) -> dict[str, Any]:
    query_text = query_path.read_text(encoding="utf-8")
    try:
        result_set = graph.query(query_text)
    except Exception as exc:
        return {
            "status": "failed",
            "assertions": [f"SPARQL query failed: {exc}"],
            "query_path": str(query_path),
            "query_sha256": _hash_text(query_text),
            "rows": [],
            "row_count": 0,
        }
    rows = [{str(variable): str(value) for variable, value in row.asdict().items()} for row in result_set]
    return {
        "status": "passed",
        "assertions": [],
        "query_path": str(query_path),
        "query_sha256": _hash_text(query_text),
        "variables": [str(variable) for variable in getattr(result_set, "vars", [])],
        "rows": rows[:10],
        "row_count": len(rows),
    }


def _run_join_probe(graph: Graph) -> dict[str, Any]:
    query_text = """
PREFIX gtfs: <http://vocab.gtfs.org/terms#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
SELECT ?trip ?routeName ?stopName ?sequence WHERE {
  ?stopTime a gtfs:StopTime ;
    gtfs:trip ?trip ;
    gtfs:stop ?stop ;
    gtfs:stopSequence ?sequence .
  ?trip gtfs:route ?route .
  ?route gtfs:shortName ?routeName .
  ?stop foaf:name ?stopName .
}
ORDER BY ?trip ?sequence
LIMIT 12
"""
    result_set = graph.query(query_text)
    rows = [{str(variable): str(value) for variable, value in row.asdict().items()} for row in result_set]
    assertions: list[str] = []
    if len(rows) < 6:
        assertions.append(f"Expected at least 6 route-trip-stop join rows, got {len(rows)}")
    if not all(row.get("routeName") and row.get("stopName") for row in rows):
        assertions.append("Route-trip-stop join rows must include routeName and stopName")
    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "query_sha256": _hash_text(query_text),
        "variables": [str(variable) for variable in getattr(result_set, "vars", [])],
        "rows": rows,
        "row_count": len(rows),
    }


def validate_gtfs_bench_official_materialization(
    *,
    source_dir: str | os.PathLike[str] | None = None,
    output_graph_path: str | os.PathLike[str] | None = None,
    adapted_mapping_path: str | os.PathLike[str] | None = None,
    sample_csv_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    assertions: list[str] = []
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    dataset_validation = validate_gtfs_bench_official_dataset_sample(source_dir)
    if dataset_validation["status"] != "passed":
        assertions.extend(dataset_validation.get("assertions") or [])

    try:
        sample = build_gtfs_bench_official_sample(source_dir)
        if sample_csv_dir:
            resolved_sample_csv_dir = Path(sample_csv_dir)
        else:
            temp_dir = tempfile.TemporaryDirectory()
            resolved_sample_csv_dir = Path(temp_dir.name) / "runtime-sample-csv"
        csv_artifacts = write_gtfs_bench_runtime_sample_csvs(sample, resolved_sample_csv_dir)

        mapping_validation = adapt_official_csv_mapping(
            source_dir=source_dir,
            sample_csv_dir=resolved_sample_csv_dir,
            output_path=adapted_mapping_path,
        )
        if mapping_validation["status"] != "passed":
            assertions.extend(mapping_validation.get("assertions") or [])

        graph, materialization_summary = materialize_gtfs_bench_official_graph(source_dir=source_dir, sample=sample)
        serialized_graph = graph.serialize(format="turtle")
        graph_path = Path(output_graph_path) if output_graph_path else None
        if graph_path is not None:
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            graph_path.write_text(serialized_graph, encoding="utf-8")

        graph_roundtrip = Graph()
        try:
            graph_roundtrip.parse(data=serialized_graph, format="turtle")
        except Exception as exc:
            assertions.append(f"Materialized graph is not parseable Turtle/RDF: {exc}")

        simple_q1_result = _query_graph(graph, Path(sample["required_paths"]["simple_query_q1"]))
        full_q1_result = _query_graph(graph, Path(sample["required_paths"]["full_query_q1"]))
        join_probe_result = _run_join_probe(graph)

        for label, result in (
            ("simple q1", simple_q1_result),
            ("full q1", full_q1_result),
            ("route-trip-stop join probe", join_probe_result),
        ):
            if result["status"] != "passed":
                assertions.extend(f"{label}: {assertion}" for assertion in result.get("assertions") or [])

        expected_shape_points = materialization_summary["table_row_counts"].get("SHAPES", 0)
        if simple_q1_result.get("row_count") != expected_shape_points:
            assertions.append(
                f"Simple q1 row count must equal SHAPES rows: {simple_q1_result.get('row_count')} != {expected_shape_points}"
            )
        if full_q1_result.get("row_count") != expected_shape_points:
            assertions.append(
                f"Full q1 row count must equal SHAPES rows: {full_q1_result.get('row_count')} != {expected_shape_points}"
            )
        if materialization_summary["triple_count"] <= expected_shape_points:
            assertions.append("Materialized graph should contain more triples than raw SHAPES rows")
    except Exception as exc:
        assertions.append(str(exc))
        sample = {}
        csv_artifacts = {}
        mapping_validation = {"status": "failed", "assertions": [str(exc)]}
        materialization_summary = {}
        graph_path = Path(output_graph_path) if output_graph_path else None
        serialized_graph = ""
        simple_q1_result = {"status": "failed", "assertions": [str(exc)], "row_count": 0}
        full_q1_result = {"status": "failed", "assertions": [str(exc)], "row_count": 0}
        join_probe_result = {"status": "failed", "assertions": [str(exc)], "row_count": 0}
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "source_dir": sample.get("source_dir") or str(source_dir or ""),
        "sample_csv_dir": str(sample_csv_dir or ""),
        "dataset_validation": dataset_validation,
        "mapping_validation": mapping_validation,
        "materialization": {
            **materialization_summary,
            "graph_path": str(graph_path) if graph_path else "",
            "graph_sha256": _hash_file(graph_path) if graph_path and graph_path.is_file() else _hash_text(serialized_graph),
            "runtime_sample_csvs": csv_artifacts,
        },
        "queries": {
            "simple_q1": simple_q1_result,
            "full_q1": full_q1_result,
            "route_trip_stop_join_probe": join_probe_result,
        },
    }


def run_gtfs_bench_official_materialization_validation(
    experiment_dir: str | os.PathLike[str] | None = None,
    *,
    source_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    started_at = datetime.now()
    component_dir = _component_dir(experiment_dir)
    graph_path = component_dir / "gtfs_bench_official_materialized.ttl" if component_dir else None
    adapted_mapping_path = component_dir / "gtfs-csv.adapted.rml.ttl" if component_dir else None
    sample_csv_dir = component_dir / "runtime-sample-csv" if component_dir else None
    validation = validate_gtfs_bench_official_materialization(
        source_dir=source_dir,
        output_graph_path=graph_path,
        adapted_mapping_path=adapted_mapping_path,
        sample_csv_dir=sample_csv_dir,
    )
    completed_at = datetime.now()
    if completed_at < started_at:
        completed_at = started_at

    case = {
        "test_case_id": "SV-GTFS-BENCH-03",
        "description": "Materialize and query a runtime sample derived from the official GTFS-Bench source",
        "type": "support",
        "case_group": "support",
        "validation_type": "functional",
        "dataspace_dimension": "official_dataset_materialization",
        "mapping_status": "mapped",
        "automation_mode": "offline_fixture",
        "execution_mode": "offline_fixture",
        "coverage_status": "automated",
        "evaluation": {
            "status": validation["status"],
            "assertions": list(validation.get("assertions") or []),
        },
        "evidence": validation,
        "expected_result": (
            "The source-derived GTFS-Bench runtime sample can be linked to the adapted official "
            "CSV mapping, materialized into RDF and queried with official shape queries."
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

    if component_dir:
        report_path = component_dir / "semantic_virtualization_gtfs_bench_official_materialization.json"
        report["artifacts"]["report_json"] = str(report_path)
        if graph_path:
            report["artifacts"]["materialized_graph"] = str(graph_path)
        if adapted_mapping_path:
            report["artifacts"]["adapted_mapping"] = str(adapted_mapping_path)
        if sample_csv_dir:
            report["artifacts"]["runtime_sample_csv_dir"] = str(sample_csv_dir)
        report["evidence_index"] = [
            {
                "scope": "suite",
                "suite": SUITE_NAME,
                "artifact_name": artifact_name,
                "path": artifact_path,
            }
            for artifact_name, artifact_path in report["artifacts"].items()
        ]
        _write_json(report_path, report)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize and query a runtime sample derived from the official GTFS-Bench source",
    )
    parser.add_argument("--experiment-dir", help="Experiment directory where evidence artifacts will be written")
    parser.add_argument("--source-dir", default="", help="Local clone of https://github.com/oeg-upm/gtfs-bench")
    args = parser.parse_args()

    report = run_gtfs_bench_official_materialization_validation(
        experiment_dir=args.experiment_dir,
        source_dir=args.source_dir or None,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
