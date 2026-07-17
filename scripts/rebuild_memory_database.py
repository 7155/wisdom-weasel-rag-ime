#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.memory_rebuild import preview_memory_rebuild, rebuild_memory_database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview or rebuild RAG-IME memory in a backed-up SQLite database."
    )
    parser.add_argument("--source", type=Path, required=True, help="Source rag-ime.sqlite")
    parser.add_argument("--output", type=Path, help="Writable rebuilt copy; required with --apply")
    parser.add_argument("--apply", action="store_true", help="Copy source to output and rebuild the copy")
    parser.add_argument("--vacuum", action="store_true", help="VACUUM the rebuilt copy after verification")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    if not source.is_file():
        parser.error(f"source database does not exist: {source}")

    if not args.apply:
        with _read_only_connection(source) as conn:
            payload = preview_memory_rebuild(conn)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.output is None:
        parser.error("--output is required with --apply; in-place rebuilds are intentionally unsupported")
    output = args.output.expanduser().resolve()
    if output == source:
        parser.error("output must differ from source; swap the verified copy manually or through the Sidecar")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        parser.error(f"output already exists: {output}")

    _online_backup(source, output)
    try:
        with sqlite3.connect(output) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            report = rebuild_memory_database(conn)
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_key_violations = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        if integrity != "ok" or foreign_key_violations:
            raise RuntimeError(
                f"rebuilt database validation failed: integrity={integrity}, foreignKeys={foreign_key_violations[:10]}"
            )
        if args.vacuum:
            with sqlite3.connect(output) as conn:
                conn.execute("VACUUM")
        report.update(
            {
                "mode": "rebuilt_copy",
                "sourcePath": str(source),
                "rebuiltPath": str(output),
                "rollbackPath": str(source),
                "integrityCheck": integrity,
                "foreignKeyViolationCount": len(foreign_key_violations),
            }
        )
        report_path = output.with_suffix(output.suffix + ".rebuild-report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**report, "reportPath": str(report_path)}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        _remove_sqlite_files(output)
        raise


def _read_only_connection(path: Path) -> sqlite3.Connection:
    # immutable avoids SQLite trying to create a SHM/journal beside the user's
    # live DB, which this maintenance process intentionally opens read-only.
    uri = f"file:{quote(str(path))}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _online_backup(source: Path, output: Path) -> None:
    for attempt in range(3):
        before = source.stat()
        with _read_only_connection(source) as source_conn, sqlite3.connect(output) as target_conn:
            source_conn.backup(target_conn, pages=2048, sleep=0.01)
            target_conn.execute(
                "PRAGMA user_version = " + str(int(source_conn.execute("PRAGMA user_version").fetchone()[0]))
            )
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
            return
        _remove_sqlite_files(output)
    raise RuntimeError("source database changed during all three snapshot attempts")


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
