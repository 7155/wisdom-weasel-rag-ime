from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher

from .memory_ingest import normalize_text
from .memory_tag_graph import TagActivation, activate_tag_graph
from .text_utils import compact_whitespace, token_terms


@dataclass(frozen=True)
class QueryExpansion:
    primary_query: str
    lexical_terms: tuple[str, ...]
    matched_aliases: tuple[str, ...]
    activated_tags: tuple[str, ...]
    activated_tag_details: tuple[TagActivation, ...]
    negative_tags: tuple[str, ...]
    expansion_terms: tuple[str, ...]


_NEGATIVE_FEEDBACK_ACTIONS = {
    "backspace_after_accept",
    "edited_after_accept",
    "ignored_repeatedly",
    "session_invalidated",
    "skipped",
    "skip",
    "rejected",
}


def build_query_expansion(
    conn: sqlite3.Connection,
    *,
    query_text: str,
    raw_input: str = "",
    preedit: str = "",
    rime_candidates: tuple[str, ...] = (),
    committed_tail: str = "",
    project: str = "",
    app: str = "",
    visible_doc_ids: tuple[str, ...] | None = None,
    visible_source_ids: tuple[str, ...] | None = None,
    visible_atom_ids: tuple[str, ...] | None = None,
) -> QueryExpansion:
    primary = _primary_query(
        query_text=query_text,
        raw_input=raw_input,
        preedit=preedit,
        rime_candidates=rime_candidates,
        committed_tail=committed_tail,
    )
    lexical_terms = _unique(
        token_terms(" ".join([primary, raw_input, preedit, committed_tail, *rime_candidates]), max_terms=32)
    )
    matched_aliases, atom_ids = _matched_aliases_and_atoms(
        conn,
        query_terms=(primary, *lexical_terms, *rime_candidates),
        allowed_atom_ids=visible_atom_ids,
    )
    activated_tags, activated_tag_details = _activated_tags(
        conn,
        query_terms=(primary, *lexical_terms, *rime_candidates, *matched_aliases),
        atom_ids=atom_ids,
        project=project,
        app=app,
        visible_doc_ids=visible_doc_ids,
    )
    negative_tags = _negative_feedback_tags(
        conn,
        project=project,
        app=app,
        visible_source_ids=visible_source_ids,
    )
    negative_tag_set = set(negative_tags)
    activated_tags = [tag for tag in activated_tags if tag not in negative_tag_set]
    activated_tag_details = [
        activation for activation in activated_tag_details if activation.tag not in negative_tag_set
    ]
    expansion_terms = _expansion_terms(
        conn,
        query_terms=(primary, *lexical_terms, *rime_candidates),
        atom_ids=atom_ids,
        activated_tags=activated_tags,
        negative_tags=negative_tags,
        project=project,
        app=app,
        visible_doc_ids=visible_doc_ids,
    )
    return QueryExpansion(
        primary_query=primary,
        lexical_terms=tuple(lexical_terms),
        matched_aliases=tuple(matched_aliases),
        activated_tags=tuple(activated_tags),
        activated_tag_details=tuple(activated_tag_details),
        negative_tags=tuple(negative_tags),
        expansion_terms=tuple(term for term in expansion_terms if term not in negative_tag_set),
    )


def _primary_query(
    *,
    query_text: str,
    raw_input: str,
    preedit: str,
    rime_candidates: tuple[str, ...],
    committed_tail: str,
) -> str:
    for value in (query_text, rime_candidates[0] if rime_candidates else "", preedit, raw_input, committed_tail):
        compact = compact_whitespace(value)
        if compact:
            return compact
    return ""


