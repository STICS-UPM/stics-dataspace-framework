from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml


DEFAULT_TARGETS_DIR = Path("validation") / "targets"
DEFAULT_PROJECT_SUITES_DIR = Path("validation") / "projects"
TARGET_PLAYWRIGHT_CONFIG = "playwright.target.config.js"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validation_targets_dir(root: str | Path | None = None) -> Path:
    return Path(root or project_root()) / DEFAULT_TARGETS_DIR


def validation_projects_dir(root: str | Path | None = None) -> Path:
    return Path(root or project_root()) / DEFAULT_PROJECT_SUITES_DIR


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Validation target must be a mapping: {path}")
    return payload


def _target_display_name(path: Path, payload: dict[str, Any] | None = None) -> str:
    name = str((payload or {}).get("name") or "").strip()
    if name:
        return name
    stem = path.name
    for suffix in (".example.yaml", ".yaml"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return path.stem


def discover_validation_targets(root: str | Path | None = None) -> list[dict[str, Any]]:
    """Return versioned examples and local target YAML files."""
    targets_dir = validation_targets_dir(root)
    if not targets_dir.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(targets_dir.glob("*.yaml")):
        try:
            payload = _safe_load_yaml(path)
            status = "available"
            error = ""
        except Exception as exc:
            payload = {}
            status = "invalid"
            error = str(exc)
        entries.append(
            {
                "name": _target_display_name(path, payload),
                "path": str(path),
                "filename": path.name,
                "example": path.name.endswith(".example.yaml"),
                "status": status,
                "error": error,
                "project": str(payload.get("project") or "").strip(),
                "environment": str(payload.get("environment") or "").strip(),
                "mode": str(payload.get("mode") or "").strip(),
            }
        )

    return sorted(entries, key=lambda item: (bool(item.get("example")), item.get("name", ""), item.get("filename", "")))


def load_validation_target(selection: str | Path, root: str | Path | None = None) -> tuple[dict[str, Any], Path]:
    """Load a target by path, filename, or configured name."""
    targets_dir = validation_targets_dir(root)
    raw = str(selection or "").strip()
    if not raw:
        raise ValueError("Validation target selection is empty.")

    direct_path = Path(raw)
    candidates = []
    if direct_path.is_absolute() or direct_path.parent != Path("."):
        candidates.append(direct_path)
    else:
        candidates.extend(
            [
                targets_dir / raw,
                targets_dir / f"{raw}.yaml",
                targets_dir / f"{raw}.example.yaml",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return _safe_load_yaml(candidate), candidate

    for entry in discover_validation_targets(root=root):
        if raw in {entry.get("name"), entry.get("filename")}:
            path = Path(str(entry["path"]))
            return _safe_load_yaml(path), path

    raise FileNotFoundError(f"Validation target not found: {selection}")


def _iter_mapping_items(payload: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(payload, dict):
        return payload.items()
    return ()


def _find_env_secret_refs(payload: Any, prefix: str = "") -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).endswith("_env") and str(value or "").strip():
                refs.append({"path": path, "env": str(value).strip()})
            refs.extend(_find_env_secret_refs(value, prefix=path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            refs.extend(_find_env_secret_refs(value, prefix=f"{prefix}[{index}]"))
    return refs


def _secret_plan(payload: dict[str, Any], environ: dict[str, str] | None = None) -> list[dict[str, str]]:
    environment = os.environ if environ is None else environ
    secret_refs = _find_env_secret_refs(payload)
    plan = []
    for ref in secret_refs:
        env_name = ref["env"]
        plan.append(
            {
                "path": ref["path"],
                "env": env_name,
                "status": "available" if environment.get(env_name) else "missing",
                "source": "environment" if environment.get(env_name) else "prompt-required",
            }
        )
    return plan


def _dataspace_plan(payload: dict[str, Any]) -> list[dict[str, Any]]:
    dataspaces = payload.get("dataspaces") or []
    if not isinstance(dataspaces, list):
        return []
    result = []
    for item in dataspaces:
        if not isinstance(item, dict):
            continue
        connectors = [connector for connector in list(item.get("connectors") or []) if isinstance(connector, dict)]
        result.append(
            {
                "name": str(item.get("name") or "").strip(),
                "public_portal_configured": bool(str(item.get("public_portal_url") or "").strip()),
                "connectors": [
                    {
                        "name": str(connector.get("name") or "").strip(),
                        "role": str(connector.get("role") or "").strip(),
                        "management_api_configured": bool(str(connector.get("management_api_url") or "").strip()),
                        "protocol_configured": bool(str(connector.get("protocol_url") or "").strip()),
                    }
                    for connector in connectors
                ],
            }
        )
    return result


def _suite_plan(payload: dict[str, Any]) -> list[dict[str, Any]]:
    suites = payload.get("suites") or {}
    result = []
    for name, config in _iter_mapping_items(suites):
        config = config if isinstance(config, dict) else {}
        result.append(
            {
                "name": str(name),
                "enabled": bool(config.get("enabled", False)),
                "profile": str(config.get("profile") or "read-only").strip() or "read-only",
                "execution": "planned" if config.get("enabled", False) else "disabled",
            }
        )
    return result


def _component_plan(payload: dict[str, Any]) -> list[dict[str, Any]]:
    components = payload.get("components") or {}
    result = []
    for name, config in _iter_mapping_items(components):
        config = config if isinstance(config, dict) else {}
        result.append(
            {
                "name": str(name),
                "enabled": bool(config.get("enabled", False)),
                "base_url_configured": bool(str(config.get("base_url") or "").strip()),
            }
        )
    return result


def _project_suite_plan(payload: dict[str, Any]) -> list[dict[str, Any]]:
    project_suites = payload.get("project_suites") or {}
    result = []
    for project, suites in _iter_mapping_items(project_suites):
        for suite_name, config in _iter_mapping_items(suites):
            config = config if isinstance(config, dict) else {}
            result.append(
                {
                    "project": str(project),
                    "suite": str(suite_name),
                    "enabled": bool(config.get("enabled", False)),
                    "profile": str(config.get("profile") or "read-only").strip() or "read-only",
                    "execution": "scaffold" if config.get("enabled", False) else "disabled",
                }
            )
    return result


def _sanitize_env_token(value: str) -> str:
    sanitized = []
    for char in str(value or "").upper():
        sanitized.append(char if char.isalnum() else "_")
    return "_".join(part for part in "".join(sanitized).split("_") if part)


def _safe_target_name(payload: dict[str, Any], target_path: str | Path | None = None) -> str:
    raw = str(payload.get("name") or _target_display_name(Path(str(target_path or "")), payload)).strip()
    safe = []
    for char in raw.lower():
        safe.append(char if char.isalnum() else "-")
    return "-".join(part for part in "".join(safe).split("-") if part) or "validation-target"


def _enabled_project_suites(payload: dict[str, Any], project: str = "inesdata") -> list[dict[str, Any]]:
    project_suites = payload.get("project_suites") or {}
    suites = project_suites.get(project) if isinstance(project_suites, dict) else {}
    result = []
    for suite_name, config in _iter_mapping_items(suites):
        config = config if isinstance(config, dict) else {}
        if not bool(config.get("enabled", False)):
            continue
        result.append(
            {
                "project": project,
                "suite": str(suite_name),
                "profile": str(config.get("profile") or "read-only").strip() or "read-only",
                "config": config,
            }
        )
    return result


def _resolve_suite_specs(
    suite: dict[str, Any],
    *,
    root: str | Path | None = None,
) -> list[Path]:
    suite_dir = validation_projects_dir(root) / suite["project"] / suite["suite"]
    specs_dir = suite_dir / "specs"
    configured_specs = suite.get("config", {}).get("specs")
    candidates: list[Path] = []
    if isinstance(configured_specs, list):
        for raw_spec in configured_specs:
            raw_spec = str(raw_spec or "").strip()
            if raw_spec:
                candidates.append((specs_dir / raw_spec).resolve())
    elif specs_dir.is_dir():
        candidates.extend(sorted(specs_dir.rglob("*.spec.ts")))
        candidates.extend(sorted(specs_dir.rglob("*.spec.js")))

    specs = []
    for path in candidates:
        if not path.is_file():
            continue
        if ".example." in path.name or path.name.endswith(".example.ts") or path.name.endswith(".example.js"):
            continue
        specs.append(path)
    return specs


def _target_experiment_dir(
    payload: dict[str, Any],
    *,
    target_path: str | Path | None = None,
    root: str | Path | None = None,
) -> Path:
    experiment_id = f"experiment_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    return Path(root or project_root()) / "experiments" / experiment_id / "targets" / _safe_target_name(payload, target_path)


def _target_playwright_artifact_paths(experiment_dir: Path, suite: str) -> dict[str, str]:
    base_dir = experiment_dir / "playwright" / suite
    paths = {
        "base_dir": str(base_dir),
        "output_dir": str(base_dir / "test-results"),
        "html_report_dir": str(base_dir / "playwright-report"),
        "blob_report_dir": str(base_dir / "blob-report"),
        "json_report_file": str(base_dir / "results.json"),
        "summary_file": str(base_dir / "target_playwright_validation.json"),
    }
    for key, value in paths.items():
        path = Path(value)
        if key.endswith("_file") or key == "summary_file":
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    return paths


def _target_runtime_payload(payload: dict[str, Any], target_path: str | Path | None = None) -> dict[str, Any]:
    return {
        "target": payload.get("name"),
        "target_path": str(target_path or ""),
        "project": payload.get("project"),
        "mode": payload.get("mode"),
        "environment": payload.get("environment"),
        "safety": payload.get("safety") if isinstance(payload.get("safety"), dict) else {},
        "auth": payload.get("auth") if isinstance(payload.get("auth"), dict) else {},
        "dataspaces": payload.get("dataspaces") if isinstance(payload.get("dataspaces"), list) else [],
    }


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_target_playwright_environment(
    payload: dict[str, Any],
    *,
    target_path: str | Path | None,
    runtime_file: Path,
    artifact_paths: dict[str, str],
    environ: dict[str, str] | None = None,
    root: str | Path | None = None,
) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    root_path = Path(root or project_root())
    ui_node_modules = root_path / "validation" / "ui" / "node_modules"
    node_path = str(ui_node_modules)
    if env.get("NODE_PATH"):
        node_path = f"{node_path}{os.pathsep}{env['NODE_PATH']}"
    env["NODE_PATH"] = node_path

    env["INESDATA_TARGET_RUNTIME_FILE"] = str(runtime_file)
    env["INESDATA_TARGET_FILE"] = str(target_path or "")
    env["INESDATA_TARGET_NAME"] = str(payload.get("name") or "")
    env["INESDATA_TARGET_ENVIRONMENT"] = str(payload.get("environment") or "")
    env["INESDATA_VALIDATION_MODE"] = "validation-only"
    env["INESDATA_VALIDATION_PROFILE"] = "read-only"
    env["PLAYWRIGHT_OUTPUT_DIR"] = artifact_paths["output_dir"]
    env["PLAYWRIGHT_HTML_REPORT_DIR"] = artifact_paths["html_report_dir"]
    env["PLAYWRIGHT_BLOB_REPORT_DIR"] = artifact_paths["blob_report_dir"]
    env["PLAYWRIGHT_JSON_REPORT_FILE"] = artifact_paths["json_report_file"]
    env.setdefault("PLAYWRIGHT_INTERACTION_MARKERS", "1")
    env.setdefault("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "150")

    auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
    env["INESDATA_AUTH_KEYCLOAK_URL"] = str(auth.get("keycloak_url") or "")
    env["INESDATA_AUTH_REALM"] = str(auth.get("realm") or "")
    env["INESDATA_AUTH_CLIENT_ID"] = str(auth.get("client_id") or "")
    username_env = str(auth.get("username_env") or "").strip()
    password_env = str(auth.get("password_env") or "").strip()
    if username_env and env.get(username_env):
        env["INESDATA_VALIDATION_USERNAME"] = env[username_env]
    if password_env and env.get(password_env):
        env["INESDATA_VALIDATION_PASSWORD"] = env[password_env]

    dataspaces = payload.get("dataspaces") if isinstance(payload.get("dataspaces"), list) else []
    for index, dataspace in enumerate(item for item in dataspaces if isinstance(item, dict)):
        token = _sanitize_env_token(dataspace.get("name") or f"dataspace_{index + 1}")
        portal_url = str(dataspace.get("public_portal_url") or "").strip()
        if portal_url:
            env[f"INESDATA_{token}_PORTAL_URL"] = portal_url
            env.setdefault("INESDATA_PRIMARY_PORTAL_URL", portal_url)
        for connector in (dataspace.get("connectors") or []):
            if not isinstance(connector, dict):
                continue
            connector_token = _sanitize_env_token(connector.get("name") or "")
            prefix = f"INESDATA_{token}_{connector_token}" if connector_token else f"INESDATA_{token}_CONNECTOR"
            for source_key, env_suffix in (
                ("portal_url", "PORTAL_URL"),
                ("management_api_url", "MANAGEMENT_API_URL"),
                ("protocol_url", "PROTOCOL_URL"),
            ):
                value = str(connector.get(source_key) or "").strip()
                if value:
                    env[f"{prefix}_{env_suffix}"] = value
    return env


def _summarize_target_playwright_json(json_report_file: str) -> dict[str, Any]:
    path = Path(json_report_file)
    if not path.is_file():
        return {
            "total_specs": 0,
            "status_counts": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "total_specs": 0,
            "status_counts": {},
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }

    status_counts: dict[str, int] = {}
    total_specs = 0

    def visit_suite(suite_payload: dict[str, Any]) -> None:
        nonlocal total_specs
        for child in suite_payload.get("suites") or []:
            if isinstance(child, dict):
                visit_suite(child)
        for spec in suite_payload.get("specs") or []:
            if not isinstance(spec, dict):
                continue
            total_specs += 1
            tests = spec.get("tests") or []
            results = tests[0].get("results") if tests else []
            status = str((results or [{}])[-1].get("status") or "skipped").lower()
            status_counts[status] = status_counts.get(status, 0) + 1

    for suite_payload in payload.get("suites") or []:
        if isinstance(suite_payload, dict):
            visit_suite(suite_payload)
    return {
        "total_specs": total_specs,
        "status_counts": status_counts,
    }


def run_validation_target_read_only(
    payload: dict[str, Any],
    *,
    target_path: str | Path | None = None,
    root: str | Path | None = None,
    environ: dict[str, str] | None = None,
    subprocess_module: Any = subprocess,
) -> dict[str, Any]:
    """Run explicitly enabled read-only target Playwright suites."""
    plan = build_validation_target_plan(payload, target_path=target_path, environ=environ)
    if plan["status"] != "planned":
        return {
            "status": "failed",
            "reason": "invalid-target",
            "plan": plan,
            "suite_results": [],
        }

    enabled_suites = _enabled_project_suites(payload, project="inesdata")
    rejected_suites = [suite for suite in enabled_suites if suite.get("profile") != "read-only"]
    runnable_suites = [suite for suite in enabled_suites if suite.get("profile") == "read-only"]
    if rejected_suites:
        return {
            "status": "failed",
            "reason": "non-read-only-suite",
            "plan": plan,
            "rejected_suites": rejected_suites,
            "suite_results": [],
        }

    suite_specs = [(suite, _resolve_suite_specs(suite, root=root)) for suite in runnable_suites]
    if not any(specs for _, specs in suite_specs):
        return {
            "status": "skipped",
            "reason": "no-read-only-specs",
            "plan": plan,
            "suite_results": [],
            "message": "No executable read-only Playwright specs were found. Files ending in .example.* are templates only.",
        }

    missing_secrets = [secret for secret in plan.get("secrets") or [] if secret.get("status") == "missing"]
    if missing_secrets:
        return {
            "status": "failed",
            "reason": "missing-secrets",
            "plan": plan,
            "missing_secrets": missing_secrets,
            "suite_results": [],
        }

    root_path = Path(root or project_root())
    config_path = validation_projects_dir(root_path) / "inesdata" / TARGET_PLAYWRIGHT_CONFIG
    if not config_path.is_file():
        return {
            "status": "failed",
            "reason": "missing-playwright-config",
            "plan": plan,
            "config": str(config_path),
            "suite_results": [],
        }

    ui_dir = root_path / "validation" / "ui"
    experiment_dir = _target_experiment_dir(payload, target_path=target_path, root=root_path)
    runtime_file = experiment_dir / "target_runtime.json"
    _write_json(runtime_file, _target_runtime_payload(payload, target_path=target_path))

    suite_results = []
    for suite, specs in suite_specs:
        if not specs:
            suite_results.append(
                {
                    "suite": suite["suite"],
                    "status": "skipped",
                    "reason": "no-specs",
                    "specs": [],
                }
            )
            continue
        artifact_paths = _target_playwright_artifact_paths(experiment_dir, suite["suite"])
        env = _build_target_playwright_environment(
            payload,
            target_path=target_path,
            runtime_file=runtime_file,
            artifact_paths=artifact_paths,
            environ=environ,
            root=root_path,
        )
        command = [
            "npx",
            "playwright",
            "test",
            "--config",
            str(config_path),
            "--workers=1",
            *[str(spec) for spec in specs],
        ]
        error = None
        try:
            completed = subprocess_module.run(command, cwd=str(ui_dir), env=env, check=False)
            exit_code = completed.returncode
            status = "passed" if exit_code == 0 else "failed"
        except OSError as exc:
            exit_code = None
            status = "skipped"
            error = {"type": type(exc).__name__, "message": str(exc)}

        result = {
            "suite": suite["suite"],
            "status": status,
            "exit_code": exit_code,
            "profile": suite["profile"],
            "specs": [str(spec) for spec in specs],
            "command": command,
            "artifacts": artifact_paths,
            "summary": _summarize_target_playwright_json(artifact_paths["json_report_file"]),
            "error": error,
        }
        _write_json(artifact_paths["summary_file"], result)
        suite_results.append(result)

    failed = any(result.get("status") == "failed" for result in suite_results)
    passed = any(result.get("status") == "passed" for result in suite_results)
    return {
        "status": "failed" if failed else "passed" if passed else "skipped",
        "reason": "completed",
        "plan": plan,
        "experiment_dir": str(experiment_dir),
        "runtime_file": str(runtime_file),
        "suite_results": suite_results,
    }


def build_validation_target_plan(
    payload: dict[str, Any],
    *,
    target_path: str | Path | None = None,
    profile: str | None = None,
    adapter: str = "inesdata",
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a safe execution plan without running external suites."""
    safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
    effective_profile = str(profile or safety.get("default_profile") or "read-only").strip() or "read-only"
    mode = str(payload.get("mode") or "").strip()
    project = str(payload.get("project") or "").strip()
    errors = []
    warnings = []

    if mode != "validation-only":
        errors.append("Target mode must be validation-only.")
    if project and project != "inesdata":
        warnings.append(f"Target project '{project}' is not supported by the current scaffold.")
    if str(adapter or "").strip().lower() != "inesdata":
        warnings.append("Target validation scaffold is currently aligned with the INESData adapter.")
    if effective_profile != "read-only" and not bool(safety.get("allow_write_tests", False)):
        warnings.append("Non read-only profile requested but write tests are not allowed by target safety settings.")

    return {
        "status": "failed" if errors else "planned",
        "target": str(payload.get("name") or _target_display_name(Path(str(target_path or "")), payload)).strip(),
        "target_path": str(target_path or ""),
        "adapter": adapter,
        "project": project,
        "mode": mode,
        "environment": str(payload.get("environment") or "").strip(),
        "profile": effective_profile,
        "execution": "read-only-runner",
        "levels_1_5": "disabled",
        "level_6": "read-only-playwright",
        "cleanup": "disabled",
        "writes": "disabled",
        "destructive_actions": "disabled",
        "dataspaces": _dataspace_plan(payload),
        "suites": _suite_plan(payload),
        "components": _component_plan(payload),
        "project_suites": _project_suite_plan(payload),
        "secrets": _secret_plan(payload, environ=environ),
        "errors": errors,
        "warnings": warnings,
        "next_step": "Complete the real target YAML and add enabled read-only Playwright specs when INESData endpoints are confirmed.",
    }


def format_validation_target_plan(plan: dict[str, Any]) -> list[str]:
    """Render a compact, non-sensitive target plan for menu output."""
    lines = [
        "Validation target plan",
        f"Target: {plan.get('target') or 'unknown'}",
        f"Mode: {plan.get('mode') or 'unknown'}",
        f"Profile: {plan.get('profile') or 'read-only'}",
        f"Execution: {plan.get('execution') or 'scaffold'}",
        f"Levels 1-5: {plan.get('levels_1_5') or 'disabled'}",
        f"Level 6: {plan.get('level_6') or 'scaffold'}",
        f"Cleanup: {plan.get('cleanup') or 'disabled'}",
        f"Writes: {plan.get('writes') or 'disabled'}",
        f"Destructive actions: {plan.get('destructive_actions') or 'disabled'}",
    ]
    if plan.get("environment"):
        lines.append(f"Environment: {plan['environment']}")
    if plan.get("project"):
        lines.append(f"Project: {plan['project']}")

    dataspaces = list(plan.get("dataspaces") or [])
    lines.append(f"Dataspaces: {len(dataspaces)}")
    for dataspace in dataspaces:
        connectors = list(dataspace.get("connectors") or [])
        name = dataspace.get("name") or "unnamed"
        lines.append(f"- {name}: {len(connectors)} connector(s)")

    suites = list(plan.get("suites") or [])
    if suites:
        lines.append("Suites:")
        for suite in suites:
            state = "enabled" if suite.get("enabled") else "disabled"
            lines.append(f"- {suite.get('name')}: {state} ({suite.get('profile')})")

    components = list(plan.get("components") or [])
    lines.append(f"Components: {sum(1 for item in components if item.get('enabled'))} enabled")

    project_suites = list(plan.get("project_suites") or [])
    if project_suites:
        lines.append("Project suites:")
        for suite in project_suites:
            state = "enabled" if suite.get("enabled") else "disabled"
            lines.append(f"- {suite.get('project')}.{suite.get('suite')}: {state} ({suite.get('profile')})")

    secrets = list(plan.get("secrets") or [])
    if secrets:
        missing = [item for item in secrets if item.get("status") == "missing"]
        lines.append(f"Secrets: {len(secrets)} required, {len(missing)} missing")
        for item in secrets:
            lines.append(f"- {item.get('env')}: {item.get('status')}")

    for error in list(plan.get("errors") or []):
        lines.append(f"Error: {error}")
    for warning in list(plan.get("warnings") or []):
        lines.append(f"Warning: {warning}")

    next_step = str(plan.get("next_step") or "").strip()
    if next_step:
        lines.append(f"Next step: {next_step}")

    return lines
