from adapters.shared import deployment as shared_deployment_module
from adapters.shared.deployment import SharedDataspaceDeploymentAdapter

from .config import INESDataConfigAdapter, InesdataConfig

requests = shared_deployment_module.requests
ensure_python_requirements = shared_deployment_module.ensure_python_requirements


class INESDataDeploymentAdapter(SharedDataspaceDeploymentAdapter):
    """Contains deployment logic for the INESData dataspace runtime."""

    def __init__(self, run, run_silent, auto_mode_getter, infrastructure_adapter, config_adapter=None, config_cls=None):
        resolved_config = config_cls or InesdataConfig
        super().__init__(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            infrastructure_adapter=infrastructure_adapter,
            config_adapter=config_adapter or INESDataConfigAdapter(resolved_config),
            config_cls=resolved_config,
        )

    @staticmethod
    def _sync_shared_bindings():
        shared_deployment_module.requests = requests
        shared_deployment_module.ensure_python_requirements = ensure_python_requirements

    def wait_for_keycloak_admin_ready(self, kc_url, kc_user, kc_password, timeout=120, poll_interval=3):
        self._sync_shared_bindings()
        return super().wait_for_keycloak_admin_ready(
            kc_url,
            kc_user,
            kc_password,
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def deploy_dataspace(self):
        self._sync_shared_bindings()
        return super().deploy_dataspace()

    def deploy_dataspace_for_topology(self, topology="local"):
        self._sync_shared_bindings()
        return super().deploy_dataspace_for_topology(topology=topology)

    def describe(self) -> str:
        return "INESDataDeploymentAdapter contains deployment logic for INESData."
