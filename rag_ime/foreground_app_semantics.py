from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from .text_utils import compact_whitespace, truncate_preserving_layout, truncate_text


ZED_SEMANTICS_SOURCE = "zed_workspace_state"
_ZED_IGNORED_ROOT_ENTRIES = frozenset(
    {
        ".DS_Store",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
_ZED_SENSITIVE_FILE_RE = re.compile(
    r"(?i)(?:^|/)(?:\.env(?:\.[^/]*)?|\.git-credentials|\.netrc|auth\.json|"
    r"credentials\.json|id_rsa|id_ed25519|[^/]+\.(?:pem|key|p12|pfx|sqlite|sqlite3|db))$"
)
_ZED_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:\bsk-[A-Za-z0-9_-]{16,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*|"
    r"\b(?:api[_-]?key|access[_-]?token|authorization|password|secret)"
    r"(\s*[:=]\s*)\S+)"
)


def enrich_window_context_with_app_semantics(
    window_context: Mapping[str, object],
    *,
    zed_state_db: str | Path | None = None,
) -> dict[str, object]:
    """Attach bounded, read-only application semantics when AX is insufficient."""

    enriched = dict(window_context)
    # Application semantics are server-owned. Never trust a similarly named
    # block supplied by a frontend or an older caller.
    enriched.pop("applicationSemantics", None)
    application = (
        window_context.get("application")
        if isinstance(window_context.get("application"), Mapping)
        else {}
    )
    if not _is_zed_application(application):
        return enriched
    semantics = _load_zed_semantics(
        window_title=str(application.get("windowTitle") or ""),
        state_db=zed_state_db,
    )
    if semantics:
        enriched["applicationSemantics"] = semantics
    return enriched


def _is_zed_application(application: Mapping[str, object]) -> bool:
    bundle_id = compact_whitespace(str(application.get("bundleId") or "")).casefold()
    name = compact_whitespace(str(application.get("name") or "")).casefold()
    return name in {"zed", "zed preview"} or bundle_id.startswith("dev.zed.")


def _load_zed_semantics(
    *,
    window_title: str,
    state_db: str | Path | None,
) -> dict[str, object]:
    db_path = _zed_state_db_path(state_db)
    if db_path is None:
        return {}
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=0.05,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            """
            SELECT
                w.workspace_id,
                w.paths,
                w.timestamp,
                p.active AS pane_active,
                i.active AS item_active,
                i.position,
                e.buffer_path,
                e.scroll_top_row,
                e.contents
            FROM workspaces AS w
            JOIN panes AS p ON p.workspace_id = w.workspace_id
            JOIN items AS i
              ON i.workspace_id = w.workspace_id
             AND i.pane_id = p.pane_id
             AND i.kind = 'Editor'
             AND i.active = 1
            JOIN editors AS e
              ON e.workspace_id = i.workspace_id
             AND e.item_id = i.item_id
            ORDER BY p.active DESC, w.timestamp DESC, i.position DESC
            LIMIT 64
            """
        ).fetchall()
    except (OSError, sqlite3.Error, ValueError):
        return {}
    finally:
        if connection is not None:
            connection.close()
    selected = _select_zed_editor(rows, window_title=window_title)
    if selected is None:
        return {}
    return _project_zed_editor(selected)


def _zed_state_db_path(configured: str | Path | None) -> Path | None:
    explicit = configured or os.environ.get("RAG_IME_ZED_STATE_DB")
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    candidates = (
        Path.home() / "Library/Application Support/Zed/db/0-stable/db.sqlite",
        Path.home() / "Library/Application Support/Zed/db/0-preview/db.sqlite",
        Path.home() / "Library/Application Support/Zed Preview/db/0-preview/db.sqlite",
    )
    return next((path for path in candidates if path.is_file()), None)


def _select_zed_editor(
    rows: list[sqlite3.Row],
    *,
    window_title: str,
) -> sqlite3.Row | None:
    normalized_title = compact_whitespace(window_title).casefold()
    best: tuple[int, int, sqlite3.Row] | None = None
    for index, row in enumerate(rows):
        root = _workspace_root(str(row["paths"] or ""))
        buffer_path = Path(str(row["buffer_path"] or "")).expanduser()
        if root is None or not buffer_path.is_absolute():
            continue
        score = 0
        project_name = root.name.casefold()
        file_name = buffer_path.name.casefold()
        if project_name and project_name in normalized_title:
            score += 80
        if file_name and file_name in normalized_title:
            score += 160
        if int(row["pane_active"] or 0) == 1:
            score += 20
        if int(row["item_active"] or 0) == 1:
            score += 10
        candidate = (score, -index, row)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best is not None else None


def _workspace_root(raw_paths: str) -> Path | None:
    text = raw_paths.strip()
    if not text:
        return None
    candidates: list[str] = []
    if text[:1] in {"[", "{"}:
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, list):
            candidates = [str(value) for value in decoded if str(value).strip()]
        elif isinstance(decoded, Mapping):
            candidates = [
                str(value)
                for value in decoded.values()
                if isinstance(value, str) and value.strip()
            ]
    if not candidates:
        candidates = [text]
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_dir():
            return path.resolve()
        if path.is_file():
            return path.resolve().parent
    return None


