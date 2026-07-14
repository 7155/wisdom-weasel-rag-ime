from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentCapabilityGateway(Protocol):
    """Plugin/tool boundary shared by Pi, native UI, Web, and remote gateways."""

    def manifests(self) -> Mapping[str, object]: ...

    def execute(self, payload: Mapping[str, object]) -> Mapping[str, object]: ...


def public_capability_catalog(gateway: AgentCapabilityGateway) -> dict[str, object]:
    payload = gateway.manifests()
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return {
        "schemaVersion": "rag-ime.control-capability-list.v1",
        "items": [
            dict(item)
            for item in items
            if isinstance(item, Mapping) and item.get("availability") != "hidden"
        ],
    }
