from __future__ import annotations

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
    "fact": "project_fact",
    "project_fact": "project_fact",
    "requirement": "project_requirement",
    "project_requirement": "project_requirement",
    "preference": "durable_preference",
    "durable_preference": "durable_preference",
    "decision": "project_decision",
    "project_decision": "project_decision",
    "plan": "project_plan",
    "project_plan": "project_plan",
    "question": "project_question",
    "project_question": "project_question",
}


def build_memory_curation_model_bundle(bundle: Mapping[str, object]) -> dict[str, object]:
    """Expose compact stable references for one Atom-first curation snapshot."""

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
                "eventIds": source_ids,
                "text": text[:600],
                "app": compact_whitespace(str(item.get("app") or ""))[:120],
                "createdAtMs": _int(item.get("createdAtMs")),
                "contextGroupId": compact_whitespace(str(item.get("contextGroupId") or ""))[:120],
                "localContext": local_context[-800:],
            }
        )

    atoms = [
        {
            "ref": f"P{index}",
            "atomId": compact_whitespace(str(item.get("atomId") or item.get("id") or "")),
            "kind": compact_whitespace(str(item.get("kind") or "project_fact")),
            "text": compact_whitespace(
                str(item.get("canonicalText") or item.get("text") or "")
            )[:500],
            "tags": _strings(item.get("tags"), limit=16),
            "groupIds": _strings(
                item.get("semanticGroupIds") or item.get("groupIds"),
                limit=8,
            ),
            "app": compact_whitespace(str(item.get("app") or ""))[:120],
            "status": compact_whitespace(str(item.get("status") or "active")),
        }
        for index, item in enumerate(_dicts(bundle.get("existingMemoryAtoms")), start=1)
        if compact_whitespace(str(item.get("atomId") or item.get("id") or ""))
        and compact_whitespace(str(item.get("canonicalText") or item.get("text") or ""))
    ]
    groups = [
        {
            "ref": f"G{index}",
            "groupId": compact_whitespace(str(item.get("groupId") or "")),
            "title": compact_whitespace(str(item.get("title") or ""))[:80],
            "description": compact_whitespace(str(item.get("description") or ""))[:240],
            "aliases": _strings(item.get("aliases"), limit=12),
            "tags": _strings(item.get("tags"), limit=16),
        }
        for index, item in enumerate(_dicts(bundle.get("existingSemanticGroups")), start=1)
        if compact_whitespace(str(item.get("groupId") or ""))
    ]
    tags = [
        {
            "ref": f"T{index}",
            "tagId": item.get("tagId"),
            "name": compact_whitespace(str(item.get("name") or ""))[:80],
            "description": compact_whitespace(str(item.get("description") or ""))[:200],
            "aliases": _strings(item.get("aliases"), limit=16),
            "groupIds": _strings(item.get("semanticGroupIds"), limit=8),
            "degree": _int(item.get("degree")),
        }
        for index, item in enumerate(_dicts(bundle.get("existingSemanticTags")), start=1)
        if compact_whitespace(str(item.get("name") or ""))
    ]
    tag_ref_by_name = {
        normalize_text(str(item["name"])): str(item["ref"])
        for item in tags
        if normalize_text(str(item["name"]))
    }
    edges: list[dict[str, object]] = []
    for item in _dicts(bundle.get("existingTagEdges")):
        source_ref = tag_ref_by_name.get(normalize_text(str(item.get("src") or "")), "")
        target_ref = tag_ref_by_name.get(normalize_text(str(item.get("dst") or "")), "")
        if not source_ref or not target_ref:
            continue
        edges.append(
            {
                "sourceRef": source_ref,
                "targetRef": target_ref,
                "type": compact_whitespace(str(item.get("edgeType") or "related_to")),
                "weight": _float(item.get("weight"), default=0.5),
            }
        )
        if len(edges) >= 240:
            break
    books = [
        {
            "ref": f"B{index}",
            "bookId": compact_whitespace(str(item.get("bookId") or "")),
            "title": compact_whitespace(str(item.get("title") or ""))[:100],
            "summary": compact_whitespace(str(item.get("summary") or ""))[:320],
            "tags": _strings(item.get("tags"), limit=16),
            "groupIds": _strings(item.get("semanticGroupIds"), limit=8),
            "atomIds": _strings(item.get("memoryAtomIds"), limit=80),
        }
        for index, item in enumerate(_dicts(bundle.get("existingMemoryBooks")), start=1)
        if compact_whitespace(str(item.get("bookId") or ""))
    ]
    return {
        "schemaVersion": MEMORY_CURATION_MODEL_BUNDLE_SCHEMA_VERSION,
        "project": compact_whitespace(str(bundle.get("project") or "")),
        "curationScope": (
            "global"
            if compact_whitespace(str(bundle.get("curationScope") or "")).lower() == "global"
            else "incremental"
        ),
        "catalogAudit": bool(bundle.get("catalogAudit")),
        "evidenceOrder": compact_whitespace(str(bundle.get("evidenceOrder") or "")),
        "inputs": evidence,
        "existingAtoms": atoms,
        "existingGroups": groups,
        "existingTags": tags,
        "existingTagEdges": edges,
        "existingBooks": books,
        "cursor": dict(bundle.get("cursor") or {}),
        "reconstruction": dict(bundle.get("reconstruction") or {}),
        "catalogTruncated": {
            "atoms": len(_dicts(bundle.get("existingMemoryAtoms"))) > len(atoms),
            "groups": len(_dicts(bundle.get("existingSemanticGroups"))) > len(groups),
            "tags": len(_dicts(bundle.get("existingSemanticTags"))) > len(tags),
            "books": len(_dicts(bundle.get("existingMemoryBooks"))) > len(books),
        },
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
    ignored_count = 0
    invalid_count = 0
    merge_count = 0

    decision_items = _curation_decision_items(
        decisions_payload,
        evidence_by_ref=evidence_by_ref,
    )
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
            continue
        if action not in {"create", "attach", "update", "supersede", "merge"}:
            warnings.append(f"invalid_atom_action_ignored:{decision_index}:{action or 'empty'}")
            invalid_count += 1
            continue
        if action != "merge" and not source_ids:
            warnings.append(f"atom_decision_missing_evidence:{decision_index}")
            invalid_count += 1
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
            continue
        if action == "supersede" and not old_atom_id:
            warnings.append(f"supersede_target_not_found:{decision_index}:{target_ref or 'empty'}")
            invalid_count += 1
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
        existing_source_ids = _unique_ints(
            [
                *_positive_ints((existing_atom or {}).get("sourceEventIds")),
                *_positive_ints((merge_source_atom or {}).get("sourceEventIds")),
                *_positive_ints((staged_atom or {}).get("sourceEventIds")),
            ],
            limit=512,
        )
        combined_source_ids = _unique_ints([*existing_source_ids, *source_ids], limit=512)
        base_atom: dict[str, object] = dict(existing_atom or {})
        for field, limit in (
            ("tags", 32),
            ("semanticGroupIds", 8),
            ("groupIds", 8),
            ("aliases", 48),
            ("queryExpansions", 48),
            ("sourceMemoryIds", 64),
        ):
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
        for existing_tag in _strings(base_atom.get("tags"), limit=32):
            resolved = _canonical_tag(
                existing_tag,
                canonical_tag_by_name=canonical_tag_by_name,
            )
            if resolved and resolved not in tag_names:
                tag_names.append(resolved)
        existing_group_ids = _strings(
            base_atom.get("semanticGroupIds")
            or base_atom.get("groupIds"),
            limit=8,
        )
        group_ids = _unique_strings([*existing_group_ids, *group_ids], limit=4)

        evidence_items = [
            evidence_by_ref[ref] for ref in evidence_refs if ref in evidence_by_ref
        ]
        scope_app = _single_app(
            [
                *evidence_items,
                {"app": base_atom.get("app")},
                {"app": (merge_source_atom or {}).get("app")},
            ]
        )
        kind = _canonical_kind(
            (
                base_atom.get("kind")
                if action in {"attach", "merge"}
                else decision.get("kind")
            )
            or base_atom.get("kind")
            or "project_fact"
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
                *_strings(base_atom.get("aliases"), limit=48),
                *merge_aliases,
                *_strings(decision.get("aliases"), limit=32),
            ],
            limit=48,
        )
        query_expansions = _unique_strings(
            [
                *_strings(base_atom.get("queryExpansions"), limit=48),
                *_strings(decision.get("queryExpansions"), limit=32),
                *tag_names,
            ],
            limit=48,
        )
        memory_atoms[atom_id] = {
            "atomId": atom_id,
            "kind": kind,
            "canonicalText": canonical,
            "summary": compact_whitespace(
                str(decision.get("summary") or (staged_atom or {}).get("summary") or canonical)
            )[:600],
            "tags": tag_names,
            "aliases": aliases,
            # Surface hints and lexicon phrases are intentionally not model
            # outputs. The Rime feedback lane below owns those proposals.
            "surfaceHints": [],
            "queryExpansions": query_expansions,
            "sourceEventIds": combined_source_ids,
            "sourceMemoryIds": _strings(base_atom.get("sourceMemoryIds"), limit=64),
            "semanticGroupIds": group_ids,
            "directCandidateAllowed": False,
            "project": compact_whitespace(str(base_atom.get("project") or project)),
            "app": scope_app,
            "confidence": _float(decision.get("confidence"), default=0.75),
            "qualityScore": _float(
                decision.get("qualityScore"),
                default=_float(decision.get("confidence"), default=0.75),
            ),
            "status": "active",
        }
        atom_groups[atom_id] = group_ids
        atom_tags[atom_id] = tag_names
        atom_source_ids[atom_id] = combined_source_ids
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

    tag_merges = _compile_tag_merges(
        decisions_payload,
        evidence_by_ref=evidence_by_ref,
        tags_by_ref=tags_by_ref,
        canonical_tag_by_name=canonical_tag_by_name,
    )
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
        if memory_atoms or semantic_groups or semantic_tags or tag_merges or phrase_candidates or negative_phrases
        else "no_changes"
    )
    return {
        "schemaVersion": MEMORY_CURATION_DECISION_SCHEMA_VERSION,
        "dailyBooks": [],
        "topicBooks": list(topic_books.values()),
        "semanticGroups": list(semantic_groups.values()),
        "semanticTags": list(semantic_tags.values()),
        "tagMerges": tag_merges,
        "memoryAtoms": list(memory_atoms.values()),
        "tagEdges": tag_edges,
        "phraseCandidates": phrase_candidates,
        "negativePhrases": negative_phrases,
        "supersedes": supersedes,
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
            "derivedGroupCount": len(semantic_groups),
            "derivedTagCount": len(semantic_tags),
            "derivedBookCount": len(topic_books),
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
) -> list[str]:
    refs = _strings(
        decision.get("topicRefs")
        or decision.get("groupRefs")
        or [decision.get("topicRef") or decision.get("groupRef")],
        limit=4,
    )
    result: list[str] = []
    for ref in refs:
        existing = groups_by_ref.get(ref)
        if existing is None and ref in source_groups_by_id:
            existing = source_groups_by_id[ref]
        if existing is not None:
            group_id = compact_whitespace(str(existing.get("groupId") or ""))
            title = compact_whitespace(str(existing.get("title") or ""))
            description = compact_whitespace(str(existing.get("description") or ""))
            aliases = _strings(existing.get("aliases"), limit=24)
            tags = _strings(existing.get("tags"), limit=24)
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
            "title": title or compact_whitespace(str((current or {}).get("title") or "个人知识")),
            "description": (
                description
                or compact_whitespace(str((current or {}).get("description") or ""))
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
    if not result and len(source_groups_by_id) == 1:
        only_group = next(iter(source_groups_by_id.values()))
        group_id = compact_whitespace(str(only_group.get("groupId") or ""))
        if _GROUP_ID_RE.fullmatch(group_id):
            result.append(group_id)
    if not result:
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
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in _dicts(decisions_payload.get("tagMerges")):
        source = _tag_name_from_ref(
            item.get("sourceRef") or item.get("source"),
            tags_by_ref=tags_by_ref,
            canonical_tag_by_name=canonical_tag_by_name,
        )
        target = _tag_name_from_ref(
            item.get("targetRef") or item.get("target"),
            tags_by_ref=tags_by_ref,
            canonical_tag_by_name=canonical_tag_by_name,
        )
        if not source or not target or normalize_text(source) == normalize_text(target):
            continue
        evidence_ids = _evidence_ids(
            _strings(item.get("evidenceRefs"), limit=40),
            evidence_by_ref=evidence_by_ref,
            explicit_ids=item.get("evidenceEventIds"),
        )
        if not evidence_ids:
            continue
        result.append(
            {
                "source": source,
                "target": target,
                "reason": compact_whitespace(str(item.get("reason") or "同义标签规范化")),
                "evidenceEventIds": evidence_ids,
                "confidence": _float(item.get("confidence"), default=0.8),
            }
        )
    return result[:32]


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
) -> dict[str, dict[str, object]]:
    existing_books = _dicts(source_bundle.get("existingMemoryBooks"))
    result: dict[str, dict[str, object]] = {}
    for group_id, atom_ids in group_atom_ids.items():
        group = semantic_groups.get(group_id)
        if group is None or not atom_ids:
            continue
        existing = next(
            (
                item
                for item in existing_books
                if group_id in _strings(item.get("semanticGroupIds"), limit=8)
            ),
            None,
        )
        title = compact_whitespace(
            str((existing or {}).get("title") or group.get("title") or "个人知识")
        )
        statements = _unique_strings(
            [
                compact_whitespace(str(memory_atoms[atom_id].get("canonicalText") or ""))
                for atom_id in atom_ids
                if atom_id in memory_atoms
            ],
            limit=24,
        )
        previous_summary = compact_whitespace(str((existing or {}).get("summary") or ""))
        additions = [
            statement
            for statement in statements
            if normalize_text(statement) not in normalize_text(previous_summary)
        ]
        if previous_summary:
            summary = previous_summary
            if additions:
                summary = compact_whitespace(
                    f"{previous_summary} 本次补充：" + "；".join(additions)
                )
        else:
            summary = compact_whitespace(
                f"本主题汇总经审核的长期记忆：" + "；".join(statements)
            )
        summary = truncate_text(summary, 900)
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
            "memoryAtomIds": _unique_strings(
                [
                    *_strings((existing or {}).get("memoryAtomIds"), limit=256),
                    *atom_ids,
                ],
                limit=256,
            ),
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


