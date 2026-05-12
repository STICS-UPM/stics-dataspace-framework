from __future__ import annotations

import os
from typing import Any

from adapters.inesdata.adapter import InesdataAdapter
from adapters.inesdata.components import INESDataComponentsAdapter
from adapters.shared.components import SharedComponentsAdapter
from adapters.inesdata.config import INESDataConfigAdapter, InesdataConfig
from deployers.shared.lib.components import (
    component_validation_groups,
    components_for_adapter,
    summarize_components_for_adapter,
)
from deployers.infrastructure.lib.contracts import DeploymentContext, ValidationProfile
from deployers.infrastructure.lib.namespaces import resolve_namespace_profile_plan
from deployers.infrastructure.lib.topology import SUPPORTED_TOPOLOGIES, build_topology_profile


class InesdataDeployer:
    """Thin wrapper around the current INESData implementation.

    This class does not replace the existing legacy deployment flow. Its goal is
    to expose the future deployer contract while delegating to the current
    adapter and component adapter that already work today.
    """

    def __init__(
        self,
        adapter: InesdataAdapter | None = None,
        components_adapter: INESDataComponentsAdapter | None = None,
        config_cls=None,
        run=None,
        run_silent=None,
        auto_mode_getter=lambda: False,
        topology: str = "local",
    ):
        self.config = config_cls or InesdataConfig
        self.topology = topology
        self.adapter = adapter or InesdataAdapter(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            config_cls=self.config,
        )
        self.config_adapter = getattr(self.adapter, "config_adapter", None) or INESDataConfigAdapter(self.config)
        self._components_adapter = components_adapter
        self.auto_mode_getter = auto_mode_getter

    def name(self) -> str:
        return "inesdata"

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

        runtime_dir = os.path.join(
            self.config.repo_dir(),
            "deployments",
            "DEV",
            dataspace_name,
        )

        return DeploymentContext(
            deployer=self.name(),
            topology=topology,
            environment=config.get("ENVIRONMENT", "DEV") or "DEV",
            dataspace_name=dataspace_name,
            ds_domain_base=ds_domain_base,
            connectors=self._resolve_primary_connectors(dataspace_name, config),
            components=self._configured_optional_components(config),
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
                "INESData connector deployment finished without deployed connectors: "
                f"{', '.join(context.connectors)}"
            )
        return []

    def deploy_components(self, context: DeploymentContext) -> dict[str, Any]:
        summary = summarize_components_for_adapter(context.config, self.name())
        components = list(summary.get("deployable") or [])
        if not components:
            return {
                "deployed": [],
                "urls": {},
                **summary,
            }
        components_namespace = str(getattr(context.namespace_roles, "components_namespace", "") or "").strip()
        result = self._resolve_components_adapter().deploy_components(
            components,
            ds_name=context.dataspace_name,
            namespace=components_namespace,
            deployer_config=context.config,
        )
        payload = dict(result or {})
        payload.setdefault("deployed", list(components))
        payload.setdefault("urls", {})
        payload.update(summary)
        return payload

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
            playwright_config="validation/ui/playwright.config.ts",
            component_validation_enabled=bool(component_groups),
            component_groups=component_groups,
        )

    def _resolve_components_adapter(self) -> INESDataComponentsAdapter:
        if self._components_adapter is None:
            adapter_components = getattr(self.adapter, "components", None)
            if isinstance(adapter_components, INESDataComponentsAdapter):
                self._components_adapter = adapter_components
            else:
                self._components_adapter = SharedComponentsAdapter(
                    run=self.adapter.run,
                    run_silent=self.adapter.run_silent,
                    auto_mode_getter=self.auto_mode_getter,
                    infrastructure_adapter=self.adapter.infrastructure,
                    config_adapter=self.config_adapter,
                    config_cls=self.config,
                    active_adapter=self.name(),
                )
        return self._components_adapter

    def _configured_optional_components(self, config: dict[str, Any]) -> list[str]:
        return components_for_adapter(config, self.name(), deployable_only=True)

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
