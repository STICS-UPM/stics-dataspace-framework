"""Shared runtime configuration helpers for transitional adapter flows."""

import os
import shlex
import shutil

from deployers.infrastructure.lib.paths import legacy_deployer_artifact_dir, resolve_shared_artifact_dir


class SharedLevel3RuntimeConfigMixin:
    """Neutral path helpers for the shared Level 3 dataspace runtime.

    This keeps the transitional dataspace bootstrap rooted in the current
    shared runtime directory without coupling adapter wrappers directly to
    adapter-specific config classes.
    """

    SHARED_LEVEL3_REPO_DIR = os.path.join("deployers", "inesdata")
    RUNTIME_LABEL = "shared dataspace"
    QUIET_REQUIREMENTS_INSTALL = True
    QUIET_SENSITIVE_DEPLOYER_OUTPUT = True

    @classmethod
    def shared_level3_repo_dir(cls):
        return os.path.join(cls.script_dir(), cls.SHARED_LEVEL3_REPO_DIR)

    @classmethod
    def repo_dir(cls):
        return cls.shared_level3_repo_dir()

    @classmethod
    def venv_path(cls):
        return os.path.join(cls.shared_level3_repo_dir(), cls.PATH_VENV)

    @classmethod
    def python_exec(cls):
        return os.path.join(cls.venv_path(), "bin", "python")

    @classmethod
    def repo_requirements_path(cls):
        return os.path.join(cls.shared_level3_repo_dir(), cls.PATH_REQUIREMENTS)

    @classmethod
    def shared_level3_bootstrap_script(cls):
        return os.path.join(cls.shared_level3_repo_dir(), "bootstrap.py")

    @classmethod
    def bootstrap_script(cls):
        return cls.shared_level3_bootstrap_script()

    @classmethod
    def bootstrap_dataspace_command(cls, action, dataspace=None):
        resolved_action = str(action or "").strip()
        resolved_dataspace = str(dataspace or cls.dataspace_name() or "").strip()
        return (
            f"{shlex.quote(cls.python_exec())} "
            f"{shlex.quote(cls.bootstrap_script())} "
            f"dataspace {shlex.quote(resolved_action)} {shlex.quote(resolved_dataspace)}"
        )


class SharedLevel3DataspaceRuntimeMixin:
    """Neutral dataspace runtime paths for the shared Level 3 bootstrap."""

    @classmethod
    def shared_level3_deployments_dir(cls):
        return os.path.join(cls.shared_level3_repo_dir(), "deployments")

    @classmethod
    def shared_level3_dataspace_runtime_dir(cls, ds_name=None, environment=None):
        return os.path.join(
            cls.shared_level3_deployments_dir(),
            environment or cls.deployment_environment_name(),
            ds_name or cls.dataspace_name(),
        )

    @classmethod
    def shared_level3_dataspace_credentials_file(cls, ds_name=None, environment=None):
        dataspace = ds_name or cls.dataspace_name()
        return os.path.join(
            cls.shared_level3_dataspace_runtime_dir(ds_name=dataspace, environment=environment),
            f"credentials-dataspace-{dataspace}.json",
        )


def resolve_shared_level3_runtime_context(delegate_config, *, dataspace, environment, target_runtime_dir):
    """Resolve the transitional shared Level 3 runtime context.

    This keeps adapter wrappers from rebuilding the same source/runtime paths
    manually while preserving the current fallback behavior.
    """
    source_repo_getter = getattr(delegate_config, "repo_dir", None)
    if not callable(source_repo_getter):
        return None

    normalized_dataspace = str(dataspace or "").strip()
    normalized_environment = str(environment or "DEV").strip().upper() or "DEV"
    if not normalized_dataspace:
        return None

    source_repo = source_repo_getter()
    source_runtime_getter = getattr(delegate_config, "shared_level3_dataspace_runtime_dir", None)
    source_runtime_dir = (
        source_runtime_getter(ds_name=normalized_dataspace, environment=normalized_environment)
        if callable(source_runtime_getter)
        else os.path.join(source_repo, "deployments", normalized_environment, normalized_dataspace)
    )
    return {
        "delegate_config": delegate_config,
        "source_repo": source_repo,
        "dataspace": normalized_dataspace,
        "environment": normalized_environment,
        "source_runtime_dir": source_runtime_dir,
        "target_runtime_dir": target_runtime_dir,
    }


