from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from validation.components.semantic_virtualization.dataspace_integration import (
    load_gtfs_madrid_bench_context,
)


COMPONENT_KEY = "ai-model-hub"
TRACEABILITY_CASE_ID = "INT-VS-AMH-01"
SEMANTIC_DATASPACE_CASE_ID = "INT-VS-DS-01"
AI_MODEL_HUB_MOBILITY_CASE_ID = "MH-MOB-01"
GTFS_DATASET_NAME = "GTFS-Madrid-Bench"
CATALOG_PATH = Path(__file__).resolve().parent / "test_cases.yaml"
DEFAULT_SEMANTIC_REPORT = (
    Path("experiments")
    / "semantic-virtualization-dataspace-20260504-gtfs-full-real"
    / "components"
    / "semantic-virtualization"
    / "integration"
    / "semantic_virtualization_dataspace_integration.json"
)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _component_dir(experiment_dir: str | None) -> Path | None:
    if not experiment_dir:
        return None
    path = Path(experiment_dir) / "components" / COMPONENT_KEY / "integration"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_ai_model_hub_case(catalog_path: Path = CATALOG_PATH) -> dict[str, Any] | None:
    with catalog_path.open("r", encoding="utf-8") as handle:
        catalog = yaml.safe_load(handle) or {}
    case_groups = [
        "test_cases",
        "functional_use_cases",
        "integration_use_cases",
        "support_checks",
    ]
    for group in case_groups:
        for case in catalog.get(group) or []:
            if case.get("id") == AI_MODEL_HUB_MOBILITY_CASE_ID:
                return {**case, "catalog_group": group}
    return None


def _passed_check(name: str, **payload: Any) -> dict[str, Any]:
    return {"name": name, "status": "passed", **payload}


def _failed_check(name: str, message: str, **payload: Any) -> dict[str, Any]:
    return {"name": name, "status": "failed", "message": message, **payload}


