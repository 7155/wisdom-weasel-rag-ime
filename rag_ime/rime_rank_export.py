from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .db import apply_database_migrations
from .text_utils import compact_whitespace


SCHEMA_VERSION = "rag-ime.rime-rank-export.v1"

_POSITIVE_ACTIONS = frozenset({"accepted", "boost", "correction_pair"})
_NEGATIVE_ACTIONS = frozenset({"backspace_downrank", "downrank", "correction_pair"})
_SOURCE_METADATA_KEYS = frozenset(
    {
        "source",
        "source_type",
        "sourcetype",
        "candidate_source",
        "candidatesource",
        "lane",
        "channel",
        "origin",
        "provider",
    }
)
_NON_RIME_SOURCE_TOKENS = frozenset(
    {
        "active_rag",
        "deepseek",
        "ds",
        "knowledge",
        "llm",
        "memory",
        "minimind",
        "mlx",
        "model",
        "notion",
        "rag",
    }
)
_PINYIN_RE = re.compile(r"^[a-zv]+(?: [a-zv]+)*$")


def ensure_rime_rank_feedback_schema(conn: sqlite3.Connection) -> None:
    apply_database_migrations(conn)


def preview_rime_rank_export(
    db_path: str | Path,
    *,
    project: str = "",
    limit: int = 200,
    dict_name: str = "rag_ime_user",
) -> dict[str, object]:
    with closing(sqlite3.connect(str(db_path))) as conn:
        ensure_rime_rank_feedback_schema(conn)
        entries = _rank_entries(conn, project=project, limit=max(1, int(limit)))
    yaml_text = _render_rime_dict(dict_name=dict_name, entries=entries)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "dryRun": True,
        "project": project,
        "dictName": dict_name,
        "entryCount": len(entries),
        "entries": entries,
        "yaml": yaml_text,
    }


def apply_rime_rank_export(
    db_path: str | Path,
    *,
    target_file: str | Path,
    project: str = "",
    limit: int = 200,
    dict_name: str = "rag_ime_user",
    confirm_text: str = "",
) -> dict[str, object]:
    if confirm_text != "APPLY_RIME_RANK_EXPORT":
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": False,
            "applied": False,
            "reason": "confirm_text_required",
            "confirmText": "APPLY_RIME_RANK_EXPORT",
        }
    preview = preview_rime_rank_export(db_path, project=project, limit=limit, dict_name=dict_name)
    target = Path(target_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.read_text(encoding="utf-8") if target.exists() else ""
    backup = ""
    if previous:
        backup = str(target.with_suffix(target.suffix + f".bak-{int(time.time())}"))
        Path(backup).write_text(previous, encoding="utf-8")
    target.write_text(str(preview["yaml"]), encoding="utf-8")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "applied": True,
        "targetFile": str(target),
        "backupFile": backup,
        "entryCount": preview["entryCount"],
    }


