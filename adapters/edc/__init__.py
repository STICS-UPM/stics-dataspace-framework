"""Generic EDC adapter package for local Validation-Environment integration."""

from .adapter import EdcAdapter
from .config import EDCConfigAdapter, EdcConfig
from .connectors import EDCConnectorsAdapter
from .deployment import EDCDeploymentAdapter


__all__ = [
    "EdcAdapter",
    "EdcConfig",
    "EDCConfigAdapter",
    "EDCDeploymentAdapter",
    "EDCConnectorsAdapter",
]
