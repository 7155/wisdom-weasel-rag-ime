from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping

from .agent_roles import (
    PersonaDefaults,
    PersonaManifest,
    PersonaRuntimeCharacteristics,
    PersonaVisualProfile,
    agent_role,
    user_persona_manifest,
)
from .db import apply_database_migrations


class AgentPersonaStore:
    """Persistent user personas; prompts and control policy stay server-owned."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def create(
        self,
        payload: Mapping[str, object],
        *,
        created_at_ms: int | None = None,
    ) -> PersonaManifest:
        allowed = {
            "displayName",
            "tagline",
            "summary",
            "traits",
            "timelineModel",
            "selectableModes",
        }
        unexpected = sorted(str(key) for key in payload if key not in allowed)
        if unexpected:
            raise ValueError(f"unsupported persona fields: {', '.join(unexpected)}")

        display_name = _public_text(payload.get("displayName"), field="displayName", maximum=40)
        tagline = _public_text(payload.get("tagline"), field="tagline", maximum=80)
        summary = _public_text(payload.get("summary"), field="summary", maximum=180)
        traits = _traits(payload.get("traits"))
        timeline_model = str(payload.get("timelineModel") or "").strip().lower()
        if timeline_model not in {"luna", "terra", "sol"}:
            raise ValueError("timelineModel must be luna, terra, or sol")
        selectable_modes = _selectable_modes(payload.get("selectableModes"))
        role_id = f"persona-{uuid.uuid4().hex[:20]}"
        version = "1"
        timestamp = int(created_at_ms if created_at_ms is not None else time.time() * 1000)

        manifest = user_persona_manifest(
            role_id=role_id,
            version=version,
            display_name=display_name,
            tagline=tagline,
            summary=summary,
            traits=traits,
            timeline_model=timeline_model,
            selectable_modes=selectable_modes,
        )
        manifest.to_payload()
        tool_policy = _tool_policy(manifest)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_personas(
                    role_id, version, display_name, tagline, summary, traits_json,
                    timeline_model, selectable_modes_json, persona_prompt,
                    visual_profile_json, model_policy, memory_policy,
                    tool_profile_version, safety_policy_version,
                    safety_policy_prompt, tool_policy_json, status,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    role_id,
                    version,
                    display_name,
                    tagline,
                    summary,
                    json.dumps(list(traits), ensure_ascii=False, separators=(",", ":")),
                    timeline_model,
                    json.dumps(list(selectable_modes), ensure_ascii=False, separators=(",", ":")),
                    manifest.persona_prompt,
                    json.dumps(
                        manifest.visual_profile.to_payload(),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    manifest.defaults.model_policy,
                    manifest.defaults.memory_policy,
                    manifest.defaults.tool_profile_version,
                    manifest.safety_policy_version,
                    manifest.safety_policy_prompt,
                    json.dumps(
                        tool_policy,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    timestamp,
                    timestamp,
                ),
            )
        return manifest

    def resolve(self, role_id: object, version: object) -> PersonaManifest:
        try:
            return agent_role(role_id, version)
        except ValueError:
            pass
        key = (str(role_id or "").strip(), str(version or "").strip())
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_personas
                WHERE role_id = ? AND version = ? AND status = 'active'
                """,
                key,
            ).fetchone()
        if row is None:
            raise ValueError(
                f"unsupported agent role: {key[0] or '<empty>'}@{key[1] or '<empty>'}"
            )
        return _manifest(row)

    def list(self) -> list[PersonaManifest]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_personas
                WHERE status = 'active'
                ORDER BY created_at_ms ASC, role_id ASC
                """
            ).fetchall()
        return [_manifest(row) for row in rows]

    def runtime_defaults(self, role_id: object, version: object) -> dict[str, str] | None:
        role = self.resolve(role_id, version)
        if role.defaults.model_policy == "fixed":
            return {
                "modelProfile": role.defaults.model_profile,
                "thinkingLevel": role.defaults.thinking_level,
            }
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT model_profile, thinking_level
                FROM agent_role_runtime_preferences
                WHERE role_id = ? AND role_version = ?
                """,
                (role.role_id, role.version),
            ).fetchone()
        if row is None:
            return None
        return {
            "modelProfile": str(row["model_profile"]),
            "thinkingLevel": str(row["thinking_level"]),
        }

    def set_runtime_defaults(
        self,
        role_id: object,
        version: object,
        *,
        model_profile: str,
        thinking_level: str,
        updated_at_ms: int | None = None,
    ) -> dict[str, str]:
        role = self.resolve(role_id, version)
        if role.defaults.model_policy == "fixed":
            raise ValueError("builtin persona runtime defaults are fixed")
        profile = _model_profile(model_profile)
        level = str(thinking_level or "").strip().lower()
        if level not in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("thinkingLevel is not supported")
        timestamp = int(updated_at_ms if updated_at_ms is not None else time.time() * 1000)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_role_runtime_preferences(
                    role_id, role_version, model_profile, thinking_level, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(role_id, role_version) DO UPDATE SET
                    model_profile = excluded.model_profile,
                    thinking_level = excluded.thinking_level,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (role.role_id, role.version, profile, level, timestamp),
            )
        return {"modelProfile": profile, "thinkingLevel": level}

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _manifest(row: sqlite3.Row) -> PersonaManifest:
    traits = _stored_text_array(row["traits_json"], field="traits")
    modes = _stored_text_array(row["selectable_modes_json"], field="selectableModes")
    visual_value = _stored_object(row["visual_profile_json"], field="visualProfile")
    tool_policy = _stored_object(row["tool_policy_json"], field="toolPolicy")
    tool_profile_version = str(row["tool_profile_version"])
    if tool_policy.get("profileVersion") != tool_profile_version:
        raise ValueError("stored persona tool policy does not match its tool profile")
    if tool_policy.get("selectableModes") != list(modes):
        raise ValueError("stored persona tool policy does not match selectable modes")
    return PersonaManifest(
        role_id=str(row["role_id"]),
        version=str(row["version"]),
        display_name=str(row["display_name"]),
        tagline=str(row["tagline"]),
        summary=str(row["summary"]),
        traits=traits,
        persona_prompt=str(row["persona_prompt"]),
        visual_profile=PersonaVisualProfile(
            avatar_asset_id=str(visual_value.get("avatarAssetId") or ""),
            symbol_name=str(visual_value.get("symbolName") or ""),
            accent_token=str(visual_value.get("accentToken") or ""),
        ),
        defaults=PersonaDefaults(
            model_policy=str(row["model_policy"]),
            memory_policy=str(row["memory_policy"]),
            tool_profile_version=tool_profile_version,
        ),
        runtime_characteristics=PersonaRuntimeCharacteristics(
            intelligence="由所选模型决定",
            speed="由所选模型决定",
            context="按 Session 模型与作用域配置",
            suitable_tasks=("用户定义的陪伴与协作任务",),
            unsuitable_tasks=("超出已连接工具、权限或证据范围的任务",),
        ),
        selectable_modes=modes,
        safety_policy_version=str(row["safety_policy_version"]),
        safety_policy_prompt=str(row["safety_policy_prompt"]),
        origin="user",
    )


