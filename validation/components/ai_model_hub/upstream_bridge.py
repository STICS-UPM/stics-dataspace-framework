"""Safe inspection helpers for the ProyectoPIONERA/AIModelHub upstream.

This module intentionally does not pull, merge or execute upstream scripts.  It
compares the local Validation-Environment integration points with the fetched
upstream tree so we can port only the AI Model Hub pieces that are actually
needed for the PIONERA demo.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable


UPSTREAM_REF = "origin/main"
UPSTREAM_CHECKOUT = Path("adapters/inesdata/sources/AIModelHub")
USE_CASES_CHECKOUT = Path("adapters/inesdata/sources/AIModelHub-Use-Cases")
SEED_SCRIPT = Path("scripts/seed_ml_assets_for_connectors.sh")
UPSTREAM_SEED_SCRIPT = "scripts/seed_ml_assets_for_connectors.sh"
LAYOUT_MARKERS_EXPECTED_BY_FRAMEWORK = ("DataDashboard", "asset-filter-template")
UPSTREAM_PIONERA_MARKERS = ("inesdata_local_deploy.py", "combined_model_server", "inesdata-deployment")
REQUIRED_USE_CASE_DATASETS = (
    Path("data/mobility-datasets/segments_test.csv"),
    Path("data/flares-datasets/5w1h_subtarea_1_test.json"),
    Path("data/flares-datasets/5w1h_subtarea_2_test.json"),
)


def project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    for parent in (current, *current.parents):
        if (parent / "main.py").is_file() and (parent / "deployers").is_dir():
            return parent
    raise RuntimeError("Could not locate Validation-Environment project root")


def _run_git(repo_dir: Path, args: Iterable[str]) -> str:
    command = ["git", "-C", str(repo_dir), *args]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"git command failed: {' '.join(command)}" + (f": {detail}" if detail else ""))
    return result.stdout


def _read_file(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _git_show(repo_dir: Path, ref_path: str) -> str:
    return _run_git(repo_dir, ["show", ref_path])


def _git_tree_names(repo_dir: Path, ref: str) -> list[str]:
    return [
        line.strip()
        for line in _run_git(repo_dir, ["ls-tree", "--name-only", ref]).splitlines()
        if line.strip()
    ]


def _git_ahead_behind(repo_dir: Path, ref: str) -> Dict[str, int]:
    output = _run_git(repo_dir, ["rev-list", "--left-right", "--count", f"HEAD...{ref}"]).strip()
    left, right = (output.split() + ["0", "0"])[:2]
    return {"ahead": int(left), "behind": int(right)}


def analyze_seed_script(script_text: str) -> Dict[str, Any]:
    """Return feature flags for an AIModelHub seed script."""
    return {
        "line_count": len(script_text.splitlines()),
        "supports_seed_scope": "--seed-scope" in script_text and "SEED_SCOPE" in script_text,
        "supports_daimo_vocabularies": (
            "JS_DAIMO_Model" in script_text
            and "JS_DAIMO_Dataset" in script_text
            and "vocabularies" in script_text
        ),
        "supports_dataset_assets": (
            "MOBILITY_SEGMENTS_DATASET_FILE" in script_text
            and "FLARES_5W1H_DATASET_FILE" in script_text
            and "create_company_dataset_policies_and_contracts" in script_text
        ),
        "supports_use_case_models": (
            "USE_CASE_MODEL_SERVER_BASE_URL" in script_text
            and "FLARES" in script_text
            and "Mobility" in script_text
        ),
        "supports_flares_metric_models": (
            "FLARES_METRIC_MODEL_SLUGS" in script_text
            and "benchmark_model_type" in script_text
            and "metric" in script_text
        ),
        "supports_combined_mode": "combined" in script_text and "COMBINED_HTTP_COUNT" in script_text,
        "supports_skip_flags": "--skip-inesdata-models" in script_text and "--skip-use-case-models" in script_text,
    }


def classify_porting_need(local_features: Dict[str, Any], upstream_features: Dict[str, Any]) -> Dict[str, Any]:
    gaps = []
    for key, description in (
        ("supports_seed_scope", "Step 9/10 selectable seed scopes"),
        ("supports_daimo_vocabularies", "Step 8 DAIMO model and dataset vocabularies"),
        ("supports_dataset_assets", "Step 9 benchmark dataset assets and contracts"),
        ("supports_flares_metric_models", "FLARES metric-model assets for custom evaluation"),
        ("supports_skip_flags", "safe split between base, dataset and use-case model seeding"),
    ):
        if upstream_features.get(key) and not local_features.get(key):
            gaps.append({"feature": key, "description": description})

    status = "port_required" if gaps else "aligned"
    return {"status": status, "gaps": gaps}


def _step_status(required_features: Iterable[str], local_features: Dict[str, Any], upstream_features: Dict[str, Any]) -> str:
    required = tuple(required_features)
    if all(local_features.get(feature) for feature in required):
        return "available"
    if any(upstream_features.get(feature) for feature in required):
        return "port_required"
    return "not_available"


def build_demo_adoption_plan(local_features: Dict[str, Any], upstream_features: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Describe how JiaYun's new AI Model Hub demo steps map to this framework.

    The plan is intentionally declarative.  It must not be treated as an
    executor because the local seed script may still lack the upstream options.
    """
    step_9_status = _step_status(
        ("supports_seed_scope", "supports_dataset_assets", "supports_skip_flags"),
        local_features,
        upstream_features,
    )
    step_8_status = _step_status(
        ("supports_seed_scope", "supports_daimo_vocabularies"),
        local_features,
        upstream_features,
    )
    step_10_status = _step_status(
        (
            "supports_seed_scope",
            "supports_use_case_models",
            "supports_skip_flags",
        ),
        local_features,
        upstream_features,
    )

    return [
        {
            "upstream_step": 7,
            "title": "Deploy/start AI Model Hub model server",
            "local_status": "available",
            "local_mapping": (
                "Use AI_MODEL_HUB_MODEL_SERVER_MODE=use-cases, then run the "
                "framework model-server deployment step."
            ),
            "notes": "The framework-owned flow intentionally avoids mock/sentiment endpoints.",
        },
        {
            "upstream_step": 8,
            "title": "Seed DAIMO model and dataset vocabularies",
            "local_status": step_8_status,
            "local_mapping": "scripts/seed_ml_assets_for_connectors.sh",
            "requires_features": [
                "supports_seed_scope",
                "supports_daimo_vocabularies",
            ],
            "target_command_after_port": (
                "bash scripts/seed_ml_assets_for_connectors.sh --seed-scope vocabularies"
            ),
            "notes": "Creates/updates only JS_DAIMO_Model and JS_DAIMO_Dataset.",
        },
        {
            "upstream_step": 9,
            "title": "Seed benchmark dataset assets and contracts",
            "local_status": step_9_status,
            "local_mapping": "scripts/seed_ml_assets_for_connectors.sh",
            "requires_features": [
                "supports_seed_scope",
                "supports_dataset_assets",
                "supports_skip_flags",
            ],
            "target_command_after_port": (
                "bash scripts/seed_ml_assets_for_connectors.sh --seed-scope datasets"
            ),
            "notes": (
                "Ready to run after the AIModelHub-Use-Cases dataset files are present."
                if step_9_status == "available"
                else "This is the first feature to port before claiming the new demo data path is ready."
            ),
        },
        {
            "upstream_step": 10,
            "title": "Seed FLARES/Mobility model assets",
            "local_status": step_10_status,
            "local_mapping": "scripts/seed_ml_assets_for_connectors.sh",
            "requires_features": [
                "supports_seed_scope",
                "supports_use_case_models",
                "supports_skip_flags",
            ],
            "target_command_after_port": (
                "bash scripts/seed_ml_assets_for_connectors.sh "
                "--seed-scope models --model-set use-cases "
                "--include-use-case-models --skip-inesdata-models"
            ),
            "notes": "Use this only after Step 7 exposes the use-cases model server to connectors.",
        },
    ]


