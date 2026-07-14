from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from .errors import ControlApiError, ControlErrorCode
from .models import ControlAccessContext, ControlMethod, ControlRequest, ControlScope


class ControlPathId(str, Enum):
    CONTROL_BOOTSTRAP = "control.bootstrap"
    CONTROL_CAPABILITIES = "control.capabilities"
    CONTROL_EVENTS = "control.events"
    SYSTEM_HEALTH = "system.health"
    OVERVIEW_GET = "overview.get"
    INPUT_SOURCE_GET = "input.source.get"

    AGENT_RUNTIME_GET = "agent.runtime.get"
    AGENT_RUNTIME_ENSURE = "agent.runtime.ensure"
    AGENT_CONFIGURATION_GET = "agent.configuration.get"
    AGENT_CONFIGURATION_UPDATE = "agent.configuration.update"
    AGENT_SESSIONS_LIST = "agent.sessions.list"
    AGENT_SESSIONS_CREATE = "agent.sessions.create"
    AGENT_SESSION_SNAPSHOT = "agent.session.snapshot"
    AGENT_SESSION_RENAME = "agent.session.rename"
    AGENT_SESSION_ARCHIVE = "agent.session.archive"
    AGENT_SESSION_MODE_UPDATE = "agent.session.mode.update"
    AGENT_SESSION_DELETE = "agent.session.delete"
    AGENT_SESSION_PROMPT = "agent.session.prompt"
    AGENT_SESSION_ABORT = "agent.session.abort"
    AGENT_SESSION_COMPACT = "agent.session.compact"
    AGENT_SESSION_MODELS = "agent.session.models"
    AGENT_SESSION_MODEL_SELECT = "agent.session.model.select"
    AGENT_SESSION_THINKING_SELECT = "agent.session.thinking.select"
    AGENT_SESSION_EVENTS = "agent.session.events"
    AGENT_SESSION_INTERCOM_LIST = "agent.session.intercom.list"
    AGENT_SESSION_INTERCOM_SEND = "agent.session.intercom.send"
    AGENT_ARTIFACT_GET = "agent.artifact.get"
    AGENT_MEDIA_LIST = "agent.media.list"
    AGENT_DEEP_SEARCH = "agent.deep-search"
    AGENT_ROOMS_LIST = "agent.rooms.list"
    AGENT_ROOMS_CREATE = "agent.rooms.create"
    AGENT_ROOM_GET = "agent.room.get"
    AGENT_ROOM_SNAPSHOT = "agent.room.snapshot"
    AGENT_ROOM_ARCHIVE = "agent.room.archive"
    AGENT_ROOM_MESSAGE = "agent.room.message"
    AGENT_ROOM_EVENTS = "agent.room.events"
    AGENT_ROLES_LIST = "agent.roles.list"
    AGENT_TOOLS_LIST = "agent.tools.list"
    AGENT_APPROVALS_LIST = "agent.approvals.list"
    AGENT_APPROVAL_GET = "agent.approval.get"
    AGENT_APPROVAL_DECIDE = "agent.approval.decide"
    AGENT_SUBAGENTS_TEMPLATES = "agent.subagents.templates"
    AGENT_SUBAGENTS_LIST = "agent.subagents.list"
    AGENT_SUBAGENTS_CREATE = "agent.subagents.create"
    AGENT_SUBAGENT_GET = "agent.subagent.get"
    AGENT_SUBAGENT_ABORT = "agent.subagent.abort"
    AGENT_MEMORY_SOURCES_LIST = "agent.memorySources.list"

    PLANNING_DASHBOARD = "planning.dashboard"
    PLANNING_MUTATION_PREVIEW = "planning.mutation.preview"
    PLANNING_TASK_SAVE = "planning.task.save"
    PLANNING_TASK_ACTION = "planning.task.action"
    PLANNING_TASK_EVENT_UNDO = "planning.taskEvent.undo"
    PLANNING_MUTATION_ROLLBACK = "planning.mutation.rollback"
    MEMORY_SUMMARY = "memory.summary"
    MEMORY_PAGES = "memory.pages"
    HISTORY_PAGE = "history.page"
    KNOWLEDGE_START = "knowledge.start"
    KNOWLEDGE_CANCEL = "knowledge.cancel"
    KNOWLEDGE_STATUS = "knowledge.status"
    KNOWLEDGE_ROUTE_STATUS = "knowledge.routeStatus"
    KNOWLEDGE_DATABASE_APPLY_PREVIEW = "knowledge.database.apply.preview"
    KNOWLEDGE_DATABASE_APPLY = "knowledge.database.apply"
    KNOWLEDGE_DATABASE_ROLLBACK = "knowledge.database.rollback"
    DIAGNOSTICS_RUNTIME = "diagnostics.runtime"
    DIAGNOSTICS_PREDICTOR = "diagnostics.predictor"
    DIAGNOSTICS_MODELS = "diagnostics.models"
    CONFIGURATION_SETTINGS = "configuration.settings"
    CONFIGURATION_SCHEMA = "configuration.schema"


