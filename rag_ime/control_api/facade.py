from __future__ import annotations

from collections.abc import Callable, Mapping

from ..contracts.json_schema import validate_contract
from .capabilities import AgentCapabilityGateway, public_capability_catalog
from .kernel import AgentControlKernel
from .route_policy import control_route_catalog


class ControlApiFacade:
    """Frontend-neutral bootstrap over Agent Kernel and capability plugins."""

    def __init__(
        self,
        *,
        agent: AgentControlKernel,
        capabilities: AgentCapabilityGateway,
        platform_capabilities: Callable[[], Mapping[str, object]] | None = None,
    ) -> None:
        self.agent = agent
        self.capabilities = capabilities
        self.platform_capabilities = platform_capabilities or (lambda: {})

    def bootstrap(self) -> dict[str, object]:
        configuration_response = self.agent.configuration()
        configuration = configuration_response.get("configuration")
        if not isinstance(configuration, Mapping):
            raise ValueError("Agent Kernel returned an invalid configuration snapshot")
        runtime = self.agent.runtime_status()
        payload = {
            "schemaVersion": "rag-ime.control-bootstrap.v1",
            "apiVersion": "control-api.v1",
            "configuration": dict(configuration),
            "runtime": _public_runtime(runtime),
            "capabilities": public_capability_catalog(self.capabilities),
            "platform": dict(self.platform_capabilities()),
            "routes": control_route_catalog(),
        }
        validate_contract(payload, "control-bootstrap.v1.json")
        return payload


def _public_runtime(runtime: Mapping[str, object]) -> dict[str, object]:
    allowed = (
        "schemaVersion",
        "enabled",
        "managed",
        "status",
        "driverId",
        "runtimeKind",
        "runtimeVersion",
        "piVersion",
        "idleTimeoutSeconds",
        "activeSessionId",
        "capabilities",
        "configurationRevision",
        "configurationSyncState",
    )
    return {key: runtime.get(key) for key in allowed if key in runtime}
