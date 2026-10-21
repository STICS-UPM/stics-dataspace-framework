#!/usr/bin/env python3
"""Summarize the JTL files of a store-concurrency experiment into summary.csv.

One row per run (warm-up runs excluded) for the measured label (default "CREATE asset"):
samples, errors, latency percentiles (ms), wall time of the measured phase and throughput.
It also flags runs whose successful sample count differs from the dataset size, which is
the first consistency signal (lost or duplicated operations).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

RUN_NAME = re.compile(r"^(?P<scenario>S\d+)_t(?P<threads>\d+)_r(?P<rep>\d+)$")


def percentile(sorted_values: list[int], q: float) -> float:
    if not sorted_values:
        return math.nan
    rank = q * (len(sorted_values) - 1)
    low, high = math.floor(rank), math.ceil(rank)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


def summarize_run(path: Path, label: str) -> dict:
    elapsed, starts, ends, errors, codes = [], [], [], 0, {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["label"] != label:
                continue
            ms, ts = int(row["elapsed"]), int(row["timeStamp"])
            elapsed.append(ms)
            starts.append(ts)
            ends.append(ts + ms)
            codes[row["responseCode"]] = codes.get(row["responseCode"], 0) + 1
            if row["success"] != "true":
                errors += 1
    elapsed.sort()
    wall_s = (max(ends) - min(starts)) / 1000 if starts else math.nan
    return {
        "samples": len(elapsed),
        "errors": errors,
        "error_rate": errors / len(elapsed) if elapsed else math.nan,
        "mean_ms": sum(elapsed) / len(elapsed) if elapsed else math.nan,
        "p50_ms": percentile(elapsed, 0.50),
        "p95_ms": percentile(elapsed, 0.95),
        "p99_ms": percentile(elapsed, 0.99),
        "max_ms": elapsed[-1] if elapsed else math.nan,
        "wall_s": wall_s,
        "throughput_ops_s": len(elapsed) / wall_s if wall_s else math.nan,
        "response_codes": ";".join(f"{code}:{n}" for code, n in sorted(codes.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("experiment_dir", type=Path)
    parser.add_argument("--label", default="CREATE asset")
    args = parser.parse_args(argv)

    expected = json.loads((args.experiment_dir / "dataset_manifest.json").read_text())["count"]
    rows = []
    for jtl in sorted((args.experiment_dir / "jtl").glob("*.jtl")):
        match = RUN_NAME.match(jtl.stem)
        if not match:  # warm-up runs
            continue
        stats = summarize_run(jtl, args.label)
        ok = stats["samples"] - stats["errors"]
        rows.append({"run": jtl.stem, "scenario": match["scenario"], "threads": int(match["threads"]),
                     "rep": int(match["rep"]), **stats,
                     "consistent": ok == expected})
    rows.sort(key=lambda r: (r["threads"], r["rep"]))
    if not rows:
        print("No measured runs found", file=sys.stderr)
        return 1

    out = args.experiment_dir / "summary.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (f"{v:.2f}" if isinstance(v, float) else v) for k, v in row.items()})

    print(f"{'run':<14}{'ok/exp':>9}{'p50':>9}{'p95':>9}{'p99':>9}{'ops/s':>9}")
    for r in rows:
        print(f"{r['run']:<14}{r['samples'] - r['errors']:>5}/{expected:<3}"
              f"{r['p50_ms']:>9.0f}{r['p95_ms']:>9.0f}{r['p99_ms']:>9.0f}{r['throughput_ops_s']:>9.1f}"
              + ("" if r["consistent"] else "  <-- inconsistent"))
    print(f"\n{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
