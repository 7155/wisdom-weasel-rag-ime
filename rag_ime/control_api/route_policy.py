from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping
from urllib.parse import unquote

from .errors import ControlApiError, ControlErrorCode
from .models import ControlAccessContext, ControlMethod, ControlRequest, ControlScope


class ControlPathId(str, Enum):
    CONTROL_BOOTSTRAP = "control.bootstrap"
    CONTROL_CAPABILITIES = "control.capabilities"
    CONTROL_EVENTS = "control.events"
    SYSTEM_HEALTH = "system.health"
    OVERVIEW_GET = "overview.get"
    INPUT_SOURCE_GET = "input.source.get"
    INPUT_LEXICON_REVIEW = "input.lexicon.review"
    INPUT_LEXICON_APPLY = "input.lexicon.apply"
    INPUT_LEXICON_ROLLBACK = "input.lexicon.rollback"
    OBSERVABILITY_SNAPSHOT = "observability.snapshot"
    OBSERVABILITY_EVENTS = "observability.events"

    AGENT_RUNTIME_GET = "agent.runtime.get"
    AGENT_RUNTIME_ENSURE = "agent.runtime.ensure"
    AGENT_PROVIDERS_GET = "agent.providers.get"
    AGENT_PROVIDER_AUTH_PREVIEW = "agent.provider.auth.preview"
    AGENT_PROVIDER_AUTH_APPLY = "agent.provider.auth.apply"
    AGENT_PROVIDER_OAUTH_STATUS = "agent.provider.oauth.status"
    AGENT_PROVIDER_OAUTH_CANCEL = "agent.provider.oauth.cancel"
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
    AGENT_SESSION_REWRITE = "agent.session.rewrite"
    AGENT_SESSION_FORKS_LIST = "agent.session.forks.list"
    AGENT_SESSION_FORKS_CREATE = "agent.session.forks.create"
    AGENT_SESSION_ABORT = "agent.session.abort"
    AGENT_SESSION_REVIEW_RESOLVE = "agent.session.review.resolve"
    AGENT_SESSION_COMPACT = "agent.session.compact"
    AGENT_SESSION_COMMANDS = "agent.session.commands"
    AGENT_SESSION_MODELS = "agent.session.models"
    AGENT_SESSION_MODEL_SELECT = "agent.session.model.select"
    AGENT_SESSION_THINKING_SELECT = "agent.session.thinking.select"
    AGENT_SESSION_EVENTS = "agent.session.events"
    AGENT_SESSION_INTERCOM_LIST = "agent.session.intercom.list"
    AGENT_SESSION_INTERCOM_SEND = "agent.session.intercom.send"
    AGENT_SESSION_CONTEXT_ITEMS_LIST = "agent.session.contextItems.list"
    AGENT_SESSION_CONTEXT_ITEM_ACK = "agent.session.contextItems.ack"
    AGENT_SESSION_CONTEXT_TRACES_LIST = "agent.session.contextTraces.list"
    AGENT_SESSION_CONTEXT_TRACE_GET = "agent.session.contextTrace.get"
    AGENT_SESSION_DEBUG_CONTEXT_GET = "agent.session.debugContext.get"
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
    AGENT_ROOM_TOPICS = "agent.room.topics"
    AGENT_ROOM_TOPIC_CREATE = "agent.room.topic.create"
    AGENT_ROOM_TOPIC_UPDATE = "agent.room.topic.update"
    AGENT_ROOM_ARTIFACTS = "agent.room.artifacts"
    AGENT_ROOM_ARTIFACT_ADD = "agent.room.artifact.add"
    AGENT_ROOM_ARTIFACT_UPDATE = "agent.room.artifact.update"
    AGENT_ROLES_LIST = "agent.roles.list"
    AGENT_ROLES_CREATE = "agent.roles.create"
    AGENT_ROLE_MODELS = "agent.role.models"
    AGENT_ROLE_RUNTIME_DEFAULTS_UPDATE = "agent.role.runtimeDefaults.update"
    AGENT_TOOLS_LIST = "agent.tools.list"
    AGENT_EXTENSIONS_LIST = "agent.extensions.list"
    AGENT_EXTENSIONS_CREATE = "agent.extensions.create"
    AGENT_EXTENSIONS_PROPOSALS = "agent.extensions.proposals"
    AGENT_EXTENSIONS_VALIDATE = "agent.extensions.validate"
    AGENT_EXTENSIONS_PREVIEW = "agent.extensions.preview"
    AGENT_EXTENSIONS_APPLY = "agent.extensions.apply"
    AGENT_APPROVALS_LIST = "agent.approvals.list"
    AGENT_APPROVAL_GET = "agent.approval.get"
    AGENT_APPROVAL_DECIDE = "agent.approval.decide"
    AGENT_MEMORY_MAINTENANCE_RUN = "agent.memoryMaintenance.run"
    AGENT_SUBAGENTS_TEMPLATES = "agent.subagents.templates"
    AGENT_SUBAGENTS_LIST = "agent.subagents.list"
    AGENT_SUBAGENTS_CREATE = "agent.subagents.create"
    AGENT_SUBAGENT_GET = "agent.subagent.get"
    AGENT_SUBAGENT_ABORT = "agent.subagent.abort"
    AGENT_MEMORY_SOURCES_LIST = "agent.memorySources.list"
    AGENT_WAKE_SCHEDULES_LIST = "agent.wakeSchedules.list"
    AGENT_WAKE_SCHEDULES_CREATE = "agent.wakeSchedules.create"
    AGENT_WAKE_SCHEDULE_RUNS = "agent.wakeSchedule.runs"
    AGENT_WAKE_SCHEDULE_ACTION = "agent.wakeSchedule.action"

    BROWSER_STATUS = "browser.status"
    BROWSER_PAIRING = "browser.pairing"
    BROWSER_TABS = "browser.tabs"
    BROWSER_SNAPSHOT_LATEST = "browser.snapshot.latest"
    BROWSER_SNAPSHOT_IMAGE = "browser.snapshot.image"
    BROWSER_TRACES = "browser.traces"
    BROWSER_PERMISSIONS = "browser.permissions"
    BROWSER_PERMISSION_GET = "browser.permission.get"
    BROWSER_PERMISSION_DECIDE = "browser.permission.decide"
    BROWSER_MODE_UPDATE = "browser.mode.update"
    BROWSER_PAIRING_ROTATE = "browser.pairing.rotate"
    BROWSER_COMMAND = "browser.command"
    BROWSER_STOP = "browser.stop"
    BROWSER_MANAGED_START = "browser.managed.start"
    BROWSER_MANAGED_STOP = "browser.managed.stop"

    PLANNING_DASHBOARD = "planning.dashboard"
    PLANNING_MUTATION_PREVIEW = "planning.mutation.preview"
    PLANNING_TASK_SAVE = "planning.task.save"
    PLANNING_GOAL_SAVE = "planning.goal.save"
    PLANNING_TASK_ACTION = "planning.task.action"
    PLANNING_TASK_EVENT_UNDO = "planning.taskEvent.undo"
    PLANNING_MUTATION_ROLLBACK = "planning.mutation.rollback"
    MEMORY_SUMMARY = "memory.summary"
    MEMORY_PAGES = "memory.pages"
    MEMORY_GRAPH_GET = "memory.graph.get"
    MEMORY_ENTITY_GET = "memory.entity.get"
    MEMORY_EDIT = "memory.edit"
    MEMORY_SOURCE_DISPOSITION = "memory.source.disposition"
    MEMORY_BOOK_ARCHIVE_PREVIEW = "memory.book.archive.preview"
    MEMORY_BOOK_ARCHIVE_APPLY = "memory.book.archive.apply"
    MEMORY_BOOK_ARCHIVE_ROLLBACK = "memory.book.archive.rollback"
    HISTORY_PAGE = "history.page"
    HISTORY_DETAIL = "history.detail"
    HISTORY_TOMBSTONE_PREVIEW = "history.tombstone.preview"
    HISTORY_TOMBSTONE_APPLY = "history.tombstone.apply"
    HISTORY_TOMBSTONE_ROLLBACK = "history.tombstone.rollback"
    KNOWLEDGE_START = "knowledge.start"
    KNOWLEDGE_CANCEL = "knowledge.cancel"
    KNOWLEDGE_STATUS = "knowledge.status"
    KNOWLEDGE_ROUTE_STATUS = "knowledge.routeStatus"
    KNOWLEDGE_DATABASE_APPLY_PREVIEW = "knowledge.database.apply.preview"
    KNOWLEDGE_DATABASE_DRAFT_EDIT = "knowledge.database.draft.edit"
    KNOWLEDGE_DATABASE_APPLY = "knowledge.database.apply"
    KNOWLEDGE_DATABASE_ROLLBACK = "knowledge.database.rollback"
    KNOWLEDGE_BASES_LIST = "knowledgeBases.list"
    KNOWLEDGE_BASES_CREATE = "knowledgeBases.create"
    KNOWLEDGE_BASES_GET = "knowledgeBases.get"
    KNOWLEDGE_BASES_UPDATE = "knowledgeBases.update"
    KNOWLEDGE_BASES_DELETE_PREVIEW = "knowledgeBases.delete.preview"
    KNOWLEDGE_BASES_DELETE_APPLY = "knowledgeBases.delete.apply"
    KNOWLEDGE_BASES_DOCUMENTS_LIST = "knowledgeBases.documents.list"
    KNOWLEDGE_BASES_DOCUMENT_IMPORT = "knowledgeBases.document.import"
    KNOWLEDGE_BASES_DOCUMENT_RETRY = "knowledgeBases.document.retry"
    KNOWLEDGE_BASES_DOCUMENT_DELETE = "knowledgeBases.document.delete"
    KNOWLEDGE_BASES_DOCUMENT_GET = "knowledgeBases.document.get"
    KNOWLEDGE_BASES_DOCUMENT_SOURCE = "knowledgeBases.document.source"
    KNOWLEDGE_BASES_ASSET_GET = "knowledgeBases.asset.get"
    KNOWLEDGE_BASES_JOBS_LIST = "knowledgeBases.jobs.list"
    KNOWLEDGE_BASES_JOB_CANCEL = "knowledgeBases.job.cancel"
    KNOWLEDGE_BASES_CHUNK_PREVIEW = "knowledgeBases.chunkPreview"
    KNOWLEDGE_BASES_SEARCH = "knowledgeBases.search"
    KNOWLEDGE_BASES_FIND = "knowledgeBases.find"
    KNOWLEDGE_BASES_OPEN = "knowledgeBases.open"
    KNOWLEDGE_BASES_GRAPH_GET = "knowledgeBases.graph.get"
    KNOWLEDGE_BASES_GRAPH_REBUILD = "knowledgeBases.graph.rebuild"
    KNOWLEDGE_BASES_REINDEX_PREVIEW = "knowledgeBases.reindexPreview"
    KNOWLEDGE_BASES_REBUILD = "knowledgeBases.rebuild"
    KNOWLEDGE_WORKER_HEALTH = "knowledgeWorker.health"
    KNOWLEDGE_PARSERS_LIST = "knowledgeParsers.list"
    DIAGNOSTICS_RUNTIME = "diagnostics.runtime"
    DIAGNOSTICS_PREDICTOR = "diagnostics.predictor"
    DIAGNOSTICS_MODELS = "diagnostics.models"
    DIAGNOSTICS_ACTION_PREVIEW = "diagnostics.action.preview"
    DIAGNOSTICS_ACTION_START = "diagnostics.action.start"
    DIAGNOSTICS_ACTION_JOB = "diagnostics.action.job"
    CONFIGURATION_SETTINGS = "configuration.settings"
    CONFIGURATION_SCHEMA = "configuration.schema"
    CONFIGURATION_SETTINGS_PREVIEW = "configuration.settings.preview"
    CONFIGURATION_SETTINGS_APPLY = "configuration.settings.apply"
    CONFIGURATION_SETTINGS_ROLLBACK = "configuration.settings.rollback"
    CONFIGURATION_IMPORT_PREVIEW = "configuration.import.preview"
    CONFIGURATION_IMPORT_APPLY = "configuration.import.apply"
    CONFIGURATION_BACKUP_EXPORT = "configuration.backup.export"
    CONFIGURATION_RESTORE_PREVIEW = "configuration.restore.preview"
    CONFIGURATION_RESTORE_APPLY = "configuration.restore.apply"


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
    binary: bool = False
    params: frozenset[str] = frozenset()
    param_values: Mapping[str, frozenset[str]] = field(default_factory=dict)
    query: frozenset[str] = frozenset()
    remote_query: frozenset[str] | None = None
    required_query: frozenset[str] = frozenset()
    body: frozenset[str] = frozenset()
    required_body: frozenset[str] = frozenset()
    remote_body: frozenset[str] = frozenset()
    remote_required_body: frozenset[str] | None = None
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
        if self.binary and self.method is not ControlMethod.GET:
            raise ValueError("binary routes must use GET")
        if self.binary and self.subscription:
            raise ValueError("binary routes cannot be subscriptions")
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
        if (
            self.remote_required_body is not None
            and not self.remote_required_body.issubset(self.remote_body)
        ):
            raise ValueError("remote required body keys must be remotely allowlisted")
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
            if key == "assetId" and re.fullmatch(r"[a-f0-9]{64}", text) is None:
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
        required_body = (
            self.remote_required_body
            if context.is_remote and self.remote_required_body is not None
            else self.required_body
        )
        _validate_keys(
            request.body,
            allowed=allowed_body,
            required=required_body,
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
        if self.binary:
            result["binary"] = True
        if self.remote_query is not None:
            result["remoteQuery"] = sorted(self.remote_query)
        if self.remote_required_body is not None:
            result["remoteRequiredBody"] = sorted(self.remote_required_body)
        if include_targets:
            result["target"] = {
                "8766": self.local_8766_path or "facade",
                "8768": (
                    "facade"
                    if self.facade_handler
                    else self.gateway_8768_path
                ),
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
        self._http_routes = tuple(
            (
                route,
                _compile_target_template(route.local_8766_path),
            )
            for route in table.values()
            if route.local_8766_path is not None
        )

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

    def authorize_http(
        self,
        *,
        method: str | ControlMethod,
        path: str,
        query: Mapping[str, object],
        body: Mapping[str, object],
        context: ControlAccessContext,
        request_id: str = "http-request",
    ) -> ControlRouteSpec:
        """Resolve a fixed legacy HTTP path back to its canonical pathId policy."""

        try:
            control_method = method if isinstance(method, ControlMethod) else ControlMethod(str(method))
        except ValueError as exc:
            raise ControlApiError(
                ControlErrorCode.METHOD_NOT_ALLOWED,
                "unsupported control HTTP method",
                status=405,
            ) from exc

        candidates: list[tuple[ControlRouteSpec, dict[str, object]]] = []
        for route, pattern in self._http_routes:
            if route.method is not control_method:
                continue
            match = pattern.fullmatch(path)
            if match is None:
                continue
            candidates.append(
                (
                    route,
                    {key: unquote(value) for key, value in match.groupdict().items()},
                )
            )
        for path_id, facade_path in _FACADE_HTTP_PATHS.items():
            route = self._routes[path_id.value]
            if route.method is control_method and path == facade_path:
                candidates.append((route, {}))

        if not candidates:
            raise ControlApiError(
                ControlErrorCode.ROUTE_NOT_FOUND,
                "control HTTP route is not allowlisted",
                details={"method": control_method.value, "path": path[:256]},
                status=404,
            )

        errors: list[ControlApiError] = []
        for route, params in candidates:
            try:
                self.authorize(
                    ControlRequest(
                        request_id=request_id,
                        path_id=route.path_id.value,
                        params=params,
                        query=query,
                        body=body,
                    ),
                    context,
                )
                return route
            except ControlApiError as exc:
                errors.append(exc)

        for code in (
            ControlErrorCode.ROUTE_NOT_ALLOWED,
            ControlErrorCode.SCOPE_REQUIRED,
            ControlErrorCode.INVALID_REQUEST,
        ):
            match = next((error for error in errors if error.code is code), None)
            if match is not None:
                raise match
        raise errors[0]

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
    binary: bool = False,
    params: Iterable[str] = (),
    param_values: Mapping[str, Iterable[str]] | None = None,
    query: Iterable[str] = (),
    remote_query: Iterable[str] | None = None,
    required_query: Iterable[str] = (),
    body: Iterable[str] = (),
    required_body: Iterable[str] = (),
    remote_body: Iterable[str] = (),
    remote_required_body: Iterable[str] | None = None,
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
        binary=binary,
        params=frozenset(params),
        param_values={key: frozenset(values) for key, values in (param_values or {}).items()},
        query=frozenset(query),
        remote_query=frozenset(remote_query) if remote_query is not None else None,
        required_query=frozenset(required_query),
        body=frozenset(body),
        required_body=frozenset(required_body),
        remote_body=frozenset(remote_body),
        remote_required_body=(
            frozenset(remote_required_body)
            if remote_required_body is not None
            else None
        ),
        remote_body_values={key: frozenset(values) for key, values in (remote_body_values or {}).items()},
    )


_SESSION = {"sessionId"}
_ROOM = {"roomId"}
_APPROVAL = {"approvalId"}
_RUN = {"runId"}
_ARTIFACT = {"artifactId"}
_CONTEXT_ITEM = {"sessionId", "itemId"}
_CONTEXT_TRACE = {"sessionId", "traceId"}
_WAKE_SCHEDULE = {"scheduleId"}
_BROWSER_SNAPSHOT = {"snapshotId"}
_BROWSER_PERMISSION = {"promptId"}
_KNOWLEDGE_BASE = {"kbId"}
_KNOWLEDGE_DOCUMENT = {"kbId", "fileId"}
_KNOWLEDGE_ASSET = {"kbId", "fileId", "assetId"}
_KNOWLEDGE_JOB = {"kbId", "jobId"}
_PAGE_QUERY = {
    "limit",
    "cursor",
    "query",
    "status",
    "ownerKind",
    "ownerId",
}
_LAST_EVENT_QUERY = {"lastEventId"}
_OBSERVATION_FILTER_QUERY = {
    "sessionId",
    "roomId",
    "traceId",
    "category",
    "status",
}


def default_route_policy() -> ControlRoutePolicy:
    routes = [
        _route(ControlPathId.CONTROL_BOOTSTRAP, ControlMethod.GET, None, None, remote_safe=True, facade=True, anonymous_remote=True),
        _route(ControlPathId.CONTROL_CAPABILITIES, ControlMethod.GET, None, None, remote_safe=True, facade=True, anonymous_remote=True),
        _route(ControlPathId.CONTROL_EVENTS, ControlMethod.GET, "/api/agent/events", "/control/v1/events", scopes=[ControlScope.CONTROL_READ], remote_safe=True, subscription=True, query=_LAST_EVENT_QUERY, required_query=_LAST_EVENT_QUERY),
        _route(ControlPathId.SYSTEM_HEALTH, ControlMethod.GET, "/api/health", "/control/v1/health", scopes=[ControlScope.CONTROL_READ], remote_safe=True),
        _route(ControlPathId.OVERVIEW_GET, ControlMethod.GET, "/api/overview", "/control/v1/overview", scopes=[ControlScope.OVERVIEW_READ], remote_safe=True),
        _route(ControlPathId.INPUT_SOURCE_GET, ControlMethod.GET, "/api/input-source", "/control/v1/input/source", scopes=[ControlScope.INPUT_READ], remote_safe=True),
        _route(ControlPathId.INPUT_LEXICON_REVIEW, ControlMethod.GET, "/api/rime-lexicon/review", "/control/v1/input/lexicon/review", query={"limit", "project"}),
        _route(ControlPathId.INPUT_LEXICON_APPLY, ControlMethod.POST, "/api/rime-lexicon/apply", "/control/v1/input/lexicon/apply", body={"reviewToken", "selectedKeys", "confirmText", "project", "limit"}, required_body={"reviewToken", "selectedKeys", "confirmText"}),
        _route(ControlPathId.INPUT_LEXICON_ROLLBACK, ControlMethod.POST, "/api/rime-lexicon/rollback", "/control/v1/input/lexicon/rollback", body={"rollbackId"}, required_body={"rollbackId"}),
        _route(ControlPathId.OBSERVABILITY_SNAPSHOT, ControlMethod.GET, "/api/observability/snapshot", "/control/v1/observability/snapshot", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"limit", "beforeSequence", *_OBSERVATION_FILTER_QUERY}),
        _route(ControlPathId.OBSERVABILITY_EVENTS, ControlMethod.GET, "/api/observability/events", "/control/v1/observability/events", scopes=[ControlScope.AGENT_READ], remote_safe=True, subscription=True, query={*_LAST_EVENT_QUERY, *_OBSERVATION_FILTER_QUERY}, required_query=_LAST_EVENT_QUERY),

        _route(ControlPathId.AGENT_RUNTIME_GET, ControlMethod.GET, "/api/agent/runtime", "/control/v1/agent/runtime", scopes=[ControlScope.AGENT_READ], remote_safe=True),
        _route(ControlPathId.AGENT_RUNTIME_ENSURE, ControlMethod.POST, "/api/agent/runtime/ensure", "/control/v1/agent/runtime/ensure", body={"sessionId"}, required_body={"sessionId"}),
        _route(ControlPathId.AGENT_PROVIDERS_GET, ControlMethod.GET, "/api/agent/providers", "/control/v1/agent/providers"),
        _route(ControlPathId.AGENT_PROVIDER_AUTH_PREVIEW, ControlMethod.POST, "/api/agent/providers/auth/preview", "/control/v1/agent/providers/auth/preview", body={"provider", "action"}, required_body={"provider", "action"}),
        _route(ControlPathId.AGENT_PROVIDER_AUTH_APPLY, ControlMethod.POST, "/api/agent/providers/auth/apply", "/control/v1/agent/providers/auth/apply", body={"previewToken", "confirmText", "apiKey"}, required_body={"previewToken", "confirmText"}),
        _route(ControlPathId.AGENT_PROVIDER_OAUTH_STATUS, ControlMethod.GET, "/api/agent/providers/oauth/status", "/control/v1/agent/providers/oauth/status", query={"loginId"}, required_query={"loginId"}),
        _route(ControlPathId.AGENT_PROVIDER_OAUTH_CANCEL, ControlMethod.POST, "/api/agent/providers/oauth/cancel", "/control/v1/agent/providers/oauth/cancel", body={"loginId"}, required_body={"loginId"}),
        _route(ControlPathId.AGENT_CONFIGURATION_GET, ControlMethod.GET, "/api/agent/configuration", "/control/v1/agent/configuration", scopes=[ControlScope.AGENT_READ], remote_safe=True),
        _route(ControlPathId.AGENT_CONFIGURATION_UPDATE, ControlMethod.POST, "/api/agent/configuration", "/control/v1/agent/configuration", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, body={"expectedRevision", "changes", "updatedBy"}, required_body={"expectedRevision", "changes"}, remote_body={"expectedRevision", "changes"}),
        _route(ControlPathId.AGENT_SESSIONS_LIST, ControlMethod.GET, "/api/agent/sessions", "/control/v1/agent/sessions", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"includeArchived", "includeInternal", "limit"}, remote_query={"includeArchived", "limit"}),
        _route(ControlPathId.AGENT_SESSIONS_CREATE, ControlMethod.POST, "/api/agent/sessions", "/control/v1/agent/sessions", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, body={"title", "mode", "roleId", "roleVersion", "modelProfile", "toolProfileVersion", "workspaceRoots"}, remote_body={"title", "mode", "roleId", "roleVersion", "modelProfile", "toolProfileVersion"}, remote_body_values={"mode": {"assistant"}}),
        _route(ControlPathId.AGENT_SESSION_SNAPSHOT, ControlMethod.GET, "/api/agent/sessions/{sessionId}/messages", "/control/v1/agent/sessions/{sessionId}/snapshot", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_RENAME, ControlMethod.PATCH, "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"title"}, required_body={"title"}, remote_body={"title"}),
        _route(ControlPathId.AGENT_SESSION_ARCHIVE, ControlMethod.PATCH, "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"archived"}, required_body={"archived"}, remote_body={"archived"}),
        _route(ControlPathId.AGENT_SESSION_MODE_UPDATE, ControlMethod.PATCH, "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", params=_SESSION, body={"mode", "workspaceRoots", "toolProfileVersion", "toolAllowlistMode", "allowedTools", "dangerousModeConfirmation"}, required_body={"mode"}),
        _route(ControlPathId.AGENT_SESSION_DELETE, ControlMethod.DELETE, "/api/agent/sessions/{sessionId}", "/control/v1/agent/sessions/{sessionId}", params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_PROMPT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/prompt", "/control/v1/agent/sessions/{sessionId}/prompt", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"message", "attachments", "clientMessageId"}, required_body={"message"}, remote_body={"message", "attachments", "clientMessageId"}, remote_required_body={"message", "clientMessageId"}),
        _route(ControlPathId.AGENT_SESSION_REWRITE, ControlMethod.POST, "/api/agent/sessions/{sessionId}/rewrite", "/control/v1/agent/sessions/{sessionId}/rewrite", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"entryId", "message", "attachments", "clientMessageId"}, required_body={"entryId", "message"}, remote_body={"entryId", "message", "attachments", "clientMessageId"}, remote_required_body={"entryId", "message", "clientMessageId"}),
        _route(ControlPathId.AGENT_SESSION_FORKS_LIST, ControlMethod.GET, "/api/agent/sessions/{sessionId}/forks", "/control/v1/agent/sessions/{sessionId}/forks", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_FORKS_CREATE, ControlMethod.POST, "/api/agent/sessions/{sessionId}/forks", "/control/v1/agent/sessions/{sessionId}/forks", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"entryId", "title"}, required_body={"entryId"}, remote_body={"entryId", "title"}),
        _route(ControlPathId.AGENT_SESSION_ABORT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/abort", "/control/v1/agent/sessions/{sessionId}/abort", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_REVIEW_RESOLVE, ControlMethod.POST, "/api/agent/sessions/{sessionId}/review", "/control/v1/agent/sessions/{sessionId}/review", params=_SESSION, body={"runId", "decision"}, required_body={"runId", "decision"}),
        _route(ControlPathId.AGENT_SESSION_COMPACT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/compact", "/control/v1/agent/sessions/{sessionId}/compact", params=_SESSION, body={"instructions"}),
        _route(ControlPathId.AGENT_SESSION_COMMANDS, ControlMethod.GET, "/api/agent/sessions/{sessionId}/commands", "/control/v1/agent/sessions/{sessionId}/commands", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_MODELS, ControlMethod.GET, "/api/agent/sessions/{sessionId}/models", "/control/v1/agent/sessions/{sessionId}/models", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION),
        _route(ControlPathId.AGENT_SESSION_MODEL_SELECT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/model", "/control/v1/agent/sessions/{sessionId}/model", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"provider", "modelId"}, required_body={"provider", "modelId"}, remote_body={"provider", "modelId"}),
        _route(ControlPathId.AGENT_SESSION_THINKING_SELECT, ControlMethod.POST, "/api/agent/sessions/{sessionId}/thinking", "/control/v1/agent/sessions/{sessionId}/thinking", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"level"}, required_body={"level"}, remote_body={"level"}),
        _route(ControlPathId.AGENT_SESSION_EVENTS, ControlMethod.GET, "/api/agent/sessions/{sessionId}/events", "/control/v1/agent/sessions/{sessionId}/events", scopes=[ControlScope.AGENT_READ], remote_safe=True, subscription=True, params=_SESSION, query=_LAST_EVENT_QUERY, required_query=_LAST_EVENT_QUERY),
        _route(ControlPathId.AGENT_SESSION_INTERCOM_LIST, ControlMethod.GET, "/api/agent/sessions/{sessionId}/intercom", "/control/v1/agent/sessions/{sessionId}/intercom", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION, query={"status", "limit"}),
        _route(ControlPathId.AGENT_SESSION_INTERCOM_SEND, ControlMethod.POST, "/api/agent/sessions/{sessionId}/intercom", "/control/v1/agent/sessions/{sessionId}/intercom", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_SESSION, body={"kind", "targetParticipantId", "clientMessageId", "replyTo", "content"}, required_body={"kind", "clientMessageId", "content"}, remote_body={"kind", "targetParticipantId", "clientMessageId", "replyTo", "content"}, remote_body_values={"kind": {"send", "ask", "reply"}}),
        _route(ControlPathId.AGENT_SESSION_CONTEXT_ITEMS_LIST, ControlMethod.GET, "/api/agent/sessions/{sessionId}/context-items", "/control/v1/agent/sessions/{sessionId}/context-items", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION, query={"status", "limit"}),
        _route(ControlPathId.AGENT_SESSION_CONTEXT_ITEM_ACK, ControlMethod.POST, "/api/agent/sessions/{sessionId}/context-items/{itemId}/ack", "/control/v1/agent/sessions/{sessionId}/context-items/{itemId}/ack", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_CONTEXT_ITEM),
        _route(ControlPathId.AGENT_SESSION_CONTEXT_TRACES_LIST, ControlMethod.GET, "/api/agent/sessions/{sessionId}/context-traces", "/control/v1/agent/sessions/{sessionId}/context-traces", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_SESSION, query={"limit"}),
        _route(ControlPathId.AGENT_SESSION_CONTEXT_TRACE_GET, ControlMethod.GET, "/api/agent/sessions/{sessionId}/context-traces/{traceId}", "/control/v1/agent/sessions/{sessionId}/context-traces/{traceId}", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_CONTEXT_TRACE),
        _route(ControlPathId.AGENT_SESSION_DEBUG_CONTEXT_GET, ControlMethod.GET, "/api/agent/sessions/{sessionId}/debug-context", None, params=_SESSION, query={"turnId"}),
        _route(ControlPathId.AGENT_ARTIFACT_GET, ControlMethod.GET, "/api/agent/artifacts/{artifactId}", "/control/v1/agent/artifacts/{artifactId}", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_ARTIFACT, query={"sessionId", "limit"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_MEDIA_LIST, ControlMethod.GET, "/api/agent/media", "/control/v1/agent/media", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"sessionId", "limit"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_DEEP_SEARCH, ControlMethod.POST, "/api/agent/deep-search", "/control/v1/agent/deep-search", body={"query", "privacyDisposition", "context", "frontAppBundleId", "contextSource", "evidence"}, required_body={"query", "privacyDisposition"}),

        _route(ControlPathId.AGENT_ROOMS_LIST, ControlMethod.GET, "/api/agent/rooms", "/control/v1/agent/rooms", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"includeArchived", "limit"}),
        _route(ControlPathId.AGENT_ROOMS_CREATE, ControlMethod.POST, "/api/agent/rooms", "/control/v1/agent/rooms", body={"title", "roomKind", "avatar", "description", "scenarioPrompt", "participants", "routingPolicy", "routingConfig", "moderatorRoleId", "workspaceRoots"}, required_body={"participants"}),
        _route(ControlPathId.AGENT_ROOM_GET, ControlMethod.GET, "/api/agent/rooms/{roomId}", "/control/v1/agent/rooms/{roomId}", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_ROOM),
        _route(ControlPathId.AGENT_ROOM_SNAPSHOT, ControlMethod.GET, "/api/agent/rooms/{roomId}/snapshot", "/control/v1/agent/rooms/{roomId}/snapshot", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_ROOM),
        _route(ControlPathId.AGENT_ROOM_ARCHIVE, ControlMethod.PATCH, "/api/agent/rooms/{roomId}", "/control/v1/agent/rooms/{roomId}", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_ROOM, body={"archived", "title", "roomKind", "avatar", "description", "scenarioPrompt", "routingPolicy", "routingConfig", "moderatorParticipantId"}, remote_body={"archived", "title", "roomKind", "avatar", "description", "scenarioPrompt", "routingPolicy", "routingConfig", "moderatorParticipantId"}),
        _route(ControlPathId.AGENT_ROOM_MESSAGE, ControlMethod.POST, "/api/agent/rooms/{roomId}/messages", "/control/v1/agent/rooms/{roomId}/messages", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_ROOM, body={"message", "clientMessageId", "participantIds"}, required_body={"message"}, remote_body={"message", "clientMessageId", "participantIds"}, remote_required_body={"message", "clientMessageId"}),
        _route(ControlPathId.AGENT_ROOM_EVENTS, ControlMethod.GET, "/api/agent/rooms/{roomId}/events", "/control/v1/agent/rooms/{roomId}/events", scopes=[ControlScope.AGENT_READ], remote_safe=True, subscription=True, params=_ROOM, query=_LAST_EVENT_QUERY, required_query=_LAST_EVENT_QUERY),
        _route(ControlPathId.AGENT_ROOM_TOPICS, ControlMethod.GET, "/api/agent/rooms/{roomId}/topics", "/control/v1/agent/rooms/{roomId}/topics", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_ROOM, query={"includeArchived"}),
        _route(ControlPathId.AGENT_ROOM_TOPIC_CREATE, ControlMethod.POST, "/api/agent/rooms/{roomId}/topics", "/control/v1/agent/rooms/{roomId}/topics", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_ROOM, body={"title", "summary"}, required_body={"title"}, remote_body={"title", "summary"}),
        _route(ControlPathId.AGENT_ROOM_TOPIC_UPDATE, ControlMethod.PATCH, "/api/agent/rooms/{roomId}/topics", "/control/v1/agent/rooms/{roomId}/topics", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_ROOM, body={"topicId", "title", "summary", "activate", "archived"}, required_body={"topicId"}, remote_body={"topicId", "title", "summary", "activate", "archived"}),
        _route(ControlPathId.AGENT_ROOM_ARTIFACTS, ControlMethod.GET, "/api/agent/rooms/{roomId}/artifacts", "/control/v1/agent/rooms/{roomId}/artifacts", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_ROOM, query={"includeArchived", "topicId", "limit"}),
        _route(ControlPathId.AGENT_ROOM_ARTIFACT_ADD, ControlMethod.POST, "/api/agent/rooms/{roomId}/artifacts", "/control/v1/agent/rooms/{roomId}/artifacts", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_ROOM, body={"path", "displayName", "topicId", "mediaType", "participantId"}, required_body={"path"}, remote_body={"path", "displayName", "topicId", "mediaType", "participantId"}),
        _route(ControlPathId.AGENT_ROOM_ARTIFACT_UPDATE, ControlMethod.PATCH, "/api/agent/rooms/{roomId}/artifacts", "/control/v1/agent/rooms/{roomId}/artifacts", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_ROOM, body={"artifactId", "archived"}, required_body={"artifactId", "archived"}, remote_body={"artifactId", "archived"}),
        _route(ControlPathId.AGENT_ROLES_LIST, ControlMethod.GET, "/api/agent/roles", "/control/v1/agent/roles", scopes=[ControlScope.AGENT_READ], remote_safe=True),
        _route(ControlPathId.AGENT_ROLES_CREATE, ControlMethod.POST, "/api/agent/roles", "/control/v1/agent/roles", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, body={"displayName", "tagline", "summary", "traits", "timelineModel", "selectableModes"}, required_body={"displayName", "tagline", "summary", "traits", "timelineModel", "selectableModes"}, remote_body={"displayName", "tagline", "summary", "traits", "timelineModel", "selectableModes"}, remote_body_values={"timelineModel": {"luna", "terra", "sol"}}),
        _route(ControlPathId.AGENT_ROLE_MODELS, ControlMethod.GET, "/api/agent/roles/models", "/control/v1/agent/roles/models", scopes=[ControlScope.AGENT_READ], remote_safe=True),
        _route(ControlPathId.AGENT_ROLE_RUNTIME_DEFAULTS_UPDATE, ControlMethod.POST, "/api/agent/roles/runtime-defaults", "/control/v1/agent/roles/runtime-defaults", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, body={"roleId", "roleVersion", "provider", "modelId", "thinkingLevel"}, required_body={"roleId", "roleVersion", "provider", "modelId", "thinkingLevel"}, remote_body={"roleId", "roleVersion", "provider", "modelId", "thinkingLevel"}, remote_body_values={"thinkingLevel": {"off", "minimal", "low", "medium", "high", "xhigh", "max"}}),
        _route(ControlPathId.AGENT_TOOLS_LIST, ControlMethod.GET, "/api/agent/tools", "/control/v1/agent/tools", query={"sessionId"}),
        _route(ControlPathId.AGENT_EXTENSIONS_LIST, ControlMethod.GET, "/api/agent/extensions", "/control/v1/agent/extensions"),
        _route(ControlPathId.AGENT_EXTENSIONS_CREATE, ControlMethod.POST, "/api/agent/extensions/drafts", "/control/v1/agent/extensions/drafts", body={"draftId", "manifest", "files"}, required_body={"draftId", "manifest", "files"}),
        _route(ControlPathId.AGENT_EXTENSIONS_PROPOSALS, ControlMethod.GET, "/api/agent/extensions/proposals", "/control/v1/agent/extensions/proposals"),
        _route(ControlPathId.AGENT_EXTENSIONS_VALIDATE, ControlMethod.POST, "/api/agent/extensions/validate", "/control/v1/agent/extensions/validate", body={"sourcePath"}, required_body={"sourcePath"}),
        _route(ControlPathId.AGENT_EXTENSIONS_PREVIEW, ControlMethod.POST, "/api/agent/extensions/preview", "/control/v1/agent/extensions/preview", body={"action", "validationToken", "pluginId", "enable"}, required_body={"action"}),
        _route(ControlPathId.AGENT_EXTENSIONS_APPLY, ControlMethod.POST, "/api/agent/extensions/apply", "/control/v1/agent/extensions/apply", body={"previewToken", "payloadSha256", "confirmText"}, required_body={"previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.AGENT_APPROVALS_LIST, ControlMethod.GET, "/api/agent/approvals", "/control/v1/agent/approvals", scopes=[ControlScope.AGENT_APPROVE], remote_safe=True, query={"sessionId", "state", "limit"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_APPROVAL_GET, ControlMethod.GET, "/api/agent/approvals/{approvalId}", "/control/v1/agent/approvals/{approvalId}", scopes=[ControlScope.AGENT_APPROVE], remote_safe=True, params=_APPROVAL),
        _route(ControlPathId.AGENT_APPROVAL_DECIDE, ControlMethod.POST, "/api/agent/approvals/{approvalId}/decision", "/control/v1/agent/approvals/{approvalId}/decision", scopes=[ControlScope.AGENT_APPROVE], remote_safe=True, params=_APPROVAL, body={"decision", "payloadSha256"}, required_body={"decision", "payloadSha256"}, remote_body={"decision", "payloadSha256"}, remote_body_values={"decision": {"approve", "reject"}}),
        _route(ControlPathId.AGENT_MEMORY_MAINTENANCE_RUN, ControlMethod.GET, "/api/agent/memory-maintenance", "/control/v1/agent/memory-maintenance", query={"runId", "project"}, required_query={"runId"}),
        _route(ControlPathId.AGENT_SUBAGENTS_TEMPLATES, ControlMethod.GET, "/api/agent/subagents/templates", "/control/v1/agent/subagents/templates", scopes=[ControlScope.AGENT_READ], remote_safe=True),
        _route(ControlPathId.AGENT_SUBAGENTS_LIST, ControlMethod.GET, "/api/agent/subagents/runs", "/control/v1/agent/subagents/runs", scopes=[ControlScope.AGENT_DELEGATE], remote_safe=True, query={"sessionId", "limit"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_SUBAGENTS_CREATE, ControlMethod.POST, "/api/agent/subagents/runs", "/control/v1/agent/subagents/runs", scopes=[ControlScope.AGENT_DELEGATE], remote_safe=True, body={"sessionId", "tasks", "agent", "version", "task", "contextMode", "wait"}, required_body={"sessionId"}, remote_body={"sessionId", "tasks", "agent", "version", "task", "contextMode", "wait"}, remote_body_values={"contextMode": {"fresh"}}),
        _route(ControlPathId.AGENT_SUBAGENT_GET, ControlMethod.GET, "/api/agent/subagents/runs/{runId}", "/control/v1/agent/subagents/runs/{runId}", scopes=[ControlScope.AGENT_DELEGATE], remote_safe=True, params=_RUN, query={"sessionId"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_SUBAGENT_ABORT, ControlMethod.POST, "/api/agent/subagents/runs/{runId}/abort", "/control/v1/agent/subagents/runs/{runId}/abort", scopes=[ControlScope.AGENT_DELEGATE], remote_safe=True, params=_RUN, body={"sessionId"}, required_body={"sessionId"}, remote_body={"sessionId"}),
        _route(ControlPathId.AGENT_MEMORY_SOURCES_LIST, ControlMethod.GET, "/api/agent/memory-sources", "/control/v1/agent/memory-sources", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"sessionId", "limit"}, required_query={"sessionId"}),
        _route(ControlPathId.AGENT_WAKE_SCHEDULES_LIST, ControlMethod.GET, "/api/agent/wake-schedules", "/control/v1/agent/wake-schedules", scopes=[ControlScope.AGENT_READ], remote_safe=True, query={"status", "targetType", "targetId", "createdBySessionId", "limit"}),
        _route(ControlPathId.AGENT_WAKE_SCHEDULES_CREATE, ControlMethod.POST, "/api/agent/wake-schedules", "/control/v1/agent/wake-schedules", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, body={"title", "instruction", "targetType", "targetSessionId", "targetRoleId", "targetRoleVersion", "wakeAtMs", "timezone", "recurrenceKind", "recurrenceInterval", "maxRuns", "planningTaskId", "confirmText"}, required_body={"instruction", "targetType", "wakeAtMs", "confirmText"}, remote_body={"title", "instruction", "targetType", "targetSessionId", "targetRoleId", "targetRoleVersion", "wakeAtMs", "timezone", "recurrenceKind", "recurrenceInterval", "maxRuns", "planningTaskId", "confirmText"}, remote_body_values={"targetType": {"session", "role"}, "recurrenceKind": {"once", "daily", "weekly"}, "confirmText": {"schedule"}}),
        _route(ControlPathId.AGENT_WAKE_SCHEDULE_RUNS, ControlMethod.GET, "/api/agent/wake-schedules/{scheduleId}/runs", "/control/v1/agent/wake-schedules/{scheduleId}/runs", scopes=[ControlScope.AGENT_READ], remote_safe=True, params=_WAKE_SCHEDULE, query={"limit"}),
        _route(ControlPathId.AGENT_WAKE_SCHEDULE_ACTION, ControlMethod.POST, "/api/agent/wake-schedules/{scheduleId}/action", "/control/v1/agent/wake-schedules/{scheduleId}/action", scopes=[ControlScope.AGENT_WRITE], remote_safe=True, params=_WAKE_SCHEDULE, body={"action", "confirmText"}, required_body={"action", "confirmText"}, remote_body={"action", "confirmText"}, remote_body_values={"action": {"pause", "resume", "cancel", "retry"}, "confirmText": {"apply"}}),

        _route(ControlPathId.BROWSER_STATUS, ControlMethod.GET, "/api/browser/status", "/control/v1/browser/status"),
        _route(ControlPathId.BROWSER_PAIRING, ControlMethod.GET, "/api/browser/pairing", "/control/v1/browser/pairing"),
        _route(ControlPathId.BROWSER_TABS, ControlMethod.GET, "/api/browser/tabs", "/control/v1/browser/tabs"),
        _route(ControlPathId.BROWSER_SNAPSHOT_LATEST, ControlMethod.GET, "/api/browser/snapshots/latest", "/control/v1/browser/snapshots/latest", query={"deviceId", "tabId", "includeMarkdown"}),
        _route(ControlPathId.BROWSER_SNAPSHOT_IMAGE, ControlMethod.GET, "/api/browser/snapshots/{snapshotId}/image", "/control/v1/browser/snapshots/{snapshotId}/image", params=_BROWSER_SNAPSHOT, binary=True),
        _route(ControlPathId.BROWSER_TRACES, ControlMethod.GET, "/api/browser/traces", "/control/v1/browser/traces", query={"limit"}),
        _route(ControlPathId.BROWSER_PERMISSIONS, ControlMethod.GET, "/api/browser/permissions", "/control/v1/browser/permissions", query={"limit"}),
        _route(ControlPathId.BROWSER_PERMISSION_GET, ControlMethod.GET, "/api/browser/permissions/{promptId}", "/control/v1/browser/permissions/{promptId}", params=_BROWSER_PERMISSION),
        _route(ControlPathId.BROWSER_PERMISSION_DECIDE, ControlMethod.POST, "/api/browser/permissions/{promptId}/decision", "/control/v1/browser/permissions/{promptId}/decision", params=_BROWSER_PERMISSION, body={"decision"}, required_body={"decision"}),
        _route(ControlPathId.BROWSER_MODE_UPDATE, ControlMethod.POST, "/api/browser/mode", "/control/v1/browser/mode", body={"mode"}, required_body={"mode"}),
        _route(ControlPathId.BROWSER_PAIRING_ROTATE, ControlMethod.POST, "/api/browser/pairing/rotate", "/control/v1/browser/pairing/rotate"),
        _route(ControlPathId.BROWSER_COMMAND, ControlMethod.POST, "/api/browser/command", "/control/v1/browser/command", body={"action", "deviceId", "tabId", "refId", "url", "text", "clear", "direction", "amount", "timeoutMs", "timeoutSeconds"}, required_body={"action"}),
        _route(ControlPathId.BROWSER_STOP, ControlMethod.POST, "/api/browser/stop", "/control/v1/browser/stop"),
        _route(ControlPathId.BROWSER_MANAGED_START, ControlMethod.POST, "/api/browser/managed/start", "/control/v1/browser/managed/start"),
        _route(ControlPathId.BROWSER_MANAGED_STOP, ControlMethod.POST, "/api/browser/managed/stop", "/control/v1/browser/managed/stop"),

        _route(ControlPathId.PLANNING_DASHBOARD, ControlMethod.GET, "/api/planning/dashboard", "/control/v1/planning/dashboard", scopes=[ControlScope.PLANNING_READ], remote_safe=True, query={"date", "project"}),
        _route(ControlPathId.PLANNING_MUTATION_PREVIEW, ControlMethod.POST, "/api/planning/mutation/preview", "/control/v1/planning/mutation/preview", body={"kind", "payload", "expectedRuntimeRevision"}, required_body={"kind", "payload", "expectedRuntimeRevision"}),
        _route(ControlPathId.PLANNING_TASK_SAVE, ControlMethod.POST, "/api/planning/task/save", "/control/v1/planning/task/save", body={"taskId", "date", "title", "detail", "priority", "status", "dueAtMs", "goalId", "project", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}, required_body={"date", "title", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.PLANNING_GOAL_SAVE, ControlMethod.POST, "/api/planning/goal/save", "/control/v1/planning/goal/save", body={"goalId", "title", "detail", "horizon", "status", "priority", "targetDate", "project", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}, required_body={"title", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.PLANNING_TASK_ACTION, ControlMethod.POST, "/api/planning/task/action", "/control/v1/planning/task/action", body={"taskId", "action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}, required_body={"taskId", "action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.PLANNING_TASK_EVENT_UNDO, ControlMethod.POST, "/api/planning/task-event/undo", "/control/v1/planning/task-event/undo", body={"eventId", "receiptId", "rollbackToken", "payloadSha256", "confirmText"}, required_body={"eventId", "receiptId", "rollbackToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.PLANNING_MUTATION_ROLLBACK, ControlMethod.POST, "/api/planning/mutation/rollback", "/control/v1/planning/mutation/rollback", body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}, required_body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.MEMORY_SUMMARY, ControlMethod.GET, "/api/memory/summary", "/control/v1/memory/summary", scopes=[ControlScope.MEMORY_READ], remote_safe=True),
        _route(ControlPathId.MEMORY_PAGES, ControlMethod.GET, "/api/memory/{kind}", "/control/v1/memory/{kind}", scopes=[ControlScope.MEMORY_READ], remote_safe=True, params={"kind"}, param_values={"kind": {"books", "atoms", "tags", "phrases", "evidence", "groups", "negative"}}, query=_PAGE_QUERY),
        _route(ControlPathId.MEMORY_GRAPH_GET, ControlMethod.GET, "/api/memory/graph", "/control/v1/memory/graph", scopes=[ControlScope.MEMORY_READ], remote_safe=True, query={"plane", "project", "status", "query", "focusId", "depth", "nodeLimit", "edgeLimit", "minWeight"}, required_query={"plane"}),
        _route(ControlPathId.MEMORY_ENTITY_GET, ControlMethod.GET, "/api/memory/entities/{kind}/{entityId}", "/control/v1/memory/entities/{kind}/{entityId}", scopes=[ControlScope.MEMORY_READ], remote_safe=True, params={"kind", "entityId"}, param_values={"kind": {"tag", "group", "book"}}, query={"project", "connectionsLimit", "connectionsCursor", "membersLimit", "membersCursor"}),
        _route(ControlPathId.MEMORY_EDIT, ControlMethod.POST, "/api/memory/edit", "/control/v1/memory/edit", body={"kind", "id", "title", "text", "summary", "note", "description", "tags", "aliases", "type", "color", "reason", "active"}, required_body={"kind", "id"}),
        _route(ControlPathId.MEMORY_SOURCE_DISPOSITION, ControlMethod.POST, "/api/memory/source/disposition", "/control/v1/memory/source/disposition", body={"sourceId", "disposition"}, required_body={"sourceId", "disposition"}),
        _route(ControlPathId.MEMORY_BOOK_ARCHIVE_PREVIEW, ControlMethod.POST, "/api/memory/book/archive/preview", "/control/v1/memory/book/archive/preview", body={"bookId", "archived", "reason", "expectedRuntimeRevision"}, required_body={"bookId", "archived", "expectedRuntimeRevision"}),
        _route(ControlPathId.MEMORY_BOOK_ARCHIVE_APPLY, ControlMethod.POST, "/api/memory/book/archive/apply", "/control/v1/memory/book/archive/apply", body={"bookId", "archived", "reason", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}, required_body={"bookId", "archived", "reason", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.MEMORY_BOOK_ARCHIVE_ROLLBACK, ControlMethod.POST, "/api/memory/book/archive/rollback", "/control/v1/memory/book/archive/rollback", body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}, required_body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.HISTORY_PAGE, ControlMethod.GET, "/api/history/page", "/control/v1/history/page", scopes=[ControlScope.HISTORY_READ], remote_safe=True, query={"limit", "cursor", "query", "filter"}),
        _route(ControlPathId.HISTORY_DETAIL, ControlMethod.GET, "/api/history/detail", "/control/v1/history/detail", scopes=[ControlScope.HISTORY_READ], remote_safe=True, query={"eventId"}, required_query={"eventId"}),
        _route(ControlPathId.HISTORY_TOMBSTONE_PREVIEW, ControlMethod.POST, "/api/history/tombstone/preview", "/control/v1/history/tombstone/preview", body={"eventId", "reason", "expectedRuntimeRevision"}, required_body={"eventId", "expectedRuntimeRevision"}),
        _route(ControlPathId.HISTORY_TOMBSTONE_APPLY, ControlMethod.POST, "/api/history/tombstone/apply", "/control/v1/history/tombstone/apply", body={"eventId", "reason", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}, required_body={"eventId", "reason", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.HISTORY_TOMBSTONE_ROLLBACK, ControlMethod.POST, "/api/history/tombstone/rollback", "/control/v1/history/tombstone/rollback", body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}, required_body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.KNOWLEDGE_START, ControlMethod.POST, "/api/knowledge/start", "/control/v1/knowledge/start", body={"question", "context", "mode", "includeNotion", "generation", "contextHash", "clientId", "project", "app", "maxChars", "latencyBudgetMs"}, required_body={"question"}),
        _route(ControlPathId.KNOWLEDGE_CANCEL, ControlMethod.POST, "/api/knowledge/cancel", "/control/v1/knowledge/cancel", body={"sessionId", "id"}),
        _route(ControlPathId.KNOWLEDGE_STATUS, ControlMethod.GET, "/api/knowledge/status", "/control/v1/knowledge/status", scopes=[ControlScope.KNOWLEDGE_READ], remote_safe=True, query={"sessionId", "id"}),
        _route(ControlPathId.KNOWLEDGE_ROUTE_STATUS, ControlMethod.GET, "/api/knowledge/route-status", "/control/v1/knowledge/route-status", scopes=[ControlScope.KNOWLEDGE_READ], remote_safe=True),
        _route(ControlPathId.KNOWLEDGE_DATABASE_APPLY_PREVIEW, ControlMethod.POST, "/api/knowledge/database/apply-preview", "/control/v1/knowledge/database/apply-preview", body={"runId", "expectedRuntimeRevision"}, required_body={"runId"}),
        _route(ControlPathId.KNOWLEDGE_DATABASE_DRAFT_EDIT, ControlMethod.POST, "/api/knowledge/database/draft-edit", "/control/v1/knowledge/database/draft-edit", body={"runId", "diffId", "selected", "payload"}, required_body={"runId", "diffId", "selected"}),
        _route(ControlPathId.KNOWLEDGE_DATABASE_APPLY, ControlMethod.POST, "/api/knowledge/database/apply", "/control/v1/knowledge/database/apply", body={"runId", "confirm", "previewToken", "payloadSha256", "expectedRuntimeRevision"}, required_body={"runId", "confirm", "previewToken", "payloadSha256", "expectedRuntimeRevision"}),
        _route(ControlPathId.KNOWLEDGE_DATABASE_ROLLBACK, ControlMethod.POST, "/api/knowledge/database/rollback", "/control/v1/knowledge/database/rollback", body={"runId", "confirm", "receiptId", "rollbackToken", "payloadSha256"}, required_body={"runId", "confirm", "receiptId", "rollbackToken", "payloadSha256"}),

        # Document knowledge is a separate local data plane. Management routes
        # deliberately have no 8768 target; Agents read through ime_knowledge.
        _route(ControlPathId.KNOWLEDGE_BASES_LIST, ControlMethod.GET, "/api/knowledge-bases", None, query={"limit", "cursor", "query", "status"}),
        _route(ControlPathId.KNOWLEDGE_BASES_CREATE, ControlMethod.POST, "/api/knowledge-bases", None, body={"name", "description", "agentEnabled", "parserProvider", "chunkingConfig", "retrievalConfig"}, required_body={"name"}),
        _route(ControlPathId.KNOWLEDGE_BASES_GET, ControlMethod.GET, "/api/knowledge-bases/{kbId}", None, params=_KNOWLEDGE_BASE),
        _route(ControlPathId.KNOWLEDGE_BASES_UPDATE, ControlMethod.PATCH, "/api/knowledge-bases/{kbId}", None, params=_KNOWLEDGE_BASE, body={"name", "description", "agentEnabled", "parserProvider", "chunkingConfig", "retrievalConfig", "expectedRevision"}, required_body={"expectedRevision"}),
        _route(ControlPathId.KNOWLEDGE_BASES_DELETE_PREVIEW, ControlMethod.POST, "/api/knowledge-bases/{kbId}/delete/preview", None, params=_KNOWLEDGE_BASE, body={"expectedRevision"}, required_body={"expectedRevision"}),
        _route(ControlPathId.KNOWLEDGE_BASES_DELETE_APPLY, ControlMethod.POST, "/api/knowledge-bases/{kbId}/delete/apply", None, params=_KNOWLEDGE_BASE, body={"expectedRevision", "previewToken", "payloadSha256", "confirmText"}, required_body={"expectedRevision", "previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.KNOWLEDGE_BASES_DOCUMENTS_LIST, ControlMethod.GET, "/api/knowledge-bases/{kbId}/documents", None, params=_KNOWLEDGE_BASE, query={"limit", "cursor", "query", "status"}),
        _route(ControlPathId.KNOWLEDGE_BASES_DOCUMENT_IMPORT, ControlMethod.POST, "/api/knowledge-bases/{kbId}/documents/import", None, params=_KNOWLEDGE_BASE, query={"fileName", "mimeType", "parserProvider"}, required_query={"fileName", "mimeType"}),
        _route(ControlPathId.KNOWLEDGE_BASES_DOCUMENT_RETRY, ControlMethod.POST, "/api/knowledge-bases/{kbId}/documents/{fileId}/retry", None, params=_KNOWLEDGE_DOCUMENT, body={"stage", "parserProvider", "expectedRevision"}, required_body={"stage", "expectedRevision"}),
        _route(ControlPathId.KNOWLEDGE_BASES_DOCUMENT_DELETE, ControlMethod.DELETE, "/api/knowledge-bases/{kbId}/documents/{fileId}", None, params=_KNOWLEDGE_DOCUMENT),
        _route(ControlPathId.KNOWLEDGE_BASES_DOCUMENT_GET, ControlMethod.GET, "/api/knowledge-bases/{kbId}/documents/{fileId}", None, params=_KNOWLEDGE_DOCUMENT, query={"offset", "limit", "lineOffset", "lineLimit"}),
        _route(ControlPathId.KNOWLEDGE_BASES_DOCUMENT_SOURCE, ControlMethod.GET, "/api/knowledge-bases/{kbId}/documents/{fileId}/source", None, params=_KNOWLEDGE_DOCUMENT, binary=True),
        _route(ControlPathId.KNOWLEDGE_BASES_ASSET_GET, ControlMethod.GET, "/api/knowledge-bases/{kbId}/documents/{fileId}/assets/{assetId}", None, params=_KNOWLEDGE_ASSET, binary=True),
        _route(ControlPathId.KNOWLEDGE_BASES_JOBS_LIST, ControlMethod.GET, "/api/knowledge-bases/{kbId}/jobs", None, params=_KNOWLEDGE_BASE, query={"limit", "cursor", "status"}),
        _route(ControlPathId.KNOWLEDGE_BASES_JOB_CANCEL, ControlMethod.POST, "/api/knowledge-bases/{kbId}/jobs/{jobId}/cancel", None, params=_KNOWLEDGE_JOB, body=set()),
        _route(ControlPathId.KNOWLEDGE_BASES_CHUNK_PREVIEW, ControlMethod.POST, "/api/knowledge-bases/{kbId}/documents/{fileId}/chunk-preview", None, params=_KNOWLEDGE_DOCUMENT, body={"chunkingConfig", "limit"}, required_body={"chunkingConfig"}),
        _route(ControlPathId.KNOWLEDGE_BASES_SEARCH, ControlMethod.POST, "/api/knowledge-bases/{kbId}/search", None, params=_KNOWLEDGE_BASE, body={"query", "topK", "mode", "threshold", "fileIds", "fileName"}, required_body={"query"}),
        _route(ControlPathId.KNOWLEDGE_BASES_FIND, ControlMethod.POST, "/api/knowledge-bases/{kbId}/documents/{fileId}/find", None, params=_KNOWLEDGE_DOCUMENT, body={"query", "regex", "lineWindow"}, required_body={"query"}),
        _route(ControlPathId.KNOWLEDGE_BASES_OPEN, ControlMethod.GET, "/api/knowledge-bases/{kbId}/documents/{fileId}/content", None, params=_KNOWLEDGE_DOCUMENT, query={"chunkId", "page", "startLine", "lines"}),
        _route(ControlPathId.KNOWLEDGE_BASES_GRAPH_GET, ControlMethod.GET, "/api/knowledge-bases/{kbId}/graph", None, params=_KNOWLEDGE_BASE, query={"documentId", "query", "kinds", "limit", "depth", "excludeChunks", "focusId"}),
        _route(ControlPathId.KNOWLEDGE_BASES_GRAPH_REBUILD, ControlMethod.POST, "/api/knowledge-bases/{kbId}/graph/rebuild", None, params=_KNOWLEDGE_BASE, body={"expectedRevision", "documentIds", "extractorMode", "modelId", "batchSize", "extractionConcurrency", "maxEntitiesPerChunk", "maxRelationsPerChunk", "maxTopicsPerChunk"}, required_body={"expectedRevision"}),
        _route(ControlPathId.KNOWLEDGE_BASES_REINDEX_PREVIEW, ControlMethod.GET, "/api/knowledge-bases/{kbId}/reindex-preview", None, params=_KNOWLEDGE_BASE),
        _route(ControlPathId.KNOWLEDGE_BASES_REBUILD, ControlMethod.POST, "/api/knowledge-bases/{kbId}/rebuild", None, params=_KNOWLEDGE_BASE, body={"previewToken", "payloadSha256", "expectedRevision", "confirmText"}, required_body={"previewToken", "payloadSha256", "expectedRevision", "confirmText"}),
        _route(ControlPathId.KNOWLEDGE_WORKER_HEALTH, ControlMethod.GET, "/api/knowledge-bases/health", None),
        _route(ControlPathId.KNOWLEDGE_PARSERS_LIST, ControlMethod.GET, "/api/knowledge-bases/parsers", None),
        _route(ControlPathId.DIAGNOSTICS_RUNTIME, ControlMethod.GET, "/api/runtime/status", "/control/v1/diagnostics/runtime", scopes=[ControlScope.DIAGNOSTICS_READ], remote_safe=True),
        _route(ControlPathId.DIAGNOSTICS_PREDICTOR, ControlMethod.GET, "/api/predictor/status", "/control/v1/diagnostics/predictor", scopes=[ControlScope.DIAGNOSTICS_READ], remote_safe=True),
        _route(ControlPathId.DIAGNOSTICS_MODELS, ControlMethod.GET, "/api/models/status", "/control/v1/diagnostics/models", scopes=[ControlScope.DIAGNOSTICS_READ], remote_safe=True),
        _route(ControlPathId.DIAGNOSTICS_ACTION_PREVIEW, ControlMethod.POST, "/api/runtime/action/preview", None, body={"action", "expectedRuntimeRevision"}, required_body={"action", "expectedRuntimeRevision"}),
        _route(ControlPathId.DIAGNOSTICS_ACTION_START, ControlMethod.POST, "/api/runtime/action/start", None, body={"action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "commandSha256", "confirmText"}, required_body={"action", "expectedRuntimeRevision", "previewToken", "payloadSha256", "commandSha256", "confirmText"}),
        _route(ControlPathId.DIAGNOSTICS_ACTION_JOB, ControlMethod.GET, "/api/runtime/job/{jobId}", None, params=frozenset({"jobId"})),
        _route(ControlPathId.CONFIGURATION_SETTINGS, ControlMethod.GET, "/api/settings", "/control/v1/configuration/settings", scopes=[ControlScope.CONFIGURATION_READ], remote_safe=True),
        _route(ControlPathId.CONFIGURATION_SCHEMA, ControlMethod.GET, "/api/settings/schema", "/control/v1/configuration/schema", scopes=[ControlScope.CONFIGURATION_READ], remote_safe=True),
        _route(ControlPathId.CONFIGURATION_SETTINGS_PREVIEW, ControlMethod.POST, "/api/settings/preview", "/control/v1/configuration/settings/preview", body={"changes", "expectedRuntimeRevision"}, required_body={"changes", "expectedRuntimeRevision"}),
        _route(ControlPathId.CONFIGURATION_SETTINGS_APPLY, ControlMethod.POST, "/api/settings/apply", "/control/v1/configuration/settings/apply", body={"changes", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}, required_body={"changes", "expectedRuntimeRevision", "previewToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.CONFIGURATION_SETTINGS_ROLLBACK, ControlMethod.POST, "/api/settings/rollback", "/control/v1/configuration/settings/rollback", body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}, required_body={"receiptId", "rollbackToken", "payloadSha256", "confirmText"}),
        _route(ControlPathId.CONFIGURATION_IMPORT_PREVIEW, ControlMethod.POST, "/api/configuration/import-preview", None, body={"path"}, required_body={"path"}),
        _route(ControlPathId.CONFIGURATION_IMPORT_APPLY, ControlMethod.POST, "/api/configuration/import-apply", None, body={"path", "expectedRuntimeRevision", "previewToken", "confirmText", "confirmRemoteModel"}, required_body={"path", "expectedRuntimeRevision", "previewToken", "confirmText"}),
        _route(ControlPathId.CONFIGURATION_BACKUP_EXPORT, ControlMethod.POST, "/api/configuration/backup-export", None, body={"destination"}, required_body={"destination"}),
        _route(ControlPathId.CONFIGURATION_RESTORE_PREVIEW, ControlMethod.POST, "/api/configuration/restore-preview", None, body={"path"}, required_body={"path"}),
        _route(ControlPathId.CONFIGURATION_RESTORE_APPLY, ControlMethod.POST, "/api/configuration/restore-apply", None, body={"path", "restoreToken", "confirmText", "expectedRuntimeRevision"}, required_body={"path", "restoreToken", "confirmText", "expectedRuntimeRevision"}),
    ]
    return ControlRoutePolicy(routes)


def route_manifest(*, include_targets: bool = True) -> list[dict[str, object]]:
    """Return the canonical pathId manifest for TS/Swift mirror generation."""

    return default_route_policy().manifest(include_targets=include_targets)


_FACADE_HTTP_PATHS = {
    ControlPathId.CONTROL_BOOTSTRAP: "/api/agent/control/bootstrap",
    ControlPathId.CONTROL_CAPABILITIES: "/api/agent/control/capabilities",
}


def _compile_target_template(target: str) -> re.Pattern[str]:
    offset = 0
    chunks = ["^"]
    for match in _TEMPLATE_PARAMETER_PATTERN.finditer(target):
        chunks.append(re.escape(target[offset : match.start()]))
        chunks.append(f"(?P<{match.group(1)}>[^/]+)")
        offset = match.end()
    chunks.append(re.escape(target[offset:]))
    chunks.append("$")
    return re.compile("".join(chunks))


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
