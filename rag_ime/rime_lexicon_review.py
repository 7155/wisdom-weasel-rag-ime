from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Iterable

from .db import apply_database_migrations
from .rime_rank_export import preview_rime_rank_export
from .text_utils import compact_whitespace


SCHEMA_VERSION = "rag-ime.rime-lexicon-review.v1"
CONFIRM_TEXT = "APPLY_REVIEWED_RIME_LEXICON"
_MANIFEST_NAME = "manifest.json"
_MAX_REVIEW_BATCH = 80
_SAFE_TEXT_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9.+#-]+$")


def review_rime_lexicon(
    db_path: str | Path,
    *,
    project: str = "",
    limit: int = 200,
    rime_user_dir: str | Path | None = None,
) -> dict[str, object]:
    preview = preview_rime_rank_export(db_path, project=project, limit=limit)
    applied_keys: set[str] = set()
    if rime_user_dir is not None:
        user_dict = Path(rime_user_dir).expanduser() / "rag_ime_user.dict.yaml"
        applied_keys = {_entry_key(entry) for entry in _read_user_dictionary(user_dict)}
    usage_entries = [{**entry, "reviewSource": "usage", "reviewReason": "来自真实选词反馈"} for entry in preview["entries"]]
    dsv4_entries = _dsv4_phrase_entries(db_path, project=project, limit=limit)
    merged_entries = _merge_review_entries(usage_entries, dsv4_entries)
    reviewed_entries: list[dict[str, object]] = []
    filtered_entry_count = 0
    for entry in merged_entries:
        if _entry_key(entry) in applied_keys:
            continue
        disposition = _common_word_disposition(entry)
        if not disposition["allowed"]:
            filtered_entry_count += 1
            continue
        reviewed_entries.append({**entry, **disposition})
    entries = reviewed_entries[: min(_MAX_REVIEW_BATCH, max(1, int(limit)))]
    review_token = _review_token(project=project, entries=entries)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "project": project,
        "entryCount": len(entries),
        "entries": [
            {
                **entry,
                "reviewKey": _entry_key(entry),
                "selected": bool(entry.get("defaultSelected")),
            }
            for entry in entries
        ],
        "reviewToken": review_token,
        "confirmText": CONFIRM_TEXT,
        "applySupported": True,
        "reviewRequired": True,
        "filteredEntryCount": filtered_entry_count + max(0, len(reviewed_entries) - len(entries)),
        "selectionPolicy": "只默认选择有至少 3 次真实反馈的常用词；模型整理词必须人工勾选",
    }


def apply_reviewed_rime_lexicon(
    db_path: str | Path,
    *,
    rime_user_dir: str | Path,
    backup_root: str | Path,
    project: str = "",
    limit: int = 200,
    review_token: str,
    selected_keys: Iterable[str] | None = None,
    confirm_text: str,
) -> dict[str, object]:
    review = review_rime_lexicon(
        db_path,
        project=project,
        limit=limit,
        rime_user_dir=rime_user_dir,
    )
    if confirm_text != CONFIRM_TEXT:
        return _failure("confirm_text_required", confirmText=CONFIRM_TEXT)
    if not review_token or review_token != review["reviewToken"]:
        return _failure("review_token_stale")

    selected = {str(value) for value in (selected_keys or []) if str(value)}
    entries = [
        entry
        for entry in review["entries"]
        if str(entry["reviewKey"]) in selected
    ]
    if not entries:
        return _failure("no_reviewed_entries")

    user_dir = Path(rime_user_dir).expanduser()
    backup_dir_root = Path(backup_root).expanduser()
    user_dict = user_dir / "rag_ime_user.dict.yaml"
    umbrella_dict = user_dir / "rag_ime.dict.yaml"
    schema_custom = user_dir / "luna_pinyin_simp.custom.yaml"
    try:
        custom_text = _schema_custom_text(schema_custom)
    except ValueError as exc:
        return _failure(str(exc))

    existing_entries = _read_user_dictionary(user_dict)
    writes = {
        user_dict: _render_user_dictionary(_merge_user_dictionary_entries(existing_entries, entries)),
        umbrella_dict: _render_umbrella_dictionary(),
        schema_custom: custom_text,
    }
    rollback_id = f"{int(time.time() * 1000)}-{str(review_token)[:12]}"
    rollback_dir = backup_dir_root / rollback_id
    rollback_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(rollback_dir, 0o700)
    manifest_entries: list[dict[str, object]] = []
    try:
        for index, target in enumerate(writes):
            existed = target.exists()
            backup_file = rollback_dir / f"{index}.bak"
            if existed:
                shutil.copy2(target, backup_file)
                os.chmod(backup_file, 0o600)
            manifest_entries.append(
                {
                    "target": str(target),
                    "existed": existed,
                    "backupFile": str(backup_file) if existed else "",
                }
            )
        manifest = {
            "schemaVersion": SCHEMA_VERSION,
            "rollbackId": rollback_id,
            "createdAtMs": int(time.time() * 1000),
            "state": "applied",
            "reviewToken": review_token,
            "project": project,
            "entryCount": len(entries),
            "files": manifest_entries,
        }
        _atomic_write(rollback_dir / _MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for target, content in writes.items():
            _atomic_write(target, content)
    except Exception:
        _restore_manifest_entries(manifest_entries)
        raise

    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "applied": True,
        "entryCount": len(entries),
        "rollbackId": rollback_id,
        "targets": [str(path) for path in writes],
        "requiresRedeploy": True,
    }


