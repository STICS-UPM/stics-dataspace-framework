from __future__ import annotations

from typing import Any, Dict, Iterable, List


PT5_CASES: List[Dict[str, str]] = [
    {
        "id": "PT5-OH-01",
        "description": "Register an ontology through URI or repository",
        "validation_type": "functional",
        "dataspace_dimension": "publication",
    },
    {
        "id": "PT5-OH-02",
        "description": "Update metadata of an existing ontology",
        "validation_type": "functional",
        "dataspace_dimension": "publication",
    },
    {
        "id": "PT5-OH-03",
        "description": "Delete a registered ontology",
        "validation_type": "functional",
        "dataspace_dimension": "publication",
    },
    {
        "id": "PT5-OH-04",
        "description": "Create, edit and delete tags",
        "validation_type": "functional",
        "dataspace_dimension": "curation",
    },
    {
        "id": "PT5-OH-05",
        "description": "Create users and validate role-based access",
        "validation_type": "functional",
        "dataspace_dimension": "access_control",
    },
    {
        "id": "PT5-OH-06",
        "description": "Run operations over ontologies",
        "validation_type": "non_functional",
        "dataspace_dimension": "governance",
    },
    {
        "id": "PT5-OH-07",
        "description": "Register an RDF/OWL ontology",
        "validation_type": "interoperability",
        "dataspace_dimension": "interoperability",
    },
    {
        "id": "PT5-OH-08",
        "description": "Search ontologies by free text",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
    },
    {
        "id": "PT5-OH-09",
        "description": "Filter by metadata and tags",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
    },
    {
        "id": "PT5-OH-10",
        "description": "Inspect specific versions",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
    },
    {
        "id": "PT5-OH-11",
        "description": "Open an ontology detail page",
        "validation_type": "functional",
        "dataspace_dimension": "visualization",
    },
    {
        "id": "PT5-OH-12",
        "description": "Inspect statistics and popularity",
        "validation_type": "functional",
        "dataspace_dimension": "visualization",
    },
    {
        "id": "PT5-OH-13",
        "description": "Run a SPARQL query",
        "validation_type": "interoperability",
        "dataspace_dimension": "interoperability",
    },
    {
        "id": "PT5-OH-14",
        "description": "Run ontology checker and pattern services",
        "validation_type": "integration",
        "dataspace_dimension": "services",
    },
    {
        "id": "PT5-OH-15",
        "description": "Access functionality through UI and API",
        "validation_type": "integration",
        "dataspace_dimension": "integration",
    },
    {
        "id": "PT5-OH-16",
        "description": "Validate connector integration",
        "validation_type": "integration",
        "dataspace_dimension": "integration",
    },
]

PT5_CASES_BY_ID = {case["id"]: case for case in PT5_CASES}

OH_APP_TO_PT5: Dict[str, List[str]] = {
    "OH-APP-00": ["PT5-OH-15"],
    "OH-APP-01": ["PT5-OH-15"],
    "OH-APP-03": ["PT5-OH-01", "PT5-OH-07"],
    "OH-APP-04": ["PT5-OH-01", "PT5-OH-07"],
    "OH-APP-05": ["PT5-OH-11"],
    "OH-APP-06": ["PT5-OH-09"],
    "OH-APP-07": ["PT5-OH-09"],
    "OH-APP-08": ["PT5-OH-09"],
    "OH-APP-09": ["PT5-OH-09"],
    "OH-APP-10": ["PT5-OH-02"],
    "OH-APP-11": ["PT5-OH-10"],
    "OH-APP-12": ["PT5-OH-10"],
    "OH-APP-13": ["PT5-OH-10"],
    "OH-APP-14": ["PT5-OH-03"],
    "OH-APP-15": ["PT5-OH-05"],
    "OH-APP-16": ["PT5-OH-05"],
    "OH-APP-17": ["PT5-OH-05"],
    "OH-APP-18": ["PT5-OH-05"],
    "OH-APP-19": ["PT5-OH-04"],
    "OH-APP-20": ["PT5-OH-04"],
    "OH-APP-21": ["PT5-OH-04"],
    "OH-APP-22": ["PT5-OH-06", "PT5-OH-14"],
    "OH-APP-23": ["PT5-OH-06", "PT5-OH-12"],
    "OH-APP-24": ["PT5-OH-06", "PT5-OH-14"],
    "OH-APP-25": ["PT5-OH-08"],
    "OH-APP-26": ["PT5-OH-09"],
    "OH-APP-27": ["PT5-OH-09"],
}

KNOWN_COMPONENT_ISSUE_CASES = {"OH-APP-05", "OH-APP-10", "OH-APP-17", "OH-APP-22"}


def _case_status(case: Dict[str, Any]) -> str:
    evaluation = dict(case.get("evaluation") or {})
    return str(evaluation.get("status") or case.get("status") or "skipped").lower()


def _case_sort_key(case_id: str) -> tuple[str, int, str]:
    parts = case_id.split("-")
    if len(parts) >= 3 and parts[-1].isdigit():
        return ("-".join(parts[:-1]), int(parts[-1]), case_id)
    return (case_id, 0, case_id)


def _aggregate_status(source_cases: Iterable[Dict[str, Any]]) -> str:
    statuses = [_case_status(case) for case in source_cases]
    if not statuses:
        return "skipped"
    if "failed" in statuses:
        return "failed"
    if "passed" in statuses:
        return "passed"
    return "skipped"


