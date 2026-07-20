from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Mapping

from .text_utils import compact_whitespace, now_ms


KNOWLEDGE_DOMAINS = frozenset(
    {
        "project_evidence",
        "room_public",
        "participant_private",
        "user_profile_preference",
        "document_library",
        "transient_session",
    }
)
SCOPE_KINDS = frozenset({"project", "room", "participant", "session", "user"})
VISIBILITIES = frozenset({"project", "room", "participant", "private"})


@dataclass(frozen=True)
class KnowledgeScope:
    owner_kind: str
    owner_id: str
    knowledge_domain: str
    scope_kind: str
    scope_id: str
    visibility: str
    authorization_revision: str
    binding_id: str
    scope_mode: str = "authoritative"

    def __post_init__(self) -> None:
        values = {
            field: compact_whitespace(str(getattr(self, field) or ""))
            for field in (
                "owner_kind",
                "owner_id",
                "knowledge_domain",
                "scope_kind",
                "scope_id",
                "visibility",
                "authorization_revision",
                "binding_id",
                "scope_mode",
            )
        }
        if values["scope_mode"] != "authoritative":
            raise ValueError("KnowledgeScope is only for authoritative bindings")
        if values["knowledge_domain"] not in KNOWLEDGE_DOMAINS:
            raise ValueError("unsupported knowledge domain")
        if values["scope_kind"] not in SCOPE_KINDS:
            raise ValueError("unsupported knowledge scope kind")
        if values["visibility"] not in VISIBILITIES:
            raise ValueError("unsupported knowledge visibility")
        if not all(values.values()):
            raise ValueError("authoritative knowledge scope is incomplete")
        for field, value in values.items():
            object.__setattr__(self, field, value)

    def columns(self) -> dict[str, str]:
        return {
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "knowledge_domain": self.knowledge_domain,
            "scope_kind": self.scope_kind,
            "scope_id": self.scope_id,
            "visibility": self.visibility,
            "authorization_revision": self.authorization_revision,
            "binding_id": self.binding_id,
            "scope_mode": self.scope_mode,
        }

    def metadata(self) -> dict[str, str]:
        return {
            "ownerKind": self.owner_kind,
            "ownerId": self.owner_id,
            "knowledgeDomain": self.knowledge_domain,
            "scopeKind": self.scope_kind,
            "scopeId": self.scope_id,
            "visibility": self.visibility,
            "authorizationRevision": self.authorization_revision,
            "bindingId": self.binding_id,
            "scopeMode": self.scope_mode,
        }


@dataclass(frozen=True)
class KnowledgeCallerContext:
    session_id: str
    participant_id: str
    room_id: str
    binding_id: str
    authorization_revision: str
    allowed_domains: tuple[str, ...]
    allowed_scopes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for field in (
            "session_id",
            "participant_id",
            "room_id",
            "binding_id",
            "authorization_revision",
        ):
            value = compact_whitespace(str(getattr(self, field) or ""))
            if not value:
                raise ValueError("authoritative Knowledge caller identity is incomplete")
            object.__setattr__(self, field, value)
        domains = tuple(dict.fromkeys(compact_whitespace(value) for value in self.allowed_domains))
        if not domains or any(value not in KNOWLEDGE_DOMAINS for value in domains):
            raise ValueError("Knowledge caller domains are invalid")
        scopes = tuple(
            dict.fromkeys(
                (compact_whitespace(kind), compact_whitespace(identity))
                for kind, identity in self.allowed_scopes
            )
        )
        if not scopes or any(kind not in SCOPE_KINDS or not identity for kind, identity in scopes):
            raise ValueError("Knowledge caller scopes are invalid")
        object.__setattr__(self, "allowed_domains", domains)
        object.__setattr__(self, "allowed_scopes", scopes)


def session_knowledge_scope(
    conn: sqlite3.Connection,
    session_id: str,
) -> tuple[str, KnowledgeScope | None, str]:
    """Resolve only server-persisted Room membership; never trust model owner input."""

    session = compact_whitespace(session_id)
    row = conn.execute(
        """
        SELECT id, room_id, session_id, participant_status
        FROM agent_room_participants WHERE session_id = ?
        """,
        (session,),
    ).fetchone()
    if row is None:
        return "legacy", None, ""
    if str(row["participant_status"]) not in {"active", "muted"}:
        return "quarantined", None, "room_participant_not_authorized"
    participant_id = str(row["id"])
    room_id = str(row["room_id"])
    binding_id, revision = _legacy_binding_identity(room_id, participant_id)
    return (
        "authoritative",
        KnowledgeScope(
            owner_kind="session",
            owner_id=session,
            knowledge_domain="participant_private",
            scope_kind="session",
            scope_id=session,
            visibility="private",
            authorization_revision=revision,
            binding_id=binding_id,
        ),
        "",
    )


