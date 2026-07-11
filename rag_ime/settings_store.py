from __future__ import annotations

import json
import re
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .db import apply_database_migrations
from .settings_models import SettingsUpdateResult, UserProfile, UserVocabularyItem
from .settings_schema import (
    deep_merge_settings,
    default_settings,
    flatten_settings,
    redact_settings,
    section_defaults,
    settings_schema,
    stable_settings_hash,
    unflatten_settings,
)
from .text_utils import now_ms


class ManagementSettingsStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._initialized = False
        self._initialize_lock = RLock()

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                ensure_management_tables(conn)
                _purge_transport_metadata(conn)
            self._initialized = True

    def get_settings(self, *, include_sensitive: bool = False) -> dict[str, object]:
        self.initialize()
        settings = default_settings()
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM management_settings").fetchall()
        for row in rows:
            key = str(row["key"])
            try:
                value = json.loads(str(row["value_json"]))
            except json.JSONDecodeError:
                continue
            candidate = {key: value}
            validated = _validated_flat_updates(flatten_settings(candidate), strict=False)
            if validated:
                settings = deep_merge_settings(settings, unflatten_settings(validated))
        return settings if include_sensitive else redact_settings(settings)

    def update_settings(
        self,
        updates: Mapping[str, object],
        *,
        updated_by: str = "local",
        confirm_text: str = "",
    ) -> SettingsUpdateResult:
        self.initialize()
        normalized = _normalize_updates(updates)
        _validate_remote_opt_in(normalized, confirm_text=confirm_text)
        before = self.get_settings(include_sensitive=True)
        after = deep_merge_settings(before, normalized)
        changed = tuple(sorted(key for key, value in flatten_settings(after).items() if flatten_settings(before).get(key) != value))
        with self._connect() as conn:
            ensure_management_tables(conn)
            audit_id = record_management_audit(
                conn,
                action="settings_update",
                target_type="settings",
                target_id=",".join(changed) or "no-op",
                payload={"updates": normalized, "updatedBy": updated_by},
                result={"changedKeys": changed},
            )
            timestamp = now_ms()
            # Dotted-key updates normalize to a partial top-level section. Persist
            # the fully merged section so changing one leaf never erases sibling
            # overrides that were already stored.
            for section in normalized:
                value = after[section]
                conn.execute(
                    """
                    INSERT INTO management_settings(key, value_json, updated_at_ms, updated_by, audit_id)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                      value_json = excluded.value_json,
                      updated_at_ms = excluded.updated_at_ms,
                      updated_by = excluded.updated_by,
                      audit_id = excluded.audit_id
                    """,
                    (section, json.dumps(value, ensure_ascii=False, sort_keys=True), timestamp, updated_by, audit_id),
                )
        return SettingsUpdateResult(settings=redact_settings(after), audit_id=int(audit_id), changed_keys=changed)

    def reset_section(self, section: str, *, updated_by: str = "local") -> SettingsUpdateResult:
        self.initialize()
        if not section_defaults(section):
            raise ValueError(f"unknown settings section: {section}")
        before = self.get_settings(include_sensitive=True)
        after = deep_merge_settings(before, {section: section_defaults(section)})
        with self._connect() as conn:
            ensure_management_tables(conn)
            audit_id = record_management_audit(
                conn,
                action="settings_reset_section",
                target_type="settings",
                target_id=section,
                payload={"section": section, "updatedBy": updated_by},
                result={"restoredDefaults": True},
            )
            conn.execute(
                """
                INSERT INTO management_settings(key, value_json, updated_at_ms, updated_by, audit_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value_json = excluded.value_json,
                  updated_at_ms = excluded.updated_at_ms,
                  updated_by = excluded.updated_by,
                  audit_id = excluded.audit_id
                """,
                (section, json.dumps(section_defaults(section), ensure_ascii=False, sort_keys=True), now_ms(), updated_by, audit_id),
            )
        changed = tuple(sorted(key for key, value in flatten_settings(after).items() if flatten_settings(before).get(key) != value))
        return SettingsUpdateResult(settings=redact_settings(after), audit_id=int(audit_id), changed_keys=changed)

    def schema_payload(self) -> dict[str, object]:
        return {
            **settings_schema(),
            "defaults": default_settings(),
        }

    def resolve_runtime_config_revision(
        self,
        *,
        snapshot_hash: str,
        settings_revision: str,
        profile: str,
    ) -> int:
        self.initialize()
        with self._connect() as conn:
            current = conn.execute(
                "SELECT runtime_revision, snapshot_hash FROM runtime_config_state WHERE singleton_id = 1"
            ).fetchone()
        if current is not None and str(current["snapshot_hash"]) == snapshot_hash:
            return int(current["runtime_revision"])

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT runtime_revision, snapshot_hash FROM runtime_config_state WHERE singleton_id = 1"
            ).fetchone()
            if row is None:
                revision = 1
                conn.execute(
                    """
                    INSERT INTO runtime_config_state(
                      singleton_id, runtime_revision, snapshot_hash,
                      settings_revision, profile, updated_at_ms
                    ) VALUES (1, ?, ?, ?, ?, ?)
                    """,
                    (revision, snapshot_hash, settings_revision, profile, now_ms()),
                )
                return revision
            revision = int(row["runtime_revision"])
            if str(row["snapshot_hash"]) == snapshot_hash:
                return revision
            revision += 1
            conn.execute(
                """
                UPDATE runtime_config_state
                SET runtime_revision = ?, snapshot_hash = ?, settings_revision = ?,
                    profile = ?, updated_at_ms = ?
                WHERE singleton_id = 1
                """,
                (revision, snapshot_hash, settings_revision, profile, now_ms()),
            )
            return revision

    def bump_runtime_config_revision(self) -> int:
        self.initialize()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT runtime_revision FROM runtime_config_state WHERE singleton_id = 1"
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO runtime_config_state(
                      singleton_id, runtime_revision, snapshot_hash,
                      settings_revision, profile, updated_at_ms
                    ) VALUES (1, 1, '', '', '', ?)
                    """,
                    (now_ms(),),
                )
                return 1
            revision = int(row["runtime_revision"]) + 1
            conn.execute(
                "UPDATE runtime_config_state SET runtime_revision = ?, updated_at_ms = ? WHERE singleton_id = 1",
                (revision, now_ms()),
            )
            return revision

    def list_profiles(self, *, kind: str = "") -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM user_profiles
                WHERE (? = '' OR profile_kind = ?)
                ORDER BY updated_at_ms DESC, profile_id ASC
                """,
                (kind, kind),
            ).fetchall()
        return {
            "schemaVersion": "rag-ime.user-profiles.v3",
            "ok": True,
            "items": [_profile_row_payload(row) for row in rows],
        }

    def save_profile(self, profile: UserProfile, *, updated_by: str = "local") -> dict[str, object]:
        self.initialize()
        if not profile.profile_id:
            raise ValueError("profile id is required")
        timestamp = now_ms()
        with self._connect() as conn:
            ensure_management_tables(conn)
            audit_id = record_management_audit(
                conn,
                action="profile_save",
                target_type="profile",
                target_id=profile.profile_id,
                payload={"kind": profile.profile_kind, "label": profile.label, "updatedBy": updated_by},
                result={"enabled": profile.enabled},
            )
            conn.execute(
                """
                INSERT INTO user_profiles(
                  profile_id, profile_kind, label, description, settings_json,
                  enabled, created_at_ms, updated_at_ms, audit_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                  profile_kind = excluded.profile_kind,
                  label = excluded.label,
                  description = excluded.description,
                  settings_json = excluded.settings_json,
                  enabled = excluded.enabled,
                  updated_at_ms = excluded.updated_at_ms,
                  audit_id = excluded.audit_id
                """,
                (
                    profile.profile_id,
                    profile.profile_kind,
                    profile.label,
                    profile.description,
                    json.dumps(profile.settings, ensure_ascii=False, sort_keys=True),
                    1 if profile.enabled else 0,
                    timestamp,
                    timestamp,
                    audit_id,
                ),
            )
        return {"schemaVersion": "rag-ime.user-profile-save.v3", "ok": True, "auditId": int(audit_id), "profileId": profile.profile_id}

    def activate_profile_dry_run(self, profile_id: str) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_profiles WHERE profile_id = ? LIMIT 1", (profile_id,)).fetchone()
        if row is None:
            return {"schemaVersion": "rag-ime.user-profile-activate-dry-run.v3", "ok": False, "error": "profile not found", "profileId": profile_id}
        profile = _profile_row_payload(row)
        settings = _json_loads_dict(profile.get("settings"))
        return {
            "schemaVersion": "rag-ime.user-profile-activate-dry-run.v3",
            "ok": True,
            "dryRun": True,
            "profile": profile,
            "commands": [
                "python3 -m rag_ime.cli debug-server",
                "scripts/restart_rag_ime_runtime.sh",
            ],
            "settingsPreview": deep_merge_settings(self.get_settings(include_sensitive=True), settings),
        }

    def list_vocabulary(self, *, status: str = "", query: str = "") -> dict[str, object]:
        self.initialize()
        q = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM user_vocabulary
                WHERE (? = '' OR status = ?)
                  AND (? = '' OR surface LIKE ? OR aliases_json LIKE ? OR tags_json LIKE ?)
                ORDER BY priority DESC, updated_at_ms DESC, surface ASC
                """,
                (status, status, query, q, q, q),
            ).fetchall()
        return {"schemaVersion": "rag-ime.user-vocabulary.v3", "ok": True, "items": [_vocab_row_payload(row) for row in rows]}

    def save_vocabulary_item(self, item: UserVocabularyItem, *, action: str = "add") -> dict[str, object]:
        self.initialize()
        vocab_id = item.vocab_id or _vocab_id(item.surface, scope=item.scope)
        timestamp = now_ms()
        with self._connect() as conn:
            ensure_management_tables(conn)
            audit_id = record_management_audit(
                conn,
                action=f"vocabulary_{action}",
                target_type="vocabulary",
                target_id=vocab_id,
                payload={"surface": item.surface, "scope": item.scope, "action": action},
                result={"status": item.status},
            )
            conn.execute(
                """
                INSERT INTO user_vocabulary(
                  vocab_id, surface, aliases_json, pinyin, tags_json, scope,
                  priority, status, created_at_ms, updated_at_ms, audit_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vocab_id) DO UPDATE SET
                  surface = excluded.surface,
                  aliases_json = excluded.aliases_json,
                  pinyin = excluded.pinyin,
                  tags_json = excluded.tags_json,
                  scope = excluded.scope,
                  priority = excluded.priority,
                  status = excluded.status,
                  updated_at_ms = excluded.updated_at_ms,
                  audit_id = excluded.audit_id
                """,
                (
                    vocab_id,
                    item.surface,
                    json.dumps(list(item.aliases), ensure_ascii=False),
                    item.pinyin,
                    json.dumps(list(item.tags), ensure_ascii=False),
                    item.scope,
                    int(item.priority),
                    item.status,
                    timestamp,
                    timestamp,
                    audit_id,
                ),
            )
        return {"schemaVersion": "rag-ime.user-vocabulary-save.v3", "ok": True, "auditId": int(audit_id), "vocabId": vocab_id}

    def delete_vocabulary_item(self, vocab_id: str) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            ensure_management_tables(conn)
            audit_id = record_management_audit(
                conn,
                action="vocabulary_delete",
                target_type="vocabulary",
                target_id=vocab_id,
                payload={},
                result={"status": "deleted"},
            )
            conn.execute(
                "UPDATE user_vocabulary SET status = 'deleted', updated_at_ms = ?, audit_id = ? WHERE vocab_id = ?",
                (now_ms(), audit_id, vocab_id),
            )
        return {"schemaVersion": "rag-ime.user-vocabulary-delete.v3", "ok": True, "auditId": int(audit_id), "vocabId": vocab_id}

    def rime_export_preview(self, *, status: str = "active") -> dict[str, object]:
        items = self.list_vocabulary(status=status).get("items", [])
        lines = [
            "# RAG-IME managed vocabulary preview",
            "# yaml-language-server: $schema=https://raw.githubusercontent.com/rime/librime/master/schema/schema.json",
            "---",
            "name: rag_ime_user",
            "version: \"1\"",
            "sort: by_weight",
            "...",
        ]
        for item in items:
            if not isinstance(item, dict):
                continue
            surface = str(item.get("surface") or "").strip()
            pinyin = str(item.get("pinyin") or "").strip()
            priority = int(item.get("priority") or 0)
            if not surface:
                continue
            lines.append("\t".join(part for part in (surface, pinyin, str(max(1, priority or 1))) if part))
        return {
            "schemaVersion": "rag-ime.vocabulary-rime-export.v3",
            "ok": True,
            "dryRun": True,
            "entryCount": max(0, len(lines) - 7),
            "text": "\n".join(lines) + "\n",
            "items": items,
        }

    def rime_export_apply(self, *, target_file: str, confirm_text: str) -> dict[str, object]:
        if confirm_text != "EXPORT RIME":
            return {
                "schemaVersion": "rag-ime.vocabulary-rime-export-apply.v3",
                "ok": False,
                "requiredConfirmText": "EXPORT RIME",
                "error": "confirmText is required",
            }
        preview = self.rime_export_preview()
        target = Path(target_file).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        backup = ""
        if target.exists():
            backup_path = target.with_name(target.name + f".rag-ime-backup-{now_ms()}")
            shutil.copy2(target, backup_path)
            backup = str(backup_path)
        target.write_text(str(preview["text"]), encoding="utf-8")
        with self._connect() as conn:
            ensure_management_tables(conn)
            audit_id = record_management_audit(
                conn,
                action="vocabulary_rime_export_apply",
                target_type="file",
                target_id=str(target),
                payload={"entryCount": preview["entryCount"]},
                result={"backup": backup},
            )
        return {
            "schemaVersion": "rag-ime.vocabulary-rime-export-apply.v3",
            "ok": True,
            "auditId": int(audit_id),
            "targetFile": str(target),
            "backupFile": backup,
            "entryCount": preview["entryCount"],
        }

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def ensure_management_tables(conn: sqlite3.Connection) -> None:
    apply_database_migrations(conn)


def record_management_audit(
    conn: sqlite3.Connection,
    *,
    action: str,
    target_type: str,
    target_id: str,
    payload: Mapping[str, object],
    result: Mapping[str, object],
) -> int:
    ensure_management_tables(conn)
    cur = conn.execute(
        """
        INSERT INTO management_audit_log(created_at_ms, action, target_type, target_id, payload_json, result_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            now_ms(),
            action,
            target_type,
            target_id,
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
            json.dumps(dict(result), ensure_ascii=False, sort_keys=True),
        ),
    )
    return int(cur.lastrowid)


