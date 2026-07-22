from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .agent_runtime_driver import AgentRuntimeError
from .agent_tool_ids import (
    CONTROL_CENTER_TOOL_PROFILE,
    CONTROL_TOOL_IDS,
    DANGEROUS_AUTO_APPROVE_TOOL_PROFILE,
    DANGEROUS_MODE_CONFIRMATION,
    READONLY_TOOL_PROFILE,
)
from .contracts.json_schema import validate_contract


class AgentSessionPolicyService:
    """Own mutable Session permissions and provider model choices."""

    def __init__(
        self,
        *,
        sessions: Any,
        runtime_provider: Callable[[], Any],
        personas: Any,
        rooms: Any,
        events: Any,
        runtime_status: Callable[[], Mapping[str, object]],
        probe_memory_maintenance: Callable[..., Mapping[str, object]],
    ) -> None:
        self.sessions = sessions
        self._runtime_provider = runtime_provider
        self.personas = personas
        self.rooms = rooms
        self.events = events
        self.runtime_status = runtime_status
        self.probe_memory_maintenance = probe_memory_maintenance

    @property
    def runtime(self) -> Any:
        return self._runtime_provider()

    def model_catalog(self, session_id: str) -> dict[str, object]:
        catalog = self.runtime.model_catalog(session_id)
        models = (
            catalog.get("models")
            if isinstance(catalog.get("models"), list)
            else []
        )
        selected = catalog.get("selected")
        if isinstance(selected, Mapping):
            selected_provider = str(selected.get("provider") or "")
            selected_id = str(
                selected.get("id") or selected.get("modelId") or ""
            )
            if selected_provider and selected_id and not any(
                isinstance(value, Mapping)
                and str(value.get("provider") or "")
                == selected_provider
                and str(
                    value.get("id") or value.get("modelId") or ""
                )
                == selected_id
                for value in models
            ):
                models = [*models, dict(selected)]
        providers: dict[str, list[dict[str, object]]] = {}
        for value in models:
            if not isinstance(value, Mapping):
                continue
            provider = str(value.get("provider") or "")
            providers.setdefault(provider, []).append(dict(value))
        response = {
            "schemaVersion": "rag-ime.agent-model-catalog.v1",
            "ok": True,
            "sessionId": session_id,
            "selected": selected,
            "thinkingLevel": str(
                catalog.get("thinkingLevel") or "off"
            ),
            "providers": [
                {
                    "id": provider,
                    "displayName": _provider_display_name(provider),
                    "models": items,
                }
                for provider, items in sorted(
                    providers.items(),
                    key=lambda item: item[0].lower(),
                )
            ],
        }
        validate_contract(response, "agent-model-catalog.v1.json")
        return response

    def command_catalog(self, session_id: str) -> dict[str, object]:
        self.sessions.get(session_id)
        runtime_available = True
        try:
            commands = self.runtime.command_catalog(session_id)
        except AgentRuntimeError:
            runtime_available = False
            commands = []
        return {
            "schemaVersion": "rag-ime.agent-command-catalog.v1",
            "ok": True,
            "sessionId": session_id,
            "runtimeAvailable": runtime_available,
            "items": commands,
        }

    def select_model(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        selected = self.runtime.set_model(
            session_id,
            provider=_required_text(payload, "provider"),
            model_id=_required_text(payload, "modelId"),
        )
        self.events.publish(
            session_id,
            "session_configuration_changed",
            {
                "kind": "model",
                "selected": selected["selected"],
                "modelProfile": selected["session"].get(
                    "modelProfile",
                    "",
                ),
            },
        )
        response = {
            "schemaVersion": "rag-ime.agent-model-selection.v1",
            "ok": True,
            "sessionId": session_id,
            "selected": selected["selected"],
            "session": selected["session"],
        }
        validate_contract(response, "agent-model-selection.v1.json")
        return response

    def select_thinking_level(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        selected = self.runtime.set_thinking_level(
            session_id,
            level=_required_text(payload, "level"),
        )
        self.events.publish(
            session_id,
            "session_configuration_changed",
            {
                "kind": "thinking",
                "thinkingLevel": selected["thinkingLevel"],
                "selected": selected.get("selected"),
            },
        )
        response = {
            "schemaVersion": "rag-ime.agent-thinking-selection.v1",
            "ok": True,
            "sessionId": session_id,
            "thinkingLevel": selected["thinkingLevel"],
            "selected": selected.get("selected"),
        }
        validate_contract(
            response,
            "agent-thinking-selection.v1.json",
        )
        return response

    def update_session(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        session = self.sessions.get(session_id)
        self._validate_archive(session_id, payload)
        if "title" in payload:
            session = self.sessions.rename(
                session_id,
                str(payload.get("title") or ""),
            )
        if "archived" in payload:
            session = self.sessions.archive(
                session_id,
                archived=_bool(payload.get("archived")),
            )
        if _has_runtime_policy_update(payload):
            self._validate_room_runtime_policy(session_id)
            session = self._update_runtime_policy(
                session_id,
                session,
                payload,
            )
        maintenance = (
            self.probe_memory_maintenance(
                session_id,
                trigger="session_archive",
            )
            if "archived" in payload
            else {}
        )
        return {
            "schemaVersion": "rag-ime.agent-session-update.v1",
            "ok": True,
            "session": session,
            "memoryMaintenance": maintenance,
        }

    def _validate_room_runtime_policy(self, session_id: str) -> None:
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=False,
        )
        if (
            participant is None
            or str(participant.get("status") or "") != "active"
        ):
            return
        room = self.rooms.get(str(participant["roomId"]))
        if str(room.get("status") or "") != "active":
            return
        raise ValueError(
            "Active Room participant runtime permissions are managed by the Room"
        )

    def _validate_archive(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> None:
        if "archived" not in payload or not _bool(
            payload.get("archived")
        ):
            return
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=False,
        )
        if (
            participant is not None
            and str(participant.get("status") or "") == "active"
        ):
            room = self.rooms.get(str(participant["roomId"]))
            if str(room.get("status") or "") == "active":
                raise ValueError(
                    "Active Room participant Sessions cannot be archived directly"
                )

    def _update_runtime_policy(
        self,
        session_id: str,
        session: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        requested_mode = str(
            payload.get("mode") or session.get("mode") or ""
        ).strip()
        role = self.personas.resolve(
            session["roleId"],
            session["roleVersion"],
        )
        if requested_mode not in role.selectable_modes:
            raise ValueError(
                f"agent role {role.role_id}@{role.version} "
                f"is not available for {requested_mode} sessions"
            )
        if str(session.get("status") or "") == "busy":
            raise ValueError(
                "结束当前 Agent Loop 后才能调整运行权限"
            )
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
        roots = payload.get("workspaceRoots")
        if roots is not None and not isinstance(roots, list):
            raise ValueError("workspaceRoots must be an array")
        requested_profile = str(
            payload.get("toolProfileVersion")
            or session.get("toolProfileVersion")
            or "control-center-v1"
        ).strip()
        self._validate_tool_profile(
            requested_profile,
            requested_mode=requested_mode,
            current_profile=str(
                session.get("toolProfileVersion") or ""
            ),
            confirmation=str(
                payload.get("dangerousModeConfirmation") or ""
            ),
        )
        allowed_tools = self._allowed_tools(
            session,
            payload,
            requested_mode=requested_mode,
        )
        for boolean_key in (
            "projectContextEnabled",
            "piSkillsEnabled",
            "codexSkillsEnabled",
        ):
            if (
                boolean_key in payload
                and not isinstance(payload.get(boolean_key), bool)
            ):
                raise ValueError(
                    f"{boolean_key} must be a boolean"
                )
        return self.sessions.set_runtime_policy(
            session_id,
            mode=requested_mode,
            tool_profile_version=requested_profile,
            allowed_tools=allowed_tools,
            project_context_enabled=(
                bool(payload["projectContextEnabled"])
                if "projectContextEnabled" in payload
                else None
            ),
            pi_skills_enabled=(
                bool(payload["piSkillsEnabled"])
                if "piSkillsEnabled" in payload
                else None
            ),
            codex_skills_enabled=(
                bool(payload["codexSkillsEnabled"])
                if "codexSkillsEnabled" in payload
                else None
            ),
            workspace_roots=(
                [str(value) for value in roots]
                if isinstance(roots, list)
                else None
            ),
        )

    @staticmethod
    def _validate_tool_profile(
        requested_profile: str,
        *,
        requested_mode: str,
        current_profile: str,
        confirmation: str,
    ) -> None:
        if requested_profile not in {
            CONTROL_CENTER_TOOL_PROFILE,
            READONLY_TOOL_PROFILE,
            DANGEROUS_AUTO_APPROVE_TOOL_PROFILE,
        }:
            raise ValueError("unsupported Agent tool profile")
        entering_dangerous = (
            requested_profile
            == DANGEROUS_AUTO_APPROVE_TOOL_PROFILE
            and current_profile
            != DANGEROUS_AUTO_APPROVE_TOOL_PROFILE
        )
        if (
            requested_profile
            == DANGEROUS_AUTO_APPROVE_TOOL_PROFILE
            and requested_mode != "coordinator"
        ):
            raise ValueError(
                "automatic approval requires coordinator mode"
            )
        if (
            entering_dangerous
            and confirmation != DANGEROUS_MODE_CONFIRMATION
        ):
            raise ValueError(
                "automatic approval mode requires an explicit native confirmation"
            )

    @staticmethod
    def _allowed_tools(
        session: Mapping[str, object],
        payload: Mapping[str, object],
        *,
        requested_mode: str,
    ) -> list[str] | None:
        requested_allowlist_mode = str(
            payload.get("toolAllowlistMode")
            or (
                "explicit"
                if "allowedTools" in payload
                else session.get("toolAllowlistMode")
            )
            or "profile"
        ).strip()
        if requested_allowlist_mode not in {"profile", "explicit"}:
            raise ValueError(
                "unsupported Agent tool allowlist mode"
            )
        if requested_allowlist_mode == "profile":
            return None
        if "allowedTools" not in payload:
            return (
                [
                    str(value)
                    for value in session.get("allowedTools") or []
                ]
                if session.get("toolAllowlistMode") == "explicit"
                else []
            )
        raw_allowed_tools = payload.get("allowedTools")
        if not isinstance(raw_allowed_tools, list):
            raise ValueError("allowedTools must be an array")
        allowed_tools: list[str] = []
        for value in raw_allowed_tools:
            tool_id = str(value or "").strip()
            if tool_id not in CONTROL_TOOL_IDS:
                raise ValueError(
                    f"unknown Agent tool: {tool_id or '(empty)'}"
                )
            if tool_id not in allowed_tools:
                allowed_tools.append(tool_id)
        if requested_mode == "assistant" and any(
            tool_id.startswith("workspace_")
            for tool_id in allowed_tools
        ):
            raise ValueError(
                "assistant sessions cannot enable workspace tools"
            )
        return allowed_tools


def _has_runtime_policy_update(
    payload: Mapping[str, object],
) -> bool:
    return any(
        key in payload
        for key in (
            "mode",
            "toolProfileVersion",
            "toolAllowlistMode",
            "allowedTools",
            "projectContextEnabled",
            "piSkillsEnabled",
            "codexSkillsEnabled",
        )
    )


def _provider_display_name(provider: str) -> str:
    normalized = provider.strip().lower()
    return {
        "anthropic": "Anthropic",
        "google": "Google",
        "openai": "OpenAI",
        "gpt": "GPT",
        "deepseek": "DeepSeek",
        "openrouter": "OpenRouter",
        "xai": "xAI",
    }.get(normalized, provider)


def _required_text(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = " ".join(str(payload.get(key) or "").split())
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
