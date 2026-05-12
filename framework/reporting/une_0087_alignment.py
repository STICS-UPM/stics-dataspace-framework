from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ASSESSMENT_TYPE = "non_certifying_alignment"
SOURCE_DOCUMENT = "02_Guia verificacion conformidad UNE 0087_v1.pdf"
TEXT_EXTENSIONS = {
    ".csv",
    ".html",
    ".json",
    ".jsonl",
    ".js",
    ".md",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "framework-report",
    "node_modules",
    "playwright-report",
    "test-results",
}
SKIP_FILES = {
    "une_0087_alignment.json",
    "une_0087_alignment.md",
}


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    dimension: str
    requirement: str
    expected_evidence: str
    evidence_type: str
    keywords: tuple[str, ...]
    status_if_evidence: str = "covered"
    status_without_evidence: str = "not_covered"
    limitation: str = ""


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "Neg.1",
        "Modelo de negocio",
        "Existe un documento de modelo de negocio con objetivos, propuesta de valor, participantes y fuentes de ingresos.",
        "Plan de negocio, memoria estrategica o documento equivalente.",
        "documental",
        ("modelo de negocio", "propuesta de valor", "participantes", "fuentes de ingresos", "e5.1", "a5.2"),
        "partially_covered",
        limitation="A5.2 puede enlazar documentacion, pero no certifica el modelo de negocio.",
    ),
    Criterion(
        "Neg.2",
        "Modelo de negocio",
        "Se identifican participantes y roles del ecosistema.",
        "Organigrama funcional, estatutos o documentacion de gobernanza.",
        "documental",
        ("provider", "consumer", "operator", "participantes", "roles", "conn-citycouncil", "conn-company"),
        "partially_covered",
    ),
    Criterion(
        "Neg.3",
        "Modelo de negocio",
        "Existe un plan de sostenibilidad o estrategia de escalado para continuidad y nuevos actores.",
        "Documento de planificacion o estrategia de crecimiento.",
        "documental",
        (
            "plan_sostenibilidad",
            "sustainability_plan",
            "business_sustainability",
            "estrategia de crecimiento aprobada",
            "continuidad economica",
        ),
        "partially_covered",
        limitation="La sostenibilidad economica queda fuera de la evidencia tecnica automatica.",
    ),
    Criterion(
        "Gob.1",
        "Sistema de gobernanza",
        "Existe constitucion formal de la autoridad de gobierno del espacio de datos.",
        "Estatuto, acta constitutiva o documentacion de constitucion.",
        "documental",
        ("authority_charter", "governance_authority_charter", "acta constitutiva", "estatuto formal"),
        "partially_covered",
        limitation="Requiere evidencia formal externa al framework.",
    ),
    Criterion(
        "Gob.2",
        "Sistema de gobernanza",
        "Existe un marco de gobernanza documentado con reglas, roles y responsabilidades.",
        "Libro de reglas, roles, reglamento interno o equivalente.",
        "documental",
        ("gobernanza", "reglas", "roles", "responsabilidades", "e5.1", "a5.2"),
        "partially_covered",
    ),
    Criterion(
        "Gob.3",
        "Sistema de gobernanza",
        "Estan documentados los procedimientos de adhesion, permanencia y salida de participantes.",
        "Formularios, contratos de adhesion, procesos publicados o registros.",
        "documental",
        ("adhesion", "alta", "registro", "participante", "usuarios", "agents", "keycloak"),
        "partially_covered",
    ),
    Criterion(
        "Gob.4",
        "Sistema de gobernanza",
        "Existen mecanismos de resolucion de conflictos y rendicion de cuentas.",
        "Protocolo de gestion de incidencias.",
        "documental",
        ("issue", "issues", "incidencia", "findings", "blocking_issues", "postflight"),
        "partially_covered",
    ),
    Criterion(
        "Gob.5",
        "Sistema de gobernanza",
        "Existe un repositorio o portal de transparencia accesible para participantes.",
        "URL, portal de transparencia o repositorio de politicas.",
        "documental",
        ("github", "repositorio", "dashboard", "report_viewer", "framework-report", "politicas"),
        "partially_covered",
    ),
    Criterion(
        "Tec.1",
        "Solucion tecnica y seguridad",
        "Existe una arquitectura tecnica definida y documentada.",
        "Diagrama de arquitectura, documentacion tecnica o ficha de diseno.",
        "documental",
        ("architecture", "arquitectura", "topology", "topologia", "deployers", "metadata.json"),
    ),
    Criterion(
        "Tec.2",
        "Solucion tecnica y seguridad",
        "Se implementan mecanismos de identificacion y autenticacion de participantes y servicios.",
        "Sistema de identidad digital, credenciales verificables o logs de acceso.",
        "tecnica",
        ("auth", "authentication", "authorization", "keycloak", "login", "token", "access"),
    ),
    Criterion(
        "Tec.3",
        "Solucion tecnica y seguridad",
        "Existe un catalogo estructurado para publicar y descubrir datos y servicios.",
        "Catalogo DCAT o plataforma de servicios registrada.",
        "tecnica",
        ("catalog", "catalogo", "dcat", "asset", "vocabulary", "ontology_hub_catalog", "ai_model_hub_catalog"),
    ),
    Criterion(
        "Tec.4",
        "Solucion tecnica y seguridad",
        "Existen mecanismos de transferencia y control con integridad y trazabilidad de intercambios.",
        "Registros de transaccion, conectores o logs de validacion.",
        "tecnica",
        ("transfer", "kafka_transfer", "negotiation", "contract", "edr", "traceability", "semantic_virtualization_dataspace"),
    ),
    Criterion(
        "Tec.5",
        "Solucion tecnica y seguridad",
        "Existen medidas de seguridad y privacidad, incluyendo cifrado, aislamiento y control de accesos conforme al RGPD.",
        "Politicas de privacidad, cifrado, consentimiento o control de accesos.",
        "mixta",
        ("privacy", "rgpd", "gdpr", "tls", "secret", "token", "127.0.0.1", "no_jwt_or_bearer", "trace"),
        "partially_covered",
        limitation="La evidencia automatica cubre controles tecnicos, no una auditoria RGPD formal.",
    ),
    Criterion(
        "Tec.6",
        "Solucion tecnica y seguridad",
        "Existen mecanismos de cumplimiento y auditoria para verificar conformidad y trazabilidad de procesos.",
        "Logs de auditoria, informes tecnicos, reportes de cumplimiento o certificaciones.",
        "mixta",
        ("summary.json", "summary.md", "framework-report", "alignment", "audit", "logs", "evidence_index"),
        "partially_covered",
        limitation="El framework genera trazabilidad tecnica, no certificaciones de seguridad.",
    ),
    Criterion(
        "Int.1",
        "Interoperabilidad",
        "El espacio de datos permite transferencia controlada de datos entre sistemas.",
        "Demostraciones de descarga, API o conector, y documentacion de red/protocolos.",
        "tecnica",
        ("transfer", "download", "api", "connector", "kafka_transfer", "dataspace", "semantic_virtualization_dataspace"),
    ),
    Criterion(
        "Int.2",
        "Interoperabilidad",
        "Existen autenticacion, autorizacion y registro para limitar el acceso a participantes acreditados.",
        "Sistema de identidad, logs de autenticacion, credenciales o politicas de autorizacion.",
        "tecnica",
        ("auth", "authorization", "keycloak", "participant", "access", "login", "credential"),
    ),
    Criterion(
        "Int.3",
        "Interoperabilidad",
        "Se validan reglas, politicas de uso y terminos contractuales antes de la transferencia.",
        "Evidencia de contrato digital, politicas, licencias o bloqueo ante incumplimiento.",
        "tecnica",
        ("policy", "contract", "negotiation", "agreement", "edr", "transfer_process"),
    ),
    Criterion(
        "Int.4",
        "Interoperabilidad",
        "Se aplican protocolos y especificaciones interoperables como conectores, APIs, DCAT, RDF u ontologias.",
        "Documentacion de APIs, conectores y estandares aplicados.",
        "tecnica",
        ("dcat", "rdf", "sparql", "ontology", "semantic", "api", "openapi", "connector", "gtfs"),
    ),
    Criterion(
        "Int.5",
        "Interoperabilidad",
        "Se mantiene un registro trazable de transacciones para auditoria posterior e integridad.",
        "Logs, auditorias automaticas, evidencias de observabilidad o paneles.",
        "tecnica",
        ("trace", "traceability", "transaction", "logs", "raw_requests", "metrics", "evidence"),
    ),
    Criterion(
        "Fun.1",
        "Verificacion funcional",
        "Existe evidencia del proceso de adhesion de un participante.",
        "Capturas de registro o demostracion del proceso de alta.",
        "observable",
        ("register", "registration", "user", "users", "agents", "keycloak", "login", "participante"),
        "partially_covered",
        limitation="La automatizacion valida usuarios/roles; la adhesion formal requiere documentacion adicional.",
    ),
    Criterion(
        "Fun.2",
        "Verificacion funcional",
        "Existe evidencia de publicacion de un producto o servicio en el catalogo.",
        "Captura o demostracion funcional de publicacion.",
        "observable",
        ("create_asset", "publish", "publication", "asset", "catalog", "bootstrap", "model", "vocabulary"),
    ),
    Criterion(
        "Fun.3",
        "Verificacion funcional",
        "Existe evidencia de consulta o descubrimiento del catalogo por un usuario.",
        "Registro de busqueda o demostracion funcional.",
        "observable",
        ("catalog", "search", "discovery", "list assets", "vocabulary", "model catalog", "consumer_catalog"),
    ),
    Criterion(
        "Fun.4",
        "Verificacion funcional",
        "Existe evidencia de transaccion efectiva de datos o servicios entre participantes.",
        "Logs de intercambio, contratos digitales o APIs.",
        "observable",
        ("transfer", "contract", "negotiation", "kafka_transfer", "api", "infer", "traceability", "finalized"),
    ),
)


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_project_evidence_paths(project_root: Path) -> list[Path]:
    relative_paths = [
        "context/01_framework_architecture.md",
        "context/02_validation_architecture.md",
        "context/03_integration_guide.md",
        "context/06_information_exchange_flow.md",
        "context/13_test_cases.md",
        "context/15_ai_model_hub_validation_plan.md",
        "context/30_deliverables_analysis_and_gap_matrix.md",
        "context/40_experiment_report_dashboard_plan.md",
        "context/41_a52_completion_plan.md",
        "context/A5.2_Casos_Prueba_ copy.xlsx",
        "context/deliverables/validation/PIONERA E5.1 - final.docx",
        "docs/report_viewer.md",
    ]
    return [project_root / path for path in relative_paths if (project_root / path).exists()]


