from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from validation.components.semantic_virtualization.gtfs_bench_official import (
    DEFAULT_SOURCE_DIR,
    GTFS_BENCH_REPOSITORY,
)


COMPONENT_KEY = "semantic-virtualization"
SUITE_NAME = "gtfs-bench-official-mini"
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "gtfs-bench-official-mini"
DEFAULT_DUMP_PATH = DEFAULT_SOURCE_DIR / "generation" / "mysql_data" / "dump-gtfs-new.sql"

PRIMARY_TRIP_ID = "4_I12-001_2016I12_1_1_4__1___"
RELATED_TRIP_ID = "4_I12-001_2016I12_2_1_4__1___"

GTFS_HEADERS: dict[str, list[str]] = {
    "AGENCY": [
        "agency_id",
        "agency_name",
        "agency_url",
        "agency_timezone",
        "agency_lang",
        "agency_phone",
        "agency_fare_url",
    ],
    "CALENDAR": [
        "service_id",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "start_date",
        "end_date",
    ],
    "CALENDAR_DATES": ["service_id", "date", "exception_type"],
    "FEED_INFO": [
        "feed_publisher_name",
        "feed_publisher_url",
        "feed_lang",
        "feed_start_date",
        "feed_end_date",
        "feed_version",
    ],
    "FREQUENCIES": ["trip_id", "start_time", "end_time", "headway_secs", "exact_times"],
    "ROUTES": [
        "route_id",
        "agency_id",
        "route_short_name",
        "route_long_name",
        "route_desc",
        "route_type",
        "route_url",
        "route_color",
        "route_text_color",
    ],
    "SHAPES": ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence", "shape_dist_traveled"],
    "STOPS": [
        "stop_id",
        "stop_code",
        "stop_name",
        "stop_desc",
        "stop_lat",
        "stop_lon",
        "zone_id",
        "stop_url",
        "location_type",
        "parent_station",
        "stop_timezone",
        "wheelchair_boarding",
    ],
    "STOP_TIMES": [
        "trip_id",
        "arrival_time",
        "departure_time",
        "stop_id",
        "stop_sequence",
        "stop_headsign",
        "pickup_type",
        "drop_off_type",
        "shape_dist_traveled",
    ],
    "TRIPS": [
        "route_id",
        "service_id",
        "trip_id",
        "trip_headsign",
        "trip_short_name",
        "direction_id",
        "block_id",
        "shape_id",
        "wheelchair_accessible",
    ],
}

EXPECTED_CSV_FILES = tuple(f"{table}.csv" for table in GTFS_HEADERS)


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


def _split_sql_tuples(values: str) -> list[str]:
    tuples: list[str] = []
    start: int | None = None
    depth = 0
    in_quote = False
    escape = False

    for index, char in enumerate(values):
        if escape:
            escape = False
            continue
        if in_quote and char == "\\":
            escape = True
            continue
        if char == "'":
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if char == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and start is not None:
                tuples.append(values[start:index])
                start = None

    return tuples


def _parse_sql_tuple(tuple_content: str) -> list[str | None]:
    values: list[str | None] = []
    token: list[str] = []
    in_quote = False
    escape = False
    quoted_token = False

    def flush() -> None:
        raw = "".join(token)
        normalized = raw if quoted_token else raw.strip()
        if not quoted_token and normalized.upper() == "NULL":
            values.append(None)
        else:
            values.append(normalized)

    index = 0
    while index < len(tuple_content):
        char = tuple_content[index]
        if escape:
            token.append(char)
            escape = False
            index += 1
            continue
        if in_quote and char == "\\":
            escape = True
            index += 1
            continue
        if char == "'":
            if in_quote and index + 1 < len(tuple_content) and tuple_content[index + 1] == "'":
                token.append("'")
                index += 2
                continue
            in_quote = not in_quote
            quoted_token = True
            index += 1
            continue
        if char == "," and not in_quote:
            flush()
            token = []
            quoted_token = False
            index += 1
            continue
        token.append(char)
        index += 1

    flush()
    return values


def parse_insert_rows(sql_path: str | os.PathLike[str], table: str) -> list[dict[str, str | None]]:
    dump_path = Path(sql_path)
    content = dump_path.read_text(encoding="utf-8")
    matches = list(re.finditer(rf"INSERT INTO `{re.escape(table)}` VALUES (.*?);", content, flags=re.DOTALL))
    if not matches:
        raise RuntimeError(f"Could not find INSERT data for table {table} in {dump_path}")

    headers = GTFS_HEADERS[table]
    rows: list[dict[str, str | None]] = []
    for match in matches:
        for tuple_content in _split_sql_tuples(match.group(1)):
            values = _parse_sql_tuple(tuple_content)
            if len(values) != len(headers):
                raise RuntimeError(
                    f"Table {table} row has {len(values)} values, expected {len(headers)}: {tuple_content[:120]}"
                )
            rows.append(dict(zip(headers, values)))
    return rows