def rollback_reviewed_rime_lexicon(
    *,
    rollback_id: str,
    backup_root: str | Path,
) -> dict[str, object]:
    root = Path(backup_root).expanduser().resolve()
    rollback_dir = (root / rollback_id).resolve()
    if root not in rollback_dir.parents or not rollback_dir.is_dir():
        return _failure("rollback_manifest_missing")
    manifest_path = rollback_dir / _MANIFEST_NAME
    if not manifest_path.is_file():
        return _failure("rollback_manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _failure("rollback_manifest_invalid")
    if not isinstance(manifest, dict) or str(manifest.get("rollbackId") or "") != rollback_id:
        return _failure("rollback_manifest_invalid")
    if str(manifest.get("state") or "applied") == "rolled_back":
        return _failure("rollback_already_applied")
    newer = _newer_applied_rollback_manifest(root, manifest)
    if newer:
        return _failure("newer_rollback_required_first", blockingRollbackId=newer)
    files = manifest.get("files")
    if not isinstance(files, list):
        return _failure("rollback_manifest_invalid")
    _restore_manifest_entries(files)
    manifest["state"] = "rolled_back"
    manifest["rolledBackAtMs"] = int(time.time() * 1000)
    _atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "rolledBack": True,
        "rollbackId": rollback_id,
        "requiresRedeploy": True,
    }


def _newer_applied_rollback_manifest(root: Path, current: dict[str, object]) -> str:
    current_key = (
        int(current.get("createdAtMs") or 0),
        str(current.get("rollbackId") or ""),
    )
    if not root.is_dir():
        return ""
    for directory in root.iterdir():
        manifest_path = directory / _MANIFEST_NAME
        if not directory.is_dir() or not manifest_path.is_file():
            continue
        try:
            candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(candidate, dict) or str(candidate.get("state") or "applied") == "rolled_back":
            continue
        candidate_id = str(candidate.get("rollbackId") or "")
        candidate_key = (int(candidate.get("createdAtMs") or 0), candidate_id)
        if candidate_id and candidate_key > current_key:
            return candidate_id
    return ""