def _iter_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.name in SKIP_FILES:
            return []
        return [path]
    if not path.is_dir():
        return []
    files: list[Path] = []
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file():
            continue
        if any(part in SKIP_DIRS for part in candidate.parts):
            continue
        if candidate.name in SKIP_FILES:
            continue
        files.append(candidate)
    return files


def _read_search_text(path: Path, max_chars: int = 120_000) -> str:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def _relative_or_absolute(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _evidence_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".json", ".jsonl", ".yaml", ".yml"}:
        return "machine-readable"
    if suffix in {".md", ".txt", ".docx", ".pdf", ".xlsx"}:
        return "documental"
    if suffix in {".html", ".png", ".jpg", ".jpeg", ".webm", ".zip"}:
        return "observable"
    return "artifact"


def collect_evidence(
    experiment_dir: str | Path,
    *,
    additional_evidence_paths: list[str | Path] | None = None,
    include_project_context: bool = True,
    project_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    root = Path(project_root) if project_root else default_project_root()
    experiment_path = Path(experiment_dir)
    sources: list[Path] = [experiment_path]
    if include_project_context:
        sources.extend(default_project_evidence_paths(root))
    sources.extend(Path(path) for path in (additional_evidence_paths or []))

    seen: set[Path] = set()
    evidence: list[dict[str, Any]] = []
    for source in sources:
        for path in _iter_files(source):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            relative_path = _relative_or_absolute(path, root)
            search_text = f"{relative_path}\n{path.name}\n{_read_search_text(path)}".lower()
            evidence.append(
                {
                    "path": str(path),
                    "relative_path": relative_path,
                    "name": path.name,
                    "kind": _evidence_kind(path),
                    "search_text": search_text,
                }
            )
    return evidence


def _matching_evidence(criterion: Criterion, evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for item in evidence:
        text = str(item.get("search_text") or "")
        matched_keywords = [keyword for keyword in criterion.keywords if keyword.lower() in text]
        if not matched_keywords:
            continue
        matches.append(
            {
                "path": str(item["relative_path"]),
                "kind": str(item["kind"]),
                "matched_keywords": sorted(set(matched_keywords)),
            }
        )
    return matches


def _criterion_status(criterion: Criterion, matches: list[dict[str, str]]) -> str:
    return criterion.status_if_evidence if matches else criterion.status_without_evidence


def _summarize_criteria(criteria: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = {
        "covered": 0,
        "partially_covered": 0,
        "not_covered": 0,
        "not_applicable": 0,
    }
    dimensions: dict[str, dict[str, int]] = {}
    for item in criteria:
        status = str(item.get("status") or "not_covered")
        statuses[status] = statuses.get(status, 0) + 1
        dimension = str(item.get("dimension") or "unknown")
        dimensions.setdefault(dimension, {key: 0 for key in statuses})
        dimensions[dimension][status] = dimensions[dimension].get(status, 0) + 1
    return {
        "total_criteria": len(criteria),
        "statuses": statuses,
        "dimensions": dimensions,
    }


def build_une_0087_alignment(
    experiment_dir: str | Path,
    *,
    additional_evidence_paths: list[str | Path] | None = None,
    include_project_context: bool = True,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    experiment_path = Path(experiment_dir)
    evidence = collect_evidence(
        experiment_path,
        additional_evidence_paths=additional_evidence_paths,
        include_project_context=include_project_context,
        project_root=project_root,
    )
    criteria = []
    for criterion in CRITERIA:
        matches = _matching_evidence(criterion, evidence)
        criteria.append(
            {
                "id": criterion.criterion_id,
                "dimension": criterion.dimension,
                "requirement": criterion.requirement,
                "expected_evidence": criterion.expected_evidence,
                "evidence_type": criterion.evidence_type,
                "status": _criterion_status(criterion, matches),
                "evidence": matches[:10],
                "evidence_count": len(matches),
                "limitation": criterion.limitation,
            }
        )

    return {
        "schema_version": "1.0",
        "assessment_type": ASSESSMENT_TYPE,
        "certification_claim": False,
        "source_document": SOURCE_DOCUMENT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment_dir": str(experiment_path),
        "notice": (
            "This report maps available A5.2 validation evidence to UNE 0087 criteria. "
            "It is a support artifact and does not claim formal certification."
        ),
        "summary": _summarize_criteria(criteria),
        "criteria": criteria,
    }


def build_une_0087_markdown(alignment: dict[str, Any]) -> str:
    summary = alignment.get("summary") if isinstance(alignment.get("summary"), dict) else {}
    statuses = summary.get("statuses") if isinstance(summary.get("statuses"), dict) else {}
    lines = [
        "# UNE 0087 Alignment",
        "",
        f"- Assessment type: `{alignment.get('assessment_type')}`",
        f"- Certification claim: `{alignment.get('certification_claim')}`",
        f"- Source: `{alignment.get('source_document')}`",
        f"- Experiment: `{alignment.get('experiment_dir')}`",
        "",
        "This is a non-certifying support artifact for A5.2 closure. It maps evidence already produced by the framework to the checklist criteria.",
        "",
        "## Summary",
        "",
        f"- Total criteria: `{summary.get('total_criteria', 0)}`",
        f"- Covered: `{statuses.get('covered', 0)}`",
        f"- Partially covered: `{statuses.get('partially_covered', 0)}`",
        f"- Not covered: `{statuses.get('not_covered', 0)}`",
        f"- Not applicable: `{statuses.get('not_applicable', 0)}`",
        "",
        "## Criteria",
        "",
        "| Criterion | Dimension | Status | Evidence |",
        "| --- | --- | --- | ---: |",
    ]
    for item in alignment.get("criteria") or []:
        lines.append(
            f"| `{item.get('id')}` | {item.get('dimension')} | `{item.get('status')}` | {item.get('evidence_count', 0)} |"
        )

    lines.extend(["", "## Notes", ""])
    for item in alignment.get("criteria") or []:
        limitation = str(item.get("limitation") or "").strip()
        if limitation:
            lines.append(f"- `{item.get('id')}`: {limitation}")

    return "\n".join(lines) + "\n"


def write_une_0087_alignment(
    experiment_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    additional_evidence_paths: list[str | Path] | None = None,
    include_project_context: bool = True,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    target_dir = Path(output_dir) if output_dir else Path(experiment_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    alignment = build_une_0087_alignment(
        experiment_dir,
        additional_evidence_paths=additional_evidence_paths,
        include_project_context=include_project_context,
        project_root=project_root,
    )
    (target_dir / "une_0087_alignment.json").write_text(
        json.dumps(alignment, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target_dir / "une_0087_alignment.md").write_text(
        build_une_0087_markdown(alignment),
        encoding="utf-8",
    )
    return alignment


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a non-certifying UNE 0087 evidence alignment report.")
    parser.add_argument("--experiment-dir", required=True, help="Experiment directory used as the primary evidence source.")
    parser.add_argument("--output-dir", help="Directory where une_0087_alignment.json/md will be written.")
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="Additional evidence file or directory. Can be passed multiple times.",
    )
    parser.add_argument(
        "--no-project-context",
        action="store_true",
        help="Do not include default docs/context evidence from the project root.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    alignment = write_une_0087_alignment(
        args.experiment_dir,
        output_dir=args.output_dir,
        additional_evidence_paths=args.evidence,
        include_project_context=not args.no_project_context,
    )
    summary = alignment["summary"]["statuses"]
    print(
        "UNE 0087 alignment generated: "
        f"covered={summary.get('covered', 0)}, "
        f"partially_covered={summary.get('partially_covered', 0)}, "
        f"not_covered={summary.get('not_covered', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
