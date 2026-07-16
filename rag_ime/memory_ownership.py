from __future__ import annotations

from collections.abc import Iterable

from .text_utils import compact_whitespace


MEMORY_OWNER_KINDS = frozenset({"user", "shared", "agent", "session", "room"})
MemoryOwner = tuple[str, str]


def normalize_memory_owner(owner_kind: object, owner_id: object) -> MemoryOwner:
    kind = compact_whitespace(str(owner_kind or ""))
    identity = compact_whitespace(str(owner_id or ""))
    if kind not in MEMORY_OWNER_KINDS:
        raise ValueError("unsupported memory owner kind")
    if not identity:
        raise ValueError("memory owner id must not be empty")
    return kind, identity


def default_visible_memory_owners(*, project: str = "") -> tuple[MemoryOwner, ...]:
    owners: list[MemoryOwner] = [("user", "default"), ("shared", "default")]
    normalized_project = compact_whitespace(project)
    if normalized_project and normalized_project != "default":
        owners.append(("shared", normalized_project))
    return tuple(owners)


def agent_visible_memory_owners(
    *,
    project: str = "",
    role_id: str = "",
    session_id: str = "",
    room_ids: Iterable[str] = (),
) -> tuple[MemoryOwner, ...]:
    owners = list(default_visible_memory_owners(project=project))
    normalized_role = compact_whitespace(role_id)
    normalized_session = compact_whitespace(session_id)
    if normalized_role:
        owners.append(("agent", normalized_role))
    if normalized_session:
        owners.append(("session", normalized_session))
    for room_id in room_ids:
        normalized_room = compact_whitespace(room_id)
        if normalized_room:
            owners.append(("room", normalized_room))
    return _unique_owners(owners)


def resolve_visible_memory_owners(
    values: Iterable[tuple[str, str]],
    *,
    project: str = "",
) -> tuple[MemoryOwner, ...]:
    requested = tuple(values)
    if not requested:
        return default_visible_memory_owners(project=project)
    return _unique_owners(normalize_memory_owner(kind, identity) for kind, identity in requested)


def sql_memory_owner_predicate(
    owners: Iterable[MemoryOwner],
    *,
    table_alias: str = "",
) -> tuple[str, tuple[str, ...]]:
    resolved = tuple(normalize_memory_owner(kind, identity) for kind, identity in owners)
    if not resolved:
        return "0 = 1", ()
    prefix = f"{table_alias}." if table_alias else ""
    clause = " OR ".join(
        f"({prefix}owner_kind = ? AND {prefix}owner_id = ?)"
        for _ in resolved
    )
    params = tuple(value for owner in resolved for value in owner)
    return f"({clause})", params


def _unique_owners(values: Iterable[MemoryOwner]) -> tuple[MemoryOwner, ...]:
    seen: set[MemoryOwner] = set()
    result: list[MemoryOwner] = []
    for value in values:
        owner = normalize_memory_owner(*value)
        if owner not in seen:
            seen.add(owner)
            result.append(owner)
    return tuple(result)
