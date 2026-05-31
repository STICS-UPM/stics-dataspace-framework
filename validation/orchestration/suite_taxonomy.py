from __future__ import annotations

from typing import Any


COMPONENT_LABELS = {
    "ontology-hub": "Ontology Hub",
    "ontology_hub": "Ontology Hub",
    "ai-model-hub": "AI Model Hub",
    "ai_model_hub": "AI Model Hub",
    "semantic-virtualization": "Semantic Virtualization",
    "semantic_virtualization": "Semantic Virtualization",
}

INTEGRATION_SUITE = "INESData integration"
AUDIT_ASSURANCE_SUITE = "Audit assurance"


def _normalized(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _canonical(value: Any) -> str:
    return _normalized(value).replace("_", "-")


def _component_label(value: str) -> str | None:
    canonical = _canonical(value)
    return COMPONENT_LABELS.get(canonical) or COMPONENT_LABELS.get(canonical.replace("-", "_"))


def _taxonomy(audit_suite: str, audit_group: str) -> dict[str, str]:
    return {
        "audit_suite": audit_suite,
        "audit_group": audit_group,
    }


def classify_playwright_spec(spec_file: Any, *, source_path: Any = "") -> dict[str, str]:
    """Classify a Playwright spec without moving it in the repository."""

    spec = _canonical(spec_file)
    source = _canonical(source_path)
    blob = f"{source} {spec}"

    if "08-ontology-hub-inesdata-readonly.spec" in blob:
        return _taxonomy(INTEGRATION_SUITE, "Ontology Hub")
    if (
        "09-ai-model-hub-httpdata.spec" in blob
        or "10-ai-model-observer.spec" in blob
        or "11-ai-model-browser.spec" in blob
        or "12-ai-model-execution.spec" in blob
        or "13-ai-model-benchmarking.spec" in blob
        or "14-ai-model-daimo-vocabulary.spec" in blob
        or "15-ai-model-external-execution.spec" in blob
        or "16-ai-model-observer-participant-summary.spec" in blob
    ):
        return _taxonomy(INTEGRATION_SUITE, "AI Model Hub")
    if "07-semantic-virtualization-httpdata.spec" in blob:
        return _taxonomy(INTEGRATION_SUITE, "Semantic Virtualization")
    if (
        "06b-minio-bucket-visibility.spec" in blob
        or "ops/minio-bucket-visibility.spec" in blob
        or "shared/specs/minio-bucket-visibility" in blob
    ):
        return _taxonomy(INTEGRATION_SUITE, "Operational Storage")
    if (
        "/ui/inesdata/" in f"/{source}/"
        or "validation/ui/adapters/inesdata/specs/" in blob
        or "validation/ui/core/" in blob
        or blob.startswith("core/")
        or blob.startswith("adapters/inesdata/specs/")
    ):
        return _taxonomy(INTEGRATION_SUITE, "Core")

    if "components/ontology-hub/functional/" in blob:
        return _taxonomy("Ontology Hub", "Functional")
    if "components/ontology-hub/integration/" in blob:
        return _taxonomy("Ontology Hub", "API integration")

    if "components/ai-model-hub/inesdata-ui/" in blob:
        return _taxonomy(INTEGRATION_SUITE, "AI Model Hub")
    if "components/ai-model-hub/ui/specs/pt5-mh-03" in blob or "components/ai-model-hub/ui/specs/pt5-mh-08" in blob:
        return _taxonomy(INTEGRATION_SUITE, "AI Model Hub")
    if "components/ai-model-hub/" in blob:
        return _taxonomy("AI Model Hub", "Functional")

    if "components/semantic-virtualization/" in blob:
        return _taxonomy("Semantic Virtualization", "Functional")

    if "/ui/edc/" in f"/{source}/" or "adapters/edc/specs/" in blob:
        return _taxonomy("EDC integration", "Core")

    return _taxonomy("Unclassified", "Review")


def classify_suite_artifact(
    *,
    kind: Any = "",
    title: Any = "",
    artifacts: list[Any] | tuple[Any, ...] | None = None,
) -> dict[str, str]:
    kind_value = _canonical(kind)
    artifact_blob = " ".join(_canonical(path) for path in artifacts or [])
    title_value = _canonical(title)
    blob = f"{kind_value} {title_value} {artifact_blob}"

    if kind_value == "newman":
        return _taxonomy(INTEGRATION_SUITE, "Core API")
    if kind_value == "kafka":
        return _taxonomy(INTEGRATION_SUITE, "Kafka / streaming transfer")
    if kind_value == "stability":
        return _taxonomy(AUDIT_ASSURANCE_SUITE, "Stability")
    if kind_value == "une-0087":
        return _taxonomy(AUDIT_ASSURANCE_SUITE, "UNE-0087")

    if "ui-ops/minio-console" in blob or "ui-ops-minio-console" in blob or "ops/minio-bucket-visibility.spec" in blob:
        return _taxonomy(INTEGRATION_SUITE, "Operational Storage")
    if "ui/inesdata/" in blob:
        return _taxonomy(INTEGRATION_SUITE, "Combined Playwright")
    if "components/ontology-hub/" in blob:
        if (
            "/integration/" in blob
            or "ontology-hub-api-integration" in blob
            or "ontology-hub-integration-component-validation" in blob
        ):
            return _taxonomy("Ontology Hub", "API integration")
        return _taxonomy("Ontology Hub", "Functional")
    if "components/ai-model-hub/inesdata-ui/" in blob:
        return _taxonomy(INTEGRATION_SUITE, "AI Model Hub")
    if "components/ai-model-hub/" in blob:
        if "/integration/" in blob:
            return _taxonomy("AI Model Hub", "Component integration")
        return _taxonomy("AI Model Hub", "Functional")
    if "components/semantic-virtualization/" in blob:
        if "/integration/" in blob:
            return _taxonomy("Semantic Virtualization", "Component integration")
        return _taxonomy("Semantic Virtualization", "Functional")
    if "ui/edc/" in blob or "adapters/edc/" in blob:
        return _taxonomy("EDC integration", "Core")

    component = _component_label(str(title or ""))
    if component:
        return _taxonomy(component, "Component validation")

    return _taxonomy("Unclassified", "Review")


def summarize_group_taxonomy(groups: list[dict[str, Any]]) -> dict[str, str]:
    if not groups:
        return _taxonomy("Unclassified", "Review")

    suites = sorted({str(group.get("audit_suite") or "Unclassified") for group in groups})
    group_names = sorted({str(group.get("audit_group") or "Review") for group in groups})
    audit_suite = suites[0] if len(suites) == 1 else "Multiple audit suites"
    audit_group = group_names[0] if len(group_names) == 1 else f"{len(group_names)} groups"
    return _taxonomy(audit_suite, audit_group)


def suite_sort_key(suite: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(suite.get("audit_suite") or "Unclassified"),
        str(suite.get("audit_group") or "Review"),
        str(suite.get("title") or suite.get("kind") or ""),
    )