def _sequence_value(value: str | None) -> int:
    if value in (None, ""):
        return 999999999
    try:
        return int(float(value))
    except ValueError:
        return 999999999


def _select_first_matching(
    rows: list[dict[str, str | None]],
    field: str,
    values: set[str | None],
) -> list[dict[str, str | None]]:
    return [row for row in rows if row.get(field) in values]


def _limited_sorted(
    rows: list[dict[str, str | None]],
    field: str,
    *,
    limit: int,
) -> list[dict[str, str | None]]:
    return sorted(rows, key=lambda row: _sequence_value(row.get(field)))[:limit]


def _build_mini_selection(dump_path: Path) -> dict[str, list[dict[str, str | None]]]:
    agencies = parse_insert_rows(dump_path, "AGENCY")
    calendars = parse_insert_rows(dump_path, "CALENDAR")
    calendar_dates = parse_insert_rows(dump_path, "CALENDAR_DATES")
    feed_info = parse_insert_rows(dump_path, "FEED_INFO")
    frequencies = parse_insert_rows(dump_path, "FREQUENCIES")
    routes = parse_insert_rows(dump_path, "ROUTES")
    shapes = parse_insert_rows(dump_path, "SHAPES")
    stops = parse_insert_rows(dump_path, "STOPS")
    stop_times = parse_insert_rows(dump_path, "STOP_TIMES")
    trips = parse_insert_rows(dump_path, "TRIPS")

    selected_trip_ids = {PRIMARY_TRIP_ID, RELATED_TRIP_ID}
    selected_trips = [row for row in trips if row["trip_id"] in selected_trip_ids]
    if len(selected_trips) != len(selected_trip_ids):
        missing = sorted(selected_trip_ids - {str(row["trip_id"]) for row in selected_trips})
        raise RuntimeError(f"Could not build GTFS mini fixture; missing expected trips: {missing}")

    selected_route_ids = {row["route_id"] for row in selected_trips}
    selected_service_ids = {row["service_id"] for row in selected_trips}
    selected_shape_ids = {row["shape_id"] for row in selected_trips}

    selected_stop_times: list[dict[str, str | None]] = []
    for trip_id in sorted(selected_trip_ids):
        trip_stop_times = [row for row in stop_times if row["trip_id"] == trip_id and row["stop_sequence"] is not None]
        selected_stop_times.extend(_limited_sorted(trip_stop_times, "stop_sequence", limit=6))

    selected_stop_ids = {row["stop_id"] for row in selected_stop_times}
    selected_stops = _select_first_matching(stops, "stop_id", selected_stop_ids)

    # Include referenced parent stations when present so joins in the official mapping remain coherent.
    parent_station_ids = {row["parent_station"] for row in selected_stops if row.get("parent_station")}
    if parent_station_ids:
        known_stop_ids = {row["stop_id"] for row in selected_stops}
        selected_stops.extend(
            row for row in _select_first_matching(stops, "stop_id", parent_station_ids) if row["stop_id"] not in known_stop_ids
        )

    selected_shapes: list[dict[str, str | None]] = []
    for shape_id in sorted(selected_shape_ids):
        shape_rows = [row for row in shapes if row["shape_id"] == shape_id]
        selected_shapes.extend(_limited_sorted(shape_rows, "shape_pt_sequence", limit=8))

    selected_routes = _select_first_matching(routes, "route_id", selected_route_ids)
    selected_agency_ids = {row["agency_id"] for row in selected_routes}
    selected_agencies = _select_first_matching(agencies, "agency_id", selected_agency_ids)
    selected_calendars = _select_first_matching(calendars, "service_id", selected_service_ids)
    selected_calendar_dates = _limited_sorted(
        _select_first_matching(calendar_dates, "service_id", selected_service_ids),
        "date",
        limit=4,
    )
    selected_frequencies: list[dict[str, str | None]] = []
    for trip_id in sorted(selected_trip_ids):
        selected_frequencies.extend(
            _limited_sorted([row for row in frequencies if row["trip_id"] == trip_id], "start_time", limit=3)
        )

    selected = {
        "AGENCY": selected_agencies,
        "CALENDAR": selected_calendars,
        "CALENDAR_DATES": selected_calendar_dates,
        "FEED_INFO": feed_info[:1],
        "FREQUENCIES": selected_frequencies,
        "ROUTES": selected_routes,
        "SHAPES": selected_shapes,
        "STOPS": sorted(selected_stops, key=lambda row: str(row["stop_id"])),
        "STOP_TIMES": sorted(
            selected_stop_times,
            key=lambda row: (str(row["trip_id"]), _sequence_value(row["stop_sequence"]), str(row["stop_id"])),
        ),
        "TRIPS": sorted(selected_trips, key=lambda row: str(row["trip_id"])),
    }

    empty_tables = [table for table, rows in selected.items() if not rows]
    if empty_tables:
        raise RuntimeError(f"Could not build GTFS mini fixture; empty selected tables: {', '.join(empty_tables)}")
    return selected


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: "" if row.get(header) is None else row.get(header) for header in headers})