def _review_token(*, project: str, entries: list[dict[str, object]]) -> str:
    payload = json.dumps(
        {"project": project, "entries": entries},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entry_key(entry: dict[str, object]) -> str:
    return f"{entry.get('text', '')}\t{entry.get('pinyin', '')}"


def _read_user_dictionary(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    entries: list[dict[str, object]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line in {"---", "..."}:
            continue
        parts = raw_line.split("\t")
        if len(parts) < 2:
            continue
        text = parts[0].strip()
        pinyin = parts[1].strip()
        if not text or not pinyin:
            continue
        try:
            weight = int(parts[2].strip()) if len(parts) >= 3 else 100
        except ValueError:
            weight = 100
        entries.append({"text": text, "pinyin": pinyin, "weight": weight})
    return entries


def _merge_user_dictionary_entries(
    existing: list[dict[str, object]],
    reviewed: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for entry in [*existing, *reviewed]:
        key = _entry_key(entry)
        if key not in merged:
            order.append(key)
            merged[key] = dict(entry)
            continue
        merged[key]["weight"] = max(int(merged[key].get("weight", 100)), int(entry.get("weight", 100)))
    return [merged[key] for key in order]


def _merge_review_entries(
    usage_entries: list[dict[str, object]],
    dsv4_entries: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for entry in [*usage_entries, *dsv4_entries]:
        key = _entry_key(entry)
        if key not in merged:
            merged[key] = dict(entry)
            continue
        current = merged[key]
        current["weight"] = max(int(current.get("weight", 0)), int(entry.get("weight", 0)))
        current["positiveCount"] = max(
            int(current.get("positiveCount", 0)),
            int(entry.get("positiveCount", 0)),
        )
        current["lastUsedAtMs"] = max(
            int(current.get("lastUsedAtMs", 0)),
            int(entry.get("lastUsedAtMs", 0)),
        )
        sources = {str(current.get("reviewSource") or ""), str(entry.get("reviewSource") or "")}
        current["reviewSource"] = "+".join(sorted(value for value in sources if value))
        reasons = [
            compact_whitespace(str(current.get("reviewReason") or "")),
            compact_whitespace(str(entry.get("reviewReason") or "")),
        ]
        current["reviewReason"] = "；".join(dict.fromkeys(value for value in reasons if value))
    result = list(merged.values())
    result.sort(
        key=lambda entry: (
            -int(entry.get("weight", 0)),
            -int(entry.get("positiveCount", 0)),
            -int(entry.get("lastUsedAtMs", 0)),
            str(entry.get("text") or ""),
        )
    )
    return result


def _common_word_disposition(entry: dict[str, object]) -> dict[str, object]:
    text = compact_whitespace(str(entry.get("text") or ""))
    pinyin = _normalize_pinyin(str(entry.get("pinyin") or ""))
    positive_count = int(entry.get("positiveCount") or 0)
    source = str(entry.get("reviewSource") or "")
    reasons = [str(value) for value in entry.get("reasons", []) if isinstance(value, str)]
    explicit_usage = source == "usage" and any(
        reason.startswith(("boost:", "correction_pair:")) for reason in reasons
    )
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    if not text or not pinyin:
        return {"allowed": False, "filterReason": "缺少词条或拼音"}
    if cjk_count < 2:
        return {"allowed": False, "filterReason": "单字或非中文词不进入自动词库"}
    if len(text) > 16 or cjk_count > 12:
        return {"allowed": False, "filterReason": "词条过长"}
    if not _SAFE_TEXT_RE.fullmatch(text):
        return {"allowed": False, "filterReason": "包含不可审计字符"}
    if positive_count < 2 and not explicit_usage:
        return {"allowed": False, "filterReason": "缺少重复使用证据"}
    is_model_candidate = "dsv4" in source
    return {
        "allowed": True,
        "defaultSelected": not is_model_candidate and (positive_count >= 3 or explicit_usage),
        "riskLabel": "模型建议，需人工确认" if is_model_candidate else "真实选词反馈",
        "filterReason": "",
    }


def _dsv4_phrase_entries(
    db_path: str | Path,
    *,
    project: str,
    limit: int,
) -> list[dict[str, object]]:
    project_value = compact_whitespace(project)
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        apply_database_migrations(conn)
        rows = conn.execute(
            """
            SELECT text, confidence, quality_score, updated_at_ms, metadata_json
            FROM memory_items
            WHERE kind = 'phrase' AND status = 'approved'
              AND (? = '' OR project = ? OR project = '')
            ORDER BY quality_score DESC, updated_at_ms DESC
            LIMIT ?
            """,
            (project_value, project_value, max(1, int(limit) * 2)),
        ).fetchall()
    entries: list[dict[str, object]] = []
    for row in rows:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(metadata, dict) or str(metadata.get("reviewSource") or "") != "dsv4":
            continue
        text = compact_whitespace(str(row["text"] or ""))
        pinyin = _normalize_pinyin(str(metadata.get("pinyin") or ""))
        if not text or not pinyin:
            continue
        quality = max(float(row["confidence"] or 0), float(row["quality_score"] or 0))
        source_ids = [value for value in metadata.get("sourceEventIds", []) if isinstance(value, int) and value > 0]
        reason = compact_whitespace(str(metadata.get("reviewReason") or metadata.get("reason") or ""))
        entries.append(
            {
                "text": text,
                "pinyin": pinyin,
                "weight": max(80, min(900, int(round(120 + quality * 680)))),
                "positiveCount": max(1, len(source_ids)),
                "negativeCount": 0,
                "lastUsedAtMs": int(row["updated_at_ms"] or 0),
                "reasons": ["dsv4_offline_review"],
                "reviewSource": "dsv4",
                "reviewReason": reason or "DSV4 根据历史证据整理",
            }
        )
    return entries


def _normalize_pinyin(value: str) -> str:
    pinyin = " ".join(compact_whitespace(value).lower().split())
    if not pinyin or any(not syllable.isascii() or not syllable.replace("v", "a").isalpha() for syllable in pinyin.split()):
        return ""
    return pinyin


def _render_user_dictionary(entries: list[dict[str, object]]) -> str:
    lines = [
        "# Reviewed RAG-IME native Rime feedback. Do not edit while applying a review.",
        "---",
        "name: rag_ime_user",
        f'version: "{time.strftime("%Y.%m.%d")}"',
        "sort: by_weight",
        "...",
    ]
    lines.extend(
        f"{entry['text']}\t{entry['pinyin']}\t{int(entry['weight'])}"
        for entry in entries
    )
    return "\n".join(lines) + "\n"


def _render_umbrella_dictionary() -> str:
    return (
        "# RAG-IME managed dictionary route. User entries remain in rag_ime_user.dict.yaml.\n"
        "---\n"
        "name: rag_ime\n"
        f'version: "{time.strftime("%Y.%m.%d")}"\n'
        "sort: by_weight\n"
        # Imported Luna entries depend on preset vocabulary weights. Without
        # this, unweighted rare characters sort ahead of ordinary words.
        "use_preset_vocabulary: true\n"
        "import_tables:\n"
        "  - luna_pinyin\n"
        "  - rag_ime_user\n"
        "...\n"
    )


def _schema_custom_text(path: Path) -> str:
    managed_key = "translator/dictionary"
    if not path.exists():
        return "patch:\n  # RAG-IME reviewed dictionary route\n  translator/dictionary: rag_ime\n"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    patch_index = next((index for index, line in enumerate(lines) if line.strip() == "patch:" and not line.startswith((" ", "\t"))), None)
    if patch_index is None:
        raise ValueError("schema_patch_root_missing")
    section_end = len(lines)
    for index in range(patch_index + 1, len(lines)):
        line = lines[index]
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            section_end = index
            break
    for index in range(patch_index + 1, section_end):
        stripped = lines[index].strip()
        if not stripped.startswith(f"{managed_key}:"):
            continue
        value = stripped.split(":", 1)[1].strip()
        if value == "rag_ime":
            return text if text.endswith("\n") else text + "\n"
        raise ValueError("translator_dictionary_conflict")
    lines[patch_index + 1:patch_index + 1] = [
        "  # RAG-IME reviewed dictionary route",
        "  translator/dictionary: rag_ime",
    ]
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _restore_manifest_entries(entries: list[dict[str, object]]) -> None:
    for item in reversed(entries):
        target = Path(str(item.get("target", "")))
        if bool(item.get("existed")):
            backup = Path(str(item.get("backupFile", "")))
            if not backup.is_file():
                raise FileNotFoundError(f"missing backup for {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        else:
            target.unlink(missing_ok=True)


def _failure(reason: str, **extra: object) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": False,
        "applied": False,
        "reason": reason,
        **extra,
    }
