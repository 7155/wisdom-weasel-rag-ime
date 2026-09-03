#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_PAW_PYTHON_ROOT_ENV = "PAW_CODEX_IMPORT_PYTHON_ROOT"
_paw_python_root = os.environ.get(_PAW_PYTHON_ROOT_ENV, "").strip()
if _paw_python_root:
    sys.path.insert(0, str(Path(_paw_python_root).expanduser()))
    from rag_ime.agent_sessions import AgentSessionStore

    module_name = "rag_ime._paw_project_codex_conversation_import"
    module_spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "rag_ime" / "codex_conversation_import.py",
    )
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError("could not load the PAW Codex conversation importer")
    import_module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = import_module
    module_spec.loader.exec_module(import_module)
    CodexConversationConflict = import_module.CodexConversationConflict
    CodexConversationImportError = import_module.CodexConversationImportError
    CodexConversationIncomplete = import_module.CodexConversationIncomplete
    discover_codex_conversation_sources = (
        import_module.discover_codex_conversation_sources
    )
    import_codex_conversation = import_module.import_codex_conversation
    parse_codex_conversation = import_module.parse_codex_conversation
else:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from rag_ime.agent_sessions import AgentSessionStore
    from rag_ime.codex_conversation_import import (
        CodexConversationConflict,
        CodexConversationImportError,
        CodexConversationIncomplete,
        discover_codex_conversation_sources,
        import_codex_conversation,
        parse_codex_conversation,
    )


BATCH_SCHEMA_VERSION = "rag-ime.codex-conversation-batch-import.v1"


def _parser() -> argparse.ArgumentParser:
    app_support = Path(
        os.environ.get("RAG_IME_APP_SUPPORT_DIR")
        or Path.home() / "Library" / "Application Support" / "RagIme"
    ).expanduser()
    parser = argparse.ArgumentParser(
        description=(
            "Discover Codex rollout JSONL files by embedded session identity and "
            "register each visible conversation in PAW. Dry-run is the default."
        )
    )
    parser.add_argument(
        "--paw-python-root",
        type=Path,
        help=(
            "Optional installed PAW Python root. Its AgentSessionStore is used "
            "while the importer itself remains the current project implementation."
        ),
    )
    parser.add_argument(
        "--source-root",
        action="append",
        type=Path,
        default=[],
        help=(
            "Root to scan recursively; repeat for local and external roots. "
            "When omitted, the three standard ~/.codex history roots are used."
        ),
    )
    parser.add_argument(
        "--state-db",
        type=Path,
        default=Path.home() / ".codex" / "state_5.sqlite",
        help="Codex state database used for titles and preferred paths",
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
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Import closed rollouts without a task_complete marker",
    )
    parser.add_argument(
        "--include-open",
        action="store_true",
        help="Include rollout files currently opened by a Codex process",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        help="Optional JSON receipt path; an existing file is never overwritten",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="Emit progress to stderr every N discovered Sessions",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write Pi transcripts and register PAW Sessions",
    )
    return parser


def _default_source_roots() -> list[Path]:
    codex_home = Path.home() / ".codex"
    return [
        codex_home / "sessions",
        codex_home / "archived_sessions",
        codex_home / "history_sync_backups",
    ]


