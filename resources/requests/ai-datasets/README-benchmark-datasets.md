# Benchmark Dataset Asset Requests

This folder contains local asset-create requests for benchmark datasets.

## Files

- `create-asset-benchmark-dataset-text-positive-v1.json`
- `create-asset-benchmark-dataset-text-negative-v1.json`
- `create-asset-benchmark-dataset-text-neutral-v1.json`
- `create-asset-benchmark-dataset-tabular-a-v1.json`
- `create-asset-benchmark-dataset-tabular-b-v1.json`

## Source data

All payloads are derived from:

- `resources/benchmark-datasets/text-benchmark-v1.json`
- `resources/benchmark-datasets/tabular-benchmark-v1.json`

## Register all 5 dataset assets

Run from `asset-filter-template/`:

```bash
./tools/register-benchmark-dataset-assets.sh
```

Optional management URL:

```bash
./tools/register-benchmark-dataset-assets.sh http://localhost:19193/management/v3/assets
```
