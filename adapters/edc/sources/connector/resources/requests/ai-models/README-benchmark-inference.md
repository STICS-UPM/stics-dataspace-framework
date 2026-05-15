# Benchmark Inference Model Pack

This pack defines 5 executable inference assets for DataDashboard benchmarking.

## Model groups

Shared schema A (`urn:pionera:schema:text-classification:v1`):
- `provider~benchmark-text-keyword-v1`
- `provider~benchmark-text-bayes-v1`
- `provider~benchmark-text-linear-v1`

Shared schema B (`urn:pionera:schema:tabular-regression:v1`):
- `provider~benchmark-tabular-linear-v1`
- `provider~benchmark-tabular-tree-v1`

All assets expose `daimo:inference_path = /infer` and include:
- `daimo:input_schema_draft`
- `daimo:input_schema`
- `daimo:input_features`
- `daimo:input_example`

## 1) Start local inference servers

From `asset-filter-template/`:

```bash
./tools/start-benchmark-model-servers.sh
```

Ports used:
- `9201` text-keyword-v1
- `9202` text-bayes-v1
- `9203` text-linear-v1
- `9301` tabular-linear-v1
- `9302` tabular-tree-v1

## 2) Register assets in provider connector

```bash
./tools/register-benchmark-model-assets.sh
```

Default target:
- `http://localhost:19193/management/v3/assets`

Custom target:

```bash
./tools/register-benchmark-model-assets.sh http://localhost:29193/management/v3/assets
```

## 3) Quick inference smoke checks

Text-model request example:

```bash
curl -sS -X POST http://localhost:9201/infer \
  -H 'Content-Type: application/json' \
  -d '{"text":"The service is excellent and very fast"}' | jq
```

Tabular-model request example:

```bash
curl -sS -X POST http://localhost:9301/infer \
  -H 'Content-Type: application/json' \
  -d '{"age":34,"income":72000,"tenure_months":18}' | jq
```

## 4) Stop local inference servers

```bash
./tools/stop-benchmark-model-servers.sh
```