def _codex_process_ids(process_snapshot: str) -> list[str]:
    process_ids: list[str] = []
    for raw_line in process_snapshot.splitlines():
        fields = raw_line.strip().split(maxsplit=1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        if Path(fields[1]).name != "codex":
            continue
        process_ids.append(fields[0])
    return process_ids


def _open_codex_rollout_paths() -> tuple[set[Path], str]:
    try:
        process_snapshot = subprocess.check_output(
            ["/bin/ps", "-Aww", "-o", "pid=,comm="],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return set(), f"Codex process discovery failed: {exc}"
    process_ids = _codex_process_ids(process_snapshot)
    if not process_ids:
        return set(), ""
    try:
        snapshot = subprocess.check_output(
            [
                "/usr/sbin/lsof",
                "-nP",
                "-a",
                "-p",
                ",".join(process_ids),
                "-Fn",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return set(), f"Codex open-file discovery failed: {exc}"
    paths: set[Path] = set()
    for line in snapshot.splitlines():
        if not line.startswith("n") or not line.endswith(".jsonl"):
            continue
        path = Path(line[1:])
        try:
            paths.add(path.resolve(strict=True))
        except OSError:
            continue
    return paths, ""


def _import_with_busy_retry(
    source: Path,
    *,
    sessions: AgentSessionStore,
    session_dir: Path,
    title: str,
    allow_incomplete: bool,
) -> dict[str, object]:
    for attempt in range(6):
        try:
            return import_codex_conversation(
                source,
                sessions=sessions,
                session_dir=session_dir,
                title=title,
                allow_incomplete=allow_incomplete,
            )
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).casefold() or attempt == 5:
                raise
            time.sleep(min(4.0, 0.25 * (2**attempt)))
    raise RuntimeError("unreachable Codex batch import retry state")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_receipt(path: Path, payload: dict[str, object]) -> None:
    parent = path.parent
    if not parent.is_dir():
        raise OSError(f"receipt parent directory does not exist: {parent}")
    temporary = parent / f".{path.name}.{os.getpid()}.tmp"
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except OSError:
            pass


def _summary(
    *,
    mode: str,
    started_at: str,
    discovery: object,
    counts: dict[str, int],
    receipt: Path | None,
    open_file_warning: str,
) -> dict[str, object]:
    skipped = (
        counts["skippedOpen"]
        + counts["skippedIncomplete"]
        + counts["notImportable"]
    )
    return {
        "schemaVersion": BATCH_SCHEMA_VERSION,
        "ok": counts["failed"] == 0,
        "status": "completed_with_skips" if skipped else "completed",
        "mode": mode,
        "pawPythonRoot": _paw_python_root or ROOT.as_posix(),
        "startedAt": started_at,
        "finishedAt": _utc_now(),
        "discovery": {
            "sources": len(discovery.sources),
            "scannedPaths": discovery.scanned_paths,
            "uniqueFiles": discovery.unique_files,
            "filesWithoutSessionMeta": discovery.files_without_session_meta,
            "statePathMismatches": discovery.state_path_mismatches,
            "missingStatePaths": discovery.missing_state_paths,
            "missingSourceRoots": list(discovery.missing_source_roots),
            "openFileWarning": open_file_warning,
        },
        "counts": dict(counts),
        "receipt": receipt.as_posix() if receipt is not None else "",
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.paw_python_root is not None:
        requested_root = args.paw_python_root.expanduser().resolve()
        if not (requested_root / "rag_ime" / "agent_sessions.py").is_file():
            print(
                f"PAW Python root has no rag_ime/agent_sessions.py: {requested_root}",
                file=sys.stderr,
            )
            return 2
        active_root = Path(_paw_python_root).expanduser().resolve() if _paw_python_root else None
        if active_root != requested_root:
            environment = dict(os.environ)
            environment[_PAW_PYTHON_ROOT_ENV] = requested_root.as_posix()
            forwarded = list(argv) if argv is not None else sys.argv[1:]
            os.execve(
                sys.executable,
                [sys.executable, Path(__file__).resolve().as_posix(), *forwarded],
                environment,
            )
    if args.progress_every < 0:
        print("--progress-every must be non-negative", file=sys.stderr)
        return 2
    receipt = args.receipt.expanduser() if args.receipt is not None else None
    if receipt is not None and receipt.exists():
        print(f"receipt already exists: {receipt}", file=sys.stderr)
        return 2
    source_roots = (
        [path.expanduser() for path in args.source_root]
        if args.source_root
        else _default_source_roots()
    )
    try:
        discovery = discover_codex_conversation_sources(
            source_roots=source_roots,
            state_db=args.state_db,
        )
    except (CodexConversationImportError, OSError, sqlite3.Error) as exc:
        print(
            json.dumps(
                {
                    "schemaVersion": BATCH_SCHEMA_VERSION,
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

    open_paths: set[Path] = set()
    open_file_warning = ""
    if not args.include_open:
        open_paths, open_file_warning = _open_codex_rollout_paths()
        if args.write and open_file_warning:
            print(open_file_warning, file=sys.stderr)
            return 2

    counts = {
        "sources": len(discovery.sources),
        "wouldImport": 0,
        "imported": 0,
        "alreadyImported": 0,
        "incompleteImported": 0,
        "skippedOpen": 0,
        "skippedIncomplete": 0,
        "notImportable": 0,
        "conflicts": 0,
        "failed": 0,
        "messages": 0,
    }
    started_at = _utc_now()
    items: list[dict[str, object]] = []
    sessions: AgentSessionStore | None = None
    if args.write:
        sessions = AgentSessionStore(args.db.expanduser())
        if not args.db.expanduser().exists():
            sessions.initialize()

    for index, source in enumerate(discovery.sources, start=1):
        item: dict[str, object] = {
            "sourceSessionId": source.source_session_id,
            "source": source.path.as_posix(),
            "indexed": source.indexed,
            "candidateCount": source.candidate_count,
        }
        try:
            resolved = source.path.resolve(strict=True)
            if resolved in open_paths:
                counts["skippedOpen"] += 1
                item["status"] = "skipped_open"
            elif args.write:
                assert sessions is not None
                result = _import_with_busy_retry(
                    resolved,
                    sessions=sessions,
                    session_dir=args.session_dir.expanduser(),
                    title=source.title,
                    allow_incomplete=args.allow_incomplete,
                )
                status = str(result.get("status") or "")
                counts["alreadyImported" if status == "already_imported" else "imported"] += 1
                source_data = result.get("source")
                source_payload = source_data if isinstance(source_data, dict) else {}
                if source_payload.get("complete") is False:
                    counts["incompleteImported"] += 1
                message_count = int(result.get("messageCount") or 0)
                counts["messages"] += message_count
                session_data = result.get("session")
                session_payload = session_data if isinstance(session_data, dict) else {}
                item.update(
                    {
                        "status": status,
                        "pawSessionId": str(session_payload.get("id") or ""),
                        "title": str(session_payload.get("title") or ""),
                        "messageCount": message_count,
                        "transcript": str(result.get("sessionFile") or ""),
                        "sourceComplete": source_payload.get("complete") is True,
                    }
                )
            else:
                conversation = parse_codex_conversation(resolved)
                if not conversation.complete and not args.allow_incomplete:
                    counts["skippedIncomplete"] += 1
                    item["status"] = "skipped_incomplete"
                else:
                    counts["wouldImport"] += 1
                    counts["messages"] += len(conversation.messages)
                    if not conversation.complete:
                        counts["incompleteImported"] += 1
                    item.update(
                        {
                            "status": "would_import",
                            "messageCount": len(conversation.messages),
                            "sourceComplete": conversation.complete,
                        }
                    )
        except CodexConversationIncomplete as exc:
            counts["skippedIncomplete"] += 1
            item.update({"status": "skipped_incomplete", "error": str(exc)})
        except CodexConversationConflict as exc:
            counts["conflicts"] += 1
            counts["failed"] += 1
            item.update({"status": "conflict", "error": str(exc)})
        except CodexConversationImportError as exc:
            text = str(exc)
            if "no visible conversation messages" in text:
                counts["notImportable"] += 1
                item.update({"status": "not_importable", "error": text})
            else:
                counts["failed"] += 1
                item.update({"status": "failed", "error": text})
        except (OSError, sqlite3.Error, ValueError) as exc:
            counts["failed"] += 1
            item.update({"status": "failed", "error": str(exc)})
        items.append(item)

        if args.progress_every and index % args.progress_every == 0:
            print(
                f"processed={index}/{len(discovery.sources)} "
                f"imported={counts['imported']} failed={counts['failed']}",
                file=sys.stderr,
                flush=True,
            )
            if receipt is not None:
                payload = _summary(
                    mode="write" if args.write else "dry_run",
                    started_at=started_at,
                    discovery=discovery,
                    counts=counts,
                    receipt=receipt,
                    open_file_warning=open_file_warning,
                )
                payload["items"] = items
                _write_receipt(receipt, payload)

    summary = _summary(
        mode="write" if args.write else "dry_run",
        started_at=started_at,
        discovery=discovery,
        counts=counts,
        receipt=receipt,
        open_file_warning=open_file_warning,
    )
    if receipt is not None:
        payload = dict(summary)
        payload["items"] = items
        _write_receipt(receipt, payload)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if counts["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