def settings_response(settings: Mapping[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.management-settings.v3",
        "ok": True,
        "settings": dict(settings),
        "settingsHash": stable_settings_hash(settings),
    }


def _normalize_updates(updates: Mapping[str, object]) -> dict[str, object]:
    source = updates.get("settings") if isinstance(updates.get("settings"), Mapping) else updates
    flat: dict[str, object] = {}
    nested: dict[str, object] = {}
    for key, value in dict(source).items():
        normalized_key = str(key)
        if normalized_key in _UPDATE_METADATA_KEYS:
            continue
        if "." in normalized_key:
            flat[normalized_key] = value
        else:
            nested[normalized_key] = value
    merged = deep_merge_settings(nested, unflatten_settings(flat))
    return unflatten_settings(_validated_flat_updates(flatten_settings(merged), strict=True))


_UPDATE_METADATA_KEYS = {
    "auditId",
    "confirmText",
    "confirm_text",
    "previewToken",
    "runtimeRevision",
    "schemaVersion",
    "settingsRevision",
    "updatedBy",
    "updated_by",
}


def _purge_transport_metadata(conn: sqlite3.Connection) -> None:
    placeholders = ",".join("?" for _ in _UPDATE_METADATA_KEYS)
    conn.execute(
        f"DELETE FROM management_settings WHERE key IN ({placeholders})",
        tuple(sorted(_UPDATE_METADATA_KEYS)),
    )


def _setting_defaults_by_key() -> dict[str, object]:
    defaults = flatten_settings(default_settings())
    # The management token is intentionally not shipped with a default value,
    # but it is a supported sensitive setting when token enforcement is enabled.
    defaults["managementSecurity.token"] = ""
    return defaults


def _setting_schema_by_key() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for section in settings_schema().get("sections", []):
        if not isinstance(section, Mapping):
            continue
        for field in section.get("fields", []):
            if isinstance(field, Mapping) and str(field.get("key") or ""):
                result[str(field["key"])] = dict(field)
    return result


def _validated_flat_updates(values: Mapping[str, object], *, strict: bool) -> dict[str, object]:
    defaults = _setting_defaults_by_key()
    fields = _setting_schema_by_key()
    validated: dict[str, object] = {}
    for key, value in values.items():
        if key not in defaults:
            if strict:
                raise ValueError(f"unknown setting key: {key}")
            continue
        try:
            normalized = _validated_setting_value(key, value, default=defaults[key], field=fields.get(key, {}))
        except ValueError:
            if strict:
                raise
            continue
        validated[key] = normalized
    return validated


def _validated_setting_value(
    key: str,
    value: object,
    *,
    default: object,
    field: Mapping[str, object],
) -> object:
    field_type = str(field.get("type") or "")
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"setting {key} must be a boolean")
        normalized: object = value
    elif isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"setting {key} must be an integer")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"setting {key} must be an integer")
        normalized = int(value)
    elif isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"setting {key} must be a number")
        normalized = float(value)
    elif isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"setting {key} must be a string")
        normalized = value
    else:
        if not isinstance(value, type(default)):
            raise ValueError(f"setting {key} has an invalid type")
        normalized = value

    options = field.get("options")
    if field_type == "enum" and isinstance(options, list) and normalized not in options:
        raise ValueError(f"setting {key} must be one of: {', '.join(str(item) for item in options)}")
    if isinstance(normalized, (int, float)) and not isinstance(normalized, bool):
        minimum = field.get("min")
        maximum = field.get("max")
        if isinstance(minimum, (int, float)) and normalized < minimum:
            raise ValueError(f"setting {key} must be >= {minimum}")
        if isinstance(maximum, (int, float)) and normalized > maximum:
            raise ValueError(f"setting {key} must be <= {maximum}")
    return normalized


