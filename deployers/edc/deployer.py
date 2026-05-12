from __future__ import annotations

from typing import Any

from adapters.edc.adapter import EdcAdapter
from adapters.edc.config import EDCConfigAdapter, EdcConfig
from deployers.shared.lib.components import (
    component_validation_groups,
    components_for_adapter,
    summarize_components_for_adapter,
)
from deployers.infrastructure.lib.contracts import DeploymentContext, ValidationProfile
from deployers.infrastructure.lib.namespaces import resolve_namespace_profile_plan
from deployers.infrastructure.lib.topology import SUPPORTED_TOPOLOGIES, build_topology_profile


class EdcDeployer:
    """Thin wrapper around the current generic EDC implementation."""

    def __init__(
        self,
        adapter: EdcAdapter | None = None,
        config_cls=None,
        run=None,
        run_silent=None,
        auto_mode_getter=lambda: False,
        topology: str = "local",
    ):
        self.config = config_cls or EdcConfig
        self.topology = topology or getattr(self.config, "DEFAULT_TOPOLOGY", "local")
        self.adapter = adapter or EdcAdapter(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            config_cls=self.config,
            topology=self.topology,
        )
        self.config_adapter = getattr(self.adapter, "config_adapter", None) or EDCConfigAdapter(
            self.config,
            topology=self.topology,
        )
        self.auto_mode_getter = auto_mode_getter

    def name(self) -> str:
        return "edc"

    @staticmethod
    def supported_topologies() -> list[str]:
        return list(SUPPORTED_TOPOLOGIES)

    def load_config(self) -> dict[str, Any]:
        return dict(self.config_adapter.load_deployer_config() or {})

    def resolve_context(self, topology: str = "local") -> DeploymentContext:
        config = self.load_config()
        dataspace_name = self.config_adapter.primary_dataspace_name()
        dataspace_namespace = self.config_adapter.primary_dataspace_namespace()
        ds_domain_base = (
            self.config_adapter.ds_domain_base()
            or config.get("DS_DOMAIN_BASE")
            or ""
        )

        namespace_plan = resolve_namespace_profile_plan(
            config,
            dataspace_name=dataspace_name,
            dataspace_namespace=dataspace_namespace,
            common_default=getattr(self.config, "NS_COMMON", "common-srvs"),
            components_default="components",
        )
        topology_profile = build_topology_profile(topology, config)

        runtime_dir = self.config_adapter.edc_dataspace_runtime_dir(ds_name=dataspace_name)

        return DeploymentContext(
            deployer=self.name(),
            topology=topology,
            environment=self.config_adapter.deployment_environment_name(),
            dataspace_name=dataspace_name,
            ds_domain_base=ds_domain_base,
            connectors=self._resolve_primary_connectors(dataspace_name, config),
            components=components_for_adapter(config, self.name(), deployable_only=True),
            namespace_profile=namespace_plan["namespace_profile"],
            namespace_roles=namespace_plan["namespace_roles"],
            planned_namespace_roles=namespace_plan["planned_namespace_roles"],
            topology_profile=topology_profile,
            runtime_dir=runtime_dir,
            config=config,
        )

    def deploy_infrastructure(self, context: DeploymentContext) -> Any:
        return self.adapter.deploy_infrastructure()

    def deploy_dataspace(self, context: DeploymentContext) -> Any:
        return self.adapter.deploy_dataspace()

    def deploy_connectors(self, context: DeploymentContext) -> list[str]:
        deployed = self.adapter.deploy_connectors()
        if deployed:
            return list(deployed)
        if context.connectors:
            raise RuntimeError(
                "EDC connector deployment finished without deployed connectors: "
                f"{', '.join(context.connectors)}"
            )
        return []

    def deploy_components(self, context: DeploymentContext) -> dict[str, Any]:
        return {
            "deployed": [],
            "urls": {},
            **summarize_components_for_adapter(context.config, self.name()),
        }

    def get_cluster_connectors(self, context: DeploymentContext | None = None) -> list[str]:
        resolved = self.adapter.get_cluster_connectors()
        if resolved:
            return list(resolved)
        if context is not None:
            return list(context.connectors)
        return []

    def get_validation_profile(self, context: DeploymentContext) -> ValidationProfile:
        component_groups = component_validation_groups(context.components)
        return ValidationProfile(
            adapter=self.name(),
            newman_enabled=True,
            test_data_cleanup_enabled=True,
            playwright_enabled=True,
            playwright_config="validation/ui/playwright.edc.config.ts",
            component_validation_enabled=bool(component_groups),
            component_groups=component_groups,
        )

    def _resolve_primary_connectors(self, dataspace_name: str, config: dict[str, Any]) -> list[str]:
        loader = getattr(getattr(self.adapter, "connectors", None), "load_dataspace_connectors", None)
        if callable(loader):
            dataspaces = loader() or []
            for dataspace in dataspaces:
                if (dataspace.get("name") or "").strip() == dataspace_name:
                    return list(dataspace.get("connectors") or [])

        raw = str(config.get("DS_1_CONNECTORS", "") or "").strip()
        if not raw:
            return []

        connectors = []
        for token in raw.split(","):
            name = token.strip()
            if not name:
                continue
            connectors.append(f"conn-{name}-{dataspace_name}")
        return connectors