def _project_zed_editor(row: sqlite3.Row) -> dict[str, object]:
    root = _workspace_root(str(row["paths"] or ""))
    buffer_path = Path(str(row["buffer_path"] or "")).expanduser()
    if root is None:
        return {}
    try:
        resolved_buffer = buffer_path.resolve()
        relative_file = resolved_buffer.relative_to(root)
    except (OSError, ValueError):
        return {}
    sensitive_file = bool(_ZED_SENSITIVE_FILE_RE.search(relative_file.as_posix()))
    stored_contents = row["contents"]
    if sensitive_file:
        content_origin = "sensitive_file_blocked"
        source_text = ""
    elif isinstance(stored_contents, str):
        content_origin = "zed_recovery_buffer"
        source_text = stored_contents
    else:
        content_origin = "workspace_file"
        try:
            if not resolved_buffer.is_file() or resolved_buffer.stat().st_size > 2_000_000:
                return {}
            source_text = resolved_buffer.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {}
    source_text = _ZED_SECRET_VALUE_RE.sub(
        lambda match: (
            f"{match.group(0).split(match.group(1), 1)[0]}{match.group(1)}[REDACTED_SECRET]"
            if match.group(1)
            else "[REDACTED_SECRET]"
        ),
        _redact_local_roots(source_text, workspace_root=root),
    )
    scroll_top_row = max(0, int(row["scroll_top_row"] or 0))
    excerpt, start_line = _visible_editor_excerpt(source_text, scroll_top_row=scroll_top_row)
    return {
        "source": ZED_SEMANTICS_SOURCE,
        "freshness": "best_effort_local_state",
        "projectName": truncate_text(compact_whitespace(root.name), 160),
        "activeFile": (
            ""
            if sensitive_file
            else truncate_text(relative_file.as_posix(), 500)
        ),
        "editorExcerpt": excerpt,
        "editorExcerptStartLine": start_line,
        "projectEntries": _project_root_entries(root),
        "projectEntriesScope": "workspace_root",
        "contentOrigin": content_origin,
        "trust": {
            "maySupportIntent": True,
            "maySupportFacts": False,
            "mayLagUnsavedChanges": content_origin == "workspace_file",
            "mustNotOverrideCurrentInput": True,
        },
    }


def _visible_editor_excerpt(text: str, *, scroll_top_row: int) -> tuple[str, int]:
    lines = text.splitlines()
    if not lines:
        return "", 1
    first_index = min(max(0, scroll_top_row - 6), len(lines) - 1)
    selected = lines[first_index : first_index + 72]
    numbered = [
        f"{first_index + offset + 1}: {line}"
        for offset, line in enumerate(selected)
    ]
    return truncate_preserving_layout("\n".join(numbered), 8_000), first_index + 1


def _project_root_entries(root: Path) -> list[str]:
    try:
        children = [
            child
            for child in root.iterdir()
            if child.name not in _ZED_IGNORED_ROOT_ENTRIES
        ]
    except OSError:
        return []
    children.sort(key=lambda child: (not child.is_dir(), child.name.casefold()))
    return [
        truncate_text(f"{child.name}/" if child.is_dir() else child.name, 240)
        for child in children[:48]
    ]


def _redact_local_roots(text: str, *, workspace_root: Path) -> str:
    redacted = text
    for root in _macos_path_aliases(workspace_root):
        redacted = redacted.replace(root, "[WORKSPACE]")
    for home in _macos_path_aliases(Path.home()):
        redacted = redacted.replace(home, "[HOME]")
    return redacted


def _macos_path_aliases(path: Path) -> tuple[str, ...]:
    canonical = str(path.resolve())
    aliases = [canonical]
    if canonical.startswith("/private/"):
        aliases.append(canonical.removeprefix("/private"))
    return tuple(sorted(set(aliases), key=len, reverse=True))