def rollback_rime_rank_export(*, target_file: str | Path, backup_file: str | Path) -> dict[str, object]:
    target = Path(target_file)
    backup = Path(backup_file)
    if not backup.exists():
        return {"schemaVersion": SCHEMA_VERSION, "ok": False, "rolledBack": False, "reason": "backup_missing"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
    return {"schemaVersion": SCHEMA_VERSION, "ok": True, "rolledBack": True, "targetFile": str(target)}


def record_rime_rank_feedback(
    db_path: str | Path,
    *,
    preedit: str,
    accepted_text: str = "",
    rejected_text: str = "",
    action: str = "accepted",
    app: str = "",
    project: str = "",
    candidate_rank: int | None = None,
    context_hash: str = "",
    metadata: dict[str, object] | None = None,
) -> int:
    with closing(sqlite3.connect(str(db_path))) as conn:
        ensure_rime_rank_feedback_schema(conn)
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO rime_rank_feedback(
                    created_at_ms, preedit, rejected_text, accepted_text, action,
                    app, project, candidate_rank, context_hash, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(time.time() * 1000),
                    compact_whitespace(preedit),
                    compact_whitespace(rejected_text),
                    compact_whitespace(accepted_text),
                    compact_whitespace(action) or "accepted",
                    compact_whitespace(app),
                    compact_whitespace(project),
                    candidate_rank,
                    compact_whitespace(context_hash),
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
        return int(cursor.lastrowid)


def _rank_entries(conn: sqlite3.Connection, *, project: str, limit: int) -> list[dict[str, object]]:
    project = compact_whitespace(project)
    where = "WHERE project = ?" if project else ""
    params: tuple[object, ...] = (project,) if project else ()
    rows = conn.execute(
        f"""
        SELECT created_at_ms, preedit, accepted_text, rejected_text, action,
               candidate_rank, context_hash, metadata_json
        FROM rime_rank_feedback
        {where}
        ORDER BY created_at_ms ASC, id ASC
        """,
        params,
    )
    scores: dict[tuple[str, str], dict[str, Any]] = {}
    seen_context_events: set[tuple[object, ...]] = set()
    for created_at_ms, preedit, accepted, rejected, action, rank, context_hash, metadata_json in rows:
        metadata = _parse_metadata(metadata_json)
        if _has_non_rime_source(metadata):
            continue
        pinyin = _normalize_pinyin(str(preedit or ""))
        if not pinyin:
            continue
        accepted_text = compact_whitespace(str(accepted or ""))
        rejected_text = compact_whitespace(str(rejected or ""))
        action_name = compact_whitespace(str(action or "")).lower()
        rank_value = max(1, int(rank or 1))
        context = compact_whitespace(str(context_hash or ""))
        if context:
            event_key = (context, pinyin, accepted_text, rejected_text, action_name, rank_value)
            if event_key in seen_context_events:
                continue
            seen_context_events.add(event_key)

        if action_name in _POSITIVE_ACTIONS and _is_dictionary_text(accepted_text):
            item = _score_item(scores, text=accepted_text, pinyin=pinyin)
            positive = _positive_score(action_name, rank=rank_value)
            item["positiveScore"] = int(item["positiveScore"]) + positive
            item["positiveCount"] = int(item["positiveCount"]) + 1
            item["lastUsedAtMs"] = max(int(item["lastUsedAtMs"]), int(created_at_ms or 0))
            if action_name in {"boost", "correction_pair"}:
                item["explicitCount"] = int(item["explicitCount"]) + 1
            if action_name == "accepted" and rank_value > 1:
                item["nonTopAcceptCount"] = int(item["nonTopAcceptCount"]) + 1
            _increment_reason(item, action_name)

        negative_text = rejected_text
        if action_name in {"backspace_downrank", "downrank"} and not negative_text:
            negative_text = accepted_text
        if action_name in _NEGATIVE_ACTIONS and _is_dictionary_text(negative_text):
            item = _score_item(scores, text=negative_text, pinyin=pinyin)
            item["negativeScore"] = int(item["negativeScore"]) + _negative_score(action_name)
            item["negativeCount"] = int(item["negativeCount"]) + 1
            item["lastUsedAtMs"] = max(int(item["lastUsedAtMs"]), int(created_at_ms or 0))
            _increment_reason(item, f"{action_name}_negative")

    entries: list[dict[str, object]] = []
    for item in scores.values():
        if not _has_enough_positive_evidence(item):
            continue
        short_penalty = 24 if _cjk_length(str(item["text"])) == 1 else 0
        weight = int(item["positiveScore"]) - int(item["negativeScore"]) - short_penalty
        if weight <= 0:
            continue
        item["weight"] = weight
        reason_counts = dict(item.pop("_reasonCounts"))
        item["reasons"] = [f"{name}:{reason_counts[name]}" for name in sorted(reason_counts)]
        item.pop("positiveScore")
        item.pop("negativeScore")
        item.pop("explicitCount")
        item.pop("nonTopAcceptCount")
        entries.append(item)
    entries.sort(
        key=lambda item: (
            -int(item["weight"]),
            -int(item["positiveCount"]),
            -int(item["lastUsedAtMs"]),
            str(item["text"]),
        )
    )
    return entries[:limit]


def _score_item(scores: dict[tuple[str, str], dict[str, Any]], *, text: str, pinyin: str) -> dict[str, Any]:
    return scores.setdefault(
        (text, pinyin),
        {
            "text": text,
            "pinyin": pinyin,
            "weight": 0,
            "positiveScore": 0,
            "negativeScore": 0,
            "positiveCount": 0,
            "negativeCount": 0,
            "explicitCount": 0,
            "nonTopAcceptCount": 0,
            "lastUsedAtMs": 0,
            "_reasonCounts": {},
        },
    )


def _positive_score(action: str, *, rank: int) -> int:
    rank_bonus = min(max(rank - 1, 0), 5) * 8
    if action == "boost":
        return 200 + rank_bonus
    if action == "correction_pair":
        return 160 + rank_bonus
    return 40 + rank_bonus


def _negative_score(action: str) -> int:
    if action == "correction_pair":
        return 180
    if action == "downrank":
        return 140
    return 100


def _has_enough_positive_evidence(item: dict[str, Any]) -> bool:
    if int(item["explicitCount"]) > 0:
        return True
    cjk_length = _cjk_length(str(item["text"]))
    if cjk_length == 1:
        return int(item["positiveCount"]) >= 3 or int(item["nonTopAcceptCount"]) >= 2
    return int(item["positiveCount"]) >= 2 or int(item["nonTopAcceptCount"]) >= 1


def _increment_reason(item: dict[str, Any], reason: str) -> None:
    reason_counts = item["_reasonCounts"]
    reason_counts[reason] = int(reason_counts.get(reason, 0)) + 1


def _normalize_pinyin(value: str) -> str:
    normalized = compact_whitespace(value).lower().replace("'", " ").replace("’", " ")
    parts = normalized.split()
    canonical: list[str] = []
    index = 0
    while index < len(parts):
        token = parts[index]
        if token == "yo" and index + 1 < len(parts) and parts[index + 1] == "n":
            canonical.append("yong")
            index += 2
            continue
        canonical.append("yong" if token == "yon" else token)
        index += 1
    normalized = " ".join(canonical)
    return normalized if _PINYIN_RE.fullmatch(normalized) else ""


def _is_dictionary_text(value: str) -> bool:
    return bool(value) and _cjk_length(value) > 0 and "\t" not in value and "\n" not in value and "\r" not in value


def _cjk_length(value: str) -> int:
    return sum(1 for char in value if "\u3400" <= char <= "\u9fff")


def _parse_metadata(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _has_non_rime_source(metadata: dict[str, object]) -> bool:
    for key, value in _walk_metadata(metadata):
        normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
        if normalized_key not in _SOURCE_METADATA_KEYS or not isinstance(value, str):
            continue
        normalized_value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        tokens = set(normalized_value.split("_"))
        if normalized_value in _NON_RIME_SOURCE_TOKENS or tokens & _NON_RIME_SOURCE_TOKENS:
            return True
    return False


def _walk_metadata(value: object) -> list[tuple[str, object]]:
    items: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            items.append((str(key), child))
            items.extend(_walk_metadata(child))
    elif isinstance(value, list):
        for child in value:
            items.extend(_walk_metadata(child))
    return items


def _render_rime_dict(*, dict_name: str, entries: list[dict[str, object]]) -> str:
    lines = [
        "# Generated by rag-ime rime-rank-export-preview/apply.",
        "---",
        f"name: {dict_name}",
        f'version: "{time.strftime("%Y.%m.%d")}"',
        "sort: by_weight",
        "...",
        "",
    ]
    for item in entries:
        lines.append(f"{item['text']}\t{item['pinyin']}\t{int(item['weight'])}")
    return "\n".join(lines) + "\n"
