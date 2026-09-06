from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping

from .memory_ingest import normalize_text
from .sensitive_content import redact_sensitive_text
from .text_utils import compact_whitespace, stable_text_hash, truncate_text


MEMORY_CURATION_DECISION_SCHEMA_VERSION = "rag-ime.memory-curation-decisions.v1"
MEMORY_CURATION_MODEL_BUNDLE_SCHEMA_VERSION = "rag-ime.memory-curation-model-bundle.v1"
MEMORY_CURATION_ARCHITECTURE = "atom-first-v1"

_GROUP_ID_RE = re.compile(r"^group:[a-z0-9][a-z0-9._-]{1,63}$")
_PINYIN_RE = re.compile(r"^[a-zv]+(?: [a-zv]+)*$")
_SAFE_KEY_RE = re.compile(r"[^a-z0-9._-]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_TAG_NOISE = {
    "使用中",
    "已记录",
    "本地记忆",
    "来源",
    "其他来源",
    "短语",
    "已确认",
    "当前",
    "弹出",
    "稳定",
    "不是",
    "那个",
}
_KIND_MAP = {
    "fact": "personal_fact",
    "personal_fact": "personal_fact",
    "habit": "personal_habit",
    "personal_habit": "personal_habit",
    "preference": "durable_preference",
    "durable_preference": "durable_preference",
    "principle": "personal_principle",
    "personal_principle": "personal_principle",
    "project_fact": "project_fact",
    "requirement": "project_requirement",
    "project_requirement": "project_requirement",
    "decision": "project_decision",
    "project_decision": "project_decision",
    "constraint": "project_constraint",
    "project_constraint": "project_constraint",
    "security_constraint": "security_constraint",
    "plan": "project_plan",
    "project_plan": "project_plan",
    "question": "project_question",
    "project_question": "project_question",
}

_ATOM_AUTHORITY_FIELDS = (
    "ownerKind",
    "ownerId",
    "privacyLevel",
    "knowledgeDomain",
    "scopeKind",
    "scopeId",
    "visibility",
    "authorizationRevision",
    "bindingId",
    "scopeMode",
)
_ATOM_IDENTITY_FIELDS = (
    "text",
    "canonicalText",
    "kind",
    "language",
    "project",
    "app",
    "claimKey",
    "lineageId",
    "claimState",
    "validFromMs",
    "validToMs",
    "supersedesId",
    "status",
    *_ATOM_AUTHORITY_FIELDS,
)
_SEMANTIC_CATALOG_MAINTENANCE_KEYS = {
    "updatedAtMs",
    "updated_at_ms",
    "archivedAtMs",
    "archived_at_ms",
    "lastActiveAtMs",
    "last_active_at_ms",
}


def _atom_field(item: Mapping[str, object], field: str) -> object:
    aliases = {
        "canonicalText": ("canonicalText", "canonical_text"),
        "claimKey": ("claimKey", "claim_key"),
        "lineageId": ("lineageId", "lineage_id"),
        "claimState": ("claimState", "claim_state"),
        "validFromMs": ("validFromMs", "valid_from_ms"),
        "validToMs": ("validToMs", "valid_to_ms"),
        "supersedesId": ("supersedesId", "supersedes_id"),
        "ownerKind": ("ownerKind", "owner_kind"),
        "ownerId": ("ownerId", "owner_id"),
        "privacyLevel": ("privacyLevel", "privacy_level"),
        "knowledgeDomain": ("knowledgeDomain", "knowledge_domain"),
        "scopeKind": ("scopeKind", "scope_kind"),
        "scopeId": ("scopeId", "scope_id"),
        "authorizationRevision": (
            "authorizationRevision",
            "authorization_revision",
        ),
        "bindingId": ("bindingId", "binding_id"),
        "scopeMode": ("scopeMode", "scope_mode"),
    }
    for candidate in aliases.get(field, (field,)):
        if candidate in item:
            return item.get(candidate)
    return None


def _atom_identity_material(item: Mapping[str, object]) -> dict[str, object]:
    return {
        field: _atom_field(item, field)
        for field in _ATOM_IDENTITY_FIELDS
    }


