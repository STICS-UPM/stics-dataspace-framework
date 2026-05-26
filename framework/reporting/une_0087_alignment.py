from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten
from typing import Any


ASSESSMENT_TYPE = "non_certifying_alignment"
SOURCE_DOCUMENT = "Guía UNE 0087:2025, Anexo A"
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


CHECKLIST_STATUS = {
    "covered": {
        "label": "Cubierto",
        "meaning": "Cubierto por evidencia técnica o documental disponible para el framework.",
    },
    "partially_covered": {
        "label": "Parcial",
        "meaning": "Existe evidencia relacionada, pero aún requiere revisión manual o documental.",
    },
    "not_covered": {
        "label": "Pendiente",
        "meaning": "No hay evidencia suficiente en el experimento de nivel 6 o en la documentación versionada.",
    },
    "not_applicable": {
        "label": "N/A",
        "meaning": "El criterio no aplica al alcance de esta validación.",
    },
}


CHECKLIST_GUIDANCE: dict[str, dict[str, str]] = {
    "Neg.1": {
        "evidence_basis": "Modelo de negocio aprobado o memoria estratégica",
        "rationale": "El nivel 6 puede referenciar trazabilidad del proyecto, pero no aprueba el modelo de negocio.",
        "pending_action": "Adjuntar la evidencia aprobada del modelo de negocio para revisión formal.",
    },
    "Neg.2": {
        "evidence_basis": "Documentación de participantes y roles",
        "rationale": "Los roles provider/consumer se ejercitan técnicamente, pero la evidencia formal de roles es documental.",
        "pending_action": "Adjuntar la evidencia oficial de participantes y roles si se persigue certificación.",
    },
    "Neg.3": {
        "evidence_basis": "Plan de sostenibilidad o escalado",
        "rationale": "Este criterio queda fuera de la evidencia técnica generada por el nivel 6.",
        "pending_action": "Aportar un documento aprobado de sostenibilidad o escalado.",
    },
    "Gob.1": {
        "evidence_basis": "Documento formal de autoridad de gobernanza",
        "rationale": "El nivel 6 no constituye autoridad legal u organizativa de gobernanza.",
        "pending_action": "Aportar estatuto, acta constitutiva o evidencia equivalente de gobernanza.",
    },
    "Gob.2": {
        "evidence_basis": "Libro de reglas de gobernanza o equivalente",
        "rationale": "El framework muestra roles operativos, no el libro completo de reglas de gobernanza.",
        "pending_action": "Adjuntar las reglas y responsabilidades de gobernanza aprobadas.",
    },
    "Gob.3": {
        "evidence_basis": "Procedimientos de adhesión, permanencia y salida",
        "rationale": "Se prueban flujos de acceso y usuario, pero el ciclo de vida formal del participante es documental.",
        "pending_action": "Adjuntar procedimientos y registros del ciclo de vida de participantes.",
    },
    "Gob.4": {
        "evidence_basis": "Procedimiento de incidencias y rendición de cuentas",
        "rationale": "Los fallos de pruebas y logs apoyan la trazabilidad, pero no sustituyen un procedimiento de conflictos.",
        "pending_action": "Adjuntar el procedimiento de gestión de incidencias y conflictos.",
    },
    "Gob.5": {
        "evidence_basis": "Portal de transparencia o repositorio de políticas",
        "rationale": "Existe evidencia de repositorio y dashboard, pero la publicación de políticas requiere revisión manual.",
        "pending_action": "Confirmar el repositorio o portal oficial de transparencia.",
    },
    "Tec.1": {
        "evidence_basis": "Documentación de arquitectura versionada y metadatos del experimento",
        "rationale": "El framework incluye documentación de arquitectura y registra metadatos de topología.",
        "pending_action": "Mantener diagramas y documentación de topologías sincronizados con el framework desplegado.",
    },
    "Tec.2": {
        "evidence_basis": "Autenticación Keycloak/Newman y evidencia de APIs autenticadas",
        "rationale": "El nivel 6 valida autenticación provider/consumer y acceso a APIs protegidas.",
        "pending_action": "Conservar la evidencia de autenticación en el reporte del experimento.",
    },
    "Tec.3": {
        "evidence_basis": "API de catálogo, catálogo UI y evidencia de catálogos de componentes",
        "rationale": "El nivel 6 valida publicación y descubrimiento mediante catálogos y vistas de componentes.",
        "pending_action": "Mantener la evidencia de catálogo enlazada desde nivel 6 y el Excel E5.2.",
    },
    "Tec.4": {
        "evidence_basis": "Transferencias Newman, verificaciones de almacenamiento y logs de conectores",
        "rationale": "El nivel 6 valida negociación, estado de transferencia y trazabilidad del destino.",
        "pending_action": "Ejecutar Kafka explícitamente cuando se requiera evidencia de transferencia streaming.",
    },
    "Tec.5": {
        "evidence_basis": "Trazas de control de acceso y configuración sin secretos",
        "rationale": "El framework aporta evidencia técnica de seguridad, no una auditoría formal RGPD/seguridad.",
        "pending_action": "Adjuntar evidencia de privacidad, cifrado y RGPD para revisión formal.",
    },
    "Tec.6": {
        "evidence_basis": "Dashboard, logs, artefactos JSON y alineación de auditoría",
        "rationale": "El framework genera artefactos de trazabilidad, pero no certificaciones externas.",
        "pending_action": "Usar el dashboard y el Excel como índice de evidencias; adjuntar certificaciones por separado si existen.",
    },
    "Int.1": {
        "evidence_basis": "Transferencia por conectores y evidencia API",
        "rationale": "El nivel 6 valida intercambio controlado entre conectores provider y consumer.",
        "pending_action": "Activar Kafka cuando la transferencia streaming deba incluirse en el paquete de evidencias.",
    },
    "Int.2": {
        "evidence_basis": "Autenticación, autorización y logs de acceso",
        "rationale": "El nivel 6 valida acceso autenticado a APIs de participantes y flujos UI.",
        "pending_action": "Conservar artefactos de autenticación y logs saneados en el reporte del experimento.",
    },
    "Int.3": {
        "evidence_basis": "Políticas, negociación contractual y evidencia de acuerdos",
        "rationale": "El nivel 6 valida negociación de políticas y contratos antes de la transferencia.",
        "pending_action": "Conservar métricas de negociación y trazas de solicitudes con el experimento.",
    },
    "Int.4": {
        "evidence_basis": "APIs de conectores, RDF/SPARQL y metadatos de catálogo",
        "rationale": "El nivel 6 ejercita APIs interoperables y protocolos semánticos usados por los componentes.",
        "pending_action": "Mantener sincronizada la evidencia API/SPARQL y los reportes de componentes.",
    },
    "Int.5": {
        "evidence_basis": "Solicitudes crudas, métricas, logs y dashboard",
        "rationale": "El nivel 6 registra trazas legibles por máquina para revisión posterior de auditoría.",
        "pending_action": "Usar el dashboard y los artefactos JSON como índice de evidencia transaccional.",
    },
    "Fun.1": {
        "evidence_basis": "Evidencia de login/usuarios/roles y documentación del ciclo de vida de participantes",
        "rationale": "El nivel 6 valida comportamiento de acceso, pero la adhesión formal sigue siendo documental.",
        "pending_action": "Adjuntar evidencia de adhesión de participantes si se requiere cierre formal del checklist.",
    },
    "Fun.2": {
        "evidence_basis": "Publicación mediante UI/API y validación de componentes",
        "rationale": "El nivel 6 valida publicación de activos, vocabularios, modelos o servicios.",
        "pending_action": "Conservar artefactos Playwright/Newman/componentes en el experimento.",
    },
    "Fun.3": {
        "evidence_basis": "Descubrimiento de catálogo mediante UI/API",
        "rationale": "El nivel 6 valida búsqueda, listado y vistas de detalle del catálogo.",
        "pending_action": "Conservar evidencia UI/API de descubrimiento en el experimento.",
    },
    "Fun.4": {
        "evidence_basis": "Transferencia negociada, llamadas API y evidencia de ejecución de servicios",
        "rationale": "El nivel 6 valida transacciones efectivas entre participantes o servicios de componentes.",
        "pending_action": "Conservar artefactos de transferencia y ejecución en el experimento.",
    },
}


