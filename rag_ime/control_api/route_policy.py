from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ControlRoute:
    path_id: str
    method: str
    local_path: str
    remote_path: str
    capability: str
    streaming: bool = False
    remote_allowed: bool = True

    def payload(self) -> dict[str, object]:
        return {
            "pathId": self.path_id,
            "method": self.method,
            "localPath": self.local_path,
            "remotePath": self.remote_path,
            "capability": self.capability,
            "streaming": self.streaming,
            "remoteAllowed": self.remote_allowed,
        }


# Page code selects a pathId. Only transport adapters are allowed to expand it
# into a concrete URL, so a WebView or plugin cannot turn the bridge into fetch().
_CONTROL_ROUTES = (
    ControlRoute("agent.configuration.get", "GET", "/api/agent/configuration", "/remote/v1/agent/configuration", "agent.settings.read"),
    ControlRoute("agent.configuration.update", "POST", "/api/agent/configuration", "/remote/v1/agent/configuration", "agent.settings.write"),
    ControlRoute("agent.control.events", "GET", "/api/agent/events", "/remote/v1/agent/events", "agent.events.read", streaming=True),
    ControlRoute("agent.runtime.get", "GET", "/api/agent/runtime", "/remote/v1/agent/runtime", "agent.runtime.read"),
    ControlRoute("agent.runtime.ensure", "POST", "/api/agent/runtime/ensure", "/remote/v1/agent/runtime/ensure", "agent.runtime.start"),
    ControlRoute("agent.roles.list", "GET", "/api/agent/roles", "/remote/v1/agent/roles", "agent.roles.read"),
    ControlRoute("agent.templates.list", "GET", "/api/agent/templates", "/remote/v1/agent/templates", "agent.templates.read"),
    ControlRoute("agent.tools.list", "GET", "/api/agent/tools", "/remote/v1/agent/tools", "agent.tools.read"),
    ControlRoute("agent.sessions.list", "GET", "/api/agent/sessions", "/remote/v1/agent/sessions", "agent.sessions.read"),
    ControlRoute("agent.sessions.create", "POST", "/api/agent/sessions", "/remote/v1/agent/sessions", "agent.sessions.write"),
    ControlRoute("agent.session.get", "GET", "/api/agent/sessions/{sessionId}", "/remote/v1/agent/sessions/{sessionId}", "agent.sessions.read"),
    ControlRoute("agent.session.update", "PATCH", "/api/agent/sessions/{sessionId}", "/remote/v1/agent/sessions/{sessionId}", "agent.sessions.write"),
    ControlRoute("agent.session.delete", "DELETE", "/api/agent/sessions/{sessionId}", "/remote/v1/agent/sessions/{sessionId}", "agent.sessions.delete"),
    ControlRoute("agent.session.messages", "GET", "/api/agent/sessions/{sessionId}/messages", "/remote/v1/agent/sessions/{sessionId}/messages", "agent.messages.read"),
    ControlRoute("agent.session.events", "GET", "/api/agent/sessions/{sessionId}/events", "/remote/v1/agent/sessions/{sessionId}/events", "agent.events.read", streaming=True),
    ControlRoute("agent.session.prompt", "POST", "/api/agent/sessions/{sessionId}/prompt", "/remote/v1/agent/sessions/{sessionId}/prompt", "agent.messages.write"),
    ControlRoute("agent.session.abort", "POST", "/api/agent/sessions/{sessionId}/abort", "/remote/v1/agent/sessions/{sessionId}/abort", "agent.turn.abort"),
    ControlRoute("agent.session.compact", "POST", "/api/agent/sessions/{sessionId}/compact", "/remote/v1/agent/sessions/{sessionId}/compact", "agent.session.compact"),
    ControlRoute("agent.session.models", "GET", "/api/agent/sessions/{sessionId}/models", "/remote/v1/agent/sessions/{sessionId}/models", "agent.models.read"),
    ControlRoute("agent.session.model", "POST", "/api/agent/sessions/{sessionId}/model", "/remote/v1/agent/sessions/{sessionId}/model", "agent.models.write"),
    ControlRoute("agent.session.thinking", "POST", "/api/agent/sessions/{sessionId}/thinking", "/remote/v1/agent/sessions/{sessionId}/thinking", "agent.models.write"),
    ControlRoute("agent.session.intercom.list", "GET", "/api/agent/sessions/{sessionId}/intercom", "/remote/v1/agent/sessions/{sessionId}/intercom", "agent.rooms.read"),
    ControlRoute("agent.session.intercom.send", "POST", "/api/agent/sessions/{sessionId}/intercom", "/remote/v1/agent/sessions/{sessionId}/intercom", "agent.messages.write"),
    ControlRoute("agent.artifact.get", "GET", "/api/agent/artifacts/{artifactId}", "/remote/v1/agent/artifacts/{artifactId}", "agent.artifacts.read"),
    ControlRoute("agent.rooms.list", "GET", "/api/agent/rooms", "/remote/v1/agent/rooms", "agent.rooms.read"),
    ControlRoute("agent.rooms.create", "POST", "/api/agent/rooms", "/remote/v1/agent/rooms", "agent.rooms.write"),
    ControlRoute("agent.room.get", "GET", "/api/agent/rooms/{roomId}", "/remote/v1/agent/rooms/{roomId}", "agent.rooms.read"),
    ControlRoute("agent.room.update", "PATCH", "/api/agent/rooms/{roomId}", "/remote/v1/agent/rooms/{roomId}", "agent.rooms.write"),
    ControlRoute("agent.room.messages", "POST", "/api/agent/rooms/{roomId}/messages", "/remote/v1/agent/rooms/{roomId}/messages", "agent.messages.write"),
    ControlRoute("agent.room.events", "GET", "/api/agent/rooms/{roomId}/events", "/remote/v1/agent/rooms/{roomId}/events", "agent.events.read", streaming=True),
    ControlRoute("agent.approvals.list", "GET", "/api/agent/approvals", "/remote/v1/agent/approvals", "agent.approvals.read"),
    ControlRoute("agent.approval.decision", "POST", "/api/agent/approvals/{approvalId}/decision", "/remote/v1/agent/approvals/{approvalId}/decision", "agent.approvals.decide"),
    ControlRoute("agent.media.list", "GET", "/api/agent/media", "/remote/v1/agent/media", "agent.media.read"),
    ControlRoute("agent.media.import", "POST", "/api/agent/media/import", "/remote/v1/agent/media/import", "agent.media.write"),
    ControlRoute("agent.deep-search", "POST", "/api/agent/deep-search", "/remote/v1/agent/deep-search", "agent.messages.write"),
    # Internal Pi tools use a process capability token and are never a browser route.
    ControlRoute("agent.tool.execute", "POST", "/api/agent/tool/execute", "", "agent.tools.execute", remote_allowed=False),
)


def control_route_catalog() -> list[dict[str, object]]:
    return [route.payload() for route in _CONTROL_ROUTES]


def control_route(path_id: str, *, remote: bool = False) -> ControlRoute:
    for route in _CONTROL_ROUTES:
        if route.path_id != path_id:
            continue
        if remote and (not route.remote_allowed or not route.remote_path):
            raise ValueError(f"control route is not available remotely: {path_id}")
        return route
    raise ValueError(f"unknown control pathId: {path_id}")
