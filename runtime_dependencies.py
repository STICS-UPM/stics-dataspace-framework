import importlib.util
import os
import re
import subprocess
import sys


DEFAULT_MODULE_REQUIREMENTS = {
    "kafka": "kafka-python",
    "ruamel.yaml": "ruamel.yaml",
    "yaml": "PyYAML",
}


def _missing_modules(module_names):
    missing = []
    for module_name in module_names:
        if importlib.util.find_spec(module_name) is None:
            missing.append(module_name)
    return missing


def _normalize_requirement_name(name):
    return re.sub(r"[-_.]+", "-", str(name or "")).lower()


def _requirement_name(requirement_line):
    candidate = str(requirement_line or "").split("#", 1)[0].strip()
    if not candidate or candidate.startswith(("-r", "--", "git+", "http://", "https://", ".")):
        return None
    match = re.match(r"([A-Za-z0-9_.-]+)", candidate)
    return match.group(1) if match else None


def _requirements_by_package(requirements_path):
    by_package = {}
    with open(requirements_path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.split("#", 1)[0].strip()
            package_name = _requirement_name(stripped)
            if not package_name:
                continue
            by_package[_normalize_requirement_name(package_name)] = stripped
    return by_package


def _install_args_for_missing_modules(requirements_path, missing_modules, module_requirements=None):
    if module_requirements is None:
        return ["-r", requirements_path]

    requirements = _requirements_by_package(requirements_path)
    install_args = []
    seen = set()
    for module_name in missing_modules:
        package_name = module_requirements.get(module_name, module_name)
        normalized = _normalize_requirement_name(package_name)
        if normalized in seen:
            continue
        seen.add(normalized)
        install_args.append(requirements.get(normalized, package_name))
    return install_args


def ensure_runtime_dependencies(requirements_path, module_names, label="framework", module_requirements=None):
    """Ensure the current interpreter can import the required modules.

    If one or more modules are missing, install the provided requirements file
    into the current interpreter and validate imports again. When
    ``module_requirements`` is provided, only the requirement entries matching
    missing modules are installed; this avoids replacing system-managed
    packages when the command runs with elevated privileges.
    """
    missing = _missing_modules(module_names)
    if not missing:
        return

    requirements_path = os.path.abspath(requirements_path)
    if not os.path.exists(requirements_path):
        raise SystemExit(
            f"Missing {label} requirements file: {requirements_path}"
        )

    print(
        f"[INFO] Missing Python dependencies for {label}: {', '.join(missing)}",
        file=sys.stderr,
    )
    module_requirements = (
        {**DEFAULT_MODULE_REQUIREMENTS, **dict(module_requirements or {})}
        if module_requirements is not None
        else None
    )
    install_args = _install_args_for_missing_modules(
        requirements_path,
        missing,
        module_requirements=module_requirements,
    )
    print(
        f"[INFO] Installing requirements with: {sys.executable} -m pip install {' '.join(install_args)}",
        file=sys.stderr,
    )

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", *install_args],
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"Failed to install {label} dependencies from {requirements_path}"
        )

    missing_after_install = _missing_modules(module_names)
    if missing_after_install:
        raise SystemExit(
            "Dependencies are still missing after installation for "
            f"{label}: {', '.join(missing_after_install)}"
        )


def ensure_python_requirements(python_executable, requirements_path, label="python environment", quiet=False):
    """Install a requirements file into the provided interpreter."""
    requirements_path = os.path.abspath(requirements_path)
    if not os.path.exists(requirements_path):
        raise RuntimeError(f"Missing {label} requirements file: {requirements_path}")

    output_mode = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    } if quiet else {}
    result = subprocess.run(
        [python_executable, "-m", "pip", "install", "-r", requirements_path],
        check=False,
        **output_mode,
    )
    if result.returncode != 0:
        if quiet:
            output = "\n".join(
                part for part in (result.stdout, result.stderr) if part
            ).strip()
            if output:
                print(output, file=sys.stderr)
        raise RuntimeError(
            f"Failed to install {label} dependencies from {requirements_path}"
        )