def build_oh_app_traceability(executed_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    traceability: List[Dict[str, Any]] = []
    for case in executed_cases:
        oh_app_id = str(case.get("test_case_id") or "")
        mapped_pt5 = list(OH_APP_TO_PT5.get(oh_app_id) or [])
        traceability.append(
            {
                "test_case_id": oh_app_id,
                "description": case.get("description", ""),
                "status": _case_status(case),
                "mapped_pt5_cases": mapped_pt5,
                "known_component_issue": oh_app_id in KNOWN_COMPONENT_ISSUE_CASES,
                "spec": (case.get("request") or {}).get("spec"),
            }
        )
    return traceability


def build_pt5_case_results_from_oh_app(executed_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cases_by_id = {str(case.get("test_case_id") or ""): case for case in executed_cases}
    pt5_results: List[Dict[str, Any]] = []

    for pt5_case in PT5_CASES:
        pt5_id = pt5_case["id"]
        mapped_oh_app_ids = [
            oh_app_id
            for oh_app_id, mapped_pt5_cases in OH_APP_TO_PT5.items()
            if pt5_id in mapped_pt5_cases
        ]
        source_cases = [cases_by_id[case_id] for case_id in mapped_oh_app_ids if case_id in cases_by_id]
        status = _aggregate_status(source_cases)
        source_case_summaries = [
            {
                "test_case_id": case.get("test_case_id"),
                "description": case.get("description", ""),
                "status": _case_status(case),
                "request": case.get("request") or {},
                "response": case.get("response") or {},
                "known_component_issue": str(case.get("test_case_id") or "") in KNOWN_COMPONENT_ISSUE_CASES,
            }
            for case in source_cases
        ]
        executed_source_ids = [str(case.get("test_case_id") or "") for case in source_cases]
        known_issue_ids = [
            case_id for case_id in executed_source_ids if case_id in KNOWN_COMPONENT_ISSUE_CASES
        ]
        assertions = [
            f"{case_id}: {_case_status(cases_by_id[case_id])}"
            for case_id in executed_source_ids
        ]
        if not source_cases:
            assertions.append("No OH-APP functional UI evidence is mapped for this PT5 case in the current run.")

        pt5_results.append(
            {
                "test_case_id": pt5_id,
                "description": pt5_case["description"],
                "case_group": "pt5",
                "validation_type": pt5_case["validation_type"],
                "dataspace_dimension": pt5_case["dataspace_dimension"],
                "mapping_status": "mapped" if source_cases else "partial",
                "coverage_status": "automated_via_oh_app" if source_cases else "not_covered_by_functional_ui",
                "automation_mode": "ui_functional_traceability",
                "execution_mode": "ui_functional_traceability",
                "expected_result": pt5_case["description"],
                "source_suite": "functional",
                "source_suites": ["functional"] if source_cases else [],
                "mapped_oh_app_cases": mapped_oh_app_ids,
                "executed_oh_app_cases": executed_source_ids,
                "known_component_issue_cases": known_issue_ids,
                "evidences": source_case_summaries,
                "evaluation": {
                    "status": status,
                    "assertions": assertions,
                },
            }
        )

    return sorted(pt5_results, key=lambda case: _case_sort_key(str(case.get("test_case_id") or "")))


def summarize_pt5_case_results(pt5_case_results: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"total": len(pt5_case_results), "passed": 0, "failed": 0, "skipped": 0}
    for case in pt5_case_results:
        status = ((case.get("evaluation") or {}).get("status") or "skipped").lower()
        if status in summary:
            summary[status] += 1
    return summary


def build_functional_catalog_alignment(
    *,
    executed_cases: List[Dict[str, Any]],
    pt5_case_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    executed_oh_app_ids = {str(case.get("test_case_id") or "") for case in executed_cases}
    executed_pt5_ids = {
        str(case.get("test_case_id") or "")
        for case in pt5_case_results
        if ((case.get("evaluation") or {}).get("status") or "skipped").lower() != "skipped"
    }
    uncovered_pt5_cases = [
        case for case in pt5_case_results if str(case.get("test_case_id") or "") not in executed_pt5_ids
    ]
    unmapped_oh_app_cases = sorted(
        case_id for case_id in executed_oh_app_ids if case_id not in OH_APP_TO_PT5
    )

    return {
        "source_file": "context/A5.2_Casos_Prueba_Framework_Reproducibles.xlsx",
        "source_documents": [
            "context/deliverables/logs.txt",
            "context/deliverables/ontology-hub/PIONERA E2.1 - final.docx",
            "context/deliverables/validation/PIONERA E5.1 - final.docx",
        ],
        "summary": {
            "declared_pt5_cases": len(PT5_CASES),
            "executed_pt5_cases": len(executed_pt5_ids),
            "uncovered_pt5_cases": len(uncovered_pt5_cases),
            "declared_oh_app_mappings": len(OH_APP_TO_PT5),
            "executed_oh_app_cases": len(executed_oh_app_ids),
            "executed_oh_app_not_mapped_to_pt5": len(unmapped_oh_app_cases),
        },
        "uncovered_pt5_cases": uncovered_pt5_cases,
        "executed_oh_app_not_mapped_to_pt5": unmapped_oh_app_cases,
    }
