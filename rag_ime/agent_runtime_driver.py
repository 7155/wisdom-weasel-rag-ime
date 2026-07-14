from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .agent_events import AgentEventHub
from .agent_sessions import AgentSessionStore


MediaResolver = Callable[[str, str, str], str]
SessionContextProvider = Callable[[Mapping[str, object]], Mapping[str, object]]


class AgentRuntimeError(RuntimeError):
    """Public failure boundary shared by all runtime drivers."""


@dataclass(frozen=True)
class RuntimeDriverContext:
    """Kernel-owned dependencies passed to a runtime driver factory."""

    sessions: AgentSessionStore
    events: AgentEventHub
    tool_gateway_token: str
    media_resolver: MediaResolver | None = None


@dataclass(frozen=True)
class AgentRuntimePolicy:
    """Runtime-neutral desired state owned by the Agent Kernel."""

    enabled: bool
    startup: str = "lazy"
    idle_timeout_seconds: int = 900

    def __post_init__(self) -> None:
        if self.startup != "lazy":
            raise ValueError("agent runtime startup only supports lazy")
        if not 0 <= int(self.idle_timeout_seconds) <= 86_400:
            raise ValueError("agent runtime idle timeout must be between 0 and 86400")


@runtime_checkable
class AgentRuntimeDriver(Protocol):
    """Runtime-neutral contract consumed by the Agent service and supervisor."""

    @property
    def runtime_kind(self) -> str: ...

    @property
    def driver_id(self) -> str: ...

    @property
    def session_root(self) -> Path: ...

    @property
    def default_model_profile(self) -> str: ...

    def runtime_status(self) -> dict[str, object]: ...

    def ensure(self, session_id: str) -> dict[str, object]: ...

    def prompt(
        self,
        session_id: str,
        message: str,
        *,
        images: list[Mapping[str, str]] | None = None,
    ) -> dict[str, object]: ...

    def messages(self, session_id: str) -> list[dict[str, object]]: ...

    def model_catalog(self, session_id: str) -> dict[str, object]: ...

    def set_model(
        self,
        session_id: str,
        *,
        provider: str,
        model_id: str,
    ) -> dict[str, object]: ...

    def set_thinking_level(self, session_id: str, *, level: str) -> dict[str, object]: ...

    def abort(self, session_id: str) -> None: ...

    def compact(self, session_id: str, instructions: str = "") -> dict[str, object]: ...

    def has_pending_approval(self, session_id: str, approval_id: str) -> bool: ...

    def resolve_approval(
        self,
        session_id: str,
        approval_id: str,
        *,
        approved: bool,
        resolution_state: str = "",
    ) -> None: ...

    def stop(self) -> None: ...


class RuntimeDriverFactory(Protocol):
    """Creates isolated runtime drivers without exposing driver config to the Kernel."""

    @property
    def runtime_kind(self) -> str: ...

    @property
    def driver_id(self) -> str: ...

    @property
    def session_root(self) -> Path: ...

    @property
    def working_root(self) -> Path: ...

    @property
    def default_model_profile(self) -> str: ...

    def create(
        self,
        context: RuntimeDriverContext,
        *,
        purpose: str,
        session_context_provider: SessionContextProvider | None = None,
    ) -> AgentRuntimeDriver: ...

    def apply_policy(self, policy: AgentRuntimePolicy) -> None: ...

    def reconfigure(self, config: object) -> None: ...