def _validate_remote_opt_in(updates: Mapping[str, object], *, confirm_text: str) -> None:
    flat = flatten_settings(updates)
    remote_keys = {
        "activeRag.allowRemoteModel",
        "privacy.allowRemoteModelForActiveRag",
    }
    if any(flat.get(key) is True for key in remote_keys) and confirm_text != "ALLOW REMOTE MODEL":
        raise ValueError("remote model enable requires confirmText=ALLOW REMOTE MODEL")


def _json_loads_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _json_loads_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _profile_row_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "profileId": str(row["profile_id"]),
        "profileKind": str(row["profile_kind"]),
        "label": str(row["label"]),
        "description": str(row["description"]),
        "settings": _json_loads_dict(row["settings_json"]),
        "enabled": bool(row["enabled"]),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "auditId": int(row["audit_id"] or 0),
    }


def _vocab_row_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "vocabId": str(row["vocab_id"]),
        "surface": str(row["surface"]),
        "aliases": _json_loads_list(row["aliases_json"]),
        "pinyin": str(row["pinyin"]),
        "tags": _json_loads_list(row["tags_json"]),
        "scope": str(row["scope"]),
        "priority": int(row["priority"] or 0),
        "status": str(row["status"]),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "auditId": int(row["audit_id"] or 0),
    }


def _vocab_id(surface: str, *, scope: str) -> str:
    normalized = re.sub(r"\s+", "-", surface.strip().lower())[:80] or "item"
    safe_scope = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", scope.strip() or "global")
    return f"hotword:{safe_scope}:{normalized}"