def memory_atom_identity_hash(item: Mapping[str, object]) -> str:
    """Hash raw Atom identity without exposing private authority values."""

    return stable_text_hash(
        json.dumps(
            _atom_identity_material(item),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def memory_atom_authority_hash(item: Mapping[str, object]) -> str:
    """Hash the complete owner/privacy/scope/binding authority tuple."""

    return stable_text_hash(
        json.dumps(
            {
                field: _atom_field(item, field)
                for field in _ATOM_AUTHORITY_FIELDS
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _semantic_catalog_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _semantic_catalog_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _SEMANTIC_CATALOG_MAINTENANCE_KEYS
        }
    if isinstance(value, (list, tuple, set)):
        items = [_semantic_catalog_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return value


def _is_global_catalog_audit(bundle: Mapping[str, object]) -> bool:
    return (
        compact_whitespace(str(bundle.get("curationScope") or "")).lower()
        == "global"
        and bool(bundle.get("catalogAudit"))
    )

def _canonical_catalog_value(value: object) -> object:
    return _semantic_catalog_value(value)


def memory_catalog_digest(bundle: Mapping[str, object]) -> str:
    """Return an order-independent semantic identity for the complete catalog."""

    catalog = {
        "atoms": bundle.get("existingMemoryAtoms", bundle.get("existingAtoms", [])),
        "books": bundle.get("existingMemoryBooks", bundle.get("existingBooks", [])),
        "groups": bundle.get("existingSemanticGroups", bundle.get("existingGroups", [])),
        "tags": bundle.get("existingSemanticTags", bundle.get("existingTags", [])),
        "edges": bundle.get("existingTagEdges", bundle.get("edges", [])),
        "atomTagRelations": bundle.get("existingAtomTagRelations", []),
        "atomGroupMemberships": bundle.get("existingAtomGroupMemberships", []),
        "tagProfiles": bundle.get("existingTagProfiles", []),
        "groupMembers": bundle.get("existingSemanticGroupMembers", []),
    }
    canonical = _canonical_catalog_value(catalog)
    return stable_text_hash(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )




def _is_complete_global_catalog(bundle: Mapping[str, object]) -> bool:
    return _is_global_catalog_audit(bundle) and bool(bundle.get("catalogComplete"))


def build_memory_curation_model_bundle(bundle: Mapping[str, object]) -> dict[str, object]:
    """Expose compact stable references for one Atom-first curation snapshot."""

    curation_scope = (
        "global"
        if compact_whitespace(str(bundle.get("curationScope") or "")).lower()
        == "global"
        else "incremental"
    )
    catalog_audit = bool(bundle.get("catalogAudit"))
    raw_atoms = _dicts(bundle.get("existingMemoryAtoms"))
    raw_groups = _dicts(bundle.get("existingSemanticGroups"))
    raw_tags = _dicts(bundle.get("existingSemanticTags"))
    raw_edges = _dicts(bundle.get("existingTagEdges"))
    raw_books = _dicts(bundle.get("existingMemoryBooks"))
    # Owner-scoped Atom-first bundles carry a complete identity-only Book
    # index beside the bounded recalled Book bodies.  Keep that distinction
    # through the compact model bundle; global catalog bundles can derive the
    # same index from their complete Book snapshot below.
    raw_book_index = _dicts(bundle.get("existingMemoryBookIndex"))
    upstream_truncation = {
        str(key): bool(value)
        for key, value in dict(bundle.get("catalogTruncated") or {}).items()
        if str(key)
    }
    declared_complete = (
        bool(bundle.get("catalogComplete"))
        if "catalogComplete" in bundle
        else not any(upstream_truncation.values())
        if catalog_audit
        else True
    )
    global_catalog = (
        curation_scope == "global"
        and catalog_audit
        and declared_complete
        and not any(upstream_truncation.values())
    )
    atoms_source = raw_atoms if global_catalog else raw_atoms[:500]
    groups_source = raw_groups if global_catalog else raw_groups[:24]
    tags_source = raw_tags if global_catalog else raw_tags[:160]
    books_source = raw_books if global_catalog else raw_books[:48]
    edges_source = raw_edges if global_catalog else raw_edges[:240]

    def catalog_strings(value: object, *, incremental_limit: int) -> list[str]:
        limit = (
            max(incremental_limit, len(_items(value)))
            if global_catalog
            else incremental_limit
        )
        return _strings(value, limit=limit)

    def catalog_text(value: object, *, max_chars: int) -> str:
        text = compact_whitespace(str(value or ""))
        return text if global_catalog else text[:max_chars]

    evidence: list[dict[str, object]] = []
    for item in _dicts(bundle.get("recentEvents")):
        if item.get("finalized") is False or item.get("memoryEligible") is False:
            continue
        text = compact_whitespace(str(item.get("text") or ""))
        source_ids = _positive_ints(item.get("sourceEventIds") or [item.get("eventId")])
        if not text or not source_ids:
            continue
        local_context = compact_whitespace(
            redact_sensitive_text(item.get("recentContext"))
        )
        if local_context == text:
            local_context = ""
        evidence.append(
            {
                "ref": f"E{len(evidence) + 1}",
                "sourceRef": compact_whitespace(str(item.get("sourceRef") or "")),
                "eventIds": source_ids,
                # Batch admission already enforces a token budget. Truncating
                # one admitted source here can hide a trailing correction while
                # still claiming that its complete Evidence was processed.
                "text": text,
                **({"decisionContext": dict(item["decisionContext"])}
                   if isinstance(item.get("decisionContext"), Mapping) else {}),
                "app": compact_whitespace(str(item.get("app") or ""))[:120],
                "createdAtMs": _int(item.get("createdAtMs")),
                "sourceOccurredAtMs": _int(item.get("sourceOccurredAtMs") or item.get("createdAtMs")),
                "project": compact_whitespace(str(item.get("project") or bundle.get("project") or "")),
                "sourceKind": compact_whitespace(str(item.get("sourceKind") or item.get("source") or "")),
                "contextGroupId": compact_whitespace(
                    str(item.get("contextGroupId") or "")
                )[:120],
                "localContext": local_context[-800:],
            }
        )

    atoms = [
        {
            "ref": f"P{index}",
            "atomId": compact_whitespace(str(item.get("atomId") or item.get("id") or "")),
            "identityHash": compact_whitespace(
                str(item.get("identityHash") or memory_atom_identity_hash(item))
            ),
            "authorityHash": compact_whitespace(
                str(item.get("authorityHash") or memory_atom_authority_hash(item))
            ),
            "kind": compact_whitespace(str(item.get("kind") or "project_fact")),
            "claimKey": compact_whitespace(str(item.get("claimKey") or "")),
            "lineageId": compact_whitespace(str(item.get("lineageId") or "")),
            "claimState": compact_whitespace(
                str(item.get("claimState") or "current")
            ),
            "validFromMs": _int(item.get("validFromMs")),
            "validToMs": (
                _int(item.get("validToMs"))
                if item.get("validToMs") is not None
                else None
            ),
            "supersedesId": compact_whitespace(
                str(item.get("supersedesId") or "")
            ),
            "text": catalog_text(
                item.get("canonicalText") or item.get("text"),
                max_chars=500,
            ),
            "tags": catalog_strings(item.get("tags"), incremental_limit=16),
            "groupIds": catalog_strings(
                item.get("semanticGroupIds") or item.get("groupIds"),
                incremental_limit=8,
            ),
            "aliases": catalog_strings(item.get("aliases"), incremental_limit=48),
            "surfaceHints": catalog_strings(
                item.get("surfaceHints"),
                incremental_limit=32,
            ),
            "queryExpansions": catalog_strings(
                item.get("queryExpansions"),
                incremental_limit=48,
            ),
            "sourceMemoryIds": catalog_strings(
                item.get("sourceMemoryIds"),
                incremental_limit=64,
            ),
            "sourceEventIds": _positive_ints(item.get("sourceEventIds")),
            "app": catalog_text(item.get("app"), max_chars=120),
            "project": catalog_text(item.get("project"), max_chars=120),
            "knowledgeDomain": compact_whitespace(
                str(item.get("knowledgeDomain") or "")
            ),
            "scopeKind": compact_whitespace(str(item.get("scopeKind") or "")),
            "scopeId": compact_whitespace(str(item.get("scopeId") or "")),
            "visibility": compact_whitespace(str(item.get("visibility") or "")),
            "authorizationRevision": compact_whitespace(
                str(item.get("authorizationRevision") or "")
            ),
            "bindingId": compact_whitespace(str(item.get("bindingId") or "")),
            "scopeMode": compact_whitespace(str(item.get("scopeMode") or "")),
            "status": compact_whitespace(str(item.get("status") or "active")),
            "confidence": _float(item.get("confidence"), default=0.0),
            "qualityScore": _float(item.get("qualityScore"), default=0.0),
            "tagRelationsHash": compact_whitespace(
                str(item.get("tagRelationsHash") or "")
            ),
            "groupMembershipsHash": compact_whitespace(
                str(item.get("groupMembershipsHash") or "")
            ),
            "aliasRecordsHash": compact_whitespace(
                str(item.get("aliasRecordsHash") or "")
            ),
        }
        for index, item in enumerate(atoms_source, start=1)
        if compact_whitespace(str(item.get("atomId") or item.get("id") or ""))
        and catalog_text(
            item.get("canonicalText") or item.get("text"),
            max_chars=500,
        )
    ]
    atom_ref_by_id = {
        compact_whitespace(str(item.get("atomId") or "")): str(item["ref"])
        for item in atoms
        if compact_whitespace(str(item.get("atomId") or ""))
    }
    groups = [
        {
            "ref": f"G{index}",
            "groupId": compact_whitespace(str(item.get("groupId") or "")),
            "title": catalog_text(item.get("title"), max_chars=80),
            "description": catalog_text(item.get("description"), max_chars=240),
            "project": catalog_text(item.get("project"), max_chars=120),
            "aliases": catalog_strings(item.get("aliases"), incremental_limit=12),
            "tags": catalog_strings(item.get("tags"), incremental_limit=16),
            "confidence": _float(item.get("confidence"), default=0.0),
            "qualityScore": _float(item.get("qualityScore"), default=0.0),
            "metadataHash": compact_whitespace(
                str(item.get("metadataHash") or "")
            ),
            "memberMetadataHash": compact_whitespace(
                str(item.get("memberMetadataHash") or "")
            ),
        }
        for index, item in enumerate(groups_source, start=1)
        if compact_whitespace(str(item.get("groupId") or ""))
    ]
    tags = [
        {
            "ref": f"T{index}",
            "tagId": item.get("tagId"),
            "name": catalog_text(item.get("name"), max_chars=80),
            "description": catalog_text(item.get("description"), max_chars=200),
            "aliases": catalog_strings(item.get("aliases"), incremental_limit=16),
            "groupIds": catalog_strings(
                item.get("semanticGroupIds"),
                incremental_limit=8,
            ),
            "type": compact_whitespace(str(item.get("type") or "concept")),
            "degree": _int(item.get("degree")),
            "qualityScore": _float(item.get("qualityScore"), default=0.0),
            "metadataHash": compact_whitespace(
                str(item.get("metadataHash") or "")
            ),
            "profileHash": compact_whitespace(
                str(item.get("profileHash") or "")
            ),
            "groupMembershipsHash": compact_whitespace(
                str(item.get("groupMembershipsHash") or "")
            ),
        }
        for index, item in enumerate(tags_source, start=1)
        if compact_whitespace(str(item.get("name") or ""))
    ]
    tag_ref_by_name = {
        normalize_text(str(item["name"])): str(item["ref"])
        for item in tags
        if normalize_text(str(item["name"]))
    }
    tag_ref_by_id = {
        str(item["tagId"]): str(item["ref"])
        for item in tags
        if item.get("tagId") not in (None, "")
    }
    edges: list[dict[str, object]] = []
    for item in edges_source:
        source_ref = tag_ref_by_id.get(
            str(item.get("srcTagId") or ""),
            "",
        ) or tag_ref_by_name.get(
            normalize_text(str(item.get("src") or "")),
            "",
        )
        target_ref = tag_ref_by_id.get(
            str(item.get("dstTagId") or ""),
            "",
        ) or tag_ref_by_name.get(
            normalize_text(str(item.get("dst") or "")),
            "",
        )
        if not source_ref or not target_ref:
            continue
        edges.append(
            {
                "sourceRef": source_ref,
                "targetRef": target_ref,
                "type": compact_whitespace(
                    str(item.get("edgeType") or "related_to")
                ),
                "weight": _float(item.get("weight"), default=0.5),
                "directionBias": _float(
                    item.get("directionBias"),
                    default=0.0,
                ),
                "evidenceCount": _int(item.get("evidenceCount")),
                "metadataHash": compact_whitespace(
                    str(item.get("metadataHash") or "")
                ),
            }
        )
    books = [
        {
            "ref": f"B{index}",
            "bookId": compact_whitespace(str(item.get("bookId") or "")),
            "bookKey": catalog_text(item.get("bookKey"), max_chars=120),
            "title": catalog_text(item.get("title"), max_chars=100),
            "summary": catalog_text(item.get("summary"), max_chars=320),
            "aliases": catalog_strings(item.get("aliases"), incremental_limit=32),
            "tags": catalog_strings(item.get("tags"), incremental_limit=16),
            "surfaceHints": catalog_strings(
                item.get("surfaceHints"),
                incremental_limit=32,
            ),
            "queryExpansions": catalog_strings(
                item.get("queryExpansions"),
                incremental_limit=48,
            ),
            "groupIds": catalog_strings(
                item.get("semanticGroupIds"),
                incremental_limit=8,
            ),
            "atomIds": catalog_strings(
                item.get("memoryAtomIds"),
                incremental_limit=80,
            ),
            "atomRefs": [
                atom_ref_by_id[atom_id]
                for atom_id in catalog_strings(
                    item.get("memoryAtomIds"),
                    incremental_limit=80,
                )
                if atom_id in atom_ref_by_id
            ],
            "memberAtoms": [
                {"atomId": atom_id, "atomRef": atom_ref_by_id[atom_id]}
                for atom_id in catalog_strings(
                    item.get("memoryAtomIds"),
                    incremental_limit=80,
                )
                if atom_id in atom_ref_by_id
            ],
            "bookType": compact_whitespace(
                str(item.get("bookType") or "topic")
            ),
            "createdAtMs": _int(item.get("createdAtMs")),
            "project": catalog_text(item.get("project"), max_chars=120),
            "app": catalog_text(item.get("app"), max_chars=120),
            "ownerKind": compact_whitespace(str(item.get("ownerKind") or "")),
            "ownerId": compact_whitespace(str(item.get("ownerId") or "")),
            "knowledgeDomain": compact_whitespace(
                str(item.get("knowledgeDomain") or "")
            ),
            "scopeKind": compact_whitespace(str(item.get("scopeKind") or "")),
            "scopeId": compact_whitespace(str(item.get("scopeId") or "")),
            "visibility": compact_whitespace(str(item.get("visibility") or "")),
            "authorizationRevision": compact_whitespace(
                str(item.get("authorizationRevision") or "")
            ),
            "bindingId": compact_whitespace(str(item.get("bindingId") or "")),
            "scopeMode": compact_whitespace(str(item.get("scopeMode") or "")),
            "metadataHash": compact_whitespace(
                str(item.get("metadataHash") or "")
            ),
            "contentHash": compact_whitespace(
                str(item.get("contentHash") or "")
            ),
            "status": compact_whitespace(str(item.get("status") or "active")),
            "supersededByBookId": compact_whitespace(
                str(item.get("supersededByBookId") or "")
            ),
        }
        for index, item in enumerate(books_source, start=1)
        if compact_whitespace(str(item.get("bookId") or ""))
    ]

    # ``existingBooks`` is the bounded body view.  ``existingMemoryBookIndex``
    # is the complete identity view used for continuity lookup.  Prefer an
    # upstream owner index when present, then overlay the bounded body only
    # for fields it actually supplies; global snapshots naturally use all
    # Books.  Member IDs stay physical, while P* refs are supplied whenever
    # the corresponding Atom is in this same compact snapshot.
    raw_book_index_by_id: dict[str, dict[str, object]] = {}
    for item in raw_book_index:
        book_id = compact_whitespace(str(item.get("bookId") or ""))
        if book_id:
            raw_book_index_by_id[book_id] = dict(item)
    for item in raw_books:
        book_id = compact_whitespace(str(item.get("bookId") or ""))
        if not book_id:
            continue
        previous = raw_book_index_by_id.get(book_id)
        if previous is None:
            raw_book_index_by_id[book_id] = dict(item)
            continue
        merged = dict(previous)
        for field, value in item.items():
            if field in {
                "aliases",
                "tags",
                "queryExpansions",
                "semanticGroupIds",
                "groupIds",
                "memoryAtomIds",
                "atomIds",
                "sourceEventIds",
            }:
                merged[field] = list(
                    dict.fromkeys(
                        [
                            *_items(previous.get(field)),
                            *_items(value),
                        ]
                    )
                )
            elif field not in merged or merged[field] in (None, "", []):
                merged[field] = value
        raw_book_index_by_id[book_id] = merged
    book_index: list[dict[str, object]] = []
    for item in raw_book_index_by_id.values():
        book_id = compact_whitespace(str(item.get("bookId") or ""))
        member_ids = catalog_strings(
            item.get("memoryAtomIds") or item.get("atomIds"),
            incremental_limit=256,
        )
        atom_refs = [
            atom_ref_by_id[atom_id]
            for atom_id in member_ids
            if atom_id in atom_ref_by_id
        ]
        book_index.append(
            {
                "bookId": book_id,
                "bookType": compact_whitespace(
                    str(item.get("bookType") or "topic")
                ),
                "bookKey": catalog_text(item.get("bookKey"), max_chars=120),
                "title": catalog_text(item.get("title"), max_chars=100),
                "aliases": catalog_strings(item.get("aliases"), incremental_limit=64),
                "tags": catalog_strings(item.get("tags"), incremental_limit=32),
                "queryExpansions": catalog_strings(
                    item.get("queryExpansions"), incremental_limit=64
                ),
                "semanticGroupIds": catalog_strings(
                    item.get("semanticGroupIds") or item.get("groupIds"),
                    incremental_limit=16,
                ),
                "memoryAtomIds": member_ids,
                "atomRefs": atom_refs,
                "memberAtoms": [
                    {"atomId": atom_id, "atomRef": atom_ref_by_id[atom_id]}
                    for atom_id in member_ids
                    if atom_id in atom_ref_by_id
                ],
                "sourceEventIds": _positive_ints(item.get("sourceEventIds")),
                "createdAtMs": _int(item.get("createdAtMs")),
                "project": catalog_text(item.get("project"), max_chars=120),
                "app": catalog_text(item.get("app"), max_chars=120),
                "ownerKind": compact_whitespace(str(item.get("ownerKind") or "")),
                "ownerId": compact_whitespace(str(item.get("ownerId") or "")),
                "knowledgeDomain": compact_whitespace(
                    str(item.get("knowledgeDomain") or "")
                ),
                "scopeKind": compact_whitespace(str(item.get("scopeKind") or "")),
                "scopeId": compact_whitespace(str(item.get("scopeId") or "")),
                "visibility": compact_whitespace(str(item.get("visibility") or "")),
                "authorizationRevision": compact_whitespace(
                    str(item.get("authorizationRevision") or "")
                ),
                "bindingId": compact_whitespace(str(item.get("bindingId") or "")),
                "scopeMode": compact_whitespace(str(item.get("scopeMode") or "")),
                "status": compact_whitespace(str(item.get("status") or "active")),
                "supersededByBookId": compact_whitespace(
                    str(item.get("supersededByBookId") or "")
                ),
            }
        )

    catalog_truncated = {
        "atoms": len(raw_atoms) > len(atoms),
        "groups": len(raw_groups) > len(groups),
        "tags": len(raw_tags) > len(tags),
        "books": len(raw_books) > len(books),
        "edges": len(raw_edges) > len(edges),
        "atomTags": (
            not global_catalog
            and any(len(_items(item.get("tags"))) > 16 for item in raw_atoms[:500])
        ),
        "atomGroups": (
            not global_catalog
            and any(
                len(_items(item.get("semanticGroupIds") or item.get("groupIds"))) > 8
                for item in raw_atoms[:500]
            )
        ),
        "atomAliases": (
            not global_catalog
            and any(len(_items(item.get("aliases"))) > 48 for item in raw_atoms[:500])
        ),
        "atomSurfaceHints": (
            not global_catalog
            and any(
                len(_items(item.get("surfaceHints"))) > 32
                for item in raw_atoms[:500]
            )
        ),
        "atomQueryExpansions": (
            not global_catalog
            and any(
                len(_items(item.get("queryExpansions"))) > 48
                for item in raw_atoms[:500]
            )
        ),
        "atomSourceMemoryIds": (
            not global_catalog
            and any(
                len(_items(item.get("sourceMemoryIds"))) > 64
                for item in raw_atoms[:500]
            )
        ),
        "groupAliases": (
            not global_catalog
            and any(len(_items(item.get("aliases"))) > 12 for item in raw_groups[:24])
        ),
        "groupTags": (
            not global_catalog
            and any(len(_items(item.get("tags"))) > 16 for item in raw_groups[:24])
        ),
        "tagAliases": (
            not global_catalog
            and any(len(_items(item.get("aliases"))) > 16 for item in raw_tags[:160])
        ),
        "tagGroups": (
            not global_catalog
            and any(
                len(_items(item.get("semanticGroupIds"))) > 8
                for item in raw_tags[:160]
            )
        ),
        "bookTags": (
            not global_catalog
            and any(len(_items(item.get("tags"))) > 16 for item in raw_books[:48])
        ),
        "bookGroups": (
            not global_catalog
            and any(
                len(_items(item.get("semanticGroupIds"))) > 8
                for item in raw_books[:48]
            )
        ),
        "bookAtoms": (
            not global_catalog
            and any(
                len(_items(item.get("memoryAtomIds"))) > 80
                for item in raw_books[:48]
            )
        ),
    }
    for key, value in upstream_truncation.items():
        if value:
            catalog_truncated[key] = True
    catalog_complete = declared_complete and not any(catalog_truncated.values())
    catalog_digest = compact_whitespace(str(bundle.get("catalogDigest") or ""))
    if _is_complete_global_catalog(
        {
            "curationScope": curation_scope,
            "catalogAudit": catalog_audit,
            "catalogComplete": catalog_complete,
        }
    ) and not catalog_digest:
        catalog_digest = memory_catalog_digest(bundle)
    return {
        "schemaVersion": MEMORY_CURATION_MODEL_BUNDLE_SCHEMA_VERSION,
        "project": compact_whitespace(str(bundle.get("project") or "")),
        "curationScope": curation_scope,
        "catalogAudit": catalog_audit,
        "catalogDigest": catalog_digest,
        "evidenceOrder": compact_whitespace(str(bundle.get("evidenceOrder") or "")),
        "inputs": evidence,
        "existingAtoms": atoms,
        "existingGroups": groups,
        "existingTags": tags,
        "existingTagEdges": edges,
        "existingBooks": books,
        "existingMemoryBookIndex": book_index,
        "cursor": dict(bundle.get("cursor") or {}),
        "reconstruction": dict(bundle.get("reconstruction") or {}),
        "catalogTruncated": catalog_truncated,
        "catalogComplete": catalog_complete,
    }


def curation_decisions_to_compile_output(
    decisions_payload: Mapping[str, object],
    *,
    source_bundle: Mapping[str, object],
    project: str,
) -> dict[str, object]:
    """Expand compact Atom decisions into one reviewable legacy diff input.

    The model decides semantic units only. Group, Tag, Book, relation and
    lexicon records are reconciled here so those tables cannot independently
    drift from the accepted Atom evidence.
    """

    model_bundle = build_memory_curation_model_bundle(source_bundle)
    catalog_audit = _is_global_catalog_audit(model_bundle)
    catalog_incomplete = catalog_audit and not bool(
        model_bundle.get("catalogComplete", True)
    )
    evidence_by_ref = {
        str(item["ref"]): item for item in _dicts(model_bundle.get("inputs"))
    }
    atoms_by_ref = {
        str(item["ref"]): item for item in _dicts(model_bundle.get("existingAtoms"))
    }
    source_atoms_by_id = {
        compact_whitespace(str(item.get("atomId") or item.get("id") or "")): item
        for item in _dicts(source_bundle.get("existingMemoryAtoms"))
        if compact_whitespace(str(item.get("atomId") or item.get("id") or ""))
    }
    atoms_by_normalized_text = {
        normalize_text(str(item.get("canonicalText") or item.get("text") or "")): item
        for item in source_atoms_by_id.values()
        if normalize_text(str(item.get("canonicalText") or item.get("text") or ""))
    }
    groups_by_ref = {
        str(item["ref"]): item for item in _dicts(model_bundle.get("existingGroups"))
    }
    source_groups_by_id = {
        compact_whitespace(str(item.get("groupId") or "")): item
        for item in _dicts(source_bundle.get("existingSemanticGroups"))
        if compact_whitespace(str(item.get("groupId") or ""))
    }
    tags_by_ref = {
        str(item["ref"]): item for item in _dicts(model_bundle.get("existingTags"))
    }
    source_tags = _dicts(source_bundle.get("existingSemanticTags"))
    canonical_tag_by_name: dict[str, dict[str, object]] = {}
    for item in source_tags:
        canonical = normalize_text(str(item.get("name") or ""))
        if canonical:
            canonical_tag_by_name[canonical] = item
        for alias in _strings(item.get("aliases"), limit=32):
            normalized_alias = normalize_text(alias)
            if normalized_alias:
                canonical_tag_by_name.setdefault(normalized_alias, item)

    warnings = _strings(decisions_payload.get("warnings"), limit=100)
    semantic_groups: dict[str, dict[str, object]] = {}
    semantic_tags: dict[str, dict[str, object]] = {}
    memory_atoms: dict[str, dict[str, object]] = {}
    atom_groups: dict[str, list[str]] = {}
    atom_tags: dict[str, list[str]] = {}
    atom_source_ids: dict[str, list[int]] = {}
    group_atom_ids: dict[str, list[str]] = defaultdict(list)
    group_source_ids: dict[str, list[int]] = defaultdict(list)
    supersedes: list[dict[str, object]] = []
    memory_retractions: list[dict[str, object]] = []
    ignored_count = 0
    invalid_count = 0
    merge_count = 0
    retraction_count = 0
    accepted_evidence_refs: set[str] = set()
    retracted_evidence_refs: set[str] = set()
    ignored_evidence_refs: set[str] = set()
    invalid_evidence_refs: set[str] = set()
    confidence_by_evidence_ref: dict[str, float] = defaultdict(float)
    reason_by_evidence_ref: dict[str, str] = {}

    decision_items = _curation_decision_items(
        decisions_payload,
        evidence_by_ref=evidence_by_ref,
    )
    if catalog_audit:
        merge_items = [
            item
            for item in decision_items
            if compact_whitespace(str(item.get("action") or "")).lower() == "merge"
        ]
        if len(merge_items) != len(decision_items):
            warnings.append("catalog_audit_disallowed_fact_action_ignored")
        if catalog_incomplete:
            warnings.append("global_catalog_incomplete")
            decision_items = []
        else:
            decision_items = merge_items
    for decision_index, decision in enumerate(decision_items, start=1):
        action = compact_whitespace(str(decision.get("action") or "create")).lower()
        evidence_refs = _strings(
            decision.get("evidenceRefs") or decision.get("sourceRefs"),
            limit=80,
        )
        source_ids = _evidence_ids(
            evidence_refs,
            evidence_by_ref=evidence_by_ref,
            explicit_ids=decision.get("sourceEventIds"),
        )
        if action == "ignore":
            ignored_count += 1
            for ref in evidence_refs:
                if ref in evidence_by_ref:
                    ignored_evidence_refs.add(ref)
                    confidence_by_evidence_ref[ref] = max(
                        confidence_by_evidence_ref[ref],
                        _float(decision.get("confidence"), default=0.95),
                    )
                    reason_by_evidence_ref[ref] = compact_whitespace(
                        str(decision.get("reason") or "model_ignored_no_durable_memory")
                    )[:160]
            continue
        if action == "retract":
            target_ref = compact_whitespace(str(decision.get("targetRef") or ""))
            referenced_atom = atoms_by_ref.get(target_ref)
            target_atom_id = compact_whitespace(
                str((referenced_atom or {}).get("atomId") or "")
            )
            if not source_ids:
                warnings.append(f"retraction_missing_evidence:{decision_index}")
                invalid_count += 1
                invalid_evidence_refs.update(
                    ref for ref in evidence_refs if ref in evidence_by_ref
                )
                continue
            if not target_atom_id or target_atom_id not in source_atoms_by_id:
                warnings.append(
                    f"retraction_target_not_found:{decision_index}:{target_ref or 'empty'}"
                )
                invalid_count += 1
                invalid_evidence_refs.update(
                    ref for ref in evidence_refs if ref in evidence_by_ref
                )
                continue
            confidence = _float(decision.get("confidence"), default=0.0)
            memory_retractions.append(
                {
                    "targetAtomId": target_atom_id,
                    "reason": compact_whitespace(
                        str(decision.get("reason") or "explicit_user_forget")
                    )[:240],
                    "sourceEventIds": source_ids,
                    "confidence": confidence,
                }
            )
            retraction_count += 1
            for ref in evidence_refs:
                if ref in evidence_by_ref:
                    retracted_evidence_refs.add(ref)
                    confidence_by_evidence_ref[ref] = max(
                        confidence_by_evidence_ref[ref],
                        confidence,
                    )
                    reason_by_evidence_ref[ref] = "explicit_memory_forget"
            continue
        if action not in {"create", "attach", "update", "supersede", "merge"}:
            warnings.append(f"invalid_atom_action_ignored:{decision_index}:{action or 'empty'}")
            invalid_count += 1
            invalid_evidence_refs.update(
                ref for ref in evidence_refs if ref in evidence_by_ref
            )
            continue
        if action != "merge" and not source_ids:
            warnings.append(f"atom_decision_missing_evidence:{decision_index}")
            invalid_count += 1
            invalid_evidence_refs.update(
                ref for ref in evidence_refs if ref in evidence_by_ref
            )
            continue

        target_ref = compact_whitespace(str(decision.get("targetRef") or ""))
        referenced_atom = atoms_by_ref.get(target_ref)
        existing_atom = (
            source_atoms_by_id.get(compact_whitespace(str((referenced_atom or {}).get("atomId") or "")))
            if referenced_atom
            else None
        )
        merge_source_atom: Mapping[str, object] | None = None
        merge_source_id = ""
        if action == "merge":
            source_ref = compact_whitespace(
                str(decision.get("sourceRef") or decision.get("mergeRef") or "")
            )
            referenced_source = atoms_by_ref.get(source_ref)
            merge_source_atom = (
                source_atoms_by_id.get(
                    compact_whitespace(str((referenced_source or {}).get("atomId") or ""))
                )
                if referenced_source
                else None
            )
            merge_source_id = compact_whitespace(
                str(
                    (merge_source_atom or {}).get("atomId")
                    or (merge_source_atom or {}).get("id")
                    or ""
                )
            )
            if existing_atom is None:
                warnings.append(
                    f"merge_target_not_found:{decision_index}:{target_ref or 'empty'}"
                )
                invalid_count += 1
                continue
            if merge_source_atom is None:
                warnings.append(
                    f"merge_source_not_found:{decision_index}:{source_ref or 'empty'}"
                )
                invalid_count += 1
                continue
            if catalog_audit and not _atoms_exactly_equivalent(
                existing_atom,
                merge_source_atom,
            ):
                warnings.append(
                    f"global_catalog_non_equivalent_atom_merge_ignored:{decision_index}"
                )
                invalid_count += 1
                continue
        existing_canonical = compact_whitespace(
            str(
                (existing_atom or {}).get("canonicalText")
                or (existing_atom or {}).get("text")
                or ""
            )
        )
        proposed_canonical = compact_whitespace(
            str(decision.get("canonicalText") or decision.get("text") or "")
        )
        canonical = (
            existing_canonical
            if action in {"attach", "merge"} and existing_canonical
            else proposed_canonical or existing_canonical
        )
        if not canonical:
            warnings.append(f"atom_decision_missing_text:{decision_index}")
            invalid_count += 1
            invalid_evidence_refs.update(
                ref for ref in evidence_refs if ref in evidence_by_ref
            )
            continue
        exact_existing = atoms_by_normalized_text.get(normalize_text(canonical))
        if action != "merge" and existing_atom is None and exact_existing is not None:
            existing_atom = exact_existing
            if action == "create":
                action = "attach"
                warnings.append(f"exact_atom_reused:{decision_index}")

        old_atom_id = compact_whitespace(
            str((existing_atom or {}).get("atomId") or (existing_atom or {}).get("id") or "")
        )
        if action in {"attach", "update", "merge"} and not old_atom_id:
            warnings.append(f"atom_target_not_found:{decision_index}:{target_ref or 'empty'}")
            invalid_count += 1
            invalid_evidence_refs.update(
                ref for ref in evidence_refs if ref in evidence_by_ref
            )
            continue
        if action == "supersede" and not old_atom_id:
            warnings.append(f"supersede_target_not_found:{decision_index}:{target_ref or 'empty'}")
            invalid_count += 1
            invalid_evidence_refs.update(
                ref for ref in evidence_refs if ref in evidence_by_ref
            )
            continue
        if action == "merge" and merge_source_id == old_atom_id:
            warnings.append(f"merge_source_equals_target:{decision_index}:{old_atom_id}")
            invalid_count += 1
            continue

        atom_id = (
            old_atom_id
            if action in {"attach", "update", "merge"}
            else f"atom:{stable_text_hash(normalize_text(canonical)).removeprefix('sha256:')}"
        )
        staged_atom = memory_atoms.get(atom_id)
        merge_limit = None if catalog_audit else 512
        existing_source_ids = _unique_ints(
            [
                *_positive_ints((existing_atom or {}).get("sourceEventIds")),
                *_positive_ints((merge_source_atom or {}).get("sourceEventIds")),
                *_positive_ints((staged_atom or {}).get("sourceEventIds")),
            ],
            limit=merge_limit,
        )
        combined_source_ids = _unique_ints(
            [*existing_source_ids, *source_ids],
            limit=merge_limit,
        )
        base_atom: dict[str, object] = dict(existing_atom or {})
        for field, incremental_limit in (
            ("tags", 32),
            ("semanticGroupIds", 8),
            ("groupIds", 8),
            ("aliases", 48),
            ("surfaceHints", 32),
            ("queryExpansions", 48),
            ("sourceMemoryIds", 64),
        ):
            limit = None if catalog_audit else incremental_limit
            base_atom[field] = _unique_strings(
                [
                    *_strings((existing_atom or {}).get(field), limit=limit),
                    *_strings((merge_source_atom or {}).get(field), limit=limit),
                    *_strings((staged_atom or {}).get(field), limit=limit),
                ],
                limit=limit,
            )
        base_atom["sourceEventIds"] = combined_source_ids
        if staged_atom:
            base_atom["canonicalText"] = staged_atom.get("canonicalText") or canonical
            base_atom["kind"] = staged_atom.get("kind") or base_atom.get("kind")
            base_atom["app"] = staged_atom.get("app") or base_atom.get("app")
            base_atom["project"] = staged_atom.get("project") or base_atom.get("project")
        projection_source_ids = source_ids or combined_source_ids
        group_ids = _resolve_decision_groups(
            decision,
            groups_by_ref=groups_by_ref,
            source_groups_by_id=source_groups_by_id,
            existing_atom=base_atom,
            project=project,
            source_ids=projection_source_ids,
            semantic_groups=semantic_groups,
            existing_books=[
                *_dicts(model_bundle.get("existingMemoryBookIndex")),
                *_dicts(model_bundle.get("existingBooks")),
            ],
        )
        tag_names = _resolve_decision_tags(
            decision,
            tags_by_ref=tags_by_ref,
            canonical_tag_by_name=canonical_tag_by_name,
            group_ids=group_ids,
            group_definitions=semantic_groups,
            source_ids=projection_source_ids,
            semantic_tags=semantic_tags,
        )
        for existing_tag in _strings(
            base_atom.get("tags"),
            limit=None if catalog_audit else 32,
        ):
            resolved = (
                existing_tag
                if catalog_audit
                else _canonical_tag(
                    existing_tag,
                    canonical_tag_by_name=canonical_tag_by_name,
                )
            )
            if resolved and resolved not in tag_names:
                tag_names.append(resolved)
        existing_group_ids = _strings(
            base_atom.get("semanticGroupIds")
            or base_atom.get("groupIds"),
            limit=None if catalog_audit else 8,
        )
        group_ids = _unique_strings(
            [*existing_group_ids, *group_ids],
            limit=None if catalog_audit else 4,
        )

        evidence_items = [
            evidence_by_ref[ref] for ref in evidence_refs if ref in evidence_by_ref
        ]
        # A new receipt's capture app is provenance, not a scope migration for
        # an explicitly selected existing claim. Changing this field prevents
        # the writer from closing the previous version in the same scope.
        scope_app = (
            compact_whitespace(str(existing_atom.get("app") or ""))
            if existing_atom is not None
            else _single_app(evidence_items)
        )
        replacement_time = max(
            (_int(item.get("sourceOccurredAtMs") or item.get("createdAtMs"))
             for item in evidence_items),
            default=0,
        )
        kind = (
            compact_whitespace(str(base_atom.get("kind") or "project_fact"))
            if catalog_audit
            else _canonical_kind(
                (
                    base_atom.get("kind")
                    if action in {"attach", "merge"}
                    else decision.get("kind")
                )
                or base_atom.get("kind")
                or "project_fact"
            )
        )
        merge_aliases = []
        if action == "merge":
            merge_alias = compact_whitespace(
                str(
                    (merge_source_atom or {}).get("canonicalText")
                    or (merge_source_atom or {}).get("text")
                    or ""
                )
            )
            if merge_alias and normalize_text(merge_alias) != normalize_text(canonical):
                merge_aliases.append(merge_alias)
        aliases = _unique_strings(
            [
                *_strings(
                    base_atom.get("aliases"),
                    limit=None if catalog_audit else 48,
                ),
                *merge_aliases,
                *(
                    _strings(decision.get("aliases"), limit=32)
                    if not catalog_audit
                    else []
                ),
            ],
            limit=None if catalog_audit else 48,
        )
        query_expansions = _unique_strings(
            [
                *_strings(
                    base_atom.get("queryExpansions"),
                    limit=None if catalog_audit else 48,
                ),
                *(
                    _strings(decision.get("queryExpansions"), limit=32)
                    if not catalog_audit
                    else []
                ),
                *(tag_names if not catalog_audit else []),
            ],
            limit=None if catalog_audit else 48,
        )
        target_identity_hash = compact_whitespace(
            str(
                (existing_atom or {}).get("identityHash")
                or memory_atom_identity_hash(existing_atom or {})
            )
        )
        target_authority_hash = compact_whitespace(
            str(
                (existing_atom or {}).get("authorityHash")
                or memory_atom_authority_hash(existing_atom or {})
            )
        )
        memory_atoms[atom_id] = {
            "atomId": atom_id,
            "identityHash": target_identity_hash,
            "authorityHash": target_authority_hash,
            "mergeSourceId": merge_source_id if action == "merge" else "",
            "operation": action,
            "kind": kind,
            "language": compact_whitespace(
                str(base_atom.get("language") or "zh")
            ),
            "claimKey": compact_whitespace(
                str(
                    (existing_atom or {}).get("claimKey")
                    or (merge_source_atom or {}).get("claimKey")
                    or decision.get("claimKey")
                    or ""
                )
            )
            if catalog_audit
            else compact_whitespace(
                str(
                    (existing_atom or {}).get("claimKey")
                    or (merge_source_atom or {}).get("claimKey")
                    or decision.get("claimKey")
                    or ""
                )
            )[:120],
            "lineageId": compact_whitespace(
                str(
                    (existing_atom or {}).get("lineageId")
                    or (merge_source_atom or {}).get("lineageId")
                    or ""
                )
            )
            if catalog_audit
            else compact_whitespace(
                str(
                    (existing_atom or {}).get("lineageId")
                    or (merge_source_atom or {}).get("lineageId")
                    or ""
                )
            )[:200],
            "claimState": compact_whitespace(
                str(
                    (existing_atom or {}).get("claimState")
                    or (merge_source_atom or {}).get("claimState")
                    or decision.get("claimState")
                    or "current"
                )
            ).lower(),
            "validFromMs": (
                replacement_time
                if action == "supersede"
                else _int((existing_atom or {}).get("validFromMs"))
                if (existing_atom or {}).get("validFromMs") is not None
                else _int((merge_source_atom or {}).get("validFromMs"))
                if (merge_source_atom or {}).get("validFromMs") is not None
                else _int(decision.get("validFromMs"))
            ),
            "validToMs": (
                _int((existing_atom or {}).get("validToMs"))
                if (existing_atom or {}).get("validToMs") is not None
                else _int((merge_source_atom or {}).get("validToMs"))
                if (merge_source_atom or {}).get("validToMs") is not None
                else _int(decision.get("validToMs"))
                if decision.get("validToMs") is not None
                else None
            ),
            "supersedesId": compact_whitespace(
                str(
                    old_atom_id if action == "supersede" else
                    (existing_atom or {}).get("supersedesId")
                    or (merge_source_atom or {}).get("supersedesId")
                    or decision.get("supersedesId")
                    or ""
                )
            )
            if catalog_audit
            else compact_whitespace(
                str(
                    old_atom_id if action == "supersede" else
                    (existing_atom or {}).get("supersedesId")
                    or (merge_source_atom or {}).get("supersedesId")
                    or decision.get("supersedesId")
                    or ""
                )
            )[:240],
            "canonicalText": canonical,
            "text": compact_whitespace(str(base_atom.get("text") or canonical)),
            "summary": compact_whitespace(
                str(decision.get("summary") or (staged_atom or {}).get("summary") or canonical)
            )[:600],
            "tags": tag_names,
            "aliases": aliases,
            "surfaceHints": (
                _strings(
                    base_atom.get("surfaceHints"),
                    limit=None if catalog_audit else 0,
                )
                if catalog_audit
                else []
            ),
            "queryExpansions": query_expansions,
            "sourceEventIds": combined_source_ids,
            "sourceMemoryIds": _strings(
                base_atom.get("sourceMemoryIds"),
                limit=None if catalog_audit else 64,
            ),
            "semanticGroupIds": group_ids,
            "directCandidateAllowed": False,
            "project": compact_whitespace(str(base_atom.get("project") or project)),
            "app": scope_app,
            "ownerKind": compact_whitespace(str(base_atom.get("ownerKind") or "")),
            "ownerId": compact_whitespace(str(base_atom.get("ownerId") or "")),
            "privacyLevel": compact_whitespace(str(base_atom.get("privacyLevel") or "")),
            "knowledgeDomain": compact_whitespace(str(base_atom.get("knowledgeDomain") or "")),
            "scopeKind": compact_whitespace(str(base_atom.get("scopeKind") or "")),
            "scopeId": compact_whitespace(str(base_atom.get("scopeId") or "")),
            "visibility": compact_whitespace(str(base_atom.get("visibility") or "")),
            "authorizationRevision": compact_whitespace(
                str(base_atom.get("authorizationRevision") or "")
            ),
            "bindingId": compact_whitespace(str(base_atom.get("bindingId") or "")),
            "scopeMode": compact_whitespace(str(base_atom.get("scopeMode") or "")),
            "confidence": _float(decision.get("confidence"), default=0.75),
            "qualityScore": _float(
                decision.get("qualityScore"),
                default=_float(decision.get("confidence"), default=0.75),
            ),
            "status": "active",
            "curationArchitecture": MEMORY_CURATION_ARCHITECTURE,
        }
        atom_groups[atom_id] = group_ids
        atom_tags[atom_id] = tag_names
        atom_source_ids[atom_id] = combined_source_ids
        for ref in evidence_refs:
            if ref not in evidence_by_ref:
                continue
            accepted_evidence_refs.add(ref)
            confidence_by_evidence_ref[ref] = max(
                confidence_by_evidence_ref[ref],
                _float(decision.get("confidence"), default=0.75),
            )
            reason_by_evidence_ref[ref] = compact_whitespace(
                str(decision.get("reason") or f"atom_{action}")
            )[:160]
        for group_id in group_ids:
            if atom_id not in group_atom_ids[group_id]:
                group_atom_ids[group_id].append(atom_id)
            group_source_ids[group_id] = _unique_ints(
                [*group_source_ids[group_id], *combined_source_ids],
                limit=512,
            )
        if action == "supersede" and old_atom_id != atom_id:
            supersedes.append(
                {
                    "oldId": old_atom_id,
                    "newId": atom_id,
                    "sourceEventIds": source_ids,
                    "reason": compact_whitespace(
                        str(decision.get("reason") or "新的完整输入更新了旧记忆")
                    ),
                }
            )
        elif action == "merge":
            merge_count += 1
            supersedes.append(
                {
                    "oldId": merge_source_id,
                    "newId": atom_id,
                    "sourceEventIds": combined_source_ids,
                    "reason": compact_whitespace(
                        str(decision.get("reason") or "语义等价 Atom 合并到规范 Atom")
                    ),
                }
            )

    tag_merges = (
        []
        if catalog_incomplete
        else _compile_tag_merges(
            decisions_payload,
            evidence_by_ref=evidence_by_ref,
            tags_by_ref=tags_by_ref,
            canonical_tag_by_name=canonical_tag_by_name,
            source_bundle=source_bundle,
        )
    )
    book_merges = (
        []
        if catalog_incomplete
        else _compile_book_merges(
            decisions_payload,
            source_bundle=source_bundle,
            project=project,
        )
    )
    if catalog_audit:
        # A catalog audit is a consolidation pass, not a second projection
        # writer.  Existing Book/Group/Tag/edge projections are rebuilt by the
        # governed apply path after Atom/tag merges, so never emit direct
        # upserts from this pass.
        semantic_groups = {}
        semantic_tags = {}
        tag_edges = []
        topic_books = {}
        phrase_candidates = []
        negative_phrases = []
        lexicon_diagnostics = {
            "source": "catalog-audit",
            "modelGenerated": False,
            "feedbackCount": 0,
            "phraseCandidateCount": 0,
            "negativePhraseCount": 0,
        }
    else:
        tag_edges = _derive_tag_edges(
            atom_tags=atom_tags,
            atom_source_ids=atom_source_ids,
        )
        topic_books = _derive_topic_books(
            source_bundle=source_bundle,
            semantic_groups=semantic_groups,
            memory_atoms=memory_atoms,
            group_atom_ids=group_atom_ids,
            group_source_ids=group_source_ids,
            atom_tags=atom_tags,
            project=project,
            excluded_atom_ids={
                *(str(item["oldId"]) for item in supersedes),
                *(str(item["targetAtomId"]) for item in memory_retractions),
            },
        )
        phrase_candidates, negative_phrases, lexicon_diagnostics = _derive_lexicon_lane(
            source_bundle=source_bundle,
            event_group_ids=_event_group_index(
                atom_groups=atom_groups,
                atom_source_ids=atom_source_ids,
            ),
            project=project,
        )
    curation_outcome = (
        "changes"
        if memory_atoms
        or memory_retractions
        or semantic_groups
        or semantic_tags
        or tag_merges
        or book_merges
        or phrase_candidates
        or negative_phrases
        else "no_changes"
    )
    source_decisions: list[dict[str, object]] = []
    for ref, evidence in evidence_by_ref.items():
        accepted = ref in accepted_evidence_refs
        retracted = ref in retracted_evidence_refs
        ignored = ref in ignored_evidence_refs
        invalid = ref in invalid_evidence_refs
        if accepted and not ignored and not invalid:
            disposition = "remember"
            reason_code = reason_by_evidence_ref.get(ref) or "durable_atom_evidence"
        elif retracted and not accepted and not ignored and not invalid:
            disposition = "not_for_memory"
            reason_code = "explicit_memory_forget"
        elif ignored and not accepted and not retracted and not invalid:
            disposition = "not_for_memory"
            reason_code = reason_by_evidence_ref.get(ref) or "model_ignored_no_durable_memory"
        else:
            disposition = "needs_review"
            reason_code = (
                "conflicting_evidence_actions"
                if (accepted or retracted) and ignored
                else "invalid_or_missing_atom_decision"
            )
        source_decisions.append(
            {
                "sourceRef": compact_whitespace(
                    str(evidence.get("sourceRef") or ref)
                ),
                "evidenceRef": ref,
                "disposition": disposition,
                "reasonCode": reason_code,
                "confidence": confidence_by_evidence_ref.get(ref, 0.0),
            }
        )
    conflicting_refs = sorted(
        (accepted_evidence_refs | retracted_evidence_refs) & ignored_evidence_refs
    )
    if conflicting_refs:
        warnings.append(
            "conflicting_evidence_actions:" + ",".join(conflicting_refs[:20])
        )
    return {
        "schemaVersion": MEMORY_CURATION_DECISION_SCHEMA_VERSION,
        "sourceDecisions": source_decisions,
        "curationScope": model_bundle.get("curationScope") or "incremental",
        "catalogAudit": bool(model_bundle.get("catalogAudit")),
        "catalogDigest": compact_whitespace(
            str(model_bundle.get("catalogDigest") or "")
        ),
        "catalogComplete": bool(model_bundle.get("catalogComplete", True)),
        "catalogTruncated": dict(model_bundle.get("catalogTruncated") or {}),
        "dailyBooks": [],
        "topicBooks": list(topic_books.values()),
        "semanticGroups": list(semantic_groups.values()),
        "semanticTags": list(semantic_tags.values()),
        "tagMerges": tag_merges,
        "bookMerges": book_merges,
        "memoryAtoms": list(memory_atoms.values()),
        "tagEdges": tag_edges,
        "phraseCandidates": phrase_candidates,
        "negativePhrases": negative_phrases,
        "supersedes": supersedes,
        "memoryRetractions": memory_retractions,
        "warnings": _unique_strings(warnings, limit=200),
        "provider": compact_whitespace(str(decisions_payload.get("provider") or "")),
        "model": compact_whitespace(str(decisions_payload.get("model") or "")),
        "instruction": compact_whitespace(str(decisions_payload.get("instruction") or "")),
        "elapsedMs": _int(decisions_payload.get("elapsedMs")),
        "modelDiagnostics": dict(decisions_payload.get("modelDiagnostics") or {}),
        "modelBundleStats": dict(decisions_payload.get("modelBundleStats") or {}),
        "curationArchitecture": MEMORY_CURATION_ARCHITECTURE,
        "curationOutcome": curation_outcome,
        "curationDiagnostics": {
            "decisionCount": len(decision_items),
            "acceptedAtomCount": len(memory_atoms),
            "ignoredDecisionCount": ignored_count,
            "invalidDecisionCount": invalid_count,
            "mergedAtomCount": merge_count,
            "retractionCount": retraction_count,
            "derivedGroupCount": len(semantic_groups),
            "derivedTagCount": len(semantic_tags),
            "derivedBookCount": len(topic_books),
            "bookMergeCount": len(book_merges),
            "derivedTagEdgeCount": len(tag_edges),
        },
        "lexiconDiagnostics": lexicon_diagnostics,
    }


def _curation_decision_items(
    payload: Mapping[str, object],
    *,
    evidence_by_ref: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    """Expand the model's compact reference protocol into canonical decisions."""

    result = _dicts(payload.get("decisions") or payload.get("atomDecisions"))

    for item in _items(payload.get("attach")):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            evidence_refs = _strings(item[0], limit=80)
            target_ref = compact_whitespace(str(item[1] or ""))
            if evidence_refs and target_ref:
                result.append(
                    {
                        "action": "attach",
                        "evidenceRefs": evidence_refs,
                        "targetRef": target_ref,
                    }
                )
        elif isinstance(item, Mapping):
            result.append(
                {
                    **dict(item),
                    "action": "attach",
                    "evidenceRefs": _strings(
                        item.get("evidenceRefs") or item.get("e") or item.get("refs"),
                        limit=80,
                    ),
                    "targetRef": compact_whitespace(
                        str(item.get("targetRef") or item.get("p") or "")
                    ),
                }
            )

    for action in ("create", "update", "supersede"):
        for item in _items(payload.get(action)):
            if isinstance(item, str):
                evidence_refs = [compact_whitespace(item)] if compact_whitespace(item) else []
                decision: dict[str, object] = {
                    "action": action,
                    "evidenceRefs": evidence_refs,
                }
            elif isinstance(item, Mapping):
                decision = {
                    **dict(item),
                    "action": action,
                    "evidenceRefs": _strings(
                        item.get("evidenceRefs") or item.get("e") or item.get("refs"),
                        limit=80,
                    ),
                    "targetRef": compact_whitespace(
                        str(item.get("targetRef") or item.get("p") or "")
                    ),
                    "canonicalText": compact_whitespace(
                        str(
                            item.get("canonicalText")
                            or item.get("text")
                            or item.get("t")
                            or ""
                        )
                    ),
                    "topicRef": compact_whitespace(
                        str(item.get("topicRef") or item.get("g") or "")
                    ),
                }
            else:
                continue
            evidence_refs = _strings(decision.get("evidenceRefs"), limit=80)
            if (
                action in {"create", "supersede"}
                and not compact_whitespace(str(decision.get("canonicalText") or ""))
                and len(evidence_refs) == 1
                and evidence_refs[0] in evidence_by_ref
            ):
                decision["canonicalText"] = compact_whitespace(
                    str(evidence_by_ref[evidence_refs[0]].get("text") or "")
                )
            result.append(decision)

    for item in _items(payload.get("merge")):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            source_ref = compact_whitespace(str(item[0] or ""))
            target_ref = compact_whitespace(str(item[1] or ""))
            if source_ref and target_ref:
                result.append(
                    {
                        "action": "merge",
                        "sourceRef": source_ref,
                        "targetRef": target_ref,
                    }
                )
        elif isinstance(item, Mapping):
            result.append(
                {
                    **dict(item),
                    "action": "merge",
                    "sourceRef": compact_whitespace(
                        str(item.get("sourceRef") or item.get("source") or "")
                    ),
                    "targetRef": compact_whitespace(
                        str(item.get("targetRef") or item.get("target") or "")
                    ),
                }
            )

    for item in _items(payload.get("retract")):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            evidence_refs = _strings(item[0], limit=80)
            target_ref = compact_whitespace(str(item[1] or ""))
            if evidence_refs and target_ref:
                result.append(
                    {
                        "action": "retract",
                        "evidenceRefs": evidence_refs,
                        "targetRef": target_ref,
                        "confidence": (
                            item[2] if len(item) >= 3 else 0.0
                        ),
                    }
                )
        elif isinstance(item, Mapping):
            result.append(
                {
                    **dict(item),
                    "action": "retract",
                    "evidenceRefs": _strings(
                        item.get("evidenceRefs") or item.get("e") or item.get("refs"),
                        limit=80,
                    ),
                    "targetRef": compact_whitespace(
                        str(item.get("targetRef") or item.get("p") or "")
                    ),
                }
            )

    ignored_refs: list[str] = []
    for item in _items(payload.get("ignore")):
        ignored_refs.extend(_strings(item, limit=200))
    if ignored_refs:
        result.append(
            {
                "action": "ignore",
                "evidenceRefs": _unique_strings(ignored_refs, limit=500),
            }
        )
    return result


def _resolve_decision_groups(
    decision: Mapping[str, object],
    *,
    groups_by_ref: Mapping[str, Mapping[str, object]],
    source_groups_by_id: Mapping[str, Mapping[str, object]],
    existing_atom: Mapping[str, object] | None,
    project: str,
    source_ids: list[int],
    semantic_groups: dict[str, dict[str, object]],
    existing_books: list[Mapping[str, object]] | None = None,
) -> list[str]:
    topic_books = [
        dict(item)
        for item in (existing_books or [])
        if isinstance(item, Mapping)
        and compact_whitespace(str(item.get("bookId") or ""))
    ]
    books_by_id = {
        compact_whitespace(str(item.get("bookId") or "")): item
        for item in topic_books
    }

    scope_fields = (
        "ownerKind",
        "ownerId",
        "project",
        "app",
        "knowledgeDomain",
        "scopeKind",
        "scopeId",
        "visibility",
        "authorizationRevision",
        "bindingId",
        "scopeMode",
    )

    def requested_scope_value(field: str) -> str | None:
        if field in decision and decision.get(field) is not None:
            return compact_whitespace(str(decision.get(field) or ""))
        if existing_atom is not None and field in existing_atom:
            return compact_whitespace(str(existing_atom.get(field) or ""))
        if field == "ownerKind":
            return "user"
        if field == "ownerId":
            return "default"
        if field == "project":
            return compact_whitespace(project)
        return None

    def compatible_book(book: Mapping[str, object]) -> bool:
        for field in scope_fields:
            requested = requested_scope_value(field)
            if requested is None or field not in book:
                # A missing field is a legacy omission, not a wildcard value.
                continue
            candidate_value = compact_whitespace(str(book.get(field) or ""))
            if field != "project" and not candidate_value:
                # The model bundle materializes omitted legacy scope fields as
                # empty strings.  Only an explicitly present project remains
                # authoritative: project="" is a global scope, never a
                # wildcard for a named project.
                continue
            if candidate_value != requested:
                return False
        return True

    def same_scope(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
        for field in scope_fields:
            if field not in left or field not in right:
                continue
            if compact_whitespace(str(left.get(field) or "")) != compact_whitespace(
                str(right.get(field) or "")
            ):
                return False
        return True

    def reference_candidates(value: object) -> list[dict[str, object]]:
        reference = compact_whitespace(str(value or ""))
        if not reference:
            return []
        direct = books_by_id.get(reference)
        if direct is not None:
            return [direct]
        normalized = normalize_text(reference)
        if not normalized:
            return []
        return [
            item
            for item in topic_books
            if normalized
            in {
                normalize_text(str(item.get("bookKey") or "")),
                normalize_text(str(item.get("title") or "")),
                *{
                    normalize_text(alias)
                    for alias in _strings(item.get("aliases"), limit=64)
                },
            }
        ]

    def resolve_book(value: object) -> dict[str, object] | None:
        resolved: dict[str, dict[str, object]] = {}
        for candidate in reference_candidates(value):
            current = dict(candidate)
            visited: set[str] = set()
            while True:
                book_id = compact_whitespace(str(current.get("bookId") or ""))
                if not book_id or book_id in visited or not compatible_book(current):
                    current = {}
                    break
                visited.add(book_id)
                if compact_whitespace(str(current.get("status") or "")) != "superseded":
                    break
                redirect_id = compact_whitespace(
                    str(current.get("supersededByBookId") or "")
                )
                next_book = books_by_id.get(redirect_id)
                if not redirect_id or next_book is None or not same_scope(current, next_book):
                    current = {}
                    break
                current = dict(next_book)
            if current:
                resolved[compact_whitespace(str(current.get("bookId") or ""))] = current
        if len(resolved) != 1:
            return None
        return next(iter(resolved.values()))

    refs = _strings(
        decision.get("topicRefs")
        or decision.get("groupRefs")
        or [decision.get("topicRef") or decision.get("groupRef")],
        limit=4,
    )
    result: list[str] = []
    rejected_known_reference = False
    for ref in refs:
        known_reference = bool(reference_candidates(ref))
        resolved_book = resolve_book(ref)
        topic_book_id = (
            compact_whitespace(str(resolved_book.get("bookId") or ""))
            if resolved_book is not None
            else ""
        )
        book_group_ids = (
            _strings(
                resolved_book.get("semanticGroupIds")
                or resolved_book.get("groupIds"),
                limit=4,
            )
            if resolved_book is not None
            else []
        )
        existing = groups_by_ref.get(ref)
        if existing is None and ref in source_groups_by_id:
            existing = source_groups_by_id[ref]
        if existing is None and book_group_ids:
            existing = (
                groups_by_ref.get(book_group_ids[0])
                or source_groups_by_id.get(book_group_ids[0])
            )
        if existing is not None:
            group_id = compact_whitespace(str(existing.get("groupId") or ""))
            title = compact_whitespace(str(existing.get("title") or ""))
            description = compact_whitespace(str(existing.get("description") or ""))
            aliases = _strings(existing.get("aliases"), limit=24)
            tags = _strings(existing.get("tags"), limit=24)
        elif resolved_book is not None:
            raw_key = compact_whitespace(
                str(resolved_book.get("bookKey") or resolved_book.get("bookId") or "")
            )
            key = _stable_key(raw_key or str(decision.get("topicTitle") or ""))
            group_id = f"group:{key}" if key else ""
            title = compact_whitespace(
                str(
                    resolved_book.get("title")
                    or decision.get("topicTitle")
                    or raw_key
                    or "个人知识"
                )
            )
            description = compact_whitespace(
                str(
                    decision.get("topicDescription")
                    or resolved_book.get("summary")
                    or ""
                )
            )
            aliases = _strings(
                [
                    *(_items(resolved_book.get("aliases"))),
                    decision.get("topicTitle"),
                ],
                limit=24,
            )
            tags = _strings(resolved_book.get("tags"), limit=24)
        elif known_reference:
            # A known ID/key/alias that is ambiguous or outside this scope is
            # not permission to invent a parallel Book.  Keep the Atom itself
            # eligible; the caller may still retain its existing group refs.
            rejected_known_reference = True
            continue
        else:
            raw_key = ref.removeprefix("new:").removeprefix("topic:")
            key = _stable_key(raw_key or str(decision.get("topicTitle") or ""))
            group_id = f"group:{key}" if key else ""
            title = compact_whitespace(
                str(decision.get("topicTitle") or raw_key or "个人知识")
            )
            description = compact_whitespace(str(decision.get("topicDescription") or ""))
            aliases = []
            tags = []
        if not _GROUP_ID_RE.fullmatch(group_id):
            continue
        current = semantic_groups.get(group_id)
        semantic_groups[group_id] = {
            "groupId": group_id,
            "topicBookId": topic_book_id,
            # A later Atom may refer to a topic created earlier in the same
            # batch while also creating another topic.  Keep the first stable
            # title instead of overwriting it with the later Atom's
            # ``topicTitle`` (which describes only its new topic).
            "title": (
                compact_whitespace(str((current or {}).get("title") or ""))
                or title
                or "个人知识"
            ),
            "description": (
                compact_whitespace(str((current or {}).get("description") or ""))
                or description
                or f"围绕{title or '个人知识'}的长期事实、要求、决定与偏好。"
            ),
            "project": project,
            "aliases": _unique_strings(
                [*_strings((current or {}).get("aliases"), limit=24), *aliases],
                limit=24,
            ),
            "tags": _unique_strings(
                [*_strings((current or {}).get("tags"), limit=24), *tags],
                limit=24,
            ),
            "sourceEventIds": _unique_ints(
                [*_positive_ints((current or {}).get("sourceEventIds")), *source_ids],
                limit=512,
            ),
            "confidence": _float(decision.get("confidence"), default=0.75),
            "qualityScore": _float(decision.get("qualityScore"), default=0.75),
            "status": "active",
        }
        result.append(group_id)

    if not result:
        existing_group_ids = _strings(
            (existing_atom or {}).get("semanticGroupIds")
            or (existing_atom or {}).get("groupIds"),
            limit=4,
        )
        result.extend(group_id for group_id in existing_group_ids if _GROUP_ID_RE.fullmatch(group_id))
    if not result and not rejected_known_reference and len(source_groups_by_id) == 1:
        only_group = next(iter(source_groups_by_id.values()))
        group_id = compact_whitespace(str(only_group.get("groupId") or ""))
        if _GROUP_ID_RE.fullmatch(group_id):
            result.append(group_id)
    if not result and not rejected_known_reference:
        group_id = "group:personal-knowledge"
        semantic_groups.setdefault(
            group_id,
            {
                "groupId": group_id,
                "title": "个人知识",
                "description": "尚未归入专门主题的长期事实、要求、决定与偏好。",
                "project": project,
                "aliases": [],
                "tags": [],
                "sourceEventIds": list(source_ids),
                "confidence": 0.6,
                "qualityScore": 0.6,
                "status": "active",
            },
        )
        result.append(group_id)
    for group_id in result:
        if group_id in semantic_groups or group_id not in source_groups_by_id:
            continue
        existing = source_groups_by_id[group_id]
        semantic_groups[group_id] = {
            "groupId": group_id,
            "title": compact_whitespace(str(existing.get("title") or "个人知识")),
            "description": compact_whitespace(
                str(existing.get("description") or "长期主题记忆。")
            ),
            "project": project,
            "aliases": _strings(existing.get("aliases"), limit=24),
            "tags": _strings(existing.get("tags"), limit=24),
            "sourceEventIds": _unique_ints(
                [*_positive_ints(existing.get("sourceEventIds")), *source_ids],
                limit=512,
            ),
            "confidence": 0.75,
            "qualityScore": 0.75,
            "status": "active",
        }
    return _unique_strings(result, limit=4)


def _resolve_decision_tags(
    decision: Mapping[str, object],
    *,
    tags_by_ref: Mapping[str, Mapping[str, object]],
    canonical_tag_by_name: Mapping[str, Mapping[str, object]],
    group_ids: list[str],
    group_definitions: Mapping[str, Mapping[str, object]],
    source_ids: list[int],
    semantic_tags: dict[str, dict[str, object]],
) -> list[str]:
    result: list[str] = []
    raw_tags = _strings(decision.get("tags") or decision.get("tagRefs"), limit=16)
    for raw in raw_tags:
        existing = tags_by_ref.get(raw)
        requested = (
            compact_whitespace(str(existing.get("name") or ""))
            if existing is not None
            else raw.removeprefix("new:")
        )
        canonical = _canonical_tag(
            requested,
            canonical_tag_by_name=canonical_tag_by_name,
        )
        if not _valid_tag_name(canonical):
            continue
        source = canonical_tag_by_name.get(normalize_text(canonical))
        current = semantic_tags.get(normalize_text(canonical))
        group_title = next(
            (
                compact_whitespace(str(group_definitions[group_id].get("title") or ""))
                for group_id in group_ids
                if group_id in group_definitions
            ),
            "个人知识",
        )
        semantic_tags[normalize_text(canonical)] = {
            "name": canonical,
            "description": (
                compact_whitespace(str((source or {}).get("description") or ""))
                or compact_whitespace(str((current or {}).get("description") or ""))
                or f"与{group_title}相关、由完整输入证据支持的稳定概念。"
            ),
            "type": compact_whitespace(str((source or {}).get("type") or "concept")),
            "aliases": _unique_strings(
                [
                    *_strings((source or {}).get("aliases"), limit=24),
                    *_strings((current or {}).get("aliases"), limit=24),
                ],
                limit=24,
            ),
            "semanticGroupIds": _unique_strings(
                [
                    *_strings((source or {}).get("semanticGroupIds"), limit=8),
                    *_strings((current or {}).get("semanticGroupIds"), limit=8),
                    *group_ids,
                ],
                limit=4,
            ),
            "sourceEventIds": _unique_ints(
                [
                    *_positive_ints((source or {}).get("sourceEventIds")),
                    *_positive_ints((current or {}).get("sourceEventIds")),
                    *source_ids,
                ],
                limit=512,
            ),
            "confidence": _float(decision.get("confidence"), default=0.75),
            "qualityScore": _float(decision.get("qualityScore"), default=0.75),
            "status": "active",
        }
        result.append(canonical)
    if not result:
        for group_id in group_ids[:1]:
            title = compact_whitespace(
                str((group_definitions.get(group_id) or {}).get("title") or "")
            )
            if _valid_tag_name(title):
                result.append(title)
                semantic_tags.setdefault(
                    normalize_text(title),
                    {
                        "name": title,
                        "description": f"{title}主题下由完整输入证据支持的稳定概念。",
                        "type": "topic",
                        "aliases": [],
                        "semanticGroupIds": [group_id],
                        "sourceEventIds": list(source_ids),
                        "confidence": 0.65,
                        "qualityScore": 0.65,
                        "status": "active",
                    },
                )
    return _unique_strings(result, limit=16)


def _compile_tag_merges(
    decisions_payload: Mapping[str, object],
    *,
    evidence_by_ref: Mapping[str, Mapping[str, object]],
    tags_by_ref: Mapping[str, Mapping[str, object]],
    canonical_tag_by_name: Mapping[str, Mapping[str, object]],
    source_bundle: Mapping[str, object],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    global_catalog = _is_global_catalog_audit(source_bundle)
    for item in _dicts(decisions_payload.get("tagMerges")):
        source_raw = compact_whitespace(
            str(item.get("sourceRef") or item.get("source") or "")
        )
        target_raw = compact_whitespace(
            str(item.get("targetRef") or item.get("target") or "")
        )
        source_item = tags_by_ref.get(source_raw) or canonical_tag_by_name.get(
            normalize_text(source_raw)
        )
        target_item = tags_by_ref.get(target_raw) or canonical_tag_by_name.get(
            normalize_text(target_raw)
        )
        source = compact_whitespace(
            str((source_item or {}).get("name") or source_raw)
        )
        target = compact_whitespace(
            str((target_item or {}).get("name") or target_raw)
        )
        source_tag_id = _int((source_item or {}).get("tagId"))
        target_tag_id = _int((target_item or {}).get("tagId"))
        if (
            not source
            or not target
            or (
                source_tag_id > 0
                and target_tag_id > 0
                and source_tag_id == target_tag_id
            )
        ):
            continue
        evidence_ids = _evidence_ids(
            _strings(item.get("evidenceRefs"), limit=40),
            evidence_by_ref=evidence_by_ref,
            explicit_ids=item.get("evidenceEventIds"),
        )
        if not evidence_ids and not global_catalog:
            continue
        if global_catalog and not _tag_items_exact_synonym(
            source_item,
            target_item,
        ):
            continue
        result.append(
            {
                "source": source,
                "target": target,
                **(
                    {"sourceTagId": source_tag_id}
                    if source_tag_id > 0
                    else {}
                ),
                **(
                    {"targetTagId": target_tag_id}
                    if target_tag_id > 0
                    else {}
                ),
                "reason": compact_whitespace(
                    str(item.get("reason") or "同义标签规范化")
                ),
                "evidenceEventIds": evidence_ids,
                "confidence": _float(item.get("confidence"), default=0.8),
            }
        )
    return result


def _compile_book_merges(
    decisions_payload: Mapping[str, object],
    *,
    source_bundle: Mapping[str, object],
    project: str,
) -> list[dict[str, object]]:
    """Compile explicit, scope-checked Topic Book merge proposals.

    Book similarity is only a discovery signal.  The model must name existing
    physical Books and provide a semantic reason; the write/inspect paths
    repeat the owner, project and scope checks against the frozen/live catalog.
    """

    if not _is_global_catalog_audit(source_bundle):
        return []
    model_bundle = build_memory_curation_model_bundle(source_bundle)
    books = _dicts(source_bundle.get("existingMemoryBooks"))
    books_by_id = {
        compact_whitespace(str(item.get("bookId") or "")): item
        for item in books
        if compact_whitespace(str(item.get("bookId") or ""))
    }
    books_by_ref = {
        compact_whitespace(str(item.get("ref") or "")): item
        for item in _dicts(model_bundle.get("existingBooks"))
        if compact_whitespace(str(item.get("ref") or ""))
    }
    books_by_key = {
        compact_whitespace(str(item.get("bookKey") or "")): item
        for item in books
        if compact_whitespace(str(item.get("bookKey") or ""))
    }
    scope_fields = (
        "ownerKind",
        "ownerId",
        "project",
        "app",
        "knowledgeDomain",
        "scopeKind",
        "scopeId",
        "visibility",
        "scopeMode",
    )

    def same_authority_scope(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
        if any(
            compact_whitespace(str(left.get(field) or ""))
            != compact_whitespace(str(right.get(field) or ""))
            for field in scope_fields
        ):
            return False
        personal = (
            compact_whitespace(str(left.get("knowledgeDomain") or ""))
            == "personal_memory"
            and compact_whitespace(str(right.get("knowledgeDomain") or ""))
            == "personal_memory"
        )
        if not personal:
            return (
                compact_whitespace(str(left.get("authorizationRevision") or ""))
                == compact_whitespace(str(right.get("authorizationRevision") or ""))
                and compact_whitespace(str(left.get("bindingId") or ""))
                == compact_whitespace(str(right.get("bindingId") or ""))
            )
        return all(
            compact_whitespace(str(item.get("authorizationRevision") or ""))
            == "memory-book-v1"
            and compact_whitespace(str(item.get("bindingId") or ""))
            == "personal-memory-book:"
            + compact_whitespace(str(item.get("bookId") or ""))
            for item in (left, right)
        )

    def resolve(value: object) -> dict[str, object] | None:
        reference = compact_whitespace(str(value or ""))
        if not reference:
            return None
        if reference in books_by_ref:
            reference = compact_whitespace(
                str(books_by_ref[reference].get("bookId") or "")
            )
        return (
            books_by_id.get(reference)
            or books_by_key.get(reference)
            or next(
                (
                    item
                    for item in books
                    if normalize_text(reference)
                    and normalize_text(reference)
                    in {
                        normalize_text(str(item.get("title") or "")),
                        *{
                            normalize_text(alias)
                            for alias in _strings(item.get("aliases"), limit=64)
                        },
                    }
                ),
                None,
            )
        )

    raw_items: list[Mapping[str, object]] = []
    for key in ("bookMerges", "topicBookMerges", "mergeBooks"):
        raw_items.extend(
            item for item in _dicts(decisions_payload.get(key)) if isinstance(item, Mapping)
        )
    for item in _dicts(decisions_payload.get("decisions")):
        action = compact_whitespace(str(item.get("action") or "")).lower()
        if action in {"merge_book", "merge_topic_book", "book_merge"}:
            raw_items.append(item)

    result: list[dict[str, object]] = []
    seen_sources: set[str] = set()
    target_sources: dict[str, list[str]] = defaultdict(list)
    for item in raw_items:
        target = resolve(
            item.get("targetRef")
            or item.get("targetBookId")
            or item.get("target")
        )
        raw_sources = item.get("sourceRefs") or item.get("sourceBookIds")
        if raw_sources is None:
            raw_sources = [
                item.get("sourceRef")
                or item.get("sourceBookId")
                or item.get("source")
            ]
        source_items = [resolve(value) for value in _items(raw_sources)]
        source_items = [item for item in source_items if item is not None]
        if target is None or not source_items:
            continue
        target_id = compact_whitespace(str(target.get("bookId") or ""))
        if (
            not target_id
            or compact_whitespace(str(target.get("bookType") or "topic")) != "topic"
            or compact_whitespace(str(target.get("status") or "")) not in {"active", "approved"}
        ):
            continue
        confidence = max(0.0, min(1.0, _float(item.get("confidence"), default=0.0)))
        reason = compact_whitespace(
            str(item.get("reason") or item.get("semanticReason") or "")
        )[:360]
        # A score alone is never authorization.  Require a human-readable
        # semantic attestation and a high-confidence explicit proposal; the
        # independent verifier and live catalog gate still decide legality.
        if not reason or confidence < 0.8:
            continue
        if item.get("confirmed") is False or item.get("semanticMatch") is False:
            continue
        accepted_sources: list[str] = []
        for source in source_items:
            source_id = compact_whitespace(str(source.get("bookId") or ""))
            if (
                not source_id
                or source_id == target_id
                or source_id in seen_sources
                or compact_whitespace(str(source.get("bookType") or "topic")) != "topic"
                or compact_whitespace(str(source.get("status") or "")) not in {"active", "approved"}
                or not same_authority_scope(source, target)
                or (
                    compact_whitespace(project)
                    and compact_whitespace(str(source.get("project") or ""))
                    != compact_whitespace(project)
                )
            ):
                continue
            accepted_sources.append(source_id)
        if not accepted_sources:
            continue
        target_sources.setdefault(target_id, []).extend(accepted_sources)
        seen_sources.update(accepted_sources)
        result.append(
            {
                "targetBookId": target_id,
                "sourceBookIds": accepted_sources,
                "ownerKind": compact_whitespace(str(target.get("ownerKind") or "")),
                "ownerId": compact_whitespace(str(target.get("ownerId") or "")),
                "project": compact_whitespace(str(target.get("project") or project)),
                "reason": reason,
                "confidence": confidence,
            }
        )
    # Coalesce repeated proposals for one target so each source has one
    # deterministic redirect and one rollback record.
    coalesced: list[dict[str, object]] = []
    for target_id, source_ids in target_sources.items():
        first = next(item for item in result if item["targetBookId"] == target_id)
        coalesced.append(
            {
                **first,
                "sourceBookIds": list(dict.fromkeys(source_ids)),
            }
        )
    return coalesced


def _derive_tag_edges(
    *,
    atom_tags: Mapping[str, list[str]],
    atom_source_ids: Mapping[str, list[int]],
) -> list[dict[str, object]]:
    evidence_by_pair: dict[tuple[str, str], list[int]] = defaultdict(list)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    display_names: dict[str, str] = {}
    for atom_id, tags in atom_tags.items():
        unique = _unique_strings(tags, limit=8)
        if len(unique) < 2:
            continue
        for tag in unique:
            display_names.setdefault(normalize_text(tag), tag)
        anchor = unique[0]
        for related in unique[1:5]:
            pair = tuple(sorted((normalize_text(anchor), normalize_text(related))))
            if not pair[0] or pair[0] == pair[1]:
                continue
            counts[pair] += 1
            evidence_by_pair[pair] = _unique_ints(
                [*evidence_by_pair[pair], *atom_source_ids.get(atom_id, [])],
                limit=128,
            )
    result = []
    for pair, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        evidence_ids = evidence_by_pair[pair]
        if not evidence_ids:
            continue
        result.append(
            {
                "src": display_names[pair[0]],
                "dst": display_names[pair[1]],
                "edgeType": "related_to",
                "weight": min(0.95, 0.55 + 0.08 * max(0, count - 1)),
                "evidenceEventIds": evidence_ids,
            }
        )
        if len(result) >= 80:
            break
    return result


def _derive_topic_books(
    *,
    source_bundle: Mapping[str, object],
    semantic_groups: Mapping[str, Mapping[str, object]],
    memory_atoms: Mapping[str, Mapping[str, object]],
    group_atom_ids: Mapping[str, list[str]],
    group_source_ids: Mapping[str, list[int]],
    atom_tags: Mapping[str, list[str]],
    project: str,
    excluded_atom_ids: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    existing_by_id: dict[str, dict[str, object]] = {}
    for item in [
        *_dicts(source_bundle.get("existingMemoryBookIndex")),
        *_dicts(source_bundle.get("existingMemoryBooks")),
    ]:
        book_id = compact_whitespace(str(item.get("bookId") or ""))
        if not book_id:
            continue
        previous = existing_by_id.get(book_id)
        if previous is None:
            existing_by_id[book_id] = dict(item)
            continue
        merged = dict(previous)
        for field, value in item.items():
            if field in {
                "aliases",
                "tags",
                "queryExpansions",
                "semanticGroupIds",
                "groupIds",
                "memoryAtomIds",
                "atomIds",
                "sourceEventIds",
            }:
                merged[field] = list(
                    dict.fromkeys(
                        [*_items(previous.get(field)), *_items(value)]
                    )
                )
            elif field not in merged or merged[field] in (None, "", []):
                merged[field] = value
        existing_by_id[book_id] = merged
    existing_books = list(existing_by_id.values())
    known_atoms = {str(item.get("atomId") or item.get("id") or ""): item
                   for item in _dicts(source_bundle.get("existingMemoryAtoms"))}
    known_atoms.update(memory_atoms)
    excluded = set(excluded_atom_ids or ())
    excluded.update(str(item.get("supersedesId")) for item in memory_atoms.values()
                    if item.get("supersedesId"))

    def resolve_book(book: Mapping[str, object] | None) -> dict[str, object] | None:
        current = dict(book or {})
        visited: set[str] = set()
        while current:
            book_id = compact_whitespace(str(current.get("bookId") or ""))
            if not book_id or book_id in visited:
                return None
            visited.add(book_id)
            book_project = compact_whitespace(str(current.get("project") or ""))
            if book_project and project and book_project != compact_whitespace(project):
                return None
            if compact_whitespace(str(current.get("status") or "")) != "superseded":
                return current
            redirect_id = compact_whitespace(
                str(current.get("supersededByBookId") or "")
            )
            if not redirect_id:
                return None
            current = dict(existing_by_id.get(redirect_id) or {})
        return None

    result: dict[str, dict[str, object]] = {}
    for group_id, atom_ids in group_atom_ids.items():
        group = semantic_groups.get(group_id)
        if group is None or not atom_ids:
            continue
        explicit_book_id = compact_whitespace(
            str(group.get("topicBookId") or group.get("bookId") or "")
        )
        existing = (
            resolve_book(existing_by_id.get(explicit_book_id))
            if explicit_book_id
            else None
        )
        if existing is None:
            existing = next(
                (
                    resolve_book(item)
                    for item in existing_books
                    if group_id in _strings(item.get("semanticGroupIds"), limit=8)
                    and (
                        compact_whitespace(str(item.get("project") or ""))
                        == compact_whitespace(project)
                        or not compact_whitespace(str(item.get("project") or ""))
                    )
                    and resolve_book(item) is not None
                ),
                None,
            )
        if existing is None:
            group_terms = {
                normalize_text(str(value or ""))
                for value in [
                    group.get("title"),
                    *_strings(group.get("aliases"), limit=16),
                ]
                if normalize_text(str(value or ""))
            }
            alias_matches = [
                resolved
                for item in existing_books
                if (
                    compact_whitespace(str(item.get("project") or ""))
                    == compact_whitespace(project)
                    or not compact_whitespace(str(item.get("project") or ""))
                )
                and group_terms.intersection(
                    {
                        normalize_text(str(item.get("title") or "")),
                        normalize_text(str(item.get("bookKey") or "")),
                        *{
                            normalize_text(alias)
                            for alias in _strings(item.get("aliases"), limit=32)
                        },
                    }
                )
                for resolved in [resolve_book(item)]
                if resolved is not None
            ]
            if len(alias_matches) == 1:
                existing = alias_matches[0]
        title = compact_whitespace(
            str((existing or {}).get("title") or group.get("title") or "个人知识")
        )
        member_ids = _unique_strings([
            *atom_ids, *_strings((existing or {}).get("memoryAtomIds"), limit=256),
        ], limit=256)
        member_ids = [atom_id for atom_id in member_ids if atom_id not in excluded
                      and str(known_atoms.get(atom_id, {}).get("status") or "active") in {"active", "approved"}
                      and str(known_atoms.get(atom_id, {}).get("claimState") or "current") == "current"]
        statements = _unique_strings(
            [
                compact_whitespace(str(known_atoms[atom_id].get("canonicalText") or known_atoms[atom_id].get("text") or ""))
                for atom_id in member_ids
                if atom_id in known_atoms
            ],
            limit=24,
        )
        # The bounded summary is rebuilt from known current members. Previously
        # generated prose is not independent evidence and cannot carry a
        # superseded conclusion forward or consume the new correction's budget.
        summary = truncate_text("；".join(statements), 900)
        book_key = compact_whitespace(str((existing or {}).get("bookKey") or ""))
        if not book_key:
            book_key = group_id.removeprefix("group:")
        book_id = compact_whitespace(str((existing or {}).get("bookId") or ""))
        if not book_id:
            book_id = f"book:topic:{book_key}"
        tags = _unique_strings(
            [
                *_strings((existing or {}).get("tags"), limit=32),
                *(
                    tag
                    for atom_id in atom_ids
                    for tag in atom_tags.get(atom_id, [])
                ),
            ],
            limit=32,
        )
        result[group_id] = {
            "bookId": book_id,
            "bookType": "topic",
            "bookKey": book_key,
            "title": title,
            "summary": summary,
            "aliases": _unique_strings(
                [
                    *_strings((existing or {}).get("aliases"), limit=32),
                    *_strings(group.get("aliases"), limit=16),
                    title,
                ],
                limit=48,
            ),
            "tags": tags,
            "surfaceHints": [],
            "queryExpansions": _unique_strings(
                [title, *_strings(group.get("aliases"), limit=16), *tags],
                limit=40,
            ),
            "sourceEventIds": _unique_ints(
                [
                    *_positive_ints((existing or {}).get("sourceEventIds")),
                    *group_source_ids.get(group_id, []),
                ],
                limit=512,
            ),
            "memoryAtomIds": member_ids,
            "semanticGroupIds": [group_id],
            "project": project,
            "app": "",
            "confidence": 0.75,
            "qualityScore": 0.75,
            "status": "active",
        }
    return result


def _derive_lexicon_lane(
    *,
    source_bundle: Mapping[str, object],
    event_group_ids: Mapping[int, list[str]],
    project: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    """Create lexicon proposals only from native Rime surface feedback."""

    events = _dicts(source_bundle.get("recentEvents"))
    positive: dict[tuple[str, str], dict[str, object]] = {}
    negative: dict[tuple[str, str], dict[str, object]] = {}
    feedback_count = 0
    for item in _dicts(source_bundle.get("rimeRankFeedback")):
        pinyin = _normalized_pinyin(item.get("preedit"))
        action = compact_whitespace(str(item.get("action") or "")).lower()
        accepted = compact_whitespace(str(item.get("acceptedText") or ""))
        rejected = compact_whitespace(str(item.get("rejectedText") or ""))
        if not pinyin:
            continue
        feedback_count += 1
        accepted_source_ids = _surface_source_ids(accepted, events=events)
        rank = max(1, _int(item.get("candidateRank")) or 1)
        if (
            action in {"accepted", "boost", "correction_pair"}
            and _valid_phrase(accepted)
            and accepted_source_ids
        ):
            key = (accepted, pinyin)
            entry = positive.setdefault(
                key,
                {
                    "count": 0,
                    "score": 0,
                    "explicit": 0,
                    "nonTop": 0,
                    "sourceEventIds": [],
                    "reasons": defaultdict(int),
                },
            )
            entry["count"] = _int(entry.get("count")) + 1
            entry["score"] = _int(entry.get("score")) + (
                200 if action == "boost" else 160 if action == "correction_pair" else 40
            ) + min(max(rank - 1, 0), 5) * 8
            if action in {"boost", "correction_pair"}:
                entry["explicit"] = _int(entry.get("explicit")) + 1
            if action == "accepted" and rank > 1:
                entry["nonTop"] = _int(entry.get("nonTop")) + 1
            entry["sourceEventIds"] = _unique_ints(
                [*_positive_ints(entry.get("sourceEventIds")), *accepted_source_ids],
                limit=128,
            )
            reasons = entry["reasons"]
            if isinstance(reasons, defaultdict):
                reasons[action] += 1
        if action in {"correction_pair", "downrank", "backspace_downrank"}:
            negative_text = rejected or accepted
            provenance_ids = accepted_source_ids or _surface_source_ids(
                negative_text,
                events=events,
            )
            if _valid_phrase(negative_text) and provenance_ids:
                key = (negative_text, pinyin)
                entry = negative.setdefault(
                    key,
                    {"count": 0, "score": 0, "sourceEventIds": []},
                )
                entry["count"] = _int(entry.get("count")) + 1
                entry["score"] = _int(entry.get("score")) + (
                    180
                    if action == "correction_pair"
                    else 140
                    if action == "downrank"
                    else 100
                )
                entry["sourceEventIds"] = _unique_ints(
                    [*_positive_ints(entry.get("sourceEventIds")), *provenance_ids],
                    limit=128,
                )

    phrase_candidates: list[dict[str, object]] = []
    for (text, pinyin), item in positive.items():
        positive_count = _int(item.get("count"))
        explicit_count = _int(item.get("explicit"))
        non_top_count = _int(item.get("nonTop"))
        enough = (
            explicit_count > 0
            or non_top_count > 0
            or positive_count >= (3 if _cjk_length(text) == 1 else 2)
        )
        negative_score = _int((negative.get((text, pinyin)) or {}).get("score"))
        net_score = _int(item.get("score")) - negative_score
        if not enough or net_score <= 0:
            continue
        source_ids = _positive_ints(item.get("sourceEventIds"))
        group_ids = _unique_strings(
            [
                group_id
                for source_id in source_ids
                for group_id in event_group_ids.get(source_id, [])
            ],
            limit=4,
        )
        reasons = item.get("reasons")
        reason_text = ""
        if isinstance(reasons, Mapping):
            reason_text = "、".join(
                f"{name} {count} 次" for name, count in sorted(reasons.items())
            )
        phrase_candidates.append(
            {
                "text": text,
                "pinyin": pinyin,
                "tags": ["个人词库"],
                "semanticGroupIds": group_ids,
                "weight": min(1.0, max(0.55, net_score / 240.0)),
                "sourceEventIds": source_ids,
                "project": project,
                "reason": f"Rime 原生反馈：{reason_text or '已接受'}",
            }
        )

    negative_phrases: list[dict[str, object]] = []
    for (text, _pinyin), item in negative.items():
        positive_score = _int((positive.get((text, _pinyin)) or {}).get("score"))
        if _int(item.get("score")) <= positive_score:
            continue
        negative_phrases.append(
            {
                "text": text,
                "sourceEventIds": _positive_ints(item.get("sourceEventIds")),
                "reason": "Rime 退格、降权或纠错反馈",
            }
        )
    phrase_candidates.sort(key=lambda item: (-float(item["weight"]), str(item["text"])))
    negative_phrases.sort(key=lambda item: str(item["text"]))
    return (
        phrase_candidates[:48],
        negative_phrases[:48],
        {
            "source": "native-rime-feedback",
            "modelGenerated": False,
            "feedbackCount": feedback_count,
            "phraseCandidateCount": min(48, len(phrase_candidates)),
            "negativePhraseCount": min(48, len(negative_phrases)),
        },
    )


def _event_group_index(
    *,
    atom_groups: Mapping[str, list[str]],
    atom_source_ids: Mapping[str, list[int]],
) -> dict[int, list[str]]:
    result: dict[int, list[str]] = defaultdict(list)
    for atom_id, source_ids in atom_source_ids.items():
        for source_id in source_ids:
            result[source_id] = _unique_strings(
                [*result[source_id], *atom_groups.get(atom_id, [])],
                limit=4,
            )
    return dict(result)


def _surface_source_ids(text: str, *, events: list[dict[str, object]]) -> list[int]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    result: list[int] = []
    for event in events:
        event_text = normalize_text(str(event.get("text") or ""))
        if normalized not in event_text:
            continue
        result.extend(
            source_id
            for source_id in _positive_ints(
                event.get("sourceEventIds") or [event.get("eventId")]
            )
            if source_id not in result
        )
    return result


def _evidence_ids(
    refs: list[str],
    *,
    evidence_by_ref: Mapping[str, Mapping[str, object]],
    explicit_ids: object,
) -> list[int]:
    legal_ids = {
        source_id
        for item in evidence_by_ref.values()
        for source_id in _positive_ints(item.get("eventIds"))
    }
    result = [
        source_id
        for ref in refs
        for source_id in _positive_ints((evidence_by_ref.get(ref) or {}).get("eventIds"))
    ]
    result.extend(
        source_id
        for source_id in _positive_ints(explicit_ids)
        if source_id in legal_ids
    )
    return _unique_ints(result, limit=512)




def _canonical_tag(
    value: str,
    *,
    canonical_tag_by_name: Mapping[str, Mapping[str, object]],
) -> str:
    normalized = normalize_text(value)
    existing = canonical_tag_by_name.get(normalized)
    return compact_whitespace(str((existing or {}).get("name") or value))



def _atoms_exactly_equivalent(
    left: Mapping[str, object] | None,
    right: Mapping[str, object] | None,
) -> bool:
    if left is None or right is None:
        return False
    left_hash = compact_whitespace(str(left.get("identityHash") or ""))
    right_hash = compact_whitespace(str(right.get("identityHash") or ""))
    if left_hash or right_hash:
        if not left_hash or not right_hash or left_hash != right_hash:
            return False
        left_authority = compact_whitespace(
            str(left.get("authorityHash") or "")
        )
        right_authority = compact_whitespace(
            str(right.get("authorityHash") or "")
        )
        return not left_authority or not right_authority or left_authority == right_authority
    return memory_atom_identity_hash(left) == memory_atom_identity_hash(right)


def _tag_items_exact_synonym(
    source_item: Mapping[str, object] | None,
    target_item: Mapping[str, object] | None,
) -> bool:
    if source_item is None or target_item is None:
        return False
    source_tag_id = _int(source_item.get("tagId"))
    target_tag_id = _int(target_item.get("tagId"))
    if (
        source_tag_id > 0
        and target_tag_id > 0
        and source_tag_id == target_tag_id
    ):
        return False
    source_name = normalize_text(str(source_item.get("name") or ""))
    target_name = normalize_text(str(target_item.get("name") or ""))
    if not source_name or not target_name:
        return False
    if source_name == target_name:
        return (
            source_tag_id > 0
            and target_tag_id > 0
            and source_tag_id != target_tag_id
        )
    source_aliases = {
        normalize_text(alias)
        for alias in _strings(source_item.get("aliases"), limit=32)
        if normalize_text(alias)
    }
    target_aliases = {
        normalize_text(alias)
        for alias in _strings(target_item.get("aliases"), limit=32)
        if normalize_text(alias)
    }
    return source_name in target_aliases or target_name in source_aliases

def _valid_tag_name(value: str) -> bool:
    text = compact_whitespace(value)
    return (
        bool(text)
        and len(text) <= 48
        and 1 <= _cjk_length(text) <= 16
        and "\t" not in text
        and "\n" not in text
        and text not in _TAG_NOISE
    )

def _valid_phrase(value: str) -> bool:
    text = compact_whitespace(value)
    return 1 <= _cjk_length(text) <= 18 and "\t" not in text and "\n" not in text


def _normalized_pinyin(value: object) -> str:
    normalized = (
        compact_whitespace(str(value or ""))
        .lower()
        .replace("'", " ")
        .replace("’", " ")
    )
    normalized = compact_whitespace(normalized)
    return normalized if _PINYIN_RE.fullmatch(normalized) else ""


def _canonical_kind(value: object) -> str:
    raw = compact_whitespace(str(value or "personal_fact")).lower()
    return _KIND_MAP.get(raw, "personal_fact")


def _single_app(items: list[Mapping[str, object]]) -> str:
    apps = {
        compact_whitespace(str(item.get("app") or ""))
        for item in items
        if compact_whitespace(str(item.get("app") or ""))
    }
    return next(iter(apps)) if len(apps) == 1 else ""


def _stable_key(value: str) -> str:
    compact = compact_whitespace(value).lower()
    ascii_key = _SAFE_KEY_RE.sub("-", compact).strip("-._")
    if len(ascii_key) >= 2:
        return ascii_key[:48]
    digest = stable_text_hash(normalize_text(compact)).removeprefix("sha256:")
    return f"topic-{digest[:16]}" if compact else ""


def _dicts(value: object) -> list[dict[str, object]]:
    return [dict(item) for item in value or [] if isinstance(item, Mapping)]


def _items(value: object) -> list[object]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [] if value is None else [value]


def _strings(value: object, *, limit: int | None) -> list[str]:
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = []
    return _unique_strings(
        [compact_whitespace(str(item or "")) for item in raw_values],
        limit=limit,
    )


def _unique_strings(values: list[str], *, limit: int | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        compact = compact_whitespace(value)
        normalized = normalize_text(compact)
        if not compact or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(compact)
        if limit is not None and len(result) >= limit:
            break
    return result


def _positive_ints(value: object) -> list[int]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set)):
        values = [value]
    else:
        values = value
    result: list[int] = []
    for item in values:
        number = _int(item)
        if number > 0 and number not in result:
            result.append(number)
    return result


def _unique_ints(values: list[int], *, limit: int | None) -> list[int]:
    result: list[int] = []
    for value in values:
        number = _int(value)
        if number <= 0 or number in result:
            continue
        result.append(number)
        if limit is not None and len(result) >= limit:
            break
    return result


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: object, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _cjk_length(value: str) -> int:
    return len(_CJK_RE.findall(value))