def session_knowledge_caller(
    conn: sqlite3.Connection,
    session_id: str,
) -> KnowledgeCallerContext | None:
    session = compact_whitespace(session_id)
    row = conn.execute(
        """
        SELECT id, room_id, participant_status
        FROM agent_room_participants WHERE session_id = ?
        """,
        (session,),
    ).fetchone()
    if row is None or str(row["participant_status"]) not in {"active", "muted"}:
        return None
    participant_id = str(row["id"])
    room_id = str(row["room_id"])
    binding_id, revision = _legacy_binding_identity(room_id, participant_id)
    return KnowledgeCallerContext(
        session_id=session,
        participant_id=participant_id,
        room_id=room_id,
        binding_id=binding_id,
        authorization_revision=revision,
        allowed_domains=(
            "project_evidence",
            "room_public",
            "participant_private",
            "transient_session",
            "user_profile_preference",
        ),
        allowed_scopes=(("room", room_id), ("participant", participant_id), ("session", session)),
    )


def bound_session_knowledge_caller(
    conn: sqlite3.Connection,
    authenticated_session_id: str,
) -> KnowledgeCallerContext | None:
    """Build a caller only from a live ParticipantBinding owned by the authenticated Session."""

    session = compact_whitespace(authenticated_session_id)
    row = conn.execute(
        """SELECT binding.participant_binding_json,binding.room_binding_json,
                  binding.manifest_hash,binding.capability_epoch,
                  participant.id AS participant_id,participant.room_id,
                  participant.participant_status
           FROM room_v2_capability_runtime_bindings binding
           JOIN agent_room_participants participant ON participant.session_id=binding.session_id
           WHERE binding.session_id=? AND binding.state='active'
           ORDER BY binding.updated_at_ms DESC LIMIT 1""",
        (session,),
    ).fetchone()
    if row is None or str(row["participant_status"]) not in {"active", "muted"}:
        return None
    participant_binding = json.loads(str(row["participant_binding_json"]))
    room_binding = json.loads(str(row["room_binding_json"]))
    participant_id = str(row["participant_id"])
    room_id = str(row["room_id"])
    if (
        participant_binding.get("sessionId") != session
        or room_binding.get("participantId") != participant_id
        or room_binding.get("roomId") != room_id
        or participant_binding.get("roomBindingRef", {}).get("bindingId") != room_binding.get("bindingId")
    ):
        raise ValueError("live ParticipantBinding identity is inconsistent")
    binding_id = str(participant_binding.get("bindingId") or "")
    revision = "sha256:" + hashlib.sha256(
        f"{row['manifest_hash']}\0{row['capability_epoch']}\0{binding_id}".encode()
    ).hexdigest()
    return KnowledgeCallerContext(
        session_id=session,
        participant_id=participant_id,
        room_id=room_id,
        binding_id=binding_id,
        authorization_revision=revision,
        allowed_domains=("room_public", "participant_private", "document_library", "transient_session"),
        allowed_scopes=(("room", room_id), ("participant", participant_id), ("session", session)),
    )


def room_public_scope(
    conn: sqlite3.Connection,
    *,
    room_id: str,
    session_id: str,
) -> KnowledgeScope:
    caller = session_knowledge_caller(conn, session_id)
    room = compact_whitespace(room_id)
    if caller is None or caller.room_id != room:
        raise ValueError("Room evidence has no matching server-side participant binding")
    return KnowledgeScope(
        owner_kind="room",
        owner_id=room,
        knowledge_domain="room_public",
        scope_kind="room",
        scope_id=room,
        visibility="room",
        authorization_revision=caller.authorization_revision,
        binding_id=caller.binding_id,
    )


def scope_sql_predicate(
    caller: KnowledgeCallerContext | None,
    *,
    table_alias: str = "",
) -> tuple[str, tuple[str, ...]]:
    prefix = f"{table_alias}." if table_alias else ""
    if caller is None:
        return f"{prefix}scope_mode = 'legacy'", ()
    domain_marks = ", ".join("?" for _ in caller.allowed_domains)
    scope_clause = " OR ".join(
        f"({prefix}scope_kind = ? AND {prefix}scope_id = ?)"
        for _ in caller.allowed_scopes
    )
    params = (
        *caller.allowed_domains,
        *(value for scope in caller.allowed_scopes for value in scope),
    )
    return (
        f"({prefix}scope_mode = 'legacy' OR ("
        f"{prefix}scope_mode = 'authoritative' "
        f"AND {prefix}knowledge_domain IN ({domain_marks}) "
        f"AND ({scope_clause})))",
        tuple(params),
    )


