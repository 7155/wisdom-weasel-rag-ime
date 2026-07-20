from __future__ import annotations


BUILTIN_ROLE_IDS = (
    "companion-future-v1",
    "companion-present-v1",
    "companion-firstlight-v1",
    "companion-flash-v1",
)

_LEGACY_BUILTIN_ROLE_IDS = {
    "vcp-v1": "companion-future-v1",
    "zhiyou-v1": "companion-present-v1",
    "hermes-v1": "companion-firstlight-v1",
    "flash-v1": "companion-flash-v1",
}


def canonical_agent_role_id(value: object) -> str:
    """Translate retired builtin IDs at the persistence compatibility edge."""

    role_id = str(value or "").strip()
    return _LEGACY_BUILTIN_ROLE_IDS.get(role_id, role_id)


def canonical_role_book_revision_id(value: object) -> str:
    revision_id = str(value or "").strip()
    if not revision_id.startswith("role-book:"):
        return revision_id
    prefix, _, suffix = revision_id.partition(":")
    role_id, separator, remainder = suffix.partition(":")
    if not separator:
        return revision_id
    canonical = canonical_agent_role_id(role_id)
    return f"{prefix}:{canonical}:{remainder}"


def is_legacy_builtin_role_id(value: object) -> bool:
    return str(value or "").strip() in _LEGACY_BUILTIN_ROLE_IDS


__all__ = [
    "BUILTIN_ROLE_IDS",
    "canonical_agent_role_id",
    "canonical_role_book_revision_id",
    "is_legacy_builtin_role_id",
]
