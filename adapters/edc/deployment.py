"""Deployment helpers for the generic EDC adapter."""

from adapters.shared.config import (
    SharedLevel3DataspaceRuntimeMixin,
    SharedLevel3RuntimeConfigMixin,
    SharedRegistrationServiceRuntimeMixin,
    resolve_shared_level3_runtime_context,
    stage_shared_level3_runtime_artifacts,
)
from adapters.shared.deployment import SharedDataspaceDeploymentAdapter

from .config import EDCConfigAdapter, EdcConfig


class EdcSharedDataspaceConfig(
    SharedRegistrationServiceRuntimeMixin,
    SharedLevel3DataspaceRuntimeMixin,
    SharedLevel3RuntimeConfigMixin,
    EdcConfig,
):
    """Transitional Level 3 config that reuses the shared dataspace runtime."""


class EDCDeploymentAdapter:
    """Thin deployment wrapper that reuses the local dataspace setup."""

    def __init__(self, run, run_silent, auto_mode_getter, infrastructure_adapter, config_adapter=None, config_cls=None, topology="local"):
        self.run = run
        self.run_silent = run_silent
        self.auto_mode_getter = auto_mode_getter
        self.infrastructure = infrastructure_adapter
        self.topology = topology or EdcConfig.DEFAULT_TOPOLOGY
        self.config = config_cls or EdcConfig
        self.config_adapter = config_adapter or EDCConfigAdapter(self.config, topology=self.topology)
        self.connectors_adapter = None
        self._delegate = SharedDataspaceDeploymentAdapter(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            infrastructure_adapter=infrastructure_adapter,
            config_adapter=self.config_adapter,
            config_cls=EdcSharedDataspaceConfig,
        )

    def _shared_level3_runtime_context(self):
        delegate_config = getattr(getattr(self, "_delegate", None), "config", None)

        dataspace_getter = getattr(self.config_adapter, "primary_dataspace_name", None)
        environment_getter = getattr(self.config_adapter, "deployment_environment_name", None)
        runtime_getter = getattr(self.config_adapter, "edc_dataspace_runtime_dir", None)
        if not (callable(dataspace_getter) and callable(environment_getter) and callable(runtime_getter)):
            return None

        dataspace = dataspace_getter()
        environment = environment_getter()
        target_runtime_dir = runtime_getter(ds_name=dataspace)
        return resolve_shared_level3_runtime_context(
            delegate_config,
            dataspace=dataspace,
            environment=environment,
            target_runtime_dir=target_runtime_dir,
        )

    def _stage_shared_dataspace_credentials(self):
        """Compatibility shim for legacy/tests that request staged dataspace credentials.

        The real staging logic now lives in the neutral shared helper layer.
        """
        return self._stage_shared_dataspace_runtime_artifacts().get("credentials")

    def _stage_shared_registration_service_values(self):
        """Compatibility shim for legacy/tests that request staged registration values.

        The real staging logic now lives in the neutral shared helper layer.
        """
        return self._stage_shared_dataspace_runtime_artifacts().get("registration_values")

    def _stage_shared_dataspace_runtime_artifacts(self):
        """Stage transitional Level 3 runtime artifacts through the shared helper layer."""
        context = self._shared_level3_runtime_context()
        return stage_shared_level3_runtime_artifacts(
            context,
            target_config_adapter=self.config_adapter,
            label="transitional EDC Level 3 artifact",
        )

    def deploy_dataspace(self):
        self._delegate.connectors_adapter = self.connectors_adapter
        result = self._delegate.deploy_dataspace()
        self._stage_shared_dataspace_runtime_artifacts()
        return result

    def deploy_dataspace_for_topology(self, topology="local"):
        self._delegate.connectors_adapter = self.connectors_adapter
        result = self._delegate.deploy_dataspace_for_topology(topology=topology)
        self._stage_shared_dataspace_runtime_artifacts()
        return result

    def build_recreate_dataspace_plan(self):
        self._delegate.connectors_adapter = self.connectors_adapter
        return self._delegate.build_recreate_dataspace_plan()

    def recreate_dataspace(self, confirm_dataspace=None):
        self._delegate.connectors_adapter = self.connectors_adapter
        return self._delegate.recreate_dataspace(confirm_dataspace=confirm_dataspace)

    def describe(self) -> str:
        return "EDCDeploymentAdapter reuses the local dataspace deployment flow for generic EDC."