def _public_text(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if any(ord(char) < 32 and not char.isspace() for char in value):
        raise ValueError(f"{field} contains unsupported control characters")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must not exceed {maximum} characters")
    return normalized


def _model_profile(value: object) -> str:
    normalized = str(value or "").strip()
    if "/" not in normalized or any(character.isspace() for character in normalized):
        raise ValueError("modelProfile must be provider/modelId")
    provider, model_id = normalized.split("/", 1)
    if not provider or not model_id or len(provider) > 80 or len(model_id) > 160:
        raise ValueError("modelProfile must be provider/modelId")
    return normalized


def _traits(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("traits must be an array")
    traits = tuple(_public_text(item, field="trait", maximum=24) for item in value)
    if not 1 <= len(traits) <= 5:
        raise ValueError("traits must contain between 1 and 5 items")
    if len(set(traits)) != len(traits):
        raise ValueError("traits must not contain duplicates")
    return traits


def _selectable_modes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("selectableModes must be an array")
    if any(not isinstance(item, str) for item in value):
        raise ValueError("selectableModes items must be strings")
    modes = tuple(item.strip() for item in value)
    if not modes or len(modes) > 2 or len(set(modes)) != len(modes):
        raise ValueError("selectableModes must contain one or two unique modes")
    if any(mode not in {"assistant", "coordinator"} for mode in modes):
        raise ValueError("selectableModes contains an unsupported mode")
    return modes


def _tool_policy(manifest: PersonaManifest) -> dict[str, object]:
    modes = list(manifest.selectable_modes)
    return {
        "schemaVersion": "rag-ime.agent-persona-tool-policy.v1",
        "profileVersion": manifest.defaults.tool_profile_version,
        "selectableModes": modes,
        "coordinatorShell": "per-command-approval" if "coordinator" in modes else "disabled",
        "writes": "structured-approval-only",
    }


def _stored_text_array(value: object, *, field: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ValueError(f"stored persona {field} is not valid JSON") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ValueError(f"stored persona {field} is not a string array")
    return tuple(parsed)


def _stored_object(value: object, *, field: str) -> dict[str, object]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ValueError(f"stored persona {field} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"stored persona {field} is not an object")
    return parsed
