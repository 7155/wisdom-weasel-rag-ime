from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .agent_roles import PersonaManifest
from .agent_execution_policy import (
    FULL_TRUST_EXECUTION_MODE,
    PER_ACTION_EXECUTION_MODE,
    WORKSPACE_MANAGED_EXECUTION_MODE,
    WORKSPACE_SCOPE_CONFIRMATION,
    canonical_tool_profile,
    normalize_execution_mode,
)
from .agent_tool_ids import (
    CONTROL_CENTER_TOOL_PROFILE,
    DANGEROUS_MODE_CONFIRMATION,
    READONLY_TOOL_PROFILE,
)


class AgentSessionApplicationService:
    """Own Session lifecycle, runtime policy, and model selection."""

    def __init__(
        self,
        *,
        sessions: Any,
        runtime_provider: Callable[[], Any],
        runtime_factory: Any,
        personas: Any,
        role_books: Any,
        configuration_store: Any,
        rooms: Any,
        delegation: Any,
        media: Any,
        events: Any,
        runtime_status: Callable[[], Mapping[str, object]],
        initial_role_runtime_defaults: Callable[..., Mapping[str, str]],
        pending_memory_bootstrap: Callable[[Mapping[str, object]], Mapping[str, object]],
        ensure_session_role_book: Callable[[str], Mapping[str, object]],
        probe_memory_maintenance: Callable[..., Mapping[str, object]],
    ) -> None:
        self.sessions = sessions
        self._runtime_provider = runtime_provider
        self.runtime_factory = runtime_factory
        self.personas = personas
        self.role_books = role_books
        self.configuration_store = configuration_store
        self.rooms = rooms
        self.delegation = delegation
        self.media = media
        self.events = events
        self.runtime_status = runtime_status
        self.initial_role_runtime_defaults = initial_role_runtime_defaults
        self.pending_memory_bootstrap = pending_memory_bootstrap
        self.ensure_session_role_book = ensure_session_role_book
        self.probe_memory_maintenance = probe_memory_maintenance

    @property
    def runtime(self) -> Any:
        return self._runtime_provider()

    def ensure_runtime(self, payload: Mapping[str, object]) -> dict[str, object]:
        session_id = _required_text(payload, "sessionId")
        self.ensure_session_role_book(session_id)
        result = self.runtime.ensure(session_id)
        maintenance = self.probe_memory_maintenance(
            session_id,
            trigger="session_switch",
        )
        return {
            "schemaVersion": "rag-ime.agent-runtime-ensure.v1",
            "ok": True,
            "runtime": dict(self.runtime_status()),
            "memoryMaintenance": maintenance,
            **result,
        }

    def list_sessions(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        value = dict(payload or {})
        sessions = self.sessions.list(
            include_archived=_bool(value.get("includeArchived")),
            include_internal=_bool(value.get("includeInternal")),
            limit=_integer(
                value.get("limit"),
                default=100,
                minimum=1,
                maximum=500,
            ),
        )
        return {
            "schemaVersion": "rag-ime.agent-session-list.v1",
            "ok": True,
            "items": sessions,
            "activeSessionId": self.runtime_status().get("activeSessionId"),
        }

    def create_session(self, payload: Mapping[str, object]) -> dict[str, object]:
        title = str(payload.get("title") or "新对话")
        mode = str(payload.get("mode") or "assistant")
        configuration = self.configuration_store.snapshot()["configuration"]
        session_defaults = configuration["sessionDefaults"]
        role = self.personas.resolve_active(
            payload.get("roleId") or session_defaults["roleId"],
            payload.get("roleVersion") or session_defaults["roleVersion"],
        )
        if mode not in role.selectable_modes:
            raise ValueError(
                f"agent role {role.role_id}@{role.version} "
                f"is not available for {mode} sessions"
            )
        requested_tool_profile = str(
            payload.get("toolProfileVersion")
            or session_defaults["toolProfileVersion"]
            or role.defaults.tool_profile_version
        )
        requested_execution_mode = normalize_execution_mode(
            payload.get("executionMode"),
            tool_profile_version=requested_tool_profile,
            default=PER_ACTION_EXECUTION_MODE,
        )
        requested_tool_profile = canonical_tool_profile(
            requested_tool_profile,
            execution_mode=requested_execution_mode,
        )
        if requested_tool_profile not in {
            CONTROL_CENTER_TOOL_PROFILE,
            READONLY_TOOL_PROFILE,
        }:
            raise ValueError(
                "new conversations must start in a controlled or read-only tool profile"
            )
        if role.origin == "user":
            if (
                payload.get("toolProfileVersion") is not None
                and requested_tool_profile != role.defaults.tool_profile_version
            ):
                raise ValueError("user persona tool policy cannot be overridden")
            requested_tool_profile = role.defaults.tool_profile_version
        roots_value = payload.get("workspaceRoots")
        if roots_value is None:
            workspace_roots: list[str] = []
        elif isinstance(roots_value, list):
            workspace_roots = [str(item) for item in roots_value]
        else:
            raise ValueError("workspaceRoots must be an array")
        internal_scope_grant = payload.get("_internalWorkspaceScopeGrant") is True
        if requested_execution_mode == WORKSPACE_MANAGED_EXECUTION_MODE and not (
            internal_scope_grant
            or str(payload.get("workspaceScopeConfirmation") or "")
            == WORKSPACE_SCOPE_CONFIRMATION
        ):
            raise ValueError(
                "workspace-managed execution requires an explicit workspace scope confirmation"
            )
        if requested_execution_mode == FULL_TRUST_EXECUTION_MODE and not (
            internal_scope_grant
            or str(payload.get("dangerousModeConfirmation") or "")
            == DANGEROUS_MODE_CONFIRMATION
        ):
            raise ValueError(
                "full-trust execution requires an explicit native confirmation"
            )
        role_runtime_defaults = self.personas.runtime_defaults(
            role.role_id,
            role.version,
        ) or self.initial_role_runtime_defaults(
            role,
            default_model_profile=str(session_defaults["modelProfile"]),
        )
        model_profile, thinking_level = self._session_model_defaults(
            role,
            payload=payload,
            session_defaults=session_defaults,
            role_runtime_defaults=role_runtime_defaults,
        )
        role_book_revision_id, role_book_status = self._seed_role_book(role)
        session = self.sessions.create(
            title=title,
            mode=mode,
            role_id=role.role_id,
            role_version=role.version,
            role_book_revision_id=role_book_revision_id,
            model_profile=model_profile,
            thinking_level=thinking_level,
            tool_profile_version=requested_tool_profile,
            execution_mode=requested_execution_mode,
            workspace_roots=workspace_roots,
        )
        return {
            "schemaVersion": "rag-ime.agent-session-create.v1",
            "ok": True,
            "session": session,
            "roleBook": role_book_status,
            "memoryBootstrap": self.pending_memory_bootstrap(session),
        }

    def delete_session(self, session_id: str) -> dict[str, object]:
        if self.rooms.participant_for_session(
            session_id,
            active_only=False,
        ) is not None:
            raise ValueError(
                "room participant sessions cannot be deleted directly"
            )
        if self.delegation.owns_session(session_id):
            raise ValueError("subagent sessions cannot be deleted directly")
        runtime = self.runtime_status()
        if (
            runtime.get("activeSessionId") == session_id
            or session_id
            in {
                str(value)
                for value in runtime.get("openSessionIds") or []
            }
        ):
            self.runtime.stop()
        media_files_deleted = self.media.delete_session_files(session_id)
        runtime_binding = self.sessions.runtime_binding(session_id)
        session = self.sessions.delete(session_id)
        session_file = ""
        if (
            isinstance(runtime_binding, Mapping)
            and runtime_binding.get("driverId") == "managed-pi"
            and runtime_binding.get("runtimeKind") == "pi_rpc"
        ):
            session_file = str(runtime_binding.get("transcriptRef") or "")
        if not session_file:
            session_file = str(session.get("sessionFile") or "")
        deleted_file = self._delete_owned_transcript(session_file)
        return {
            "schemaVersion": "rag-ime.agent-session-delete.v1",
            "ok": True,
            "sessionId": session_id,
            "sessionFileDeleted": deleted_file,
            "mediaFilesDeleted": media_files_deleted,
        }

    def _session_model_defaults(
        self,
        role: PersonaManifest,
        *,
        payload: Mapping[str, object],
        session_defaults: Mapping[str, object],
        role_runtime_defaults: Mapping[str, str] | None,
    ) -> tuple[str, str]:
        requested_model_profile = payload.get("modelProfile")
        if (
            role.defaults.model_policy == "fixed"
            and payload.get("_internalModelOverride") is not True
        ):
            effective = role_runtime_defaults or {
                "modelProfile": role.defaults.model_profile,
                "thinkingLevel": role.defaults.thinking_level,
            }
            if (
                requested_model_profile is not None
                and str(requested_model_profile)
                != str(effective["modelProfile"])
            ):
                raise ValueError(
                    "builtin persona model cannot be overridden"
                )
            return (
                str(effective["modelProfile"]),
                str(effective.get("thinkingLevel", "")),
            )
        if requested_model_profile is not None:
            return str(requested_model_profile), ""
        if role_runtime_defaults is not None:
            return (
                str(role_runtime_defaults["modelProfile"]),
                str(role_runtime_defaults.get("thinkingLevel", "")),
            )
        return str(session_defaults["modelProfile"]), ""

    def _seed_role_book(
        self,
        role: PersonaManifest,
    ) -> tuple[str, dict[str, object]]:
        try:
            revision_id = str(
                self.role_books.ensure_seeded(
                    role.role_id,
                    role.version,
                    role.display_name,
                    role.summary,
                    role.version,
                )["revisionId"]
            )
        except Exception as exc:
            return "", {
                "ok": False,
                "status": "base_persona_fallback",
                "revisionId": "",
                "error": _public_error(exc),
            }
        return revision_id, {
            "ok": True,
            "status": "pinned",
            "revisionId": revision_id,
        }

    def _delete_owned_transcript(self, session_file: str) -> bool:
        if not session_file:
            return False
        path = Path(session_file).expanduser().resolve(strict=False)
        root = (
            self.runtime_factory.session_root
            .expanduser()
            .resolve(strict=False)
        )
        if (
            _is_within(path, root)
            and path.is_file()
            and not path.is_symlink()
        ):
            path.unlink()
            return True
        return False


def _required_text(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = " ".join(str(payload.get(key) or "").split())
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value


def _public_error(error: BaseException) -> str:
    return compact_error(str(error))


def compact_error(value: str) -> str:
    return " ".join(str(value or "").split())[:1_000]


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _integer(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