# Short integration name used by the generated TypeScript and Swift mirrors.
RouteId = ControlPathId


_PARAMETER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TEMPLATE_PARAMETER_PATTERN = re.compile(r"\{([A-Za-z][A-Za-z0-9]*)\}")
_QUERY_SCALAR_TYPES = (str, int, float, bool)


@dataclass(frozen=True)
class ControlRouteSpec:
    path_id: ControlPathId
    method: ControlMethod
    local_8766_path: str | None
    gateway_8768_path: str | None
    remote_safe: bool = False
    remote_scopes: frozenset[str] = frozenset()
    subscription: bool = False
    facade_handler: bool = False
    anonymous_remote: bool = False
    params: frozenset[str] = frozenset()
    param_values: Mapping[str, frozenset[str]] = field(default_factory=dict)
    query: frozenset[str] = frozenset()
    remote_query: frozenset[str] | None = None
    required_query: frozenset[str] = frozenset()
    body: frozenset[str] = frozenset()
    required_body: frozenset[str] = frozenset()
    remote_body: frozenset[str] = frozenset()
    remote_body_values: Mapping[str, frozenset[object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "param_values",
            MappingProxyType({key: frozenset(values) for key, values in self.param_values.items()}),
        )
        object.__setattr__(
            self,
            "remote_body_values",
            MappingProxyType({key: frozenset(values) for key, values in self.remote_body_values.items()}),
        )
        if self.facade_handler:
            if self.local_8766_path is not None or self.gateway_8768_path is not None:
                raise ValueError("facade routes cannot declare an upstream target")
        elif self.local_8766_path is None and self.gateway_8768_path is None:
            raise ValueError("upstream routes require at least one target")
        for target in (self.local_8766_path, self.gateway_8768_path):
            if target is not None:
                _validate_target_template(target, self.params)
        if self.remote_safe and not (self.gateway_8768_path or self.facade_handler):
            raise ValueError("remote-safe routes require a gateway or facade target")
        if self.anonymous_remote and not self.remote_safe:
            raise ValueError("anonymous remote routes must be remote-safe")
        if self.remote_scopes and not self.remote_safe:
            raise ValueError("local-only routes cannot declare remote scopes")
        if self.subscription and self.method is not ControlMethod.GET:
            raise ValueError("subscriptions must use GET")
        if self.subscription and "lastEventId" not in self.required_query:
            raise ValueError("subscriptions must require lastEventId")
        if not self.required_query.issubset(self.query):
            raise ValueError("required query keys must be allowlisted")
        if self.remote_query is not None and not self.remote_query.issubset(self.query):
            raise ValueError("remote query keys must be a subset of local query keys")
        if (
            self.remote_safe
            and self.remote_query is not None
            and not self.required_query.issubset(self.remote_query)
        ):
            raise ValueError("required query keys must remain available remotely")
        if not self.required_body.issubset(self.body):
            raise ValueError("required body keys must be allowlisted")
        if not self.remote_body.issubset(self.body):
            raise ValueError("remote body keys must be a subset of local body keys")
        if set(self.param_values) - self.params:
            raise ValueError("param value allowlists must name declared parameters")
        if set(self.remote_body_values) - self.remote_body:
            raise ValueError("remote value allowlists must name remote body keys")

    def validate_request(
        self,
        request: ControlRequest,
        context: ControlAccessContext,
    ) -> None:
        _validate_keys(request.params, allowed=self.params, required=self.params, field_name="params")
        for key, value in request.params.items():
            text = str(value)
            if not _PARAMETER_PATTERN.fullmatch(text):
                raise _invalid_field("params", key)
            allowed = self.param_values.get(key)
            if allowed is not None and text not in allowed:
                raise _invalid_field("params", key)

        allowed_query = (
            self.remote_query
            if context.is_remote and self.remote_query is not None
            else self.query
        )
        _validate_keys(
            request.query,
            allowed=allowed_query,
            required=self.required_query,
            field_name="query",
        )
        for key, value in request.query.items():
            if value is None or not isinstance(value, _QUERY_SCALAR_TYPES):
                raise _invalid_field("query", key)
            if isinstance(value, float) and not math.isfinite(value):
                raise _invalid_field("query", key)
            if isinstance(value, str) and (
                len(value) > 2_048 or any(ord(char) < 32 for char in value)
            ):
                raise _invalid_field("query", key)

        allowed_body = self.remote_body if context.is_remote else self.body
        _validate_keys(
            request.body,
            allowed=allowed_body,
            required=self.required_body,
            field_name="body",
        )
        if request.body and self.method is ControlMethod.GET:
            raise ControlApiError(
                ControlErrorCode.INVALID_REQUEST,
                "GET control routes do not accept a request body",
                details={"pathId": self.path_id.value},
            )
        if context.is_remote:
            for key, allowed_values in self.remote_body_values.items():
                if key in request.body and request.body[key] not in allowed_values:
                    raise _invalid_field("body", key)

    def authorize(self, context: ControlAccessContext) -> None:
        if not context.is_remote:
            return
        if not self.remote_safe:
            raise ControlApiError(
                ControlErrorCode.ROUTE_NOT_ALLOWED,
                "control route is not available to remote clients",
                details={"pathId": self.path_id.value},
                status=403,
            )
        if self.anonymous_remote:
            return
        if not context.remote_authenticated:
            raise ControlApiError(
                ControlErrorCode.SCOPE_REQUIRED,
                "paired remote device scope is required",
                details={"pathId": self.path_id.value, "missingScopes": sorted(self.remote_scopes)},
                status=403,
            )
        missing = sorted(self.remote_scopes - context.granted_scopes)
        if missing:
            raise ControlApiError(
                ControlErrorCode.SCOPE_REQUIRED,
                "remote device is missing required control scopes",
                details={"pathId": self.path_id.value, "missingScopes": missing},
                status=403,
            )

    def manifest_entry(self, *, include_targets: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "pathId": self.path_id.value,
            "method": self.method.value,
            "remoteSafe": self.remote_safe,
            "subscription": self.subscription,
            "params": sorted(self.params),
            "query": sorted(self.query),
        }
        if self.remote_scopes:
            result["remoteScopes"] = sorted(self.remote_scopes)
        if self.remote_query is not None:
            result["remoteQuery"] = sorted(self.remote_query)
        if include_targets:
            result["target"] = {
                "8766": self.local_8766_path or "facade",
                "8768": self.gateway_8768_path or "facade",
            }
        return result


class ControlRoutePolicy:
    def __init__(self, routes: Iterable[ControlRouteSpec]) -> None:
        table: dict[str, ControlRouteSpec] = {}
        for route in routes:
            raw = route.path_id.value
            if raw in table:
                raise ValueError(f"duplicate control pathId: {raw}")
            table[raw] = route
        if set(table) != {item.value for item in ControlPathId}:
            missing = sorted({item.value for item in ControlPathId} - set(table))
            extra = sorted(set(table) - {item.value for item in ControlPathId})
            raise ValueError(f"control route table is incomplete: missing={missing}, extra={extra}")
        self._routes = MappingProxyType(table)

    def resolve(self, path_id: str | ControlPathId) -> ControlRouteSpec:
        raw = path_id.value if isinstance(path_id, ControlPathId) else str(path_id)
        try:
            return self._routes[raw]
        except KeyError as exc:
            raise ControlApiError(
                ControlErrorCode.ROUTE_NOT_FOUND,
                "unknown control pathId",
                details={"pathId": raw[:128]},
                status=404,
            ) from exc

    def authorize(
        self,
        request: ControlRequest,
        context: ControlAccessContext,
    ) -> ControlRouteSpec:
        route = self.resolve(request.path_id)
        route.authorize(context)
        route.validate_request(request, context)
        return route

    def manifest(
        self,
        *,
        context: ControlAccessContext | None = None,
        include_targets: bool = False,
    ) -> list[dict[str, object]]:
        result = []
        for route in self._routes.values():
            if context is not None:
                try:
                    route.authorize(context)
                except ControlApiError:
                    continue
            result.append(route.manifest_entry(include_targets=include_targets))
        return result


def _route(
    path_id: ControlPathId,
    method: ControlMethod,
    local: str | None,
    gateway: str | None,
    *,
    scopes: Iterable[ControlScope] = (),
    remote_safe: bool = False,
    subscription: bool = False,
    facade: bool = False,
    anonymous_remote: bool = False,
    params: Iterable[str] = (),
    param_values: Mapping[str, Iterable[str]] | None = None,
    query: Iterable[str] = (),
    remote_query: Iterable[str] | None = None,
    required_query: Iterable[str] = (),
    body: Iterable[str] = (),
    required_body: Iterable[str] = (),
    remote_body: Iterable[str] = (),
    remote_body_values: Mapping[str, Iterable[object]] | None = None,
) -> ControlRouteSpec:
    return ControlRouteSpec(
        path_id=path_id,
        method=method,
        local_8766_path=local,
        gateway_8768_path=gateway,
        remote_safe=remote_safe,
        remote_scopes=frozenset(value.value for value in scopes),
        subscription=subscription,
        facade_handler=facade,
        anonymous_remote=anonymous_remote,
        params=frozenset(params),
        param_values={key: frozenset(values) for key, values in (param_values or {}).items()},
        query=frozenset(query),
        remote_query=frozenset(remote_query) if remote_query is not None else None,
        required_query=frozenset(required_query),
        body=frozenset(body),
        required_body=frozenset(required_body),
        remote_body=frozenset(remote_body),
        remote_body_values={key: frozenset(values) for key, values in (remote_body_values or {}).items()},
    )


_SESSION = {"sessionId"}
_ROOM = {"roomId"}
_APPROVAL = {"approvalId"}
_RUN = {"runId"}
_ARTIFACT = {"artifactId"}
_PAGE_QUERY = {"limit", "cursor", "query", "status"}
_LAST_EVENT_QUERY = {"lastEventId"}


def default_route_policy() -> ControlRoutePolicy:
    routes = [
        _route(ControlPathId.CONTROL_BOOTSTRAP, ControlMethod.GET, None, None, remote_safe=True, facade=True, anonymous_remote=True),
        _route(ControlPathId.CONTROL_CAPABILITIES, ControlMethod.GET, None, None, remote_safe=True, facade=True, anonymous_remote=True),
        _route(ControlPathId.CONTROL_EVENTS, ControlMethod.GET, "/api/agent/events", "/control/v1/events", scopes=[ControlScope.CONTROL_READ], remote_safe=True, subscription=True, query=_LAST_EVENT_QUERY, required_query=_LAST_EVENT_QUERY),
        _route(ControlPathId.SYSTEM_HEALTH, ControlMethod.GET, "/api/health", "/control/v1/health", scopes=[ControlScope.CONTROL_READ], remote_safe=True),
        _route(ControlPathId.OVERVIEW_GET, ControlMethod.GET, "/api/overview", "/control/v1/overview", scopes=[ControlScope.OVERVIEW_READ], remote_safe=True),
        _route(ControlPathId.INPUT_SOURCE_GET, ControlMethod.GET, "/api/input-source", "/control/v1/input/source", scopes=[ControlScope.INPUT_READ], remote_safe=True),

        _route(ControlPathId.AGENT_RUNTIME_GET, ControlMethod.GET, "/api/agent/runtime", "/control/v1/agent/runtime", scopes=[ControlScope.AGENT_READ], remote_safe=True),
        _route(ControlPathId.AGENT_RUNTIME_ENSURE, ControlMethod.POST, "/api/agent/runtime/ensure", "/control/v1/agent/runtime/ensure", body={"sessionId"}, required_body={"sessionId"}),
        _route(ControlPathId.AGENT_CONFIGURATION_GET, ControlMethod.GET, "/api/agent/configuration", "/control/v1/agent/configuration", scopes=[ControlScope.AGENT_READ], remote_safe=True),
        _route(ControlPathId.AGENT_CONFIGURATION_UPDATE, ControlMethod.POST, "/api/agent/configuration", "/control/v1/agent/configuration", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, body={"expectedRevision", "changes", "updatedBy"}, required_body={"expectedRevision", "changes"}, remote_body={"expectedRevision", "changes"}),
        _route(ControlPathId.AGENT_SESSIONS_LIST, ControlMethod.GET, "/api/agent/sessions", "/control/v1/agent/sessions", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"includeArchived", "includeInternal", "limit"}, remote_query={"includeArchived", "limit"}),
        _route(ControlPathId.AGENT_SESSIONS_CREATE, ControlMethod.POST, "/api/agent/sessions", "/control/v1/agent/sessions", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, body={"title", "mode", "roleId", "roleVersion", "modelProfile", "toolProfileVersion", "workspaceRoots"}, remote_body={"title", "mode", "roleId", "roleVersion", "modelProfile", "toolProfileVersion"}, remote_body_values={"mode": {"assistant"}}),
        _route(ControlPathId.AGENT_SESSION_SNAPSHOT, ControlMethod.GET, "/api/agent/sessions/{sessionId}/messages", "/control/v1/agent/sessions/{sessionId}/snapshot", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_RENAME, ControlMethod.PATCH, "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"title"}, required_body={"title"}, remote_body={"title"}),
        _route(ControlPathId.AGENT_SESSION_ARCHIVE, ControlMethod.PATCH, "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"archived"}, required_body={"archived"}, remote_body={"archived"}),
        _route(ControlPathId.AGENT_SESSION_MODE_UPDATE, ControlMethod.PATCH, "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", params=_SESSION, body={"mode", "workspaceRoots"}, required_body={"mode"}),
        _route(ControlPathId.AGENT_SESSION_DELETE, ControlMethod.DELETE, "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_PROMPT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/prompt", "/control/v1/agent/sessions/{sessionId}/prompt", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"message", "attachments", "clientMessageId"}, required_body={"message"}, remote_body={"message", "attachments", "clientMessageId"}),
        _route(ControlPathId.AGENT_SESSION_ABORT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/abort", "/control/v1/agent/sessions/{sessionId}/abort", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_COMPACT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/compact", "/control/v1/agent/sessions/{sessionId}/compact", params=_SESSION, body={"instructions"}),
        _route(ControlPathId.AGENT_SESSION_MODELS, ControlMethod.GET, "/api/agent/sessions/{sessionId}/models", "/control/v1/agent/sessions/{sessionId}/models", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_MODEL_SELECT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/model", "/control/v1/agent/sessions/{sessionId}/model", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"provider", "modelId"}, required_body={"provider", "modelId"}, remote_body={"provider", "modelId"}),
        _route(ControlPathId.AGENT_SESSION_THINKING_SELECT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/thinking", "/control/v1/agent/sessions/{sessionId}/thinking", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"level"}, required_body={"level"}, remote_body={"level"}),
        _route(ControlPathId.AGENT_SESSION_EVENTS, ControlMethod.GET, "/api/agent/sessions/{sessionId}/events", "/control/v1/agent/sessions/{sessionId}/events", scopes=[ControlScope.AGENT_READ], remote_safe=True, subscription=True, params=_SESSION, query=_LAST_EVENT_QUERY, required_query=_LAST_EVENT_QUERY),
        _route(ControlPathId.AGENT_SESSION_INTERCOM_LIST, ControlMethod.GET, "/api/agent/sessions/{sessionId}/intercom", "/control/v1/agent/sessions/{sessionId}/intercom", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION, query={"status", "limit"}),
        _route(ControlPathId.AGENT_SESSION_INTERCOM_SEND, ControlMethod.POST, "/api/agent/sessions/{sessionId}/intercom", "/control/v1/agent/sessions/{sessionId}/intercom", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"kind", "targetParticipantId", "clientMessageId", "replyTo", "content"}, required_body={"kind", "clientMessageId", "content"}, remote_body={"kind", "targetParticipantId", "clientMessageId", "replyTo", "content"}, remote_body_values={"kind": {"send", "ask", "reply"}}),
        _route(ControlPathId.AGENT_ARTIFACT_GET, ControlMethod.GET, "/api/agent/artifacts/{artifactId}", "/control/v1/agent/artifacts/{artifactId}", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_ARTIFACT, query={"sessionId", "limit"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_MEDIA_LIST, ControlMethod.GET, "/api/agent/media", "/control/v1/agent/media", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"sessionId", "limit"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_DEEP_SEARCH, ControlMethod.POST, "/api/agent/deep-search", "/control/v1/agent/deep-search", body={"query", "privacyDisposition", "context", "frontAppBundleId", "contextSource", "evidence"}, required_body={"query", "privacyDisposition"}),

        _route(ControlPathId.AGENT_ROOMS_LIST, ControlMethod.GET, "/api/agent/rooms", "/control/v1/agent/rooms", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"includeArchived", "limit"}),
        _route(ControlPathId.AGENT_ROOMS_CREATE, ControlMethod.POST, "/api/agent/rooms", "/control/v1/agent/rooms", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, body={"title", "participants", "routingPolicy", "moderatorRoleId"}, required_body={"participants"}, remote_body={"title", "participants", "routingPolicy", "moderatorRoleId"}),
        _route(ControlPathId.AGENT_ROOM_GET, ControlMethod.GET, "/api/agent/rooms/{roomId}", "/control/v1/agent/rooms/{roomId}", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_ROOM),
        _route(ControlPathId.AGENT_ROOM_SNAPSHOT, ControlMethod.GET, "/api/agent/rooms/{roomId}/snapshot", "/control/v1/agent/rooms/{roomId}/snapshot", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_ROOM),
        _route(ControlPathId.AGENT_ROOM_ARCHIVE, ControlMethod.PATCH, "/api/agent/rooms/{roomId}", "/control/v1/agent/rooms/{roomId}", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_ROOM, body={"archived"}, required_body={"archived"}, remote_body={"archived"}),
        _route(ControlPathId.AGENT_ROOM_MESSAGE, ControlMethod.POST, "/api/agent/rooms/{roomId}/messages", "/control/v1/agent/rooms/{roomId}/messages", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_ROOM, body={"message", "clientMessageId"}, required_body={"message"}, remote_body={"message", "clientMessageId"}),
        _route(ControlPathId.AGENT_ROOM_EVENTS, ControlMethod.GET, "/api/agent/rooms/{roomId}/events", "/control/v1/agent/rooms/{roomId}/events", scopes=[ControlScope.AGENT_READ], remote_safe=True, subscription=True, params=_ROOM, query=_LAST_EVENT_QUERY, required_query=_LAST_EVENT_QUERY),
        _route(ControlPathId.AGENT_ROLES_LIST, ControlMethod.GET, "/api/agent/roles", "/control/v1/agent/roles", scopes=[ControlScope.AGENT_READ], remote_safe=True),
        _route(ControlPathId.AGENT_TOOLS_LIST, ControlMethod.GET, "/api/agent/tools", "/control/v1/agent/tools"),
        _route(ControlPathId.AGENT_APPROVALS_LIST, ControlMethod.GET, "/api/agent/approvals", "/control/v1/agent/approvals", scopes=[ControlScope.AGENT_APPROVE], remote_safe=True, query={"sessionId", "state", "limit"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_APPROVAL_GET, ControlMethod.GET, "/api/agent/approvals/{approvalId}", "/control/v1/agent/approvals/{approvalId}", scopes=[ControlScope.AGENT_APPROVE], remote_safe=True, params=_APPROVAL),
        _route(ControlPathId.AGENT_APPROVAL_DECIDE, ControlMethod.POST, "/api/agent/approvals/{approvalId}/decision", "/control/v1/agent/approvals/{approvalId}/decision", scopes=[ControlScope.AGENT_APPROVE], remote_safe=True, params=_APPROVAL, body={"decision", "payloadSha256"}, required_body={"decision", "payloadSha256"}, remote_body={"decision", "payloadSha256"}, remote_body_values={"decision": {"approve", "reject"}}),
        _route(ControlPathId.AGENT_SUBAGENTS_TEMPLATES, ControlMethod.GET, "/api/agent/subagents/templates", "/control/v1/agent/subagents/templates", scopes=[ControlScope.AGENT_READ], remote_safe=True),
        _route(ControlPathId.AGENT_SUBAGENTS_LIST, ControlMethod.GET, "/api/agent/subagents/runs", "/control/v1/agent/subagents/runs", scopes=[ControlScope.AGENT_DELEGATE], remote_safe=True, query={"sessionId", "limit"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_SUBAGENTS_CREATE, ControlMethod.POST, "/api/agent/subagents/runs", "/control/v1/agent/subagents/runs", scopes=[ControlScope.AGENT_DELEGATE], remote_safe=True, body={"sessionId", "tasks", "agent", "version", "task", "contextMode", "wait"}, required_body={"sessionId"}, remote_body={"sessionId", "tasks", "agent", "version", "task", "contextMode", "wait"}, remote_body_values={"contextMode": {"fresh"}}),
        _route(ControlPathId.AGENT_SUBAGENT_GET, ControlMethod.GET, "/api/agent/subagents/runs/{runId}", "/control/v1/agent/subagents/runs/{runId}", scopes=[ControlScope.AGENT_DELEGATE], remote_safe=True, params=_RUN, query={"sessionId"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_SUBAGENT_ABORT, ControlMethod.POST, "/api/agent/subagents/runs/{runId}/abort", "/control/v1/agent/subagents/runs/{runId}/abort", scopes=[ControlScope.AGENT_DELEGATE], remote_safe=True, params=_RUN, body={"sessionId"}, required_body={"sessionId"}, remote_body={"sessionId"}),
        _route(ControlPathId.AGENT_MEMORY_SOURCES_LIST, ControlMethod.GET, "/api/agent/memory-sources", "/control/v1/agent/memory-sources", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"sessionId", "limit"}, required_query={"sessionId"}),

        _route(ControlPathId.PLANNING_DASHBOARD, ControlMethod.GET, "/api/planning/dashboard", "/control/v1/planning/dashboard", scopes=[ControlScope.PLANNING_READ], remote_safe=True, query={"date", "project"}),
        _route(ControlPathId.PLANNING_MUTATION_PREVIEW, ControlMethod.POST, "/api/planning/mutation/preview", "/control/v1/planning/mutation/preview", body={"kind", "payload", "expectedRuntimeRevision"}, required_body={"kind", "payload", "expectedRuntimeRevision"}),
        _route(ControlPathId.PLANNING_TASK_SAVE, ControlMethod.POST, "/api/planning/task/save", "/control/v1/planning/task/save", body={"taskId", "date", "title", "detail", "priority", "status", "dueAtMs", "goalId", "project", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}, required_body={"date", "title", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.PLANNING_TASK_ACTION, ControlMethod.POST, "/api/planning/task/action", "/control/v1/planning/task/action", body={"taskId", "action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}, required_body={"taskId", "action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.PLANNING_TASK_EVENT_UNDO, ControlMethod.POST, "/api/planning/task-event/undo", "/control/v1/planning/task-event/undo", body={"eventId", "receiptId", "rollbackToken", "payloadSha256", "confirmText"}, required_body={"eventId", "receiptId", "rollbackToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.PLANNING_MUTATION_ROLLBACK, ControlMethod.POST, "/api/planning/mutation/rollback", "/control/v1/planning/mutation/rollback", body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}, required_body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.MEMORY_SUMMARY, ControlMethod.GET, "/api/memory/summary", "/control/v1/memory/summary", scopes=[ControlScope.MEMORY_READ], remote_safe=True),
        _route(ControlPathId.MEMORY_PAGES, ControlMethod.GET, "/api/memory/{kind}", "/control/v1/memory/{kind}", scopes=[ControlScope.MEMORY_READ], remote_safe=True, params={"kind"}, param_values={"kind": {"books", "atoms", "tags", "phrases", "groups", "negative"}}, query=_PAGE_QUERY),
        _route(ControlPathId.HISTORY_PAGE, ControlMethod.GET, "/api/history/page", "/control/v1/history/page", scopes=[ControlScope.HISTORY_READ], remote_safe=True, query={"limit", "cursor", "query", "filter"}),
        _route(ControlPathId.KNOWLEDGE_START, ControlMethod.POST, "/api/knowledge/start", "/control/v1/knowledge/start", body={"question", "context", "mode", "includeNotion", "generation", "contextHash", "clientId", "project", "app", "maxChars", "latencyBudgetMs"}, required_body={"question"}),
        _route(ControlPathId.KNOWLEDGE_CANCEL, ControlMethod.POST, "/api/knowledge/cancel", "/control/v1/knowledge/cancel", body={"sessionId", "id"}),
        _route(ControlPathId.KNOWLEDGE_STATUS, ControlMethod.GET, "/api/knowledge/status", "/control/v1/knowledge/status", scopes=[ControlScope.KNOWLEDGE_READ], remote_safe=True, query={"sessionId", "id"}),
        _route(ControlPathId.KNOWLEDGE_ROUTE_STATUS, ControlMethod.GET, "/api/knowledge/route-status", "/control/v1/knowledge/route-status", scopes=[ControlScope.KNOWLEDGE_READ], remote_safe=True),
        _route(ControlPathId.KNOWLEDGE_DATABASE_APPLY_PREVIEW, ControlMethod.POST, "/api/knowledge/database/apply-preview", "/control/v1/knowledge/database/apply-preview", body={"runId", "expectedRuntimeRevision"}, required_body={"runId"}),
        _route(ControlPathId.KNOWLEDGE_DATABASE_APPLY, ControlMethod.POST, "/api/knowledge/database/apply", "/control/v1/knowledge/database/apply", body={"runId", "confirm", "previewToken", "payloadSha256", "expectedRuntimeRevision"}, required_body={"runId", "confirm", "previewToken", "payloadSha256", "expectedRuntimeRevision"}),
        _route(ControlPathId.KNOWLEDGE_DATABASE_ROLLBACK, ControlMethod.POST, "/api/knowledge/database/rollback", "/control/v1/knowledge/database/rollback", body={"runId", "confirm", "receiptId", "rollbackToken", "payloadSha256"}, required_body={"runId", "confirm", "receiptId", "rollbackToken", "payloadSha256"}),
        _route(ControlPathId.DIAGNOSTICS_RUNTIME, ControlMethod.GET, "/api/runtime/status", "/control/v1/diagnostics/runtime", scopes=[ControlScope.DIAGNOSTICS_READ], remote_safe=True),
        _route(ControlPathId.DIAGNOSTICS_PREDICTOR, ControlMethod.GET, "/api/predictor/status", "/control/v1/diagnostics/predictor", scopes=[ControlScope.DIAGNOSTICS_READ], remote_safe=True),
        _route(ControlPathId.DIAGNOSTICS_MODELS, ControlMethod.GET, "/api/models/status", "/control/v1/diagnostics/models", scopes=[ControlScope.DIAGNOSTICS_READ], remote_safe=True),
        _route(ControlPathId.CONFIGURATION_SETTINGS, ControlMethod.GET, "/api/settings", "/control/v1/configuration/settings", scopes=[ControlScope.CONFIGURATION_READ], remote_safe=True),
        _route(ControlPathId.CONFIGURATION_SCHEMA, ControlMethod.GET, "/api/settings/schema", "/control/v1/configuration/schema", scopes=[ControlScope.CONFIGURATION_READ], remote_safe=True),
    ]
    return ControlRoutePolicy(routes)


def route_manifest(*, include_targets: bool = True) -> list[dict[str, object]]:
    """Return the canonical pathId manifest for TS/Swift mirror generation."""

    return default_route_policy().manifest(include_targets=include_targets)


def _validate_target_template(target: str, params: frozenset[str]) -> None:
    if not target.startswith("/") or "?" in target or "#" in target or "\\" in target:
        raise ValueError(f"invalid control route target: {target}")
    if any(segment == ".." for segment in target.split("/")):
        raise ValueError(f"control route target traverses a parent: {target}")
    placeholders = frozenset(_TEMPLATE_PARAMETER_PATTERN.findall(target))
    if placeholders != params:
        raise ValueError(
            f"control target parameters do not match route params: target={target}, params={sorted(params)}"
        )


def _validate_keys(
    value: Mapping[str, object],
    *,
    allowed: frozenset[str],
    required: frozenset[str],
    field_name: str,
) -> None:
    keys = frozenset(value)
    unsupported = sorted(keys - allowed)
    if unsupported:
        raise ControlApiError(
            ControlErrorCode.INVALID_REQUEST,
            f"control request contains unsupported {field_name} fields",
            details={"field": field_name, "fields": unsupported},
        )
    missing = sorted(required - keys)
    if missing:
        raise ControlApiError(
            ControlErrorCode.INVALID_REQUEST,
            f"control request is missing required {field_name} fields",
            details={"field": field_name, "fields": missing},
        )


def _invalid_field(field_name: str, key: str) -> ControlApiError:
    return ControlApiError(
        ControlErrorCode.INVALID_REQUEST,
        f"control request {field_name} field is invalid",
        details={"field": field_name, "key": key},
    )


def control_route_catalog() -> list[dict[str, object]]:
    """Compatibility name backed by the one canonical strict manifest."""

    return route_manifest(include_targets=True)


def control_route(path_id: str, *, remote: bool = False) -> ControlRouteSpec:
    """Compatibility resolver backed by ``default_route_policy``."""

    try:
        route = default_route_policy().resolve(path_id)
    except ControlApiError as exc:
        raise ValueError(f"unknown control pathId: {path_id}") from exc
    if remote and (not route.remote_safe or route.gateway_8768_path is None):
        raise ValueError(f"control route is not available remotely: {path_id}")
    return route