def scope_visible(
    metadata: Mapping[str, object],
    caller: KnowledgeCallerContext | None,
) -> bool:
    mode = compact_whitespace(str(metadata.get("scopeMode") or "legacy"))
    if mode == "legacy":
        return True
    if mode != "authoritative" or caller is None:
        return False
    domain = compact_whitespace(str(metadata.get("knowledgeDomain") or ""))
    scope = (
        compact_whitespace(str(metadata.get("scopeKind") or "")),
        compact_whitespace(str(metadata.get("scopeId") or "")),
    )
    return domain in caller.allowed_domains and scope in caller.allowed_scopes


def scope_from_row(row: Mapping[str, object]) -> KnowledgeScope | None:
    mode = compact_whitespace(str(row.get("scope_mode") or "legacy"))
    if mode == "legacy":
        return None
    if mode != "authoritative":
        raise ValueError("knowledge source is quarantined")
    return KnowledgeScope(
        owner_kind=str(row.get("owner_kind") or ""),
        owner_id=str(row.get("owner_id") or ""),
        knowledge_domain=str(row.get("knowledge_domain") or ""),
        scope_kind=str(row.get("scope_kind") or ""),
        scope_id=str(row.get("scope_id") or ""),
        visibility=str(row.get("visibility") or ""),
        authorization_revision=str(row.get("authorization_revision") or ""),
        binding_id=str(row.get("binding_id") or ""),
    )


def quarantine_scope_issue(
    conn: sqlite3.Connection,
    *,
    source_table: str,
    source_id: str,
    reason_code: str,
    observed_scope: Mapping[str, object] | None = None,
    observed_at_ms: int | None = None,
) -> str:
    timestamp = now_ms() if observed_at_ms is None else max(0, int(observed_at_ms))
    identity = f"{source_table}\0{source_id}\0{reason_code}"
    quarantine_id = "knowledge-quarantine:" + hashlib.sha256(identity.encode()).hexdigest()[:32]
    conn.execute(
        """
        INSERT INTO knowledge_scope_quarantine(
            quarantine_id, source_table, source_id, reason_code,
            observed_scope_json, first_observed_at_ms, last_observed_at_ms,
            observation_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(source_table, source_id, reason_code) DO UPDATE SET
            observed_scope_json = excluded.observed_scope_json,
            last_observed_at_ms = excluded.last_observed_at_ms,
            observation_count = knowledge_scope_quarantine.observation_count + 1
        """,
        (
            quarantine_id,
            compact_whitespace(source_table),
            compact_whitespace(source_id),
            compact_whitespace(reason_code),
            json.dumps(dict(observed_scope or {}), ensure_ascii=False, sort_keys=True),
            timestamp,
            timestamp,
        ),
    )
    return quarantine_id


def record_shadow_diff(
    conn: sqlite3.Connection,
    *,
    query: str,
    primary_refs: tuple[str, ...],
    shadow_refs: tuple[str, ...],
    root_id: str = "",
    session_id: str = "",
    created_at_ms: int | None = None,
) -> dict[str, object]:
    """Persist a comparison of already-produced refs; this cannot execute retrieval."""

    timestamp = now_ms() if created_at_ms is None else max(0, int(created_at_ms))
    primary = tuple(dict.fromkeys(compact_whitespace(value) for value in primary_refs if compact_whitespace(value)))
    shadow = tuple(dict.fromkeys(compact_whitespace(value) for value in shadow_refs if compact_whitespace(value)))
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    identity = json.dumps([root_id, session_id, query_hash, primary, shadow], ensure_ascii=False)
    diff_id = "knowledge-shadow:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    added = tuple(value for value in shadow if value not in primary)
    removed = tuple(value for value in primary if value not in shadow)
    conn.execute(
        """
        INSERT INTO knowledge_shadow_diffs(
            diff_id, root_id, session_id, query_hash, primary_refs_json,
            shadow_refs_json, added_refs_json, removed_refs_json, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(root_id, session_id, query_hash, primary_refs_json, shadow_refs_json)
        DO NOTHING
        """,
        (
            diff_id,
            compact_whitespace(root_id),
            compact_whitespace(session_id),
            query_hash,
            json.dumps(primary, ensure_ascii=False),
            json.dumps(shadow, ensure_ascii=False),
            json.dumps(added, ensure_ascii=False),
            json.dumps(removed, ensure_ascii=False),
            timestamp,
        ),
    )
    return {"diffId": diff_id, "addedRefs": list(added), "removedRefs": list(removed)}


def _legacy_binding_identity(room_id: str, participant_id: str) -> tuple[str, str]:
    material = f"{room_id}\0{participant_id}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    return f"legacy-room-participant:{participant_id}", f"sha256:{digest}"