def _matched_aliases_and_atoms(
    conn: sqlite3.Connection,
    *,
    query_terms: tuple[str, ...],
    allowed_atom_ids: tuple[str, ...] | None = None,
) -> tuple[list[str], list[str]]:
    if allowed_atom_ids is not None and not allowed_atom_ids:
        return [], []
    if allowed_atom_ids is None:
        aliases = conn.execute(
            """SELECT memory_atom_id, alias, alias_type FROM memory_aliases
               ORDER BY weight DESC, created_at_ms ASC"""
        ).fetchall()
    else:
        aliases = conn.execute(
            """
            SELECT a.memory_atom_id, a.alias, a.alias_type
            FROM memory_aliases AS a
            JOIN json_each(?) AS visible ON CAST(visible.value AS TEXT) = a.memory_atom_id
            ORDER BY a.weight DESC, a.created_at_ms ASC
            """,
            (json.dumps(tuple(dict.fromkeys(allowed_atom_ids))),),
        ).fetchall()
    matched_atom_ids: list[str] = []
    matched_aliases: list[str] = []
    for row in aliases:
        alias = compact_whitespace(str(row["alias"] or ""))
        if not alias:
            continue
        if any(_alias_matches_query(alias, term) for term in query_terms if compact_whitespace(term)):
            atom_id = str(row["memory_atom_id"] or "")
            if atom_id and atom_id not in matched_atom_ids:
                matched_atom_ids.append(atom_id)
    if matched_atom_ids:
        placeholders = ", ".join("?" for _ in matched_atom_ids)
        rows = conn.execute(
            f"""
            SELECT alias
            FROM memory_aliases
            WHERE memory_atom_id IN ({placeholders})
            ORDER BY weight DESC, created_at_ms ASC
            """,
            tuple(matched_atom_ids),
        ).fetchall()
        matched_aliases = _unique(str(row["alias"]) for row in rows if compact_whitespace(str(row["alias"])))
    return matched_aliases, matched_atom_ids


def _alias_matches_query(alias: str, query: str) -> bool:
    alias_norm = normalize_text(alias)
    query_norm = normalize_text(query)
    if not alias_norm or not query_norm:
        return False
    if alias_norm in query_norm or query_norm in alias_norm:
        return True
    if len(alias_norm) >= 3 and len(query_norm) >= 3:
        return SequenceMatcher(None, alias_norm, query_norm).ratio() >= 0.66
    return False


def _activated_tags(
    conn: sqlite3.Connection,
    *,
    query_terms: tuple[str, ...],
    atom_ids: list[str],
    project: str,
    app: str,
    visible_doc_ids: tuple[str, ...] | None,
) -> tuple[list[str], list[TagActivation]]:
    seed_energies: dict[int, float] = {}
    tags: list[str] = []
    for tag_id, tag, energy in _direct_tag_matches(conn, query_terms=query_terms):
        seed_energies[tag_id] = max(seed_energies.get(tag_id, 0.0), energy)
        if tag not in tags:
            tags.append(tag)
    for tag_id, tag, energy in _atom_tags(conn, atom_ids=atom_ids):
        seed_energies[tag_id] = max(seed_energies.get(tag_id, 0.0), energy)
        if tag not in tags:
            tags.append(tag)
    for tag in _retrieval_doc_tags(
        conn,
        query_terms=query_terms,
        project=project,
        app=app,
        visible_doc_ids=visible_doc_ids,
    ):
        if tag not in tags:
            tags.append(tag)
    activations = activate_tag_graph(
        conn,
        seed_energies=seed_energies,
        max_hops=2,
        max_neighbors=8,
        min_energy=0.05,
    )
    ordered_activations = sorted(
        activations.values(),
        key=lambda activation: (activation.hop, -activation.energy, activation.tag_id),
    )
    for activation in ordered_activations:
        if activation.tag not in tags:
            tags.append(activation.tag)
    allowed_tags = set(tags[:32])
    return tags[:32], [activation for activation in ordered_activations if activation.tag in allowed_tags]


def _direct_tag_matches(
    conn: sqlite3.Connection,
    *,
    query_terms: tuple[str, ...],
) -> list[tuple[int, str, float]]:
    matches: list[tuple[int, str, float]] = []
    rows = conn.execute(
        """
        SELECT id, tag, normalized_tag, quality_score
        FROM memory_tags
        WHERE status = 'active' AND source IN ('dsv4', 'user')
        ORDER BY quality_score DESC, id ASC
        """
    ).fetchall()
    for row in rows:
        tag = str(row["tag"] or "")
        normalized = str(row["normalized_tag"] or normalize_text(tag))
        for term in query_terms:
            term_norm = normalize_text(term)
            if not term_norm:
                continue
            if normalized == term_norm or normalized in term_norm or term_norm in normalized:
                matches.append((int(row["id"]), tag, _seed_energy(row["quality_score"])))
                break
    return matches


