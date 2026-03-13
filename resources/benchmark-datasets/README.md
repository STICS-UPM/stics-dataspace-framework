# Benchmark Datasets (DataDashboard)

These datasets are made for the 5 local benchmark models:
- text-keyword-v1
- text-bayes-v1
- text-linear-v1
- tabular-linear-v1
- tabular-tree-v1

## Files

Text:
- `text-benchmark-v1.json` (30 rows, includes expected labels)
- `text-benchmark-v1.jsonl` (same content as JSONL)
- `text-benchmark-v1-input-only.csv` (input-only CSV)

Tabular:
- `tabular-benchmark-v1.json` (30 rows)
- `tabular-benchmark-v1.jsonl` (same content as JSONL)
- `tabular-benchmark-v1-input-only.csv` (input-only CSV)

## Recommended benchmark mapping

Field meanings:
- `inputPath`: path in each dataset row used as inference payload. If empty, the full row is sent.
- `expectedPath`: path in each dataset row used as ground truth for accuracy.
- `predictionPath`: path in model response used as predicted value for accuracy comparison.

Text JSON/JSONL (with accuracy):
- `inputPath`: `input`
- `expectedPath`: `expected_label`
- `predictionPath`: `result.label`

Text CSV (no accuracy):
- `inputPath`: leave empty
- `expectedPath`: leave empty
- `predictionPath`: `result.label`

Tabular JSON/JSONL:
- `inputPath`: `input`
- `expectedPath`: leave empty
- `predictionPath`: `result.value`

Tabular CSV:
- `inputPath`: leave empty
- `expectedPath`: leave empty
- `predictionPath`: `result.value`

## Notes

- Use text dataset only with the 3 text models.
- Use tabular dataset only with the 2 tabular models.
- If you mix text and tabular models in one benchmark run, schema compatibility checks will block execution.