def resolve_shared_level3_bootstrap_runtime(delegate_config):
    """Resolve the effective shared Level 3 bootstrap runtime once.

    This centralizes the bootstrap cwd/script/python/requirements resolution so
    the deployment flow does not rebuild those paths inline.
    """
    repo_getter = getattr(delegate_config, "repo_dir", None)
    python_getter = getattr(delegate_config, "python_exec", None)
    requirements_getter = getattr(delegate_config, "repo_requirements_path", None)
    bootstrap_getter = getattr(delegate_config, "bootstrap_script", None)
    command_getter = getattr(delegate_config, "bootstrap_dataspace_command", None)
    runtime_dir_getter = getattr(delegate_config, "deployment_runtime_dir", None)
    if not callable(repo_getter):
        return None

    repo_dir = repo_getter()
    return {
        "repo_dir": repo_dir,
        "python_exec": python_getter() if callable(python_getter) else "",
        "requirements_path": (
            requirements_getter()
            if callable(requirements_getter)
            else os.path.join(repo_dir, "requirements.txt")
        ),
        "runtime_dir": (
            runtime_dir_getter()
            if callable(runtime_dir_getter)
            else os.path.join(
                repo_dir,
                "deployments",
                str(getattr(delegate_config, "deployment_environment_name", lambda: "DEV")() or "DEV").strip().upper(),
                str(getattr(delegate_config, "dataspace_name", lambda: "")() or "").strip(),
            )
        ),
        "bootstrap_script": bootstrap_getter() if callable(bootstrap_getter) else os.path.join(repo_dir, "bootstrap.py"),
        "bootstrap_dataspace_command": command_getter if callable(command_getter) else None,
    }


def stage_transitional_runtime_file(source_file, target_file, *, remove_empty_source_dir=False, label="transitional Level 3 artifact"):
    """Copy a transitional runtime file into its canonical runtime location."""
    if not source_file or not os.path.isfile(source_file):
        return None

    os.makedirs(os.path.dirname(target_file), exist_ok=True)
    if os.path.abspath(source_file) != os.path.abspath(target_file):
        shutil.copy2(source_file, target_file)
        try:
            os.remove(source_file)
            source_dir = os.path.dirname(source_file)
            if remove_empty_source_dir and os.path.isdir(source_dir) and not os.listdir(source_dir):
                os.rmdir(source_dir)
        except OSError as exc:
            print(f"Warning: could not clean {label} {source_file}: {exc}")
    return target_file


def stage_shared_level3_runtime_artifacts(context, *, target_config_adapter, label="transitional Level 3 artifact"):
    """Stage shared Level 3 dataspace artifacts into the adapter runtime."""
    if not context:
        return {
            "credentials": None,
            "registration_values": None,
        }

    delegate_config = context["delegate_config"]
    dataspace = context["dataspace"]
    environment = context["environment"]
    source_runtime_dir = context["source_runtime_dir"]
    target_runtime_dir = context["target_runtime_dir"]

    source_credentials_getter = getattr(delegate_config, "shared_level3_dataspace_credentials_file", None)
    target_credentials_getter = getattr(target_config_adapter, "edc_dataspace_credentials_file", None)
    source_credentials_file = (
        source_credentials_getter(ds_name=dataspace, environment=environment)
        if callable(source_credentials_getter)
        else os.path.join(source_runtime_dir, f"credentials-dataspace-{dataspace}.json")
    )
    target_credentials_file = (
        target_credentials_getter(ds_name=dataspace)
        if callable(target_credentials_getter)
        else os.path.join(target_runtime_dir, f"credentials-dataspace-{dataspace}.json")
    )
    staged_credentials = stage_transitional_runtime_file(
        source_credentials_file,
        target_credentials_file,
        remove_empty_source_dir=True,
        label=label,
    )

    source_values_getter = getattr(delegate_config, "legacy_registration_values_file", None)
    target_values_getter = getattr(delegate_config, "registration_values_file", None)
    ensure_values_getter = getattr(delegate_config, "ensure_registration_values_file", None)
    if callable(source_values_getter) and callable(target_values_getter):
        source_values_file = source_values_getter()
        target_values_file = (
            ensure_values_getter(refresh=True)
            if callable(ensure_values_getter)
            else target_values_getter()
        )
        staged_registration_values = (
            stage_transitional_runtime_file(
                source_values_file,
                target_values_file,
                label=label,
            )
            if source_values_file and target_values_file
            else None
        )
    else:
        staged_registration_values = None

    return {
        "credentials": staged_credentials,
        "registration_values": staged_registration_values,
    }


class SharedRegistrationServiceRuntimeMixin:
    """Neutral registration-service artifact paths for transitional Level 3."""

    @classmethod
    def registration_service_dir(cls):
        return resolve_shared_artifact_dir("dataspace", "registration-service", required_file="Chart.yaml")

    @classmethod
    def registration_values_file(cls):
        values_name = f"values-{cls.dataspace_name()}.yaml"
        if cls.use_shared_deployer_artifacts():
            return os.path.join(cls.deployment_runtime_dir(), "dataspace", "registration-service", values_name)
        return os.path.join(cls.registration_service_dir(), values_name)

    @classmethod
    def legacy_registration_service_dir(cls):
        return str(legacy_deployer_artifact_dir("inesdata", "dataspace", "registration-service"))

    @classmethod
    def legacy_registration_values_file(cls):
        return os.path.join(cls.legacy_registration_service_dir(), f"values-{cls.dataspace_name()}.yaml")

    @classmethod
    def ensure_registration_values_file(cls, refresh=False):
        values_file = cls.registration_values_file()
        if not cls.use_shared_deployer_artifacts():
            return values_file

        source_file = cls.legacy_registration_values_file()
        if (refresh or not os.path.exists(values_file)) and os.path.exists(source_file):
            os.makedirs(os.path.dirname(values_file), exist_ok=True)
            shutil.copy2(source_file, values_file)
        return values_file
