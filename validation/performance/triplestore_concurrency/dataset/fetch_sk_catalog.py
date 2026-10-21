#!/usr/bin/env python3
"""Freeze a snapshot of real dataset metadata from the Slovak National Open Data Catalogue.

Queries the public SPARQL endpoint of data.slovensko.sk (DCAT-AP) and stores a JSON
snapshot under sources/sk-catalog/ that generate_assets.py turns into EDC assets offline.
The live catalogue changes over time, so the benchmark always runs from a committed
snapshot; this script only needs to run again to build a new one.

Selection (deterministic for a given catalogue state):
  * dataset has a Slovak title and a description, and one of the requested EU data themes
  * at least one distribution with a downloadURL, media type CSV or JSON, and terms of use
    licensing the author's work under CC BY 4.0 or CC0
  * per theme, datasets ordered by IRI, first --per-theme kept; a dataset listed under
    several themes is assigned to the first theme in --themes order
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://data.slovensko.sk/api/sparql"
THEME_NS = "http://publications.europa.eu/resource/authority/data-theme/"
LICENCES = [
    "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0",
    "http://publications.europa.eu/resource/authority/licence/CC0",
]
LEG = "https://data.gov.sk/def/ontology/legislation/"
PREFIXES = f"""PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX leg: <{LEG}>
"""
# A distribution qualifies when it is downloadable CSV/JSON under an open licence.
QUALIFYING_DISTRIBUTION = """
  ?x dcat:downloadURL ?dl ; dcat:mediaType ?mt ; leg:termsOfUse ?tou .
  ?tou leg:authorsWorkType ?lic .
  FILTER(?lic IN ({licences}))
  FILTER(STRENDS(STR(?mt), "/text/csv") || STRENDS(STR(?mt), "/application/json"))
