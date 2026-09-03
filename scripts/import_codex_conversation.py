#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.codex_conversation_import import (
    IMPORT_FIDELITY,
    IMPORT_SCHEMA_VERSION,
    CodexConversationImportError,
    import_codex_conversation,
    parse_codex_conversation,
    resolve_codex_session,
)


def _import_with_busy_retry(
    source: Path,
    *,
    sessions: AgentSessionStore,
    session_dir: Path,
    title: str,
    allow_incomplete: bool,
) -> dict[str, object]:
    for attempt in range(4):
        try:
            return import_codex_conversation(
                source,
                sessions=sessions,
                session_dir=session_dir,
                title=title,
                allow_incomplete=allow_incomplete,
            )
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).casefold() or attempt == 3:
                raise
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError("unreachable Codex import retry state")


def _parser() -> argparse.ArgumentParser:
    app_support = Path(
        os.environ.get("RAG_IME_APP_SUPPORT_DIR")
        or Path.home() / "Library" / "Application Support" / "RagIme"
    ).expanduser()
    parser = argparse.ArgumentParser(
        description=(
            "Import one completed Codex rollout as a provenance-marked PAW/Pi "
            "conversation. Dry-run is the default."
        )
    )
    parser.add_argument(
        "source",
        help="Codex session id or an explicit rollout JSONL path",
    )
    parser.add_argument(
        "--state-db",
        type=Path,
        default=Path.home() / ".codex" / "state_5.sqlite",
        help="Codex state database used when source is a session id",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(
            os.environ.get("RAG_IME_DB_PATH") or app_support / "rag-ime.sqlite"
        ),
        help="PAW SQLite database",
    )
    parser.add_argument(
        "--session-dir",
        type=Path,
        default=app_support / "Agent" / "sessions",
        help="PAW managed Pi session directory",
    )
    parser.add_argument("--title", default="", help="Optional PAW conversation title")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Allow a Codex rollout without a task_complete marker",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the Pi transcript and register it in PAW",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source, discovered_title = resolve_codex_session(
            args.source,
            state_db=args.state_db,
        )
        title = str(args.title or discovered_title).strip()
        if args.write:
            sessions = AgentSessionStore(args.db)
            if not args.db.exists():
                sessions.initialize()
            result = _import_with_busy_retry(
                source,
                sessions=sessions,
                session_dir=args.session_dir,
                title=title,
                allow_incomplete=args.allow_incomplete,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        conversation = parse_codex_conversation(source)
        would_import = conversation.complete or args.allow_incomplete
        result = {
            "schemaVersion": IMPORT_SCHEMA_VERSION,
            "ok": would_import,
            "status": "dry_run",
            "wouldImport": would_import,
            "source": {
                "provider": "codex",
                "sessionId": conversation.source_session_id,
                "file": conversation.source_file,
                "sha256": conversation.source_sha256,
                "complete": conversation.complete,
            },
            "target": {
                "database": args.db.as_posix(),
                "sessionDirectory": args.session_dir.as_posix(),
                "title": title or conversation.messages[0].text[:96],
            },
            "fidelity": {
                "mode": IMPORT_FIDELITY,
                "includedRoles": ["user", "assistant"],
                "omittedKinds": list(conversation.omitted_kinds),
            },
            "messageCount": len(conversation.messages),
            "nextAction": (
                "rerun with --write"
                if would_import
                else "wait for Codex task_complete or pass --allow-incomplete"
            ),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if would_import else 2
    except (CodexConversationImportError, OSError, sqlite3.Error, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": IMPORT_SCHEMA_VERSION,
                    "ok": False,
                    "status": "rejected",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