def recommended_action_for_porting(porting: Dict[str, Any]) -> str:
    if porting["status"] != "port_required":
        return "No seed-script port is currently required."
    missing = ", ".join(gap["description"] for gap in porting["gaps"])
    return f"Port the remaining seed feature(s): {missing}."


def inspect_use_case_datasets(root_dir: Path) -> Dict[str, Any]:
    source_dir = root_dir / USE_CASES_CHECKOUT
    datasets = []
    for relative_path in REQUIRED_USE_CASE_DATASETS:
        path = source_dir / relative_path
        datasets.append(
            {
                "relative_path": str(relative_path),
                "path": str(path),
                "available": path.is_file(),
                "size_bytes": path.stat().st_size if path.is_file() else 0,
            }
        )
    return {
        "source_dir": str(source_dir),
        "available": source_dir.is_dir(),
        "datasets_available": all(item["available"] for item in datasets),
        "datasets": datasets,
    }


def analyze_upstream_bridge(root: Path | None = None, upstream_ref: str = UPSTREAM_REF) -> Dict[str, Any]:
    root_dir = project_root(root)
    local_seed_path = root_dir / SEED_SCRIPT
    upstream_repo = root_dir / UPSTREAM_CHECKOUT

    local_seed = _read_file(local_seed_path) if local_seed_path.is_file() else ""
    local_features = analyze_seed_script(local_seed)

    upstream: Dict[str, Any] = {
        "checkout": str(upstream_repo),
        "ref": upstream_ref,
        "available": upstream_repo.is_dir(),
    }
    upstream_features: Dict[str, Any] = {}
    layout = {
        "direct_pull_safe": False,
        "reason": "upstream checkout is not available",
        "root_entries": [],
    }

    if upstream_repo.is_dir():
        upstream_seed = _git_show(upstream_repo, f"{upstream_ref}:{UPSTREAM_SEED_SCRIPT}")
        upstream_features = analyze_seed_script(upstream_seed)
        root_entries = _git_tree_names(upstream_repo, upstream_ref)
        has_expected_layout = all(entry in root_entries for entry in LAYOUT_MARKERS_EXPECTED_BY_FRAMEWORK)
        has_pionera_layout = any(entry in root_entries for entry in UPSTREAM_PIONERA_MARKERS)
        layout = {
            "direct_pull_safe": bool(has_expected_layout and not has_pionera_layout),
            "reason": (
                "upstream keeps the framework-expected AIModelHub layout"
                if has_expected_layout and not has_pionera_layout
                else "upstream root is AIModelHub_Pionera-style; port selected files instead of pulling"
            ),
            "root_entries": root_entries,
            "has_expected_layout": has_expected_layout,
            "has_pionera_layout": has_pionera_layout,
        }
        upstream.update(_git_ahead_behind(upstream_repo, upstream_ref))

    porting = classify_porting_need(local_features, upstream_features)
    demo_plan = build_demo_adoption_plan(local_features, upstream_features)
    use_case_datasets = inspect_use_case_datasets(root_dir)
    return {
        "component": "ai-model-hub",
        "upstream": upstream,
        "layout": layout,
        "use_case_datasets": use_case_datasets,
        "local_seed_script": {
            "path": str(local_seed_path),
            "available": local_seed_path.is_file(),
            "features": local_features,
        },
        "upstream_seed_script": {
            "path": UPSTREAM_SEED_SCRIPT,
            "features": upstream_features,
        },
        "porting": porting,
        "demo_adoption_plan": demo_plan,
        "recommended_action": recommended_action_for_porting(porting),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect AIModelHub upstream porting status safely.")
    parser.add_argument("--json", action="store_true", help="Print the raw JSON payload.")
    parser.add_argument("--ref", default=os.environ.get("AI_MODEL_HUB_UPSTREAM_REF", UPSTREAM_REF))
    args = parser.parse_args(argv)

    result = analyze_upstream_bridge(upstream_ref=args.ref)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"AI Model Hub upstream: {result['upstream']['checkout']} ({result['upstream']['ref']})")
        print(f"Direct pull safe: {result['layout']['direct_pull_safe']} - {result['layout']['reason']}")
        print(f"Porting status: {result['porting']['status']}")
        for gap in result["porting"]["gaps"]:
            print(f"- {gap['description']} ({gap['feature']})")
        print("Demo adoption plan:")
        for item in result["demo_adoption_plan"]:
            print(f"- Upstream Step {item['upstream_step']}: {item['local_status']} - {item['title']}")
        print(
            "Use-case datasets: "
            f"{'available' if result['use_case_datasets']['datasets_available'] else 'missing'} "
            f"({result['use_case_datasets']['source_dir']})"
        )
        print(result["recommended_action"])
    return 0 if result["upstream"]["available"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