""".format(licences=", ".join(f"<{iri}>" for iri in LICENCES))

CANDIDATES_QUERY = PREFIXES + """SELECT DISTINCT ?d WHERE {{
  ?d a dcat:Dataset ; dcat:theme <{theme}> ; dct:title ?t ; dct:description ?desc ; dcat:distribution ?x .
  FILTER(LANG(?t) = "sk")
""" + QUALIFYING_DISTRIBUTION + """}}
ORDER BY STR(?d)
LIMIT {limit}"""

DATASET_QUERY = PREFIXES + """SELECT ?d ?p ?o ?pubName WHERE {{
  VALUES ?d {{ {values} }}
  VALUES ?p {{ dct:title dct:description dcat:keyword dct:publisher dct:spatial dct:issued dct:modified
              dct:accrualPeriodicity dct:identifier dcat:landingPage dcat:theme
              <http://data.europa.eu/r5r/hvdCategory> }}
  ?d ?p ?o .
  OPTIONAL {{ FILTER(?p = dct:publisher) ?o foaf:name ?pubName }}
}}"""

DISTRIBUTION_QUERY = PREFIXES + """SELECT ?d ?x ?dl ?mt ?fmt ?lic ?personal ?title WHERE {{
  VALUES ?d {{ {values} }}
  ?d dcat:distribution ?x .
""" + QUALIFYING_DISTRIBUTION + """  OPTIONAL {{ ?x dct:format ?fmt }}
  OPTIONAL {{ ?x dct:title ?title }}
  OPTIONAL {{ ?tou leg:personalDataContainmentType ?personal }}
}}"""


def sparql(query: str, timeout: int) -> list[dict]:
    data = urllib.parse.urlencode({"query": query}).encode()
    request = urllib.request.Request(ENDPOINT, data=data, headers={
        "Accept": "application/sparql-results+json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "stics-validation-benchmark/1.0",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return [{k: v for k, v in row.items()} for row in payload["results"]["bindings"]]


def chunks(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def literal(binding: dict) -> tuple[str, str | None]:
    return binding["value"], binding.get("xml:lang")


def build_record(iri: str, theme: str, rows: list[dict], dists: list[dict]) -> dict:
    titles, descriptions, keywords = {}, {}, set()
    record: dict = {"iri": iri, "theme": theme, "themes": set(), "spatial": set(), "hvd_category": set()}
    for row in rows:
        prop, (value, lang) = row["p"]["value"], literal(row["o"])
        name = prop.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if name == "title":
            titles.setdefault(lang or "", value)
        elif name == "description":
            descriptions.setdefault(lang or "", value)
        elif name == "keyword" and lang in (None, "", "sk"):
            keywords.add(value.strip())
        elif name == "publisher":
            record["publisher"] = value
            if "pubName" in row:
                record["publisher_name"] = row["pubName"]["value"]
        elif name == "spatial":
            record["spatial"].add(value)
        elif name == "theme":
            record["themes"].add(value)
        elif name == "hvdCategory":
            record["hvd_category"].add(value)
        else:
            key = {"accrualPeriodicity": "accrual_periodicity", "landingPage": "landing_page"}.get(name, name)
            record.setdefault(key, value)

    # Deterministic choice among qualifying distributions: smallest downloadURL.
    best = min(dists, key=lambda r: (r["dl"]["value"], r["x"]["value"]))
    record.update({
        "title": titles,
        "description": descriptions,
        "keywords": sorted(k for k in keywords if k),
        "distribution": {
            "iri": best["x"]["value"],
            "download_url": best["dl"]["value"],
            "media_type": best["mt"]["value"].rsplit("media-types/", 1)[-1],
            "format": best.get("fmt", {}).get("value"),
            "licence": best["lic"]["value"],
            "personal_data_occurrence": best.get("personal", {}).get("value"),
            "title": best.get("title", {}).get("value"),
        },
    })
    for key in ("themes", "spatial", "hvd_category"):
        record[key] = sorted(record[key])
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--themes", default="TRAN,ENVI,ENER,ECON,GOVE,REGI",
                        help="EU data theme codes, in assignment order (default: %(default)s)")
    parser.add_argument("--per-theme", type=int, default=200, help="max datasets per theme (default: 200)")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parent / "sources" / "sk-catalog")
    args = parser.parse_args(argv)
    themes = [t.strip().upper() for t in args.themes.split(",") if t.strip()]
    retrieved = datetime.now(timezone.utc)

    queries, assigned, order = {}, {}, []
    for code in themes:
        query = CANDIDATES_QUERY.format(theme=THEME_NS + code, limit=args.per_theme)
        queries[f"candidates_{code}"] = query
        rows = sparql(query, args.timeout)
        fresh = [r["d"]["value"] for r in rows if r["d"]["value"] not in assigned]
        for iri in fresh:
            assigned[iri] = code
            order.append(iri)
        print(f"{code}: {len(rows)} candidates, {len(fresh)} assigned", file=sys.stderr)
    queries["dataset_details"] = DATASET_QUERY.format(values="?_")
    queries["distributions"] = DISTRIBUTION_QUERY.format(values="?_")

    details: dict[str, list[dict]] = {iri: [] for iri in order}
    distributions: dict[str, list[dict]] = {iri: [] for iri in order}
    for batch in chunks(order, 40):
        values = " ".join(f"<{iri}>" for iri in batch)
        for row in sparql(DATASET_QUERY.format(values=values), args.timeout):
            details[row["d"]["value"]].append(row)
        for row in sparql(DISTRIBUTION_QUERY.format(values=values), args.timeout):
            distributions[row["d"]["value"]].append(row)

    records = [build_record(iri, THEME_NS + assigned[iri], details[iri], distributions[iri])
               for iri in order if distributions[iri]]
    records_blob = json.dumps(records, sort_keys=True, ensure_ascii=False).encode()
    snapshot = {
        "source": "Národný katalóg otvorených dát (Slovak National Open Data Catalogue)",
        "endpoint": ENDPOINT,
        "retrieved_at": retrieved.isoformat(timespec="seconds"),
        "selection": {"themes": themes, "per_theme": args.per_theme, "licences": LICENCES,
                      "media_types": ["text/csv", "application/json"], "order": "STR(?dataset) ascending"},
        "queries": queries,
        "queries_sha256": hashlib.sha256(json.dumps(queries, sort_keys=True).encode()).hexdigest(),
        "record_count": len(records),
        "records_by_theme": {code: sum(1 for r in records if r["theme"] == THEME_NS + code) for code in themes},
        "records_sha256": hashlib.sha256(records_blob).hexdigest(),
        "records": records,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"snapshot-{retrieved.date().isoformat()}.json"
    path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(path)
    print(f"{len(records)} records {snapshot['records_by_theme']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
