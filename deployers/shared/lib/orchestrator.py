from __future__ import annotations

from typing import Any

from .contracts import DeploymentContext, ValidationProfile


class DeployerOrchestrator:
    """Small orchestration layer for future deployer-based execution."""

    def __init__(self, deployer: Any, validation_executor=None):
        self.deployer = deployer
        self.validation_executor = validation_executor

    def load_config(self) -> dict[str, Any]:
        loader = getattr(self.deployer, "load_config", None)
        if callable(loader):
            return dict(loader() or {})
        return {}

    def resolve_context(self, topology: str = "local") -> DeploymentContext:
        supported = getattr(self.deployer, "supported_topologies", None)
        if callable(supported):
            allowed = list(supported() or [])
            if allowed and topology not in allowed:
                raise ValueError(
                    f"Unsupported topology '{topology}' for deployer '{self._deployer_name()}'. "
                    f"Supported topologies: {', '.join(allowed)}"
                )

        resolver = getattr(self.deployer, "resolve_context", None)
        if not callable(resolver):
            raise RuntimeError(f"Deployer '{self._deployer_name()}' does not implement resolve_context()")

        context = resolver(topology=topology)
        if isinstance(context, DeploymentContext):
            return context
        if isinstance(context, dict):
            return DeploymentContext.from_mapping(context)
        raise RuntimeError("resolve_context() must return DeploymentContext or dict")

    def deploy(self, topology: str = "local") -> dict[str, Any]:
        context = self.resolve_context(topology=topology)
        return {
            "context": context,
            "infrastructure": self._call_optional("deploy_infrastructure", context),
            "dataspace": self._call_optional("deploy_dataspace", context),
            "connectors": self._call_optional("deploy_connectors", context),
            "components": self._call_optional("deploy_components", context),
        }

    def validate(self, topology: str = "local") -> dict[str, Any]:
        context = self.resolve_context(topology=topology)
        profile = self.get_validation_profile(context)
        connectors = self.get_cluster_connectors(context)

        result = {
            "context": context,
            "profile": profile,
            "connectors": connectors,
        }
        if callable(self.validation_executor):
            result["validation"] = self.validation_executor(
                deployer=self.deployer,
                context=context,
                profile=profile,
                connectors=connectors,
            )
        return result

    def run(self, topology: str = "local") -> dict[str, Any]:
        deployment = self.deploy(topology=topology)
        validation = self.validate(topology=topology)
        return {
            "deployment": deployment,
            "validation": validation,
        }

    def get_cluster_connectors(self, context: DeploymentContext | None = None) -> list[str]:
        getter = getattr(self.deployer, "get_cluster_connectors", None)
        if not callable(getter):
            return []
        resolved = getter(context=context) if context is not None else getter()
        return list(resolved or [])

    def get_validation_profile(self, context: DeploymentContext) -> ValidationProfile:
        getter = getattr(self.deployer, "get_validation_profile", None)
        if not callable(getter):
            return ValidationProfile(adapter=self._deployer_name())
        profile = getter(context)
        if isinstance(profile, ValidationProfile):
            return profile
        if isinstance(profile, dict):
            return ValidationProfile.from_mapping(profile)
        raise RuntimeError("get_validation_profile() must return ValidationProfile or dict")

    def _call_optional(self, method_name: str, context: DeploymentContext):
        method = getattr(self.deployer, method_name, None)
        if not callable(method):
            return None
        return method(context)

    def _deployer_name(self) -> str:
        getter = getattr(self.deployer, "name", None)
        if callable(getter):
            value = getter()
            if value:
                return str(value)
        return type(self.deployer).__name__.lower()
