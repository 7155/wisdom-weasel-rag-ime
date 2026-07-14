from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentControlKernel(Protocol):
    """Stable control-plane view implemented by any Agent Kernel."""

    def configuration(self) -> Mapping[str, object]: ...

    def runtime_status(self) -> Mapping[str, object]: ...
