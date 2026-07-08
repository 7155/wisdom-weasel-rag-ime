from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .text_utils import compact_whitespace


SCHEMA_VERSION = "rag-ime.rime-rank-export.v1"


def ensure_rime_rank_feedback_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS rime_rank_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at_ms INTEGER NOT NULL,
            preedit TEXT NOT NULL,
            rejected_text TEXT NOT NULL DEFAULT '',
            accepted_text TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            app TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            candidate_rank INTEGER,
            context_hash TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_rime_rank_feedback_lookup
        ON rime_rank_feedback(project, preedit, accepted_text, rejected_text, action);
        """
    )


def preview_rime_rank_export(
    db_path: str | Path,
    *,
    project: str = "",
    limit: int = 200,
    dict_name: str = "rag_ime_user",
) -> dict[str, object]:
    with sqlite3.connect(str(db_path)) as conn:
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
    with sqlite3.connect(str(db_path)) as conn:
        ensure_rime_rank_feedback_schema(conn)
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
        SELECT preedit, accepted_text, rejected_text, action, candidate_rank, COUNT(*) AS n
        FROM rime_rank_feedback
        {where}
        GROUP BY preedit, accepted_text, rejected_text, action, candidate_rank
        ORDER BY n DESC, MAX(created_at_ms) DESC
        LIMIT ?
        """,
        (*params, limit * 4),
    ).fetchall()
    scores: dict[tuple[str, str], dict[str, Any]] = {}
    for preedit, accepted, rejected, action, rank, count in rows:
        accepted_text = compact_whitespace(str(accepted or ""))
        rejected_text = compact_whitespace(str(rejected or ""))
        pinyin = compact_whitespace(str(preedit or ""))
        count = int(count or 0)
        rank_penalty = max(0, int(rank or 1) - 1)
        if accepted_text:
            item = scores.setdefault((accepted_text, pinyin), {"text": accepted_text, "pinyin": pinyin, "weight": 0, "reasons": []})
            item["weight"] = int(item["weight"]) + 80 * count + max(0, 20 - rank_penalty * 2)
            item["reasons"].append(f"{action}:{count}")
        if rejected_text and action in {"backspace_downrank", "correction_pair"}:
            item = scores.setdefault((rejected_text, pinyin), {"text": rejected_text, "pinyin": pinyin, "weight": 0, "reasons": []})
            item["weight"] = int(item["weight"]) - 60 * count
            item["reasons"].append(f"downrank:{count}")
    entries = [item for item in scores.values() if int(item["weight"]) > 0 and item["text"] and item["pinyin"]]
    entries.sort(key=lambda item: (-int(item["weight"]), str(item["text"])))
    return entries[:limit]


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
