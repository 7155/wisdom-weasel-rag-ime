from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .agent_roles import agent_role, builtin_role_book_seed
from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


ROLE_BOOK_SCHEMA_VERSION = "rag-ime.agent-role-book.v1"
ROLE_ROUTING_PROFILE_SCHEMA_VERSION = "rag-ime.agent-role-routing-profile.v1"
ROLE_BOOK_PROMPT_PREFIX = "这位伙伴已经形成的稳定工作画像："

_SECTION_LIMITS = {
    "personality": 6,
    "capabilities": 12,
    "recentWork": 8,
    "lessonsAndLimits": 8,
    "activeCommitments": 8,
}
_SECTION_TITLES = {
    "personality": "性格与协作方式",
    "capabilities": "已验证能力",
    "recentWork": "近期工作",
    "lessonsAndLimits": "经验、教训与能力边界",
    "activeCommitments": "当前承诺",
}
_USABLE_REVISION_STATUSES = frozenset({"active", "superseded", "rolled_back"})
_MAX_ITEM_TEXT = 280
_MAX_PROMPT_CHARS = 2_400
_PROMPT_SECTION_ITEM_LIMIT = 2
_RECENT_WORK_TTL_MS = 14 * 24 * 60 * 60 * 1_000

_SENSITIVE_PATTERNS = (
    re.compile(
        r"(?:api[_ -]?key|access[_ -]?token|password|passwd|secret|authorization)"
        r"\s*[:=]\s*[^\s,;，。]{4,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bbearer\s+[a-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[a-z0-9_-]{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    re.compile(r"(?<!\d)(?:\d[ -]?){16,19}(?!\d)"),
    re.compile(r"(?:/Users|/Volumes|/private|/tmp)/[^\s,;，。]+"),
    re.compile(r"[A-Za-z]:\\Users\\[^\s,;，。]+", re.IGNORECASE),
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(
        r"\b(?:ignore|disregard|override|bypass)\b.{0,48}"
        r"\b(?:previous|prior|system|developer|safety)\b.{0,32}"
        r"\b(?:instruction|message|prompt|policy|rule)s?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:reveal|print|show|leak|repeat)\b.{0,32}"
        r"\b(?:system|developer)\s+(?:prompt|message|instruction)s?\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:<\|/?(?:system|assistant|developer|user)\|>|\[/?INST\])", re.IGNORECASE),
    re.compile(r"(?:^|\n)\s*(?:system|developer|assistant)\s*:", re.IGNORECASE),
    re.compile(
        r"(?:忽略|无视|覆盖|绕过).{0,24}"
        r"(?:系统|开发者|安全|之前).{0,20}(?:指令|提示词|规则|限制)"
    ),
    re.compile(
        r"(?:输出|泄露|展示|复述).{0,20}"
        r"(?:系统提示词|开发者消息|隐藏指令)"
    ),
)


class AgentRoleBookStore:
    """Versioned, evidence-backed role memory with immutable session pinning."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def ensure_seeded(
        self,
        role_id: object,
        role_version: object,
        display_name: object = "",
        mission: object = "",
        base_persona_version: object = "",
        *,
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        role = _identifier(role_id, field="roleId", maximum=120)
        version = _identifier(role_version, field="roleVersion", maximum=80)
        display = _safe_text(
            display_name,
            field="displayName",
            maximum=80,
            allow_empty=True,
            prompt_guard=True,
        )
        normalized_mission = _safe_text(
            mission,
            field="mission",
            maximum=400,
            allow_empty=True,
            prompt_guard=True,
        )
        persona_version = _identifier(
            base_persona_version,
            field="basePersonaVersion",
            maximum=120,
            allow_empty=True,
        )
        timestamp = _timestamp(created_at_ms)

        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_role_books(
                    role_id, role_version, display_name, mission,
                    base_persona_version, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    role,
                    version,
                    display,
                    normalized_mission,
                    persona_version,
                    timestamp,
                    timestamp,
                ),
            )
            book = conn.execute(
                """
                SELECT * FROM agent_role_books
                WHERE role_id = ? AND role_version = ?
                """,
                (role, version),
            ).fetchone()
            if book is None:  # pragma: no cover - protected by the transaction
                raise RuntimeError("role book seed was not persisted")
            self._fill_blank_book_identity(
                conn,
                book,
                display_name=display,
                mission=normalized_mission,
                base_persona_version=persona_version,
                updated_at_ms=timestamp,
            )
            book = conn.execute(
                """
                SELECT * FROM agent_role_books
                WHERE role_id = ? AND role_version = ?
                """,
                (role, version),
            ).fetchone()
            assert book is not None
            _assert_identity_matches(
                book,
                display_name=display,
                mission=normalized_mission,
                base_persona_version=persona_version,
            )
            active = self._active_row(conn, role, version)
            if active is not None:
                seeded_sections = _initial_role_book_sections(role, version)
                if seeded_sections is not None and _is_empty_system_seed(active):
                    return self._upgrade_empty_system_seed(
                        conn,
                        book,
                        active,
                        sections=seeded_sections,
                        timestamp=timestamp,
                    )
                return _revision_payload(book, active)
            existing_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM agent_role_book_revisions
                    WHERE role_id = ? AND role_version = ?
                    """,
                    (role, version),
                ).fetchone()[0]
            )
            if existing_count:
                raise RuntimeError("role book has revisions but no active revision")

            revision_id = _new_revision_id(role, version)
            sections = _initial_role_book_sections(role, version) or _empty_sections()
            conn.execute(
                """
                INSERT INTO agent_role_book_revisions(
                    revision_id, role_id, role_version, revision_number, status,
                    content_json, source_revision_id, change_summary, proposed_by,
                    created_at_ms, activated_at_ms
                ) VALUES (?, ?, ?, 1, 'active', ?, '', ?, 'system:seed', ?, ?)
                """,
                (
                    revision_id,
                    role,
                    version,
                    _json(sections),
                    "Initial built-in Persona role book",
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_role_book_revisions WHERE revision_id = ?",
                (revision_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - protected by the transaction
                raise RuntimeError("role book seed revision was not persisted")
            return _revision_payload(book, row)

    def _upgrade_empty_system_seed(
        self,
        conn: sqlite3.Connection,
        book: sqlite3.Row,
        active: sqlite3.Row,
        *,
        sections: Mapping[str, object],
        timestamp: int,
    ) -> dict[str, object]:
        """Supersede the old empty seed without moving existing Session pins."""

        role = str(active["role_id"])
        version = str(active["role_version"])
        previous_id = str(active["revision_id"])
        revision_id = _new_revision_id(role, version)
        revision_number = int(active["revision_number"]) + 1
        conn.execute(
            """
            UPDATE agent_role_book_revisions
            SET status = 'superseded', superseded_at_ms = ?
            WHERE revision_id = ? AND status = 'active'
            """,
            (timestamp, previous_id),
        )
        conn.execute(
            """
            INSERT INTO agent_role_book_revisions(
                revision_id, role_id, role_version, revision_number, status,
                content_json, source_revision_id, change_summary, proposed_by,
                created_at_ms, activated_at_ms
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, 'system:persona-seed-v1', ?, ?)
            """,
            (
                revision_id,
                role,
                version,
                revision_number,
                _json(sections),
                previous_id,
                "Replace legacy empty seed with the built-in Persona role book",
                timestamp,
                timestamp,
            ),
        )
        self._record_activation_event(
            conn,
            role_id=role,
            role_version=version,
            from_revision_id=previous_id,
            to_revision_id=revision_id,
            event_type="activate",
            actor="system:persona-seed-v1",
            reason="upgrade legacy empty role book seed",
            timestamp=timestamp,
        )
        row = self._revision_row(conn, revision_id)
        return _revision_payload(book, row)

    def propose_revision(
        self,
        role_id: object,
        role_version: object,
        updates: Mapping[str, object],
        *,
        proposed_by: object = "agent",
        change_summary: object = "",
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            return self.propose_revision_in_connection(
                conn,
                role_id,
                role_version,
                updates,
                proposed_by=proposed_by,
                change_summary=change_summary,
                created_at_ms=created_at_ms,
            )

    def propose_revision_idempotent(
        self,
        role_id: object,
        role_version: object,
        updates: Mapping[str, object],
        *,
        idempotency_key: object,
        change_summary: object = "",
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Persist one review draft without activating it or moving session pins."""

        role = _identifier(role_id, field="roleId", maximum=120)
        version = _identifier(role_version, field="roleVersion", maximum=80)
        key = _identifier(
            idempotency_key,
            field="idempotencyKey",
            maximum=280,
        )
        if not isinstance(updates, Mapping):
            raise ValueError("role book updates must be an object")
        unexpected = sorted(str(item) for item in updates if item not in _SECTION_LIMITS)
        if unexpected:
            raise ValueError(
                "role book revisions may only change "
                f"{', '.join(_SECTION_LIMITS)}; unsupported fields: {', '.join(unexpected)}"
            )
        if not updates:
            raise ValueError("role book revision must change at least one allowed section")
        normalized_updates = {
            section: _normalize_items(updates[section], section=section)
            for section in updates
        }
        proposed_by = (
            "personal-context:"
            f"{hashlib.sha256(key.encode()).hexdigest()[:32]}"
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM agent_role_book_revisions
                WHERE role_id = ? AND role_version = ? AND proposed_by = ?
                LIMIT 1
                """,
                (role, version, proposed_by),
            ).fetchone()
            if existing is not None:
                stored_sections = _stored_sections(existing["content_json"])
                if any(
                    stored_sections[section] != items
                    for section, items in normalized_updates.items()
                ):
                    raise ValueError(
                        "role book revision idempotencyKey already belongs to different content"
                    )
                book = self._book_row(conn, role, version)
                return _revision_payload(book, existing)
            return self.propose_revision_in_connection(
                conn,
                role,
                version,
                normalized_updates,
                proposed_by=proposed_by,
                change_summary=change_summary,
                created_at_ms=created_at_ms,
            )

    def propose_revision_in_connection(
        self,
        conn: sqlite3.Connection,
        role_id: object,
        role_version: object,
        updates: Mapping[str, object],
        *,
        proposed_by: object = "agent",
        change_summary: object = "",
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Create a draft inside a caller-owned governance transaction."""

        role = _identifier(role_id, field="roleId", maximum=120)
        version = _identifier(role_version, field="roleVersion", maximum=80)
        if not isinstance(updates, Mapping):
            raise ValueError("role book updates must be an object")
        unexpected = sorted(str(key) for key in updates if key not in _SECTION_LIMITS)
        if unexpected:
            raise ValueError(
                "role book revisions may only change "
                f"{', '.join(_SECTION_LIMITS)}; unsupported fields: {', '.join(unexpected)}"
            )
        if not updates:
            raise ValueError("role book revision must change at least one allowed section")
        actor = _identifier(proposed_by, field="proposedBy", maximum=120)
        summary = _safe_text(
            change_summary,
            field="changeSummary",
            maximum=400,
            allow_empty=True,
        )
        normalized_updates = {
            section: _normalize_items(updates[section], section=section)
            for section in updates
        }
        timestamp = _timestamp(created_at_ms)

        book = self._book_row(conn, role, version)
        source = self._active_row(conn, role, version)
        if source is None:
            raise ValueError(f"role book has no active revision: {role}@{version}")
        sections = _stored_sections(source["content_json"])
        for section, items in normalized_updates.items():
            sections[section] = items
        _validate_sections(sections)
        next_number = int(
            conn.execute(
                """
                SELECT COALESCE(MAX(revision_number), 0) + 1
                FROM agent_role_book_revisions
                WHERE role_id = ? AND role_version = ?
                """,
                (role, version),
            ).fetchone()[0]
        )
        revision_id = _new_revision_id(role, version)
        conn.execute(
            """
            INSERT INTO agent_role_book_revisions(
                revision_id, role_id, role_version, revision_number, status,
                content_json, source_revision_id, change_summary, proposed_by,
                created_at_ms
            ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                role,
                version,
                next_number,
                _json(sections),
                str(source["revision_id"]),
                summary,
                actor,
                timestamp,
            ),
        )
        row = conn.execute(
            "SELECT * FROM agent_role_book_revisions WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("role book draft was not persisted")
        return _revision_payload(book, row)

    def activate_revision(
        self,
        revision_id: object,
        *,
        activated_by: object = "user",
        reason: object = "",
        activated_at_ms: int | None = None,
    ) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            return self.activate_revision_in_connection(
                conn,
                revision_id,
                activated_by=activated_by,
                reason=reason,
                activated_at_ms=activated_at_ms,
            )

    def activate_revision_in_connection(
        self,
        conn: sqlite3.Connection,
        revision_id: object,
        *,
        activated_by: object = "user",
        reason: object = "",
        activated_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Activate a draft inside a caller-owned governance transaction."""

        revision = _identifier(revision_id, field="revisionId", maximum=240)
        actor = _identifier(activated_by, field="activatedBy", maximum=120)
        normalized_reason = _safe_text(reason, field="reason", maximum=400, allow_empty=True)
        timestamp = _timestamp(activated_at_ms)

        target = self._revision_row(conn, revision)
        book = self._book_row(conn, target["role_id"], target["role_version"])
        if str(target["status"]) == "active":
            return _revision_payload(book, target)
        if str(target["status"]) != "draft":
            raise ValueError("only a draft role book revision can be activated")
        current = self._active_row(conn, target["role_id"], target["role_version"])
        from_revision_id = str(current["revision_id"]) if current is not None else ""
        if str(target["source_revision_id"] or "") != from_revision_id:
            raise ValueError(
                "role book draft is stale; create a new draft from the active revision"
            )
        if current is not None:
            conn.execute(
                """
                UPDATE agent_role_book_revisions
                SET status = 'superseded', superseded_at_ms = ?
                WHERE revision_id = ?
                """,
                (timestamp, from_revision_id),
            )
        conn.execute(
            """
            UPDATE agent_role_book_revisions
            SET status = 'active', activated_at_ms = ?,
                superseded_at_ms = NULL, rolled_back_at_ms = NULL
            WHERE revision_id = ?
            """,
            (timestamp, revision),
        )
        self._record_activation_event(
            conn,
            role_id=str(target["role_id"]),
            role_version=str(target["role_version"]),
            from_revision_id=from_revision_id,
            to_revision_id=revision,
            event_type="activate",
            actor=actor,
            reason=normalized_reason,
            timestamp=timestamp,
        )
        conn.execute(
            """
            UPDATE agent_role_books SET updated_at_ms = ?
            WHERE role_id = ? AND role_version = ?
            """,
            (timestamp, target["role_id"], target["role_version"]),
        )
        activated = self._revision_row(conn, revision)
        return _revision_payload(book, activated)

    def rollback(
        self,
        role_id: object,
        role_version: object,
        target_revision_id: object = "",
        *,
        rolled_back_by: object = "user",
        reason: object = "",
        rolled_back_at_ms: int | None = None,
    ) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            return self.rollback_in_connection(
                conn,
                role_id,
                role_version,
                target_revision_id,
                rolled_back_by=rolled_back_by,
                reason=reason,
                rolled_back_at_ms=rolled_back_at_ms,
            )

    def rollback_in_connection(
        self,
        conn: sqlite3.Connection,
        role_id: object,
        role_version: object,
        target_revision_id: object = "",
        *,
        rolled_back_by: object = "user",
        reason: object = "",
        rolled_back_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Rollback inside a caller-owned governance transaction."""

        role = _identifier(role_id, field="roleId", maximum=120)
        version = _identifier(role_version, field="roleVersion", maximum=80)
        target_id = _identifier(
            target_revision_id,
            field="targetRevisionId",
            maximum=240,
            allow_empty=True,
        )
        actor = _identifier(rolled_back_by, field="rolledBackBy", maximum=120)
        normalized_reason = _safe_text(reason, field="reason", maximum=400, allow_empty=True)
        timestamp = _timestamp(rolled_back_at_ms)

        book = self._book_row(conn, role, version)
        current = self._active_row(conn, role, version)
        if current is None:
            raise ValueError(f"role book has no active revision: {role}@{version}")
        if target_id:
            target = self._revision_row(conn, target_id)
        else:
            source_id = str(current["source_revision_id"] or "")
            target = (
                self._revision_row(conn, source_id)
                if source_id
                else conn.execute(
                    """
                    SELECT * FROM agent_role_book_revisions
                    WHERE role_id = ? AND role_version = ?
                      AND status IN ('superseded', 'rolled_back')
                    ORDER BY revision_number DESC LIMIT 1
                    """,
                    (role, version),
                ).fetchone()
            )
            if target is None:
                raise ValueError("role book has no revision available for rollback")
            target_id = str(target["revision_id"])
        if (str(target["role_id"]), str(target["role_version"])) != (role, version):
            raise ValueError("rollback target belongs to another role book")
        if target_id == str(current["revision_id"]):
            return _revision_payload(book, current)
        if str(target["status"]) not in {"superseded", "rolled_back"}:
            raise ValueError("rollback target must be a previously active revision")

        conn.execute(
            """
            UPDATE agent_role_book_revisions
            SET status = 'rolled_back', rolled_back_at_ms = ?
            WHERE revision_id = ?
            """,
            (timestamp, current["revision_id"]),
        )
        conn.execute(
            """
            UPDATE agent_role_book_revisions
            SET status = 'active', activated_at_ms = ?,
                superseded_at_ms = NULL, rolled_back_at_ms = NULL
            WHERE revision_id = ?
            """,
            (timestamp, target_id),
        )
        self._record_activation_event(
            conn,
            role_id=role,
            role_version=version,
            from_revision_id=str(current["revision_id"]),
            to_revision_id=target_id,
            event_type="rollback",
            actor=actor,
            reason=normalized_reason,
            timestamp=timestamp,
        )
        conn.execute(
            """
            UPDATE agent_role_books SET updated_at_ms = ?
            WHERE role_id = ? AND role_version = ?
            """,
            (timestamp, role, version),
        )
        active = self._revision_row(conn, target_id)
        return _revision_payload(book, active)

    def active(self, role_id: object, role_version: object) -> dict[str, object] | None:
        role = _identifier(role_id, field="roleId", maximum=120)
        version = _identifier(role_version, field="roleVersion", maximum=80)
        with self._connect() as conn:
            book = conn.execute(
                """
                SELECT * FROM agent_role_books
                WHERE role_id = ? AND role_version = ?
                """,
                (role, version),
            ).fetchone()
            if book is None:
                return None
            row = self._active_row(conn, role, version)
            return _revision_payload(book, row) if row is not None else None

    def get_revision(self, revision_id: object) -> dict[str, object]:
        revision = _identifier(revision_id, field="revisionId", maximum=240)
        with self._connect() as conn:
            row = self._revision_row(conn, revision)
            book = self._book_row(conn, row["role_id"], row["role_version"])
            return _revision_payload(book, row)

    def history(
        self,
        role_id: object,
        role_version: object,
        *,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        role = _identifier(role_id, field="roleId", maximum=120)
        version = _identifier(role_version, field="roleVersion", maximum=80)
        bounded_limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            book = self._book_row(conn, role, version)
            rows = conn.execute(
                """
                SELECT *
                FROM agent_role_book_revisions
                WHERE role_id = ? AND role_version = ?
                ORDER BY revision_number DESC
                LIMIT ?
                """,
                (role, version, bounded_limit),
            ).fetchall()
            return [_revision_payload(book, row) for row in rows]

    def apply_safe_recent_work(
        self,
        request: Mapping[str, object],
        *,
        applied_at_ms: int | None = None,
    ) -> dict[str, object]:
        """Idempotently apply the one field allowed across the daily auto-apply gate."""

        if not isinstance(request, Mapping):
            raise ValueError("safe recent-work request must be an object")
        allowed = {
            "schemaVersion",
            "idempotencyKey",
            "runId",
            "project",
            "roleId",
            "baseRoleVersion",
            "sourceDigestId",
            "recentWork",
        }
        unexpected = sorted(str(key) for key in request if key not in allowed)
        if unexpected:
            raise ValueError(
                "safe recent-work request contains unsupported fields: "
                + ", ".join(unexpected)
            )
        if (
            str(request.get("schemaVersion") or "")
            != "rag-ime.role-book-safe-recent-work-apply.v1"
        ):
            raise ValueError("unsupported safe recent-work schemaVersion")
        idempotency_key = _identifier(
            request.get("idempotencyKey"),
            field="idempotencyKey",
            maximum=320,
        )
        role = _identifier(request.get("roleId"), field="roleId", maximum=120)
        version = _identifier(
            request.get("baseRoleVersion"),
            field="baseRoleVersion",
            maximum=80,
        )
        project = _identifier(
            request.get("project"),
            field="project",
            maximum=200,
        )
        _identifier(request.get("runId"), field="runId", maximum=240)
        source_digest_id = _identifier(
            request.get("sourceDigestId"),
            field="sourceDigestId",
            maximum=240,
        )
        timestamp = _timestamp(applied_at_ms)
        actor = f"personal-context:{hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]}"

        # The idempotency lookup, revision insert, activation, and prior-active
        # update share one write transaction. The 0055 partial unique index is
        # the database-level backstop if this code is called concurrently.
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM agent_role_book_revisions
                WHERE role_id = ? AND role_version = ? AND proposed_by = ?
                ORDER BY revision_number DESC
                LIMIT 1
                """,
                (role, version, actor),
            ).fetchone()
            book = self._book_row(conn, role, version)
            if existing is not None:
                if str(existing["status"]) == "draft":
                    self._activate_safe_recent_work_revision(
                        conn,
                        target=existing,
                        timestamp=timestamp,
                        reason="Resume idempotent daily recent-work activation",
                    )
                    existing = self._revision_row(
                        conn,
                        str(existing["revision_id"]),
                    )
                return _revision_payload(book, existing)

            active = self._active_row(conn, role, version)
            if active is None:
                raise ValueError(f"role book has no active revision: {role}@{version}")
            incoming = _verified_safe_recent_work(
                conn,
                request.get("recentWork"),
                project=project,
                role_id=role,
                at_ms=timestamp,
            )
            if not incoming:
                return _revision_payload(book, active)
            sections = _stored_sections(active["content_json"])
            merged = _merge_recent_work(
                incoming,
                sections["recentWork"],
                at_ms=timestamp,
            )
            if not merged:
                return _revision_payload(book, active)
            sections["recentWork"] = merged
            _validate_sections(sections)
            next_number = int(
                conn.execute(
                    """
                    SELECT COALESCE(MAX(revision_number), 0) + 1
                    FROM agent_role_book_revisions
                    WHERE role_id = ? AND role_version = ?
                    """,
                    (role, version),
                ).fetchone()[0]
            )
            revision_id = _new_revision_id(role, version)
            conn.execute(
                """
                INSERT INTO agent_role_book_revisions(
                    revision_id, role_id, role_version, revision_number, status,
                    content_json, source_revision_id, change_summary, proposed_by,
                    created_at_ms
                ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    role,
                    version,
                    next_number,
                    _json(sections),
                    str(active["revision_id"]),
                    (
                        "Policy auto-apply: verified structured recent work only; "
                        f"digest={source_digest_id}"
                    ),
                    actor,
                    timestamp,
                ),
            )
            target = self._revision_row(conn, revision_id)
            self._activate_safe_recent_work_revision(
                conn,
                target=target,
                timestamp=timestamp,
                reason="Daily consolidation safe recent-work field",
            )
            activated = self._revision_row(conn, revision_id)
            return _revision_payload(book, activated)

    def _activate_safe_recent_work_revision(
        self,
        conn: sqlite3.Connection,
        *,
        target: sqlite3.Row,
        timestamp: int,
        reason: str,
    ) -> None:
        current = self._active_row(
            conn,
            target["role_id"],
            target["role_version"],
        )
        from_revision_id = str(current["revision_id"]) if current is not None else ""
        if current is not None and from_revision_id != str(target["revision_id"]):
            conn.execute(
                """
                UPDATE agent_role_book_revisions
                SET status = 'superseded', superseded_at_ms = ?
                WHERE revision_id = ? AND status = 'active'
                """,
                (timestamp, from_revision_id),
            )
        conn.execute(
            """
            UPDATE agent_role_book_revisions
            SET status = 'active', activated_at_ms = ?,
                superseded_at_ms = NULL, rolled_back_at_ms = NULL
            WHERE revision_id = ? AND status = 'draft'
            """,
            (timestamp, target["revision_id"]),
        )
        self._record_activation_event(
            conn,
            role_id=str(target["role_id"]),
            role_version=str(target["role_version"]),
            from_revision_id=from_revision_id,
            to_revision_id=str(target["revision_id"]),
            event_type="activate",
            actor="policy:recent-work",
            reason=reason,
            timestamp=timestamp,
        )
        conn.execute(
            """
            UPDATE agent_role_books SET updated_at_ms = ?
            WHERE role_id = ? AND role_version = ?
            """,
            (timestamp, target["role_id"], target["role_version"]),
        )

    def pin_session(
        self,
        session_id: object,
        role_id: object,
        role_version: object,
        display_name: object = "",
        mission: object = "",
        base_persona_version: object = "",
        *,
        revision_id: object = "",
        pinned_at_ms: int | None = None,
    ) -> dict[str, object]:
        session = _identifier(session_id, field="sessionId", maximum=240)
        role = _identifier(role_id, field="roleId", maximum=120)
        version = _identifier(role_version, field="roleVersion", maximum=80)
        requested_revision = _identifier(
            revision_id,
            field="revisionId",
            maximum=240,
            allow_empty=True,
        )
        seed = self.ensure_seeded(
            role,
            version,
            display_name,
            mission,
            base_persona_version,
            created_at_ms=pinned_at_ms,
        )

        with self._connect(immediate=True) as conn:
            session_row = conn.execute(
                """
                SELECT id, role_id, role_version, role_book_revision_id
                FROM agent_sessions WHERE id = ?
                """,
                (session,),
            ).fetchone()
            if session_row is None:
                raise ValueError(f"agent session not found: {session}")
            if (str(session_row["role_id"]), str(session_row["role_version"])) != (role, version):
                raise ValueError("session role does not match the requested role book")
            existing_id = str(session_row["role_book_revision_id"] or "")
            if existing_id:
                existing = self._revision_row(conn, existing_id)
                if (str(existing["role_id"]), str(existing["role_version"])) != (role, version):
                    raise RuntimeError("session is pinned to a different role book")
                book = self._book_row(conn, role, version)
                return _revision_payload(book, existing)

            selected_id = requested_revision or str(seed["revisionId"])
            selected = self._revision_row(conn, selected_id)
            if (str(selected["role_id"]), str(selected["role_version"])) != (role, version):
                raise ValueError("requested role book revision belongs to another role")
            if str(selected["status"]) != "active":
                raise ValueError("a new session can only pin the active role book revision")
            conn.execute(
                """
                UPDATE agent_sessions
                SET role_book_revision_id = ?
                WHERE id = ? AND role_book_revision_id = ''
                """,
                (selected_id, session),
            )
            pinned_id = str(
                conn.execute(
                    "SELECT role_book_revision_id FROM agent_sessions WHERE id = ?",
                    (session,),
                ).fetchone()[0]
            )
            pinned = self._revision_row(conn, pinned_id)
            if (str(pinned["role_id"]), str(pinned["role_version"])) != (role, version):
                raise RuntimeError("session role book pin changed concurrently")
            book = self._book_row(conn, role, version)
            return _revision_payload(book, pinned)

    def prompt_block(self, session: Mapping[str, object]) -> str:
        if not isinstance(session, Mapping):
            return ""
        revision_id = str(
            session.get("roleBookRevisionId")
            or session.get("role_book_revision_id")
            or ""
        ).strip()
        if not revision_id:
            return ""
        try:
            revision = self.get_revision(revision_id)
        except (ValueError, RuntimeError, sqlite3.Error):
            return ""
        if str(revision["status"]) == "draft":
            return ""
        session_role = str(session.get("roleId") or session.get("role_id") or "").strip()
        session_version = str(
            session.get("roleVersion") or session.get("role_version") or ""
        ).strip()
        if session_role and session_role != revision["roleId"]:
            return ""
        if session_version and session_version != revision["roleVersion"]:
            return ""
        return compile_role_book_prompt(revision)

    def routing_profile(
        self,
        role_id: object,
        role_version: object,
        revision_id: object = "",
    ) -> dict[str, object]:
        role = _identifier(role_id, field="roleId", maximum=120)
        version = _identifier(role_version, field="roleVersion", maximum=80)
        requested = _identifier(
            revision_id,
            field="revisionId",
            maximum=240,
            allow_empty=True,
        )
        revision = self.get_revision(requested) if requested else self.active(role, version)
        if revision is None:
            raise ValueError(f"role book has no active revision: {role}@{version}")
        if (revision["roleId"], revision["roleVersion"]) != (role, version):
            raise ValueError("routing revision belongs to another role book")
        if revision["status"] not in _USABLE_REVISION_STATUSES:
            raise ValueError("draft role book revisions cannot be used for routing")
        sections = revision["sections"]
        assert isinstance(sections, Mapping)
        visible_sections = _visible_sections(sections)
        payload: dict[str, object] = {
            "schemaVersion": ROLE_ROUTING_PROFILE_SCHEMA_VERSION,
            "roleId": role,
            "roleVersion": version,
            "revisionId": revision["revisionId"],
            "revisionNumber": revision["revisionNumber"],
            "advisoryOnly": True,
            "personality": list(visible_sections["personality"]),
            "capabilities": list(visible_sections["capabilities"]),
            "recentWork": list(visible_sections["recentWork"]),
            "activeCommitments": list(visible_sections["activeCommitments"]),
            "lessonsAndLimits": list(visible_sections["lessonsAndLimits"]),
        }
        validate_contract(payload, "agent-role-routing-profile.v1.json")
        return payload

    @staticmethod
    def _fill_blank_book_identity(
        conn: sqlite3.Connection,
        book: sqlite3.Row,
        *,
        display_name: str,
        mission: str,
        base_persona_version: str,
        updated_at_ms: int,
    ) -> None:
        replacements = {
            "display_name": display_name,
            "mission": mission,
            "base_persona_version": base_persona_version,
        }
        changed = False
        values: dict[str, str] = {}
        for column, requested in replacements.items():
            current = str(book[column] or "")
            values[column] = current or requested
            changed = changed or (not current and bool(requested))
        if changed:
            conn.execute(
                """
                UPDATE agent_role_books
                SET display_name = ?, mission = ?, base_persona_version = ?,
                    updated_at_ms = ?
                WHERE role_id = ? AND role_version = ?
                """,
                (
                    values["display_name"],
                    values["mission"],
                    values["base_persona_version"],
                    updated_at_ms,
                    book["role_id"],
                    book["role_version"],
                ),
            )

    @staticmethod
    def _record_activation_event(
        conn: sqlite3.Connection,
        *,
        role_id: str,
        role_version: str,
        from_revision_id: str,
        to_revision_id: str,
        event_type: str,
        actor: str,
        reason: str,
        timestamp: int,
    ) -> None:
        conn.execute(
            """
            INSERT INTO agent_role_book_activation_events(
                event_id, role_id, role_version, from_revision_id,
                to_revision_id, event_type, actor, reason, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"role-book-event:{uuid.uuid4()}",
                role_id,
                role_version,
                from_revision_id,
                to_revision_id,
                event_type,
                actor,
                reason,
                timestamp,
            ),
        )

    @staticmethod
    def _active_row(
        conn: sqlite3.Connection,
        role_id: object,
        role_version: object,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM agent_role_book_revisions
            WHERE role_id = ? AND role_version = ? AND status = 'active'
            """,
            (str(role_id), str(role_version)),
        ).fetchone()

    @staticmethod
    def _book_row(
        conn: sqlite3.Connection,
        role_id: object,
        role_version: object,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT * FROM agent_role_books
            WHERE role_id = ? AND role_version = ?
            """,
            (str(role_id), str(role_version)),
        ).fetchone()
        if row is None:
            raise ValueError(f"role book not found: {role_id}@{role_version}")
        return row

    @staticmethod
    def _revision_row(conn: sqlite3.Connection, revision_id: object) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM agent_role_book_revisions WHERE revision_id = ?",
            (str(revision_id),),
        ).fetchone()
        if row is None:
            raise ValueError(f"role book revision not found: {revision_id}")
        return row

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def compile_role_book_prompt(revision: Mapping[str, object]) -> str:
    status = str(revision.get("status") or "")
    if status not in _USABLE_REVISION_STATUSES:
        return ""
    sections = revision.get("sections")
    if not isinstance(sections, Mapping):
        return ""
    try:
        normalized_sections = _visible_sections({
            section: _normalize_items(sections.get(section), section=section)
            for section in _SECTION_LIMITS
        })
        role_id = _identifier(revision.get("roleId"), field="roleId", maximum=120)
        role_version = _identifier(
            revision.get("roleVersion"),
            field="roleVersion",
            maximum=80,
        )
    except (TypeError, ValueError):
        return ""
    try:
        base_persona = agent_role(role_id, role_version).persona_prompt
    except ValueError:
        base_persona = ""
    normalized_base = " ".join(base_persona.split()).casefold()
    prompt_sections = (
        ("personality", "协作偏好"),
        ("capabilities", "已验证能力"),
        ("lessonsAndLimits", "经验边界"),
    )
    lines = [ROLE_BOOK_PROMPT_PREFIX]
    for section, title in prompt_sections:
        raw_items = normalized_sections[section]
        section_lines: list[str] = []
        for item in raw_items[:_PROMPT_SECTION_ITEM_LIMIT]:
            if not isinstance(item, Mapping):
                continue
            text = str(item.get("text") or "").strip()
            provenance = item.get("provenance")
            evidence = item.get("evidenceIds")
            if (
                not text
                or not isinstance(provenance, Mapping)
                or not isinstance(evidence, Sequence)
            ):
                continue
            source_type = str(provenance.get("sourceType") or "").strip()
            source_id = str(provenance.get("sourceId") or "").strip()
            evidence_ids = [
                str(value).strip()
                for value in evidence
                if isinstance(value, str) and str(value).strip()
            ][:16]
            if not source_type or not source_id or not evidence_ids:
                continue
            if normalized_base and " ".join(text.split()).casefold() in normalized_base:
                continue
            # Provenance remains in the signed Role Book revision and Inspector.
            # The Provider needs the role memory itself, not internal IDs on every line.
            candidate = f"- {text}"
            projected = "\n".join([*lines, f"{title}：", *section_lines, candidate])
            if len(projected) > _MAX_PROMPT_CHARS:
                break
            section_lines.append(candidate)
        if section_lines:
            lines.append(f"{title}：")
            lines.extend(section_lines)
    if len(lines) == 1:
        return ""
    block = "\n".join(lines)
    return block[:_MAX_PROMPT_CHARS]


def _revision_payload(book: sqlite3.Row, row: sqlite3.Row) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": ROLE_BOOK_SCHEMA_VERSION,
        "revisionId": str(row["revision_id"]),
        "roleId": str(row["role_id"]),
        "roleVersion": str(row["role_version"]),
        "revisionNumber": int(row["revision_number"]),
        "status": str(row["status"]),
        "displayName": str(book["display_name"]),
        "mission": str(book["mission"]),
        "basePersonaVersion": str(book["base_persona_version"]),
        "sections": _stored_sections(row["content_json"]),
        "sourceRevisionId": str(row["source_revision_id"]),
        "changeSummary": str(row["change_summary"]),
        "proposedBy": str(row["proposed_by"]),
        "createdAtMs": int(row["created_at_ms"]),
        "activatedAtMs": _optional_int(row["activated_at_ms"]),
        "supersededAtMs": _optional_int(row["superseded_at_ms"]),
        "rolledBackAtMs": _optional_int(row["rolled_back_at_ms"]),
    }
    validate_contract(payload, "agent-role-book.v1.json")
    return payload


def _normalize_items(value: object, *, section: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{section} must be an array")
    limit = _SECTION_LIMITS[section]
    if len(value) > limit:
        raise ValueError(f"{section} must contain at most {limit} items")
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(value):
        if not isinstance(raw_item, Mapping):
            raise ValueError(f"{section}[{index}] must be an object")
        allowed_fields = {"itemId", "text", "provenance", "evidenceIds"}
        if section == "recentWork":
            allowed_fields.add("expiresAtMs")
        unexpected = sorted(
            str(key)
            for key in raw_item
            if key not in allowed_fields
        )
        if unexpected:
            raise ValueError(f"{section}[{index}] has unsupported fields: {', '.join(unexpected)}")
        text = _safe_text(
            raw_item.get("text"),
            field=f"{section}[{index}].text",
            maximum=_MAX_ITEM_TEXT,
            prompt_guard=True,
        )
        provenance = _normalize_provenance(
            raw_item.get("provenance"),
            field=f"{section}[{index}].provenance",
        )
        evidence_ids = _identifier_list(
            raw_item.get("evidenceIds"),
            field=f"{section}[{index}].evidenceIds",
            limit=16,
        )
        item_id = _identifier(
            raw_item.get("itemId"),
            field=f"{section}[{index}].itemId",
            maximum=160,
            allow_empty=True,
        )
        if not item_id:
            item_id = _derived_item_id(section, text, provenance, evidence_ids)
        if item_id in seen:
            raise ValueError(f"{section} contains duplicate itemId: {item_id}")
        seen.add(item_id)
        item: dict[str, object] = {
            "itemId": item_id,
            "text": text,
            "provenance": provenance,
            "evidenceIds": evidence_ids,
        }
        expires_at = raw_item.get("expiresAtMs")
        if expires_at is not None:
            if (
                section != "recentWork"
                or isinstance(expires_at, bool)
                or not isinstance(expires_at, int)
                or expires_at < 0
            ):
                raise ValueError(
                    f"{section}[{index}].expiresAtMs must be a non-negative integer"
                )
            item["expiresAtMs"] = expires_at
        normalized.append(item)
    return normalized


def normalize_role_book_review_item(
    value: Mapping[str, object],
    *,
    section: str,
) -> dict[str, object]:
    """Validate one generated review item at the same boundary as a revision."""

    if section not in _SECTION_LIMITS or section == "recentWork":
        raise ValueError("review proposals require a non-recentWork Role Book section")
    return _normalize_items([value], section=section)[0]


def _visible_sections(
    sections: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    at_ms: int | None = None,
) -> dict[str, list[dict[str, object]]]:
    timestamp = _timestamp(at_ms)
    visible: dict[str, list[dict[str, object]]] = {}
    for section in _SECTION_LIMITS:
        values: list[dict[str, object]] = []
        for raw in sections.get(section, ()):
            item = dict(raw)
            if section == "recentWork":
                expires_at = item.get("expiresAtMs")
                if isinstance(expires_at, int) and not isinstance(expires_at, bool):
                    if expires_at <= timestamp:
                        continue
            values.append(item)
        visible[section] = values
    return visible


def _merge_recent_work(
    incoming: Sequence[Mapping[str, object]],
    existing: Sequence[Mapping[str, object]],
    *,
    at_ms: int,
) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[str] = set()
    for source, values in (("incoming", incoming), ("existing", existing)):
        for raw in values:
            item = dict(raw)
            item_id = str(item.get("itemId") or "")
            if not item_id or item_id in seen:
                continue
            expires_at = item.get("expiresAtMs")
            if isinstance(expires_at, int) and not isinstance(expires_at, bool):
                if expires_at <= at_ms:
                    continue
            elif source == "existing":
                # Legacy recent-work rows receive a bounded lifetime on their
                # next safe consolidation instead of remaining forever.
                item["expiresAtMs"] = at_ms + _RECENT_WORK_TTL_MS
            seen.add(item_id)
            merged.append(item)
            if len(merged) >= _SECTION_LIMITS["recentWork"]:
                return merged
    return merged


def _verified_safe_recent_work(
    conn: sqlite3.Connection,
    value: object,
    *,
    project: str,
    role_id: str,
    at_ms: int,
) -> list[dict[str, object]]:
    """Replace untrusted receipt text with a structured, DB-verified summary."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("recentWork must be an array")
    if len(value) > _SECTION_LIMITS["recentWork"]:
        raise ValueError(
            f"recentWork must contain at most {_SECTION_LIMITS['recentWork']} items"
        )
    verified: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        normalized = _normalize_items([raw], section="recentWork")[0]
        evidence_ids = [str(item) for item in normalized["evidenceIds"]]
        placeholders = ", ".join("?" for _ in evidence_ids)
        rows = conn.execute(
            f"""
            SELECT *
            FROM agent_memory_evidence
            WHERE evidence_id IN ({placeholders})
            """,
            evidence_ids,
        ).fetchall()
        by_id = {str(row["evidence_id"]): row for row in rows}
        ordered: list[sqlite3.Row] = []
        for evidence_id in evidence_ids:
            evidence = by_id.get(evidence_id)
            if evidence is None:
                raise ValueError(
                    f"recentWork[{index}] evidence does not exist: {evidence_id}"
                )
            if (
                str(evidence["project"]) != project
                or str(evidence["role_id"]) != role_id
                or str(evidence["status"]) != "active"
            ):
                raise ValueError(
                    "recentWork evidence is inactive or belongs to another project/role"
                )
            source_kind = str(evidence["source_kind"])
            metadata = _json_mapping(evidence["metadata_json"])
            if source_kind == "tool_receipt":
                verified_state = metadata.get("applied") is True
            elif source_kind in {"work_receipt", "room_event"}:
                verified_state = metadata.get("accepted") is True
            else:
                verified_state = False
            if not verified_state:
                raise ValueError(
                    "recentWork evidence must be an applied or accepted receipt"
                )
            provenance = _json_mapping(evidence["provenance_json"])
            if (
                str(provenance.get("project") or "") != project
                or str(provenance.get("roleId") or "") != role_id
                or str(provenance.get("sourceType") or "") != source_kind
                or str(provenance.get("sourceId") or "")
                != str(evidence["source_id"])
            ):
                raise ValueError("recentWork evidence provenance does not match its row")
            ordered.append(evidence)
        item_id = str(normalized["itemId"])
        if item_id in seen:
            raise ValueError(f"recentWork contains duplicate itemId: {item_id}")
        seen.add(item_id)
        observed_at_ms = max(int(row["occurred_at_ms"]) for row in ordered)
        safe_item = {
            "itemId": item_id,
            "text": _structured_receipt_summary(ordered),
            "provenance": {
                "sourceType": "verified_receipt_summary",
                "sourceId": evidence_ids[0],
                "observedAtMs": observed_at_ms,
            },
            "evidenceIds": evidence_ids,
            "expiresAtMs": max(at_ms, observed_at_ms) + _RECENT_WORK_TTL_MS,
        }
        # Run the final prompt-boundary validation after replacing source text.
        verified.append(_normalize_items([safe_item], section="recentWork")[0])
    return verified


def _structured_receipt_summary(rows: Sequence[sqlite3.Row]) -> str:
    if len(rows) != 1:
        return f"已通过 {len(rows)} 条受治理回执验证近期工作"
    row = rows[0]
    source_kind = str(row["source_kind"])
    metadata = _json_mapping(row["metadata_json"])
    provenance = _json_mapping(row["provenance_json"])
    if source_kind == "tool_receipt":
        tool = _safe_structured_label(metadata.get("toolName"))
        operation = _safe_structured_label(metadata.get("operation"))
        if tool and operation:
            return f"已验证完成工具操作 {tool}.{operation}"
        return "已验证完成一次受审批工具操作"
    if source_kind == "work_receipt":
        work_item = _safe_structured_label(provenance.get("workItemId"))
        return (
            f"已验收工作项 {work_item}"
            if work_item
            else "已验收一项受治理工作"
        )
    event_type = _safe_structured_label(metadata.get("eventType"))
    return (
        f"已验收协作事件 {event_type}"
        if event_type
        else "已验收一次受治理协作事件"
    )


def _safe_structured_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text or len(text) > 80:
        return ""
    if not re.fullmatch(r"[\w.@:+/-]+", text, flags=re.UNICODE):
        return ""
    _reject_sensitive(text, field="receipt metadata")
    _reject_prompt_injection(text, field="receipt metadata")
    return text


def _json_mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _normalize_provenance(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    unexpected = sorted(
        str(key) for key in value if key not in {"sourceType", "sourceId", "observedAtMs"}
    )
    if unexpected:
        raise ValueError(f"{field} has unsupported fields: {', '.join(unexpected)}")
    observed = value.get("observedAtMs")
    if observed is not None:
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            raise ValueError(f"{field}.observedAtMs must be a non-negative integer or null")
    return {
        "sourceType": _identifier(
            value.get("sourceType"),
            field=f"{field}.sourceType",
            maximum=80,
        ),
        "sourceId": _identifier(
            value.get("sourceId"),
            field=f"{field}.sourceId",
            maximum=240,
        ),
        "observedAtMs": observed,
    }


def _identifier_list(value: object, *, field: str, limit: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field} must be an array")
    if not 1 <= len(value) <= limit:
        raise ValueError(f"{field} must contain between 1 and {limit} items")
    normalized = [
        _identifier(item, field=f"{field}[{index}]", maximum=240)
        for index, item in enumerate(value)
    ]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} must not contain duplicates")
    return normalized


def _validate_sections(sections: Mapping[str, object]) -> None:
    if set(sections) != set(_SECTION_LIMITS):
        raise ValueError("stored role book sections do not match the supported schema")
    for section in _SECTION_LIMITS:
        _normalize_items(sections[section], section=section)


def _stored_sections(value: object) -> dict[str, list[dict[str, object]]]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored role book content is not valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("stored role book content must be an object")
    if set(parsed) != set(_SECTION_LIMITS):
        raise ValueError("stored role book sections do not match the supported schema")
    return {
        section: _normalize_items(parsed[section], section=section)
        for section in _SECTION_LIMITS
    }


def _empty_sections() -> dict[str, list[dict[str, object]]]:
    return {section: [] for section in _SECTION_LIMITS}


def _initial_role_book_sections(
    role_id: str,
    role_version: str,
) -> dict[str, list[dict[str, object]]] | None:
    seed = builtin_role_book_seed(role_id, role_version)
    if seed is None:
        return None
    evidence_id = f"builtin-persona:{role_id}@{role_version}"
    sections: dict[str, list[dict[str, object]]] = {}
    for section in _SECTION_LIMITS:
        values = seed.get(section, ())
        sections[section] = [
            {
                "itemId": f"builtin:{role_id}:{section}:{index}",
                "text": text,
                "provenance": {
                    "sourceType": "builtin_persona_manifest",
                    "sourceId": evidence_id,
                    "observedAtMs": None,
                },
                "evidenceIds": [evidence_id],
            }
            for index, text in enumerate(values, start=1)
        ]
    _validate_sections(sections)
    return sections


def _is_empty_system_seed(row: sqlite3.Row) -> bool:
    if str(row["status"]) != "active" or int(row["revision_number"]) != 1:
        return False
    if str(row["proposed_by"]) != "system:seed":
        return False
    try:
        sections = _stored_sections(row["content_json"])
    except ValueError:
        return False
    return all(not values for values in sections.values())


def _assert_identity_matches(
    book: sqlite3.Row,
    *,
    display_name: str,
    mission: str,
    base_persona_version: str,
) -> None:
    requested = {
        "display_name": display_name,
        "mission": mission,
        "base_persona_version": base_persona_version,
    }
    for column, value in requested.items():
        if value and str(book[column] or "") != value:
            raise ValueError(f"role book {column} is immutable after seeding")


def _safe_text(
    value: object,
    *,
    field: str,
    maximum: int,
    allow_empty: bool = False,
    prompt_guard: bool = False,
) -> str:
    if not isinstance(value, str):
        if allow_empty and value is None:
            return ""
        raise ValueError(f"{field} must be a string")
    canonical = unicodedata.normalize("NFKC", value)
    if any(
        (ord(character) < 32 and not character.isspace())
        or unicodedata.category(character) == "Cf"
        for character in canonical
    ):
        raise ValueError(f"{field} contains unsupported control characters")
    normalized = " ".join(canonical.split())
    if not normalized and not allow_empty:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must not exceed {maximum} characters")
    _reject_sensitive(normalized, field=field)
    if prompt_guard:
        _reject_prompt_injection(normalized, field=field)
    return normalized


def _identifier(
    value: object,
    *,
    field: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if value is None and allow_empty:
        return ""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        if allow_empty:
            return ""
        raise ValueError(f"{field} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{field} must not exceed {maximum} characters")
    if any(
        character.isspace()
        or ord(character) < 33
        or unicodedata.category(character) == "Cf"
        for character in text
    ):
        raise ValueError(f"{field} must not contain whitespace or control characters")
    if not re.fullmatch(r"[\w.@:+/-]+", text, flags=re.UNICODE):
        raise ValueError(f"{field} contains unsupported characters")
    return text


def _reject_sensitive(text: str, *, field: str) -> None:
    if text and any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS):
        raise ValueError(f"{field} contains sensitive text")


def _reject_prompt_injection(text: str, *, field: str) -> None:
    if text and any(pattern.search(text) for pattern in _PROMPT_INJECTION_PATTERNS):
        raise ValueError(f"{field} contains prompt injection instructions")


def _derived_item_id(
    section: str,
    text: str,
    provenance: Mapping[str, object],
    evidence_ids: Sequence[str],
) -> str:
    digest = hashlib.sha256(
        _json(
            {
                "section": section,
                "text": text,
                "provenance": dict(provenance),
                "evidenceIds": list(evidence_ids),
            }
        ).encode("utf-8")
    ).hexdigest()[:20]
    return f"role-item:{digest}"


def _new_revision_id(role_id: str, role_version: str) -> str:
    role_slug = re.sub(r"[^\w.-]+", "-", role_id, flags=re.UNICODE).strip("-")[:48] or "role"
    version_slug = re.sub(r"[^\w.-]+", "-", role_version, flags=re.UNICODE).strip("-")[:24] or "v"
    return f"role-book:{role_slug}:{version_slug}:{uuid.uuid4()}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _timestamp(value: int | None) -> int:
    return int(time.time() * 1000) if value is None else max(0, int(value))


__all__ = [
    "AgentRoleBookStore",
    "ROLE_BOOK_PROMPT_PREFIX",
    "ROLE_BOOK_SCHEMA_VERSION",
    "ROLE_ROUTING_PROFILE_SCHEMA_VERSION",
    "compile_role_book_prompt",
    "normalize_role_book_review_item",
]