CHECKLIST_ARTIFACTS: dict[str, list[dict[str, str]]] = {
    "Neg.1": [
        {"scope": "project", "path": "docs/E5.2_Resultados_Validacion_Componentes.xlsx", "title": "Excel E5.2"},
        {"scope": "project", "path": "docs/A5.2_Casos_Prueba_.xlsx", "title": "Casos de prueba A5.2"},
    ],
    "Neg.2": [
        {"scope": "experiment", "path": "metadata.json", "title": "Metadatos del experimento"},
        {"scope": "project", "path": "docs/E5.2_Resultados_Validacion_Componentes.xlsx", "title": "Excel E5.2"},
    ],
    "Neg.3": [],
    "Gob.1": [],
    "Gob.2": [
        {"scope": "project", "path": "docs/44_audit_navigation_guide.md", "title": "Guía de navegación para auditoría"},
        {"scope": "project", "path": "docs/30_framework_current_state.md", "title": "Estado actual del framework"},
    ],
    "Gob.3": [
        {"scope": "experiment", "path": "level6_console.log", "title": "Log de consola de nivel 6"},
        {"scope": "project", "path": "docs/37_validation.md", "title": "Documentación de validación"},
    ],
    "Gob.4": [
        {"scope": "experiment", "path": "level6_console.log", "title": "Log de consola de nivel 6"},
        {"scope": "experiment", "path": "local_stability_postflight.json", "title": "Postflight de estabilidad local"},
    ],
    "Gob.5": [
        {"scope": "experiment", "path": "framework-report/index.html", "title": "Dashboard del framework"},
        {"scope": "project", "path": "docs/44_audit_navigation_guide.md", "title": "Guía de navegación para auditoría"},
    ],
    "Tec.1": [
        {"scope": "project", "path": "docs/34_architecture.md", "title": "Documentación de arquitectura"},
        {"scope": "project", "path": "docs/35_deployers_and_topologies.md", "title": "Deployers y topologías"},
        {"scope": "experiment", "path": "metadata.json", "title": "Metadatos del experimento"},
    ],
    "Tec.2": [
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
        {"scope": "experiment", "path": "test_results.json", "title": "Aserciones Newman"},
        {"scope": "experiment", "path": "level6_console.log", "title": "Log de consola de nivel 6"},
    ],
    "Tec.3": [
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
        {"scope": "experiment", "path": "ui/inesdata/results.json", "title": "Resultados UI INESData"},
        {"scope": "experiment", "path": "components/*/*_component_validation.json", "title": "JSON de validación de componentes"},
    ],
    "Tec.4": [
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
        {"scope": "experiment", "path": "raw_requests.jsonl", "title": "Traza de solicitudes crudas"},
        {"scope": "experiment", "path": "storage_checks", "title": "Verificaciones de almacenamiento"},
        {"scope": "experiment", "path": "kafka_transfer_results.json", "title": "Resultados de transferencia Kafka"},
    ],
    "Tec.5": [
        {"scope": "experiment", "path": "level6_console.log", "title": "Log de consola de nivel 6"},
        {"scope": "project", "path": "docs/35_deployers_and_topologies.md", "title": "Deployers y topologías"},
    ],
    "Tec.6": [
        {"scope": "experiment", "path": "framework-report/index.html", "title": "Dashboard del framework"},
        {"scope": "experiment", "path": "level6_console.log", "title": "Log de consola de nivel 6"},
        {"scope": "experiment", "path": "une_0087_alignment.json", "title": "UNE 0087 JSON"},
    ],
    "Int.1": [
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
        {"scope": "experiment", "path": "kafka_transfer_results.json", "title": "Resultados de transferencia Kafka"},
        {"scope": "experiment", "path": "ui/inesdata/results.json", "title": "Resultados UI INESData"},
    ],
    "Int.2": [
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
        {"scope": "experiment", "path": "test_results.json", "title": "Aserciones Newman"},
        {"scope": "experiment", "path": "level6_console.log", "title": "Log de consola de nivel 6"},
    ],
    "Int.3": [
        {"scope": "experiment", "path": "negotiation_metrics.json", "title": "Métricas de negociación"},
        {"scope": "experiment", "path": "raw_requests.jsonl", "title": "Traza de solicitudes crudas"},
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
    ],
    "Int.4": [
        {"scope": "experiment", "path": "components/*/*_component_validation.json", "title": "JSON de validación de componentes"},
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
    ],
    "Int.5": [
        {"scope": "experiment", "path": "raw_requests.jsonl", "title": "Traza de solicitudes crudas"},
        {"scope": "experiment", "path": "aggregated_metrics.json", "title": "Métricas agregadas"},
        {"scope": "experiment", "path": "framework-report/index.html", "title": "Dashboard del framework"},
    ],
    "Fun.1": [
        {"scope": "experiment", "path": "ui/inesdata/results.json", "title": "Resultados UI INESData"},
        {"scope": "experiment", "path": "level6_console.log", "title": "Log de consola de nivel 6"},
    ],
    "Fun.2": [
        {"scope": "experiment", "path": "ui/inesdata/results.json", "title": "Resultados UI INESData"},
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
        {"scope": "experiment", "path": "components/*/*_component_validation.json", "title": "JSON de validación de componentes"},
    ],
    "Fun.3": [
        {"scope": "experiment", "path": "ui/inesdata/results.json", "title": "Resultados UI INESData"},
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
        {"scope": "experiment", "path": "components/*/*_component_validation.json", "title": "JSON de validación de componentes"},
    ],
    "Fun.4": [
        {"scope": "experiment", "path": "newman_results.json", "title": "Resultados Newman"},
        {"scope": "experiment", "path": "storage_checks", "title": "Verificaciones de almacenamiento"},
        {"scope": "experiment", "path": "components/*/*_component_validation.json", "title": "JSON de validación de componentes"},
        {"scope": "experiment", "path": "kafka_transfer_results.json", "title": "Resultados de transferencia Kafka"},
    ],
}


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "Neg.1",
        "Modelo de negocio",
        "Existe un documento de modelo de negocio con objetivos, propuesta de valor, participantes y fuentes de ingresos.",
        "Plan de negocio, memoria estratégica o documento equivalente.",
        "documental",
        ("modelo de negocio", "propuesta de valor", "participantes", "fuentes de ingresos", "e5.1", "a5.2"),
        "partially_covered",
        limitation="A5.2 puede enlazar documentación, pero no certifica el modelo de negocio.",
    ),
    Criterion(
        "Neg.2",
        "Modelo de negocio",
        "Se identifican participantes y roles del ecosistema.",
        "Organigrama funcional, estatutos o documentación de gobernanza.",
        "documental",
        ("provider", "consumer", "operator", "participantes", "roles", "conn-citycouncil", "conn-company"),
        "partially_covered",
    ),
    Criterion(
        "Neg.3",
        "Modelo de negocio",
        "Existe un plan de sostenibilidad o estrategia de escalado para continuidad y nuevos actores.",
        "Documento de planificación o estrategia de crecimiento.",
        "documental",
        (
            "plan_sostenibilidad",
            "sustainability_plan",
            "business_sustainability",
            "estrategia de crecimiento aprobada",
            "continuidad economica",
        ),
        "partially_covered",
        limitation="La sostenibilidad económica queda fuera de la evidencia técnica automática.",
    ),
    Criterion(
        "Gob.1",
        "Sistema de gobernanza",
        "Existe constitución formal de la autoridad de gobierno del espacio de datos.",
        "Estatuto, acta constitutiva o documentación de constitución.",
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
        "Están documentados los procedimientos de adhesión, permanencia y salida de participantes.",
        "Formularios, contratos de adhesión, procesos publicados o registros.",
        "documental",
        ("adhesion", "alta", "registro", "participante", "usuarios", "agents", "keycloak"),
        "partially_covered",
    ),
    Criterion(
        "Gob.4",
        "Sistema de gobernanza",
        "Existen mecanismos de resolución de conflictos y rendición de cuentas.",
        "Protocolo de gestión de incidencias.",
        "documental",
        ("issue", "issues", "incidencia", "findings", "blocking_issues", "postflight"),
        "partially_covered",
    ),
    Criterion(
        "Gob.5",
        "Sistema de gobernanza",
        "Existe un repositorio o portal de transparencia accesible para participantes.",
        "URL, portal de transparencia o repositorio de políticas.",
        "documental",
        ("github", "repositorio", "dashboard", "report_viewer", "framework-report", "politicas"),
        "partially_covered",
    ),
    Criterion(
        "Tec.1",
        "Solución técnica y seguridad",
        "Existe una arquitectura técnica definida y documentada.",
        "Diagrama de arquitectura, documentación técnica o ficha de diseño.",
        "documental",
        ("architecture", "arquitectura", "topology", "topologia", "deployers", "metadata.json"),
    ),
    Criterion(
        "Tec.2",
        "Solución técnica y seguridad",
        "Se implementan mecanismos de identificación y autenticación de participantes y servicios.",
        "Sistema de identidad digital, credenciales verificables o logs de acceso.",
        "técnica",
        ("auth", "authentication", "authorization", "keycloak", "login", "token", "access"),
    ),
    Criterion(
        "Tec.3",
        "Solución técnica y seguridad",
        "Existe un catálogo estructurado para publicar y descubrir datos y servicios.",
        "Catálogo DCAT o plataforma de servicios registrada.",
        "técnica",
        ("catalog", "catalogo", "dcat", "asset", "vocabulary", "ontology_hub_catalog", "ai_model_hub_catalog"),
    ),
    Criterion(
        "Tec.4",
        "Solución técnica y seguridad",
        "Existen mecanismos de transferencia y control con integridad y trazabilidad de intercambios.",
        "Registros de transacción, conectores o logs de validación.",
        "técnica",
        ("transfer", "kafka_transfer", "negotiation", "contract", "edr", "traceability", "semantic_virtualization_dataspace"),
    ),
    Criterion(
        "Tec.5",
        "Solución técnica y seguridad",
        "Existen medidas de seguridad y privacidad, incluyendo cifrado, aislamiento y control de accesos conforme al RGPD.",
        "Políticas de privacidad, cifrado, consentimiento o control de accesos.",
        "mixta",
        ("privacy", "rgpd", "gdpr", "tls", "secret", "token", "127.0.0.1", "no_jwt_or_bearer", "trace"),
        "partially_covered",
        limitation="La evidencia automática cubre controles técnicos, no una auditoría RGPD formal.",
    ),
    Criterion(
        "Tec.6",
        "Solución técnica y seguridad",
        "Existen mecanismos de cumplimiento y auditoría para verificar conformidad y trazabilidad de procesos.",
        "Logs de auditoría, informes técnicos, reportes de cumplimiento o certificaciones.",
        "mixta",
        ("summary.json", "summary.md", "framework-report", "alignment", "audit", "logs", "evidence_index"),
        "partially_covered",
        limitation="El framework genera trazabilidad técnica, no certificaciones de seguridad.",
    ),
    Criterion(
        "Int.1",
        "Interoperabilidad",
        "El espacio de datos permite transferencia controlada de datos entre sistemas.",
        "Demostraciones de descarga, API o conector, y documentación de red/protocolos.",
        "técnica",
        ("transfer", "download", "api", "connector", "kafka_transfer", "dataspace", "semantic_virtualization_dataspace"),
    ),
    Criterion(
        "Int.2",
        "Interoperabilidad",
        "Existen autenticación, autorización y registro para limitar el acceso a participantes acreditados.",
        "Sistema de identidad, logs de autenticación, credenciales o políticas de autorización.",
        "técnica",
        ("auth", "authorization", "keycloak", "participant", "access", "login", "credential"),
    ),
    Criterion(
        "Int.3",
        "Interoperabilidad",
        "Se validan reglas, políticas de uso y términos contractuales antes de la transferencia.",
        "Evidencia de contrato digital, políticas, licencias o bloqueo ante incumplimiento.",
        "técnica",
        ("policy", "contract", "negotiation", "agreement", "edr", "transfer_process"),
    ),
    Criterion(
        "Int.4",
        "Interoperabilidad",
        "Se aplican protocolos y especificaciones interoperables como conectores, APIs, DCAT, RDF u ontologías.",
        "Documentación de APIs, conectores y estándares aplicados.",
        "técnica",
        ("dcat", "rdf", "sparql", "ontology", "semantic", "api", "openapi", "connector", "gtfs"),
    ),
    Criterion(
        "Int.5",
        "Interoperabilidad",
        "Se mantiene un registro trazable de transacciones para auditoría posterior e integridad.",
        "Logs, auditorías automáticas, evidencias de observabilidad o paneles.",
        "técnica",
        ("trace", "traceability", "transaction", "logs", "raw_requests", "metrics", "evidence"),
    ),
    Criterion(
        "Fun.1",
        "Verificación funcional",
        "Existe evidencia del proceso de adhesión de un participante.",
        "Capturas de registro o demostración del proceso de alta.",
        "observable",
        ("register", "registration", "user", "users", "agents", "keycloak", "login", "participante"),
        "partially_covered",
        limitation="La automatización valida usuarios/roles; la adhesión formal requiere documentación adicional.",
    ),
    Criterion(
        "Fun.2",
        "Verificación funcional",
        "Existe evidencia de publicación de un producto o servicio en el catálogo.",
        "Captura o demostración funcional de publicación.",
        "observable",
        ("create_asset", "publish", "publication", "asset", "catalog", "bootstrap", "model", "vocabulary"),
    ),
    Criterion(
        "Fun.3",
        "Verificación funcional",
        "Existe evidencia de consulta o descubrimiento del catálogo por un usuario.",
        "Registro de búsqueda o demostración funcional.",
        "observable",
        ("catalog", "search", "discovery", "list assets", "vocabulary", "model catalog", "consumer_catalog"),
    ),
    Criterion(
        "Fun.4",
        "Verificación funcional",
        "Existe evidencia de transacción efectiva de datos o servicios entre participantes.",
        "Logs de intercambio, contratos digitales o APIs.",
        "observable",
        ("transfer", "contract", "negotiation", "kafka_transfer", "api", "infer", "traceability", "finalized"),
    ),
)


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_project_evidence_paths(project_root: Path) -> list[Path]:
    relative_paths = [
        "README.md",
        "docs/00_overview.md",
        "docs/01_framework_architecture.md",
        "docs/02_validation_architecture.md",
        "docs/13_test_cases.md",
        "docs/30_framework_current_state.md",
        "docs/31_postman_newman_collections.md",
        "docs/34_architecture.md",
        "docs/35_deployers_and_topologies.md",
        "docs/37_validation.md",
        "docs/40_report_viewer.md",
        "docs/44_audit_navigation_guide.md",
        "docs/A5.2_Casos_Prueba_.xlsx",
        "docs/E5.2_Resultados_Validacion_Componentes.xlsx",
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


def _artifact_base(scope: str, experiment_path: Path, project_root: Path) -> Path:
    return experiment_path if scope == "experiment" else project_root


def _artifact_display_path(scope: str, path: str) -> str:
    return path if scope == "experiment" else path


def _artifact_link(scope: str, path: str, experiment_path: Path, project_root: Path) -> str:
    base = _artifact_base(scope, experiment_path, project_root)
    absolute = base / path
    if any(char in path for char in "*?["):
        return _artifact_display_path(scope, path)
    return os.path.relpath(absolute, start=experiment_path).replace(os.sep, "/")


def _resolve_artifact_candidate(
    candidate: dict[str, str],
    experiment_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    scope = str(candidate.get("scope") or "experiment")
    path = str(candidate.get("path") or "")
    base = _artifact_base(scope, experiment_path, project_root)
    absolute = base / path
    matches = sorted(base.glob(path)) if any(char in path for char in "*?[") else []
    if matches:
        first_match = matches[0]
        display_path = _relative_or_absolute(first_match, experiment_path if scope == "experiment" else project_root)
        link = os.path.relpath(first_match, start=experiment_path).replace(os.sep, "/")
        exists = True
    else:
        display_path = _artifact_display_path(scope, path)
        link = _artifact_link(scope, path, experiment_path, project_root)
        exists = absolute.exists()
    return {
        "title": str(candidate.get("title") or display_path),
        "path": display_path,
        "link": link,
        "scope": scope,
        "exists": exists,
    }


def _primary_artifacts(criterion_id: str, experiment_path: Path, project_root: Path) -> list[dict[str, Any]]:
    return [
        _resolve_artifact_candidate(candidate, experiment_path, project_root)
        for candidate in CHECKLIST_ARTIFACTS.get(criterion_id, [])
    ]


def _primary_artifact_label(item: dict[str, Any]) -> str:
    artifacts = item.get("primary_artifacts") if isinstance(item, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        return "Evidencia documental externa requerida"
    existing = [artifact for artifact in artifacts if artifact.get("exists")]
    selected = existing[0] if existing else artifacts[0]
    suffix = "" if selected.get("exists") else " (esperado)"
    return f"{selected.get('path')}{suffix}"


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _markdown_artifact_link(item: dict[str, Any]) -> str:
    artifacts = item.get("primary_artifacts") if isinstance(item, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        return "Evidencia documental externa requerida"
    existing = [artifact for artifact in artifacts if artifact.get("exists")]
    selected = existing[0] if existing else artifacts[0]
    label = _markdown_cell(selected.get("title") or selected.get("path"))
    link = str(selected.get("link") or selected.get("path") or "").replace(" ", "%20")
    suffix = "" if selected.get("exists") else " (esperado)"
    return f"[{label}]({link}){suffix}"


def _evidence_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".json", ".jsonl", ".yaml", ".yml"}:
        return "legible por máquina"
    if suffix in {".md", ".txt", ".docx", ".pdf", ".xlsx"}:
        return "documental"
    if suffix in {".html", ".png", ".jpg", ".jpeg", ".webm", ".zip"}:
        return "observable"
    return "artefacto"


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
    root = Path(project_root) if project_root else default_project_root()
    experiment_path = Path(experiment_dir)
    if not experiment_path.is_absolute():
        experiment_path = root / experiment_path
    evidence = collect_evidence(
        experiment_path,
        additional_evidence_paths=additional_evidence_paths,
        include_project_context=include_project_context,
        project_root=root,
    )
    criteria = []
    for criterion in CRITERIA:
        matches = _matching_evidence(criterion, evidence)
        status = _criterion_status(criterion, matches)
        status_info = CHECKLIST_STATUS.get(status, CHECKLIST_STATUS["not_covered"])
        guidance = CHECKLIST_GUIDANCE.get(criterion.criterion_id, {})
        primary_artifacts = _primary_artifacts(criterion.criterion_id, experiment_path, root)
        criteria.append(
            {
                "id": criterion.criterion_id,
                "dimension": criterion.dimension,
                "requirement": criterion.requirement,
                "expected_evidence": criterion.expected_evidence,
                "evidence_type": criterion.evidence_type,
                "status": status,
                "status_label": status_info["label"],
                "evidence": matches[:10],
                "evidence_count": len(matches),
                "limitation": criterion.limitation,
                "checklist": {
                    "status": status,
                    "status_label": status_info["label"],
                    "status_meaning": status_info["meaning"],
                    "evidence_basis": guidance.get("evidence_basis", criterion.expected_evidence),
                    "primary_artifacts": primary_artifacts,
                    "primary_artifact": _primary_artifact_label({"primary_artifacts": primary_artifacts}),
                    "rationale": guidance.get("rationale", criterion.limitation),
                    "pending_action": guidance.get("pending_action", criterion.limitation),
                    "detected_evidence_matches": len(matches),
                },
            }
        )

    return {
        "schema_version": "1.0",
        "assessment_type": ASSESSMENT_TYPE,
        "certification_claim": False,
        "source_document": SOURCE_DOCUMENT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment_dir": _relative_or_absolute(experiment_path, root),
        "notice": (
            "Este reporte relaciona la evidencia de validación A5.2 disponible con criterios UNE 0087. "
            "Es un artefacto de apoyo y no declara certificación formal."
        ),
        "summary": _summarize_criteria(criteria),
        "criteria": criteria,
    }


def _assessment_type_label(value: Any) -> str:
    if value == ASSESSMENT_TYPE:
        return "alineación no certificante"
    return str(value or "")


def _certification_claim_label(value: Any) -> str:
    return "Sí" if bool(value) else "No"


def build_une_0087_markdown(alignment: dict[str, Any]) -> str:
    summary = alignment.get("summary") if isinstance(alignment.get("summary"), dict) else {}
    statuses = summary.get("statuses") if isinstance(summary.get("statuses"), dict) else {}
    lines = [
        "# Alineación UNE 0087",
        "",
        f"- Tipo de evaluación: `{_assessment_type_label(alignment.get('assessment_type'))}`",
        f"- Declaración de certificación: `{_certification_claim_label(alignment.get('certification_claim'))}`",
        f"- Fuente: `{alignment.get('source_document')}`",
        f"- Experimento: `{alignment.get('experiment_dir')}`",
        "",
        "Este es un artefacto de apoyo no certificante para el cierre de A5.2. Relaciona evidencia ya producida por el framework con los criterios de la guía.",
        "",
        "## Resumen",
        "",
        f"- Total de criterios: `{summary.get('total_criteria', 0)}`",
        f"- Cubiertos: `{statuses.get('covered', 0)}`",
        f"- Parcialmente cubiertos: `{statuses.get('partially_covered', 0)}`",
        f"- Pendientes: `{statuses.get('not_covered', 0)}`",
        f"- No aplicables: `{statuses.get('not_applicable', 0)}`",
        "",
        "## Criterios",
        "",
        "| Criterio | Dimensión | Estado | Artefacto principal | Justificación | Acción pendiente |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in alignment.get("criteria") or []:
        checklist = item.get("checklist") if isinstance(item.get("checklist"), dict) else {}
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('id'))}` | "
            f"{_markdown_cell(item.get('dimension'))} | "
            f"{_markdown_cell(checklist.get('status_label') or item.get('status_label') or item.get('status'))} | "
            f"{_markdown_artifact_link(checklist)} | "
            f"{_markdown_cell(checklist.get('rationale'))} | "
            f"{_markdown_cell(checklist.get('pending_action'))} |"
        )

    lines.extend(
        [
            "",
            "## Coincidencias de evidencia detectadas",
            "",
            "Los valores siguientes son coincidencias por palabras clave usadas sólo como apoyo de trazabilidad; no son puntuaciones de cumplimiento.",
            "",
            "| Criterio | Coincidencias detectadas |",
            "| --- | ---: |",
        ]
    )
    for item in alignment.get("criteria") or []:
        checklist = item.get("checklist") if isinstance(item.get("checklist"), dict) else {}
        lines.append(
            f"| `{_markdown_cell(item.get('id'))}` | {checklist.get('detected_evidence_matches', item.get('evidence_count', 0))} |"
        )

    lines.extend(["", "## Notas", ""])
    for item in alignment.get("criteria") or []:
        limitation = str(item.get("limitation") or "").strip()
        if limitation:
            lines.append(f"- `{item.get('id')}`: {limitation}")

    return "\n".join(lines) + "\n"


def format_une_0087_console_rows(alignment: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in alignment.get("criteria") or []:
        checklist = item.get("checklist") if isinstance(item.get("checklist"), dict) else {}
        rows.append(
            {
                "Criterio": str(item.get("id") or ""),
                "Dimensión": shorten(str(item.get("dimension") or ""), width=28, placeholder="..."),
                "Estado": str(checklist.get("status_label") or item.get("status_label") or item.get("status") or ""),
                "Artefacto principal": shorten(
                    str(checklist.get("primary_artifact") or "Evidencia documental externa requerida"),
                    width=54,
                    placeholder="...",
                ),
                "Nota de revisión": shorten(str(checklist.get("rationale") or ""), width=82, placeholder="..."),
            }
        )
    return rows


def format_une_0087_console_summary(alignment: dict[str, Any]) -> list[dict[str, str]]:
    summary = alignment.get("summary") if isinstance(alignment, dict) else {}
    statuses = summary.get("statuses") if isinstance(summary, dict) else {}
    return [
        {"Status": "Total", "Criteria": str(summary.get("total_criteria", 0))},
        {"Status": "Covered", "Criteria": str(statuses.get("covered", 0))},
        {"Status": "Partial", "Criteria": str(statuses.get("partially_covered", 0))},
        {"Status": "Missing", "Criteria": str(statuses.get("not_covered", 0))},
        {"Status": "Not applicable", "Criteria": str(statuses.get("not_applicable", 0))},
    ]


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
    parser = argparse.ArgumentParser(description="Genera un reporte de alineación no certificante UNE 0087.")
    parser.add_argument(
        "--experiment-dir",
        required=True,
        help="Directorio del experimento usado como fuente principal de evidencia.",
    )
    parser.add_argument("--output-dir", help="Directorio donde se escriben une_0087_alignment.json/md.")
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="Archivo o directorio de evidencia adicional. Puede indicarse varias veces.",
    )
    parser.add_argument(
        "--no-project-context",
        action="store_true",
        help="No incluir evidencia documental por defecto desde la raíz del proyecto.",
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
        f"partial={summary.get('partially_covered', 0)}, "
        f"missing={summary.get('not_covered', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