def _atom_tags(conn: sqlite3.Connection, *, atom_ids: list[str]) -> list[tuple[int, str, float]]:
    if not atom_ids:
        return []
    placeholders = ", ".join("?" for _ in atom_ids)
    return [
        (
            int(row["id"]),
            str(row["tag"]),
            _seed_energy(float(row["quality_score"] or 0.5) * float(row["item_weight"] or 1.0)),
        )
        for row in conn.execute(
            f"""
            SELECT t.id, t.tag, t.quality_score, at.weight AS item_weight
            FROM memory_atom_tags at
            JOIN memory_tags t ON CAST(t.id AS TEXT) = CAST(at.tag_id AS TEXT)
            WHERE at.memory_atom_id IN ({placeholders})
              AND t.status = 'active'
              AND t.source IN ('dsv4', 'user')
            ORDER BY at.weight DESC, t.quality_score DESC
            """,
            tuple(atom_ids),
        ).fetchall()
    ]


def _retrieval_doc_tags(
    conn: sqlite3.Connection,
    *,
    query_terms: tuple[str, ...],
    project: str,
    app: str,
    visible_doc_ids: tuple[str, ...] | None,
) -> list[str]:
    if visible_doc_ids is not None and not visible_doc_ids:
        return []
    if visible_doc_ids is None:
        rows = conn.execute(
            """
            SELECT raw_text, tags_text, aliases_text, surface_hints_text, query_expansions_text, project, app
            FROM memory_retrieval_docs
            WHERE status = 'active'
              AND (? = '' OR project = ? OR project = '')
              AND (? = '' OR app = ? OR app = '')
            LIMIT 200
            """,
            (project, project, app, app),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT d.raw_text, d.tags_text, d.aliases_text, d.surface_hints_text,
                   d.query_expansions_text, d.project, d.app
            FROM memory_retrieval_docs AS d
            JOIN json_each(?) AS visible ON CAST(visible.value AS TEXT) = d.doc_id
            WHERE d.status = 'active'
            LIMIT 200
            """,
            (json.dumps(tuple(dict.fromkeys(visible_doc_ids))),),
        ).fetchall()
    tags: list[str] = []
    for row in rows:
        haystack = " ".join(
            str(row[key] or "")
            for key in ("raw_text", "tags_text", "aliases_text", "surface_hints_text", "query_expansions_text")
        )
        if not any(_term_hits_text(term, haystack) for term in query_terms):
            continue
        for tag in compact_whitespace(str(row["tags_text"] or "")).split():
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def _negative_feedback_tags(
    conn: sqlite3.Connection,
    *,
    project: str,
    app: str,
    visible_source_ids: tuple[str, ...] | None,
) -> list[str]:
    if visible_source_ids is not None and not visible_source_ids:
        return []
    join_visible = ""
    params: tuple[object, ...]
    if visible_source_ids is None:
        params = (*sorted(_NEGATIVE_FEEDBACK_ACTIONS), project, project, app, app)
    else:
        join_visible = "JOIN json_each(?) AS visible ON CAST(visible.value AS TEXT) = cf.memory_id"
        params = (json.dumps(tuple(dict.fromkeys(visible_source_ids))), *sorted(_NEGATIVE_FEEDBACK_ACTIONS), project, project, app, app)
    action_placeholders = ", ".join("?" for _ in _NEGATIVE_FEEDBACK_ACTIONS)
    rows = conn.execute(
        f"""
        SELECT cf.memory_id, cf.candidate_text
        FROM candidate_feedback cf
        {join_visible}
        WHERE cf.action IN ({action_placeholders})
          AND (? = '' OR cf.project = ? OR cf.project = '')
          AND (? = '' OR cf.app = ? OR cf.app = '')
        ORDER BY cf.created_at_ms DESC
        LIMIT 50
        """,
        params,
    ).fetchall()
    tags: list[str] = []
    for row in rows:
        memory_id = compact_whitespace(str(row["memory_id"] or ""))
        if not memory_id:
            continue
        tag_rows = conn.execute(
            """
            SELECT tag
            FROM (
                SELECT t.tag AS tag, mit.weight AS weight
                FROM memory_items mi
                JOIN memory_item_tags mit ON mit.memory_item_id = mi.id
                JOIN memory_tags t ON t.id = mit.tag_id
                WHERE mi.memory_id = ?
                  AND t.status = 'active'
                  AND t.source IN ('dsv4', 'user')

                UNION ALL

                SELECT t.tag AS tag, mat.weight AS weight
                FROM memory_atom_tags mat
                JOIN memory_tags t ON CAST(t.id AS TEXT) = CAST(mat.tag_id AS TEXT)
                WHERE mat.memory_atom_id = ?
                  AND t.status = 'active'
                  AND t.source IN ('dsv4', 'user')
            ) governed_tags
            ORDER BY weight DESC
            """,
            (memory_id, memory_id),
        ).fetchall()
        for tag_row in tag_rows:
            tag = str(tag_row["tag"] or "")
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def _expansion_terms(
    conn: sqlite3.Connection,
    *,
    query_terms: tuple[str, ...],
    atom_ids: list[str],
    activated_tags: list[str],
    negative_tags: list[str],
    project: str,
    app: str,
    visible_doc_ids: tuple[str, ...] | None,
) -> list[str]:
    terms: list[str] = []
    negative = set(negative_tags)
    if atom_ids:
        placeholders = ", ".join("?" for _ in atom_ids)
        rows = conn.execute(
            f"""
            SELECT alias, alias_type
            FROM memory_aliases
            WHERE memory_atom_id IN ({placeholders})
              AND alias_type IN ('alias', 'query_expansion', 'surface_hint')
            ORDER BY weight DESC, created_at_ms ASC
            """,
            tuple(atom_ids),
        ).fetchall()
        for row in rows:
            alias = str(row["alias"] or "")
            if alias and alias not in negative:
                terms.append(alias)
    for tag in activated_tags:
        if tag not in negative:
            terms.append(tag)
    for tag in _retrieval_doc_expansions(
        conn,
        query_terms=query_terms,
        project=project,
        app=app,
        visible_doc_ids=visible_doc_ids,
    ):
        if tag not in negative:
            terms.append(tag)
    return _unique(terms)[:32]


def _retrieval_doc_expansions(
    conn: sqlite3.Connection,
    *,
    query_terms: tuple[str, ...],
    project: str,
    app: str,
    visible_doc_ids: tuple[str, ...] | None,
) -> list[str]:
    if visible_doc_ids is not None and not visible_doc_ids:
        return []
    if visible_doc_ids is None:
        rows = conn.execute(
            """
            SELECT query_expansions_text, surface_hints_text
            FROM memory_retrieval_docs
            WHERE status = 'active'
              AND (? = '' OR project = ? OR project = '')
              AND (? = '' OR app = ? OR app = '')
            LIMIT 200
            """,
            (project, project, app, app),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT d.query_expansions_text, d.surface_hints_text
            FROM memory_retrieval_docs AS d
            JOIN json_each(?) AS visible ON CAST(visible.value AS TEXT) = d.doc_id
            WHERE d.status = 'active'
            LIMIT 200
            """,
            (json.dumps(tuple(dict.fromkeys(visible_doc_ids))),),
        ).fetchall()
    result: list[str] = []
    for row in rows:
        haystack = f"{row['query_expansions_text'] or ''} {row['surface_hints_text'] or ''}"
        if not any(_term_hits_text(term, haystack) for term in query_terms):
            continue
        result.extend(compact_whitespace(haystack).split())
    return result


def _term_hits_text(term: str, text: str) -> bool:
    term_norm = normalize_text(term)
    text_norm = normalize_text(text)
    return bool(term_norm and (term_norm in text_norm or text_norm in term_norm))


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = compact_whitespace(str(value))
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _seed_energy(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.5
    return max(0.2, min(1.0, parsed))