def _write_readme(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# GTFS-Bench Official Mini",
                "",
                "`gtfs-bench-official-mini` is a small, deterministic CSV slice derived",
                "from the official `oeg-upm/gtfs-bench` repository resources.",
                "",
                "It keeps the full official benchmark out of default validation runs, while",
                "preserving traceability to the upstream dump, ontology, CSV RML mapping and",
                "SPARQL query catalog.",
                "",
                "## Intended Use",
                "",
                "- validate that Semantic Virtualization can work with official GTFS-Bench shaped CSV files;",
                "- provide a stable mapping-editor and API fixture for A5.2 evidence;",
                "- keep Docker/MySQL/full benchmark generation as an explicit maintenance activity outside Level 6;",
                "- support future INESData HttpData demos without publishing the full dataset by default.",
                "",
                "## Regeneration",
                "",
                "Run:",
                "",
                "```bash",
                "python3 validation/components/semantic_virtualization/gtfs_bench_mini.py --regenerate",
                "```",
                "",
                "The local upstream clone is expected at `adapters/inesdata/sources/gtfs-bench`.",
                "Review upstream data rights before publishing evidence outside the validation workspace.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _copy_reference_artifacts(source_dir: Path, fixture_dir: Path) -> dict[str, str]:
    references_dir = fixture_dir / "references"
    references_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "ontology": source_dir / "ontology" / "gtfs.ttl",
        "csv_mapping": source_dir / "mappings" / "gtfs-csv.rml.ttl",
        "simple_query_q1": source_dir / "queries" / "simple" / "q1.rq",
        "full_query_q1": source_dir / "queries" / "q1.rq",
    }
    target_names = {
        "ontology": "gtfs.ttl",
        "csv_mapping": "gtfs-csv.rml.ttl",
        "simple_query_q1": "simple-q1.rq",
        "full_query_q1": "full-q1.rq",
    }
    copied: dict[str, str] = {}
    for key, source_path in artifacts.items():
        if not source_path.is_file():
            continue
        target_path = references_dir / target_names[key]
        shutil.copyfile(source_path, target_path)
        copied[key] = str(target_path.relative_to(fixture_dir))
    return copied


