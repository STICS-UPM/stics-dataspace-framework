#!/usr/bin/env python3
"""Deterministic generator of EDC assets for the store-concurrency benchmark.

Two sources:
  * sk-catalog (default): real dataset metadata from a committed snapshot of the Slovak
    National Open Data Catalogue (see fetch_sk_catalog.py). Assets are taken round-robin
    across the snapshot themes, keeping the original DCAT-AP metadata and provenance.
  * synthetic: STICS-like metadata drawn from a seeded RNG (no snapshot needed, any size).

Produces the EDC Management API v3 payloads used by the JMeter plans (create + update
variant per asset), a CSV index for JMeter's CSV Data Set Config and a manifest with
SHA-256 hashes so that any run can prove which dataset it used.

Metadata uses DCAT / Dublin Core terms (the vocabulary exposed through the DSP catalog),
so the same assets are readable by any IDSA/DSP-compliant participant.

Only the standard library is used; output is byte-identical for the same arguments.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

GENERATOR_VERSION = "2.0.0"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "sources" / "sk-catalog"
SYNTHETIC_DATA_BASE_URL = "https://jsonplaceholder.typicode.com/todos"

EDC_NS = "https://w3id.org/edc/v0.0.1/ns/"
CONTEXT = {
    "@vocab": EDC_NS,
    "dct": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
}

# Synthetic STICS domains: (theme code, label, EU data theme IRI, keywords, dataset nouns)
DOMAINS = [
    ("mobility", "Mobility", "http://publications.europa.eu/resource/authority/data-theme/TRAN",
     ["traffic", "public transport", "gtfs", "parking", "bike sharing"],
     ["traffic counts", "bus stop events", "parking occupancy", "bike station availability"]),
    ("energy", "Energy", "http://publications.europa.eu/resource/authority/data-theme/ENER",
     ["smart meter", "consumption", "photovoltaic", "grid"],
     ["building energy consumption", "photovoltaic production", "street lighting load"]),
    ("environment", "Environment", "http://publications.europa.eu/resource/authority/data-theme/ENVI",
     ["air quality", "noise", "weather", "emissions"],
     ["air quality measurements", "noise levels", "weather station readings"]),
    ("tourism", "Tourism", "http://publications.europa.eu/resource/authority/data-theme/ECON",
     ["visitors", "accommodation", "events", "points of interest"],
     ["visitor flows", "accommodation occupancy", "cultural events agenda"]),
    ("urban", "Urban services", "http://publications.europa.eu/resource/authority/data-theme/GOVE",
     ["waste", "water", "citizen requests", "infrastructure"],
     ["waste container fill levels", "water network telemetry", "citizen service requests"]),
]

CITIES = ["Madrid", "Valencia", "Zaragoza", "Sevilla", "Bilbao", "Malaga", "Valladolid", "Murcia"]
PUBLISHERS = ["STICS City Council", "STICS Mobility Operator", "STICS Energy Utility",
              "STICS Research Lab", "STICS Tourism Board"]
FORMATS = [("application/json", "JSON"), ("text/csv", "CSV"), ("application/ld+json", "JSON-LD")]
LICENSES = [
    "https://creativecommons.org/licenses/by/4.0/",
    "https://creativecommons.org/licenses/by-sa/4.0/",
    "https://creativecommons.org/publicdomain/zero/1.0/",
]
PERIODICITY = ["hourly", "daily", "weekly", "monthly"]
BASE_DATE = date(2024, 1, 1)


def build_asset(index: int, rng: random.Random, args: argparse.Namespace) -> tuple[str, dict, dict]:
    asset_id = f"{args.id_prefix}-{index:04d}"
    code, label, theme_iri, keywords, nouns = DOMAINS[index % len(DOMAINS)]
    noun = rng.choice(nouns)
    city = rng.choice(CITIES)
    media_type, fmt = rng.choice(FORMATS)
    issued = BASE_DATE + timedelta(days=rng.randrange(0, 730))
    title = f"{noun.capitalize()} - {city}"
    description = (
        f"Synthetic STICS {label.lower()} dataset with {noun} for {city}, "
        f"published {rng.choice(PERIODICITY)} for data space benchmarking."
    )

    properties = {
        "name": title,
        "version": "1.0.0",
        "shortDescription": description[:120],
        "assetType": "dataset",
        "contenttype": media_type,
        "dct:title": title,
        "dct:description": description,
        "dct:identifier": asset_id,
        "dct:publisher": rng.choice(PUBLISHERS),
        "dct:issued": issued.isoformat(),
        "dct:license": rng.choice(LICENSES),
        "dct:format": fmt,
        "dct:spatial": city,
        "dcat:theme": theme_iri,
        "dcat:keyword": sorted(rng.sample(keywords, k=min(3, len(keywords))) + ["stics", code]),
        "dcat:mediaType": media_type,
    }
    create = {
        "@context": CONTEXT,
        "@id": asset_id,
        "@type": "Asset",
        "properties": properties,
        "dataAddress": {
            "type": "HttpData",
            "baseUrl": f"{(args.data_base_url or SYNTHETIC_DATA_BASE_URL).rstrip('/')}/{index % 200 + 1}",
            "name": asset_id,
        },
    }

    # Update variant: same id, bumped version and modified metadata (for PUT /v3/assets).
    update = json.loads(json.dumps(create))
    update["properties"]["version"] = "1.1.0"
    update["properties"]["dct:modified"] = (issued + timedelta(days=rng.randrange(1, 90))).isoformat()
    update["properties"]["dct:description"] = description + " Updated revision."
    return asset_id, create, update


def select_round_robin(snapshot: dict, count: int) -> list[dict]:
    """Interleave snapshot records by theme (selection order) so any prefix is theme-balanced."""
    theme_ns = "http://publications.europa.eu/resource/authority/data-theme/"
    queues = [[r for r in snapshot["records"] if r["theme"] == theme_ns + code]
              for code in snapshot["selection"]["themes"]]
    selected = []
    while len(selected) < count and any(queues):
        for queue in queues:
            if queue and len(selected) < count:
                selected.append(queue.pop(0))
    if len(selected) < count:
        raise SystemExit(f"snapshot has only {len(selected)} records, --count {count} requested")
    return selected


def build_sk_asset(index: int, record: dict, args: argparse.Namespace,
                   retrieved: str) -> tuple[str, dict, dict]:
    asset_id = f"{args.id_prefix}-{index:04d}"
    title = record["title"].get("sk") or next(iter(record["title"].values()))
    description = record["description"].get("sk") or next(iter(record["description"].values()))
    dist = record["distribution"]
    properties = {
        "name": title,
        "version": "1.0.0",
        "shortDescription": description[:120],
        "assetType": "dataset",
        "contenttype": dist["media_type"],
        "dct:title": title,
        "dct:description": description,
        "dct:identifier": record.get("identifier") or record["iri"],
        "dct:source": record["iri"],
        "dct:language": "http://publications.europa.eu/resource/authority/language/SLK",
        "dct:publisher": record["publisher_name"],
        "dct:license": dist["licence"],
        "dcat:theme": record["theme"],
        "dcat:keyword": record["keywords"][:10],
        "dcat:mediaType": dist["media_type"],
        "dcat:downloadURL": dist["download_url"],
    }
    if "en" in record["title"]:
        properties["dct:alternative"] = record["title"]["en"]
    optional = {"dct:issued": "issued", "dct:modified": "modified",
                "dct:accrualPeriodicity": "accrual_periodicity", "dcat:landingPage": "landing_page",
                "dct:format": None}
    for prop, key in optional.items():
        value = dist.get("format") if prop == "dct:format" else record.get(key)
        if value:
            properties[prop] = value
    if record["spatial"]:
        properties["dct:spatial"] = record["spatial"]
    create = {
        "@context": CONTEXT,
        "@id": asset_id,
        "@type": "Asset",
        "properties": properties,
        "dataAddress": {
            "type": "HttpData",
            # Original distribution unless a local mirror is given (avoids external network
            # noise once transfers are measured).
            "baseUrl": (f"{args.data_base_url.rstrip('/')}/{asset_id}" if args.data_base_url
                        else dist["download_url"]),
            "name": asset_id,
        },
    }
    update = json.loads(json.dumps(create))
    update["properties"]["version"] = "1.1.0"
    update["properties"]["dct:modified"] = retrieved
    update["properties"]["dct:description"] = description + " [benchmark update]"
    return asset_id, create, update


def latest_snapshot() -> Path:
    snapshots = sorted(SNAPSHOT_DIR.glob("snapshot-*.json"))
    if not snapshots:
        raise SystemExit(f"no snapshot in {SNAPSHOT_DIR}; run fetch_sk_catalog.py first")
    return snapshots[-1]


def dump(path: Path, payload: dict) -> str:
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=["sk-catalog", "synthetic"], default="sk-catalog",
                        help="asset metadata source (default: sk-catalog)")
    parser.add_argument("--snapshot", type=Path,
                        help="sk-catalog snapshot (default: latest in dataset/sources/sk-catalog/)")
    parser.add_argument("--count", type=int, default=100, help="number of assets (default: 100)")
    parser.add_argument("--seed", type=int, default=20261014,
                        help="RNG seed, synthetic source only (default: 20261014)")
    parser.add_argument("--id-prefix", default="stics-bench", help="asset @id prefix")
    parser.add_argument("--data-base-url",
                        help="HttpData base URL the assets point to; sk-catalog default is the "
                             "original downloadURL, synthetic default " + SYNTHETIC_DATA_BASE_URL)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "generated",
                        help="output root; files go to <out>/<id-prefix>-<source>-n<count>-<seed|snapshot>/")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be >= 1")

    if args.source == "sk-catalog":
        snapshot_path = (args.snapshot or latest_snapshot()).resolve()
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot = json.loads(snapshot_bytes)
        records = select_round_robin(snapshot, args.count)
        retrieved = snapshot["retrieved_at"]
        out_dir = args.out / f"{args.id_prefix}-sk-n{args.count}-{snapshot_path.stem}"
        builders = (build_sk_asset(i, rec, args, retrieved) for i, rec in enumerate(records, start=1))
    else:
        out_dir = args.out / f"{args.id_prefix}-n{args.count}-s{args.seed}"
        rng = random.Random(args.seed)
        builders = (build_asset(i, rng, args) for i in range(1, args.count + 1))
    (out_dir / "create").mkdir(parents=True, exist_ok=True)
    (out_dir / "update").mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}
    rows = []
    for asset_id, create, update in builders:
        create_rel, update_rel = f"create/{asset_id}.json", f"update/{asset_id}.json"
        files[create_rel] = dump(out_dir / create_rel, create)
        files[update_rel] = dump(out_dir / update_rel, update)
        rows.append((asset_id, create_rel, update_rel))

    csv_path = out_dir / "assets.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["asset_id", "create_file", "update_file"])
        writer.writerows(rows)
    files["assets.csv"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    dataset_sha = hashlib.sha256(
        "".join(f"{name}:{digest}\n" for name, digest in sorted(files.items())).encode()
    ).hexdigest()
    manifest = {
        "generator": "validation/performance/triplestore_concurrency/dataset/generate_assets.py",
        "generator_version": GENERATOR_VERSION,
        "source": args.source,
        "count": args.count,
        "id_prefix": args.id_prefix,
        "data_base_url": args.data_base_url,
        "vocabularies": CONTEXT,
        "dataset_sha256": dataset_sha,
        **({"seed": args.seed} if args.source == "synthetic" else {
            "snapshot": {"file": snapshot_path.name,
                         "sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
                         "retrieved_at": retrieved,
                         "endpoint": snapshot["endpoint"],
                         "records_sha256": snapshot["records_sha256"]},
            "source_datasets": [rec["iri"] for rec in records],
        }),
        "files": dict(sorted(files.items())),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{out_dir}\n{args.count} assets, dataset_sha256={dataset_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