def _tag_name_from_ref(
    value: object,
    *,
    tags_by_ref: Mapping[str, Mapping[str, object]],
    canonical_tag_by_name: Mapping[str, Mapping[str, object]],
) -> str:
    raw = compact_whitespace(str(value or ""))
    if raw in tags_by_ref:
        raw = compact_whitespace(str(tags_by_ref[raw].get("name") or ""))
    return _canonical_tag(
        raw.removeprefix("new:"),
        canonical_tag_by_name=canonical_tag_by_name,
    )


def _canonical_tag(
    value: str,
    *,
    canonical_tag_by_name: Mapping[str, Mapping[str, object]],
) -> str:
    normalized = normalize_text(value)
    existing = canonical_tag_by_name.get(normalized)
    return compact_whitespace(str((existing or {}).get("name") or value))


def _valid_tag_name(value: str) -> bool:
    text = compact_whitespace(value)
    if not 2 <= len(text) <= 32:
        return False
    if text in _TAG_NOISE:
        return False
    lowered = text.lower()
    return not (
        lowered.startswith("com.")
        or lowered.startswith("app:")
        or lowered.startswith("source:")
        or ":" in lowered and lowered.split(":", 1)[0] in {"source", "status", "app"}
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
    raw = compact_whitespace(str(value or "project_fact")).lower()
    return _KIND_MAP.get(raw, "project_fact")


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


def _strings(value: object, *, limit: int) -> list[str]:
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


def _unique_strings(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        compact = compact_whitespace(value)
        normalized = normalize_text(compact)
        if not compact or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(compact)
        if len(result) >= limit:
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


def _unique_ints(values: list[int], *, limit: int) -> list[int]:
    result: list[int] = []
    for value in values:
        number = _int(value)
        if number <= 0 or number in result:
            continue
        result.append(number)
        if len(result) >= limit:
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