def generate_gtfs_bench_official_mini_fixture(
    *,
    source_dir: str | os.PathLike[str] | None = None,
    fixture_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    resolved_source_dir = Path(source_dir or DEFAULT_SOURCE_DIR).resolve()
    resolved_fixture_dir = Path(fixture_dir or DEFAULT_FIXTURE_DIR).resolve()
    dump_path = resolved_source_dir / "generation" / "mysql_data" / "dump-gtfs-new.sql"
    if not dump_path.is_file():
        raise RuntimeError(f"Official GTFS-Bench dump is missing: {dump_path}")

    selected = _build_mini_selection(dump_path)
    csv_dir = resolved_fixture_dir / "csv"
    for generated_subdir in (csv_dir, resolved_fixture_dir / "references"):
        if generated_subdir.exists():
            shutil.rmtree(generated_subdir)
    for table, rows in selected.items():
        _write_csv(csv_dir / f"{table}.csv", GTFS_HEADERS[table], rows)

    copied_references = _copy_reference_artifacts(resolved_source_dir, resolved_fixture_dir)
    _write_readme(resolved_fixture_dir / "README.md")

    commit = _git_output(resolved_source_dir, ["rev-parse", "HEAD"])
    remote = _git_output(resolved_source_dir, ["config", "--get", "remote.origin.url"])
    hashes = {
        str(path.relative_to(resolved_fixture_dir)): _hash_file(path)
        for path in sorted(csv_dir.glob("*.csv"))
        if path.is_file()
    }
    hashes.update(
        {
            str(path.relative_to(resolved_fixture_dir)): _hash_file(path)
            for path in sorted((resolved_fixture_dir / "references").glob("*"))
            if path.is_file()
        }
    )

    manifest = {
        "datasetName": "GTFS-Bench-official-mini",
        "domain": "mobility",
        "task": "Semantic Virtualization official GTFS-Bench mini fixture",
        "format": "text/csv",
        "version": "official-mini-v1",
        "generatedAt": datetime.now().isoformat(),
        "source": {
            "name": "GTFS-Madrid-Bench",
            "repository": GTFS_BENCH_REPOSITORY,
            "remote": remote or GTFS_BENCH_REPOSITORY,
            "commit": commit,
            "dump": "generation/mysql_data/dump-gtfs-new.sql",
            "mapping": "mappings/gtfs-csv.rml.ttl",
            "ontology": "ontology/gtfs.ttl",
            "queries": ["queries/simple/q1.rq", "queries/q1.rq"],
            "license": "Apache-2.0 repository license; review upstream data terms before external publication.",
        },
        "selection": {
            "objective": "Small, deterministic slice for A5.2 Semantic Virtualization tests and demos.",
            "primaryTripId": PRIMARY_TRIP_ID,
            "relatedTripId": RELATED_TRIP_ID,
            "entities": list(GTFS_HEADERS.keys()),
            "recordCounts": {table: len(rows) for table, rows in selected.items()},
            "notes": [
                "The slice preserves GTFS joins across agency, route, service, trip, stop times, stops and shapes.",
                "The full official generator is kept as an explicit maintenance activity outside Level 6 because it requires MySQL/Docker-style runtime services.",
                "This fixture is intentionally small and does not replace the complete benchmark.",
            ],
        },
        "files": {
            "csvDirectory": "csv",
            "csvFiles": list(EXPECTED_CSV_FILES),
            "references": copied_references,
        },
        "hashes": hashes,
    }
    _write_json(resolved_fixture_dir / "manifest.json", manifest)
    return validate_gtfs_bench_official_mini_fixture(resolved_fixture_dir)


def validate_gtfs_bench_official_mini_fixture(
    fixture_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    resolved_fixture_dir = Path(fixture_dir or DEFAULT_FIXTURE_DIR).resolve()
    assertions: list[str] = []
    csv_dir = resolved_fixture_dir / "csv"
    manifest_path = resolved_fixture_dir / "manifest.json"
    manifest: dict[str, Any] = {}

    if not manifest_path.is_file():
        assertions.append(f"GTFS-Bench official mini manifest is missing: {manifest_path}")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            assertions.append(f"GTFS-Bench official mini manifest is not valid JSON: {exc}")

    csv_summaries: dict[str, dict[str, Any]] = {}
    for table, expected_headers in GTFS_HEADERS.items():
        csv_path = csv_dir / f"{table}.csv"
        if not csv_path.is_file():
            assertions.append(f"Missing GTFS mini CSV file: {csv_path}")
            continue
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        if not rows:
            assertions.append(f"GTFS mini CSV file is empty: {csv_path}")
            continue
        if rows[0] != expected_headers:
            assertions.append(f"{csv_path.name} header mismatch: {rows[0]} != {expected_headers}")
        if len(rows) <= 1:
            assertions.append(f"{csv_path.name} has no data rows")
        csv_summaries[table] = {
            "path": str(csv_path),
            "header": rows[0],
            "row_count": max(0, len(rows) - 1),
            "sha256": _hash_file(csv_path),
        }

    hashes = manifest.get("hashes") or {}
    for relative_path, expected_hash in hashes.items():
        path = resolved_fixture_dir / relative_path
        if not path.is_file():
            assertions.append(f"Manifest hash references missing file: {relative_path}")
            continue
        actual_hash = _hash_file(path)
        if actual_hash != expected_hash:
            assertions.append(f"Hash mismatch for {relative_path}: {actual_hash} != {expected_hash}")

    record_counts = ((manifest.get("selection") or {}).get("recordCounts") or {}) if manifest else {}
    for table in ("AGENCY", "ROUTES", "TRIPS", "STOP_TIMES", "STOPS", "SHAPES"):
        if int(record_counts.get(table) or 0) <= 0:
            assertions.append(f"Manifest record count for {table} must be greater than zero")

    def load_csv_dicts(table: str) -> list[dict[str, str]]:
        path = csv_dir / f"{table}.csv"
        if not path.is_file():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    agencies = load_csv_dicts("AGENCY")
    calendars = load_csv_dicts("CALENDAR")
    routes = load_csv_dicts("ROUTES")
    shapes = load_csv_dicts("SHAPES")
    stops = load_csv_dicts("STOPS")
    stop_times = load_csv_dicts("STOP_TIMES")
    trips = load_csv_dicts("TRIPS")

    agency_ids = {row["agency_id"] for row in agencies}
    service_ids = {row["service_id"] for row in calendars}
    route_ids = {row["route_id"] for row in routes}
    shape_ids = {row["shape_id"] for row in shapes}
    stop_ids = {row["stop_id"] for row in stops}
    trip_ids = {row["trip_id"] for row in trips}

    for row in routes:
        if row["agency_id"] not in agency_ids:
            assertions.append(f"ROUTES.csv references missing agency_id {row['agency_id']}")
    for row in trips:
        if row["route_id"] not in route_ids:
            assertions.append(f"TRIPS.csv references missing route_id {row['route_id']}")
        if row["service_id"] not in service_ids:
            assertions.append(f"TRIPS.csv references missing service_id {row['service_id']}")
        if row["shape_id"] not in shape_ids:
            assertions.append(f"TRIPS.csv references missing shape_id {row['shape_id']}")
    for row in stop_times:
        if row["trip_id"] not in trip_ids:
            assertions.append(f"STOP_TIMES.csv references missing trip_id {row['trip_id']}")
        if row["stop_id"] not in stop_ids:
            assertions.append(f"STOP_TIMES.csv references missing stop_id {row['stop_id']}")
    for row in stops:
        parent_station = row.get("parent_station") or ""
        if parent_station and parent_station not in stop_ids:
            assertions.append(f"STOPS.csv references missing parent_station {parent_station}")

    if manifest:
        source = manifest.get("source") or {}
        if source.get("repository") != GTFS_BENCH_REPOSITORY:
            assertions.append("Manifest does not point to the official GTFS-Bench repository")
        if not source.get("commit"):
            assertions.append("Manifest does not record the official GTFS-Bench source commit")
        if manifest.get("datasetName") != "GTFS-Bench-official-mini":
            assertions.append("Manifest datasetName must be GTFS-Bench-official-mini")

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "fixture_dir": str(resolved_fixture_dir),
        "dataset_name": manifest.get("datasetName") if manifest else "",
        "source": manifest.get("source") if manifest else {},
        "selection": manifest.get("selection") if manifest else {},
        "csv_summaries": csv_summaries,
    }


def run_gtfs_bench_official_mini_validation(
    experiment_dir: str | os.PathLike[str] | None = None,
    *,
    source_dir: str | os.PathLike[str] | None = None,
    fixture_dir: str | os.PathLike[str] | None = None,
    regenerate: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now()
    if regenerate:
        validation = generate_gtfs_bench_official_mini_fixture(source_dir=source_dir, fixture_dir=fixture_dir)
    else:
        validation = validate_gtfs_bench_official_mini_fixture(fixture_dir)
    completed_at = datetime.now()
    if completed_at < started_at:
        completed_at = started_at

    case = {
        "test_case_id": "SV-GTFS-BENCH-02",
        "description": "Validate a mini fixture derived from official GTFS-Madrid-Bench resources",
        "type": "support",
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "official_dataset_traceability",
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
            "The framework has a small reproducible GTFS-Bench CSV fixture derived from "
            "official resources, with manifest, hashes and join-preserving GTFS tables."
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
        report_path = component_dir / "semantic_virtualization_gtfs_bench_official_mini.json"
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
        description="Generate or validate the official-derived GTFS-Bench mini fixture",
    )
    parser.add_argument("--experiment-dir", help="Experiment directory where evidence artifacts will be written")
    parser.add_argument("--source-dir", default="", help="Local clone of https://github.com/oeg-upm/gtfs-bench")
    parser.add_argument("--fixture-dir", default="", help="Fixture directory to validate or regenerate")
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Regenerate the mini fixture from the official dump before validation",
    )
    args = parser.parse_args()

    report = run_gtfs_bench_official_mini_validation(
        experiment_dir=args.experiment_dir,
        source_dir=args.source_dir or None,
        fixture_dir=args.fixture_dir or None,
        regenerate=args.regenerate,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