def build_vs_ai_model_hub_traceability(
    *,
    semantic_report_path: str | Path,
    experiment_dir: str | None = None,
    source_dir: str | None = None,
    catalog_path: str | Path = CATALOG_PATH,
) -> dict[str, Any]:
    started_at = datetime.now().isoformat()
    checks: list[dict[str, Any]] = []
    artifacts: dict[str, str] = {}
    semantic_path = Path(semantic_report_path)
    catalog_file = Path(catalog_path)

    try:
        semantic_report = _read_json(semantic_path)
        gtfs_context = load_gtfs_madrid_bench_context(source_dir)
        ai_model_hub_case = _load_ai_model_hub_case(catalog_file)

        semantic_context = semantic_report.get("integration_context") or {}
        asset_payload = semantic_report.get("asset_payload") or {}
        asset_properties = asset_payload.get("properties") or {}
        local_digest = hashlib.sha256(
            json.dumps(gtfs_context.get("record_counts") or {}, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        if semantic_report.get("status") == "passed" and semantic_report.get("test_case_id") == SEMANTIC_DATASPACE_CASE_ID:
            checks.append(
                _passed_check(
                    "semantic_virtualization_dataspace_evidence_passed",
                    semantic_status=semantic_report.get("status"),
                    semantic_case_id=semantic_report.get("test_case_id"),
                )
            )
        else:
            checks.append(
                _failed_check(
                    "semantic_virtualization_dataspace_evidence_passed",
                    "Semantic Virtualization dataspace evidence is not a passed INT-VS-DS-01 report",
                    semantic_status=semantic_report.get("status"),
                    semantic_case_id=semantic_report.get("test_case_id"),
                )
            )

        if (
            semantic_context.get("case_id") == AI_MODEL_HUB_MOBILITY_CASE_ID
            and semantic_context.get("dataset_name") == GTFS_DATASET_NAME
        ):
            checks.append(
                _passed_check(
                    "semantic_report_contains_gtfs_mobility_context",
                    case_id=semantic_context.get("case_id"),
                    dataset_name=semantic_context.get("dataset_name"),
                )
            )
        else:
            checks.append(
                _failed_check(
                    "semantic_report_contains_gtfs_mobility_context",
                    "Semantic report is not linked to MH-MOB-01 / GTFS-Madrid-Bench",
                    case_id=semantic_context.get("case_id"),
                    dataset_name=semantic_context.get("dataset_name"),
                )
            )

        semantic_digest = asset_properties.get("daimo:expectedOutputsDigest")
        if semantic_digest == local_digest:
            checks.append(
                _passed_check(
                    "expected_outputs_digest_matches_ai_model_hub_dataset",
                    digest=local_digest,
                    expected_outputs_source=gtfs_context.get("expected_outputs_source"),
                )
            )
        else:
            checks.append(
                _failed_check(
                    "expected_outputs_digest_matches_ai_model_hub_dataset",
                    "HttpData asset digest does not match AI Model Hub dataset-derived expectations",
                    semantic_digest=semantic_digest,
                    local_digest=local_digest,
                )
            )

        semantic_counts = semantic_context.get("record_counts") or {}
        local_counts = gtfs_context.get("record_counts") or {}
        if semantic_counts == local_counts:
            checks.append(_passed_check("record_counts_match", record_counts=local_counts))
        else:
            checks.append(
                _failed_check(
                    "record_counts_match",
                    "Semantic report record counts differ from the AI Model Hub mobility dataset",
                    semantic_counts=semantic_counts,
                    local_counts=local_counts,
                )
            )

        semantic_join_keys = semantic_context.get("join_keys") or []
        local_join_keys = gtfs_context.get("join_keys") or []
        if semantic_join_keys == local_join_keys:
            checks.append(_passed_check("join_keys_match", join_keys=local_join_keys))
        else:
            checks.append(
                _failed_check(
                    "join_keys_match",
                    "Semantic report join keys differ from the AI Model Hub mobility dataset",
                    semantic_join_keys=semantic_join_keys,
                    local_join_keys=local_join_keys,
                )
            )

        if (
            asset_properties.get("assetType") == "semantic-virtualization-mobility-output"
            and asset_properties.get("daimo:sourceDataset") == GTFS_DATASET_NAME
            and AI_MODEL_HUB_MOBILITY_CASE_ID in (asset_properties.get("dcat:keyword") or [])
        ):
            checks.append(
                _passed_check(
                    "httpdata_asset_carries_ai_model_hub_mobility_metadata",
                    asset_type=asset_properties.get("assetType"),
                    source_dataset=asset_properties.get("daimo:sourceDataset"),
                )
            )
        else:
            checks.append(
                _failed_check(
                    "httpdata_asset_carries_ai_model_hub_mobility_metadata",
                    "HttpData asset does not carry the expected AI Model Hub mobility metadata",
                    asset_properties=asset_properties,
                )
            )

        if ai_model_hub_case:
            automation = ai_model_hub_case.get("automation") or {}
            checks.append(
                _passed_check(
                    "ai_model_hub_mobility_case_registered",
                    case_id=ai_model_hub_case.get("id"),
                    catalog_group=ai_model_hub_case.get("catalog_group"),
                    automation_status=automation.get("status"),
                    dataset_source=automation.get("dataset_source") or automation.get("fixture"),
                )
            )
        else:
            checks.append(
                _failed_check(
                    "ai_model_hub_mobility_case_registered",
                    "MH-MOB-01 is not registered in AI Model Hub test_cases.yaml",
                    catalog_path=str(catalog_file),
                )
            )

        checks.append(
            _passed_check(
                "scope_limitation_recorded",
                limitation=(
                    "AI Model Hub benchmarking does not yet consume the negotiated HttpData asset directly; "
                    "this slice closes the integration as a reproducible traceability bridge."
                ),
            )
        )

        status = "failed" if any(check.get("status") == "failed" for check in checks) else "passed"
        error_payload = None
    except Exception as exc:
        semantic_report = {}
        gtfs_context = {}
        ai_model_hub_case = None
        asset_properties = {}
        status = "failed"
        error_payload = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(_failed_check("traceability_runner_error", str(exc), type=type(exc).__name__))

    summary = {
        "total": len(checks),
        "passed": sum(1 for check in checks if check.get("status") == "passed"),
        "failed": sum(1 for check in checks if check.get("status") == "failed"),
        "skipped": sum(1 for check in checks if check.get("status") == "skipped"),
    }
    result = {
        "component": COMPONENT_KEY,
        "suite": "virtualization-mobility-traceability",
        "test_case_id": TRACEABILITY_CASE_ID,
        "linked_cases": [
            SEMANTIC_DATASPACE_CASE_ID,
            AI_MODEL_HUB_MOBILITY_CASE_ID,
            "INT-AMH-MOB-01",
        ],
        "status": status,
        "summary": summary,
        "timestamp": started_at,
        "integration_strategy": "traceability_bridge",
        "semantic_report_path": str(semantic_path),
        "catalog_path": str(catalog_file),
        "dataset": {
            "name": (gtfs_context or {}).get("dataset_name"),
            "expected_outputs_source": (gtfs_context or {}).get("expected_outputs_source"),
            "record_counts": (gtfs_context or {}).get("record_counts"),
            "join_keys": (gtfs_context or {}).get("join_keys"),
        },
        "semantic_virtualization_evidence": {
            "status": (semantic_report or {}).get("status"),
            "summary": (semantic_report or {}).get("summary"),
            "created_entities": (semantic_report or {}).get("created_entities"),
            "asset_properties": asset_properties,
        },
        "ai_model_hub_case": ai_model_hub_case,
        "checks": checks,
        "limitations": [
            "No AI Model Hub UI or backend extension was introduced for this closure slice.",
            "The negotiated HttpData asset is not yet consumed directly by Model Benchmarking.",
            "The integration is closed as reproducible evidence that Semantic Virtualization output and AI Model Hub mobility validation refer to the same GTFS-Madrid-Bench source.",
        ],
        "error": error_payload,
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = component_dir / "vs_ai_model_hub_mobility_traceability.json"
        _write_json(report_path, result)
        artifacts["report_json"] = str(report_path)
    result["artifacts"] = artifacts
    return result


def _default_experiment_dir() -> str:
    return os.path.join(
        "experiments",
        f"vs-ai-model-hub-mobility-traceability-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate VS + AI Model Hub mobility traceability for INT-VS-AMH-01."
    )
    parser.add_argument("--semantic-report", default=str(DEFAULT_SEMANTIC_REPORT))
    parser.add_argument("--experiment-dir", default="")
    parser.add_argument("--source-dir", default="")
    parser.add_argument("--catalog-path", default=str(CATALOG_PATH))
    args = parser.parse_args(argv)

    result = build_vs_ai_model_hub_traceability(
        semantic_report_path=args.semantic_report,
        experiment_dir=args.experiment_dir or _default_experiment_dir(),
        source_dir=args.source_dir or None,
        catalog_path=args.catalog_path,
    )
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "summary": result.get("summary"),
                "artifact": (result.get("artifacts") or {}).get("report_json"),
            },
            indent=2,
        )
    )
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
