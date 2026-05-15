from __future__ import annotations

import json
from pathlib import Path

from validation.components.semantic_virtualization.gtfs_bench_dataset import (
    GTFS_HEADERS,
    PRIMARY_TRIP_ID,
    RELATED_TRIP_ID,
)


def create_flares_source(root: str | Path) -> Path:
    source_dir = Path(root) / "flares-dataset"
    source_dir.mkdir(parents=True, exist_ok=True)
    trial_records = [
        {
            "Id": 463,
            "Text": "Con el Plan Nacional de Vacunacion se protege a los trabajadores de la salud.",
            "Reliability_Label": "confiable",
            "5W1H_Label": "WHO",
            "Tag_Text": "a los trabajadores de la salud",
            "Tag_Start": 47,
            "Tag_End": 77,
        },
        {
            "Id": 106,
            "Text": "Privar al cerebro de oxigeno no solo es peligroso sino absolutamente criminal.",
            "Reliability_Label": "no confiable",
            "5W1H_Label": "WHAT",
            "Tag_Text": "absolutamente criminal",
            "Tag_Start": 58,
            "Tag_End": 81,
        },
        {
            "Id": 113,
            "Text": "Sus cerebros tambien son activos porque tienen mucho que aprender.",
            "Reliability_Label": "semiconfiable",
            "5W1H_Label": "WHY",
            "Tag_Text": "porque tienen mucho que aprender",
            "Tag_Start": 34,
            "Tag_End": 63,
        },
    ]
    test_records = [
        {
            "Id": 157,
            "Text": "Texto de prueba no etiquetado.",
            "5W1H_Label": "WHAT",
            "Tag_Text": "Texto de prueba",
            "Tag_Start": 0,
            "Tag_End": 15,
        }
    ]
    (source_dir / "5w1h_subtask_2_trial.json").write_text(
        json.dumps(trial_records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (source_dir / "5w1h_subtarea_2_test.json").write_text(
        json.dumps(test_records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return source_dir


def _sql_value(value: str | int | None) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _insert_statement(table: str, rows: list[dict[str, str | int | None]]) -> str:
    headers = GTFS_HEADERS[table]
    values = []
    for row in rows:
        values.append("(" + ",".join(_sql_value(row.get(header)) for header in headers) + ")")
    return f"INSERT INTO `{table}` VALUES " + ",".join(values) + ";\n"


def create_gtfs_source(root: str | Path) -> Path:
    source_dir = Path(root) / "gtfs-bench"
    (source_dir / "generation" / "mysql_data").mkdir(parents=True, exist_ok=True)
    (source_dir / "mappings").mkdir(parents=True, exist_ok=True)
    (source_dir / "ontology").mkdir(parents=True, exist_ok=True)
    (source_dir / "queries" / "simple").mkdir(parents=True, exist_ok=True)
    (source_dir / "queries").mkdir(parents=True, exist_ok=True)

    shape_a = "4__1____1__IT_1"
    shape_b = "4__1____2__IT_1"
    stops_a = [f"stop-a-{index}" for index in range(1, 7)]
    stops_b = [f"stop-b-{index}" for index in range(1, 7)]
    stop_rows = [
        {
            "stop_id": stop_id,
            "stop_code": stop_id,
            "stop_name": f"Stop {stop_id}",
            "stop_desc": "",
            "stop_lat": f"40.{index:04d}",
            "stop_lon": f"-3.{index:04d}",
            "zone_id": "A",
            "stop_url": "",
            "location_type": "0",
            "parent_station": "",
            "stop_timezone": "",
            "wheelchair_boarding": "1",
        }
        for index, stop_id in enumerate(stops_a + stops_b, start=1)
    ]
    trip_rows = [
        {
            "route_id": "route-a",
            "service_id": "weekday",
            "trip_id": PRIMARY_TRIP_ID,
            "trip_headsign": "Route A",
            "trip_short_name": "",
            "direction_id": "0",
            "block_id": "",
            "shape_id": shape_a,
            "wheelchair_accessible": "1",
        },
        {
            "route_id": "route-b",
            "service_id": "weekday",
            "trip_id": RELATED_TRIP_ID,
            "trip_headsign": "Route B",
            "trip_short_name": "",
            "direction_id": "0",
            "block_id": "",
            "shape_id": shape_b,
            "wheelchair_accessible": "1",
        },
    ]
    stop_time_rows = []
    for trip_id, stop_ids, start_hour in ((PRIMARY_TRIP_ID, stops_a, 8), (RELATED_TRIP_ID, stops_b, 9)):
        for sequence, stop_id in enumerate(stop_ids, start=1):
            minute = (sequence - 1) * 4
            time_value = f"{start_hour:02d}:{minute:02d}:00"
            stop_time_rows.append(
                {
                    "trip_id": trip_id,
                    "arrival_time": time_value,
                    "departure_time": time_value,
                    "stop_id": stop_id,
                    "stop_sequence": str(sequence),
                    "stop_headsign": "",
                    "pickup_type": "0",
                    "drop_off_type": "0",
                    "shape_dist_traveled": str(sequence),
                }
            )
    shape_rows = []
    for shape_id in (shape_a, shape_b):
        for sequence in range(1, 9):
            shape_rows.append(
                {
                    "shape_id": shape_id,
                    "shape_pt_lat": f"40.{sequence:04d}",
                    "shape_pt_lon": f"-3.{sequence:04d}",
                    "shape_pt_sequence": str(sequence),
                    "shape_dist_traveled": str(sequence),
                }
            )

    rows_by_table: dict[str, list[dict[str, str | int | None]]] = {
        "AGENCY": [
            {
                "agency_id": "agency",
                "agency_name": "Madrid Transit",
                "agency_url": "https://example.test",
                "agency_timezone": "Europe/Madrid",
                "agency_lang": "es",
                "agency_phone": "",
                "agency_fare_url": "",
            }
        ],
        "CALENDAR": [
            {
                "service_id": "weekday",
                "monday": "1",
                "tuesday": "1",
                "wednesday": "1",
                "thursday": "1",
                "friday": "1",
                "saturday": "0",
                "sunday": "0",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
            }
        ],
        "CALENDAR_DATES": [{"service_id": "weekday", "date": "2026-01-01", "exception_type": "1"}],
        "FEED_INFO": [
            {
                "feed_publisher_name": "PIONERA",
                "feed_publisher_url": "https://example.test",
                "feed_lang": "es",
                "feed_start_date": "2026-01-01",
                "feed_end_date": "2026-12-31",
                "feed_version": "test",
            }
        ],
        "FREQUENCIES": [
            {
                "trip_id": PRIMARY_TRIP_ID,
                "start_time": "08:00:00",
                "end_time": "09:00:00",
                "headway_secs": "600",
                "exact_times": "0",
            },
            {
                "trip_id": RELATED_TRIP_ID,
                "start_time": "09:00:00",
                "end_time": "10:00:00",
                "headway_secs": "600",
                "exact_times": "0",
            },
        ],
        "ROUTES": [
            {
                "route_id": "route-a",
                "agency_id": "agency",
                "route_short_name": "A",
                "route_long_name": "Route A",
                "route_desc": "",
                "route_type": "1",
                "route_url": "",
                "route_color": "",
                "route_text_color": "",
            },
            {
                "route_id": "route-b",
                "agency_id": "agency",
                "route_short_name": "B",
                "route_long_name": "Route B",
                "route_desc": "",
                "route_type": "1",
                "route_url": "",
                "route_color": "",
                "route_text_color": "",
            },
        ],
        "SHAPES": shape_rows,
        "STOPS": stop_rows,
        "STOP_TIMES": stop_time_rows,
        "TRIPS": trip_rows,
    }
    dump_text = "".join(_insert_statement(table, rows_by_table[table]) for table in GTFS_HEADERS)
    (source_dir / "generation" / "mysql_data" / "dump-gtfs-new.sql").write_text(dump_text, encoding="utf-8")

    triples_maps = []
    logical_sources = []
    for index, csv_file in enumerate([f"{table}.csv" for table in GTFS_HEADERS], start=1):
        logical_sources.append(
            f"<#logical-source-{index}> a rml:LogicalSource ; rml:source \"/data/{csv_file}\" ."
        )
    for index in range(1, 14):
        triples_maps.append(f"<#triples-map-{index}> a rr:TriplesMap .")
    (source_dir / "mappings" / "gtfs-csv.rml.ttl").write_text(
        "\n".join(
            [
                "@prefix rml: <http://semweb.mmlab.be/ns/rml#> .",
                "@prefix rr: <http://www.w3.org/ns/r2rml#> .",
                *logical_sources,
                *triples_maps,
            ]
        ),
        encoding="utf-8",
    )
    (source_dir / "ontology" / "gtfs.ttl").write_text(
        "@prefix gtfs: <http://vocab.gtfs.org/terms#> . gtfs:Shape a gtfs:Class .",
        encoding="utf-8",
    )
    q1 = """
PREFIX gtfs: <http://vocab.gtfs.org/terms#>
PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#>
SELECT ?shape ?shapePoint ?lat ?long WHERE {
  ?shape gtfs:shapePoint ?shapePoint .
  ?shapePoint geo:lat ?lat ;
    geo:long ?long .
}
ORDER BY ?shape ?shapePoint
"""
    (source_dir / "queries" / "simple" / "q1.rq").write_text(q1.strip() + "\n", encoding="utf-8")
    (source_dir / "queries" / "q1.rq").write_text(q1.strip() + "\n", encoding="utf-8")
    (source_dir / "README.md").write_text("# GTFS Bench\n", encoding="utf-8")
    (source_dir / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    return source_dir
