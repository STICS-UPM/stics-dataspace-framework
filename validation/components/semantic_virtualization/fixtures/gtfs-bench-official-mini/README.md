# GTFS-Bench Official Mini

`gtfs-bench-official-mini` is a small, deterministic CSV slice derived
from the official `oeg-upm/gtfs-bench` repository resources.

It keeps the full official benchmark out of default validation runs, while
preserving traceability to the upstream dump, ontology, CSV RML mapping and
SPARQL query catalog.

## Intended Use

- validate that Semantic Virtualization can work with official GTFS-Bench shaped CSV files;
- provide a stable mapping-editor and API fixture for A5.2 evidence;
- keep Docker/MySQL/full benchmark generation as an explicit maintenance activity outside Level 6;
- support future INESData HttpData demos without publishing the full dataset by default.

## Regeneration

Run:

```bash
python3 validation/components/semantic_virtualization/gtfs_bench_mini.py --regenerate
```

The local upstream clone is expected at `adapters/inesdata/sources/gtfs-bench`.
Review upstream data rights before publishing evidence outside the validation workspace.
