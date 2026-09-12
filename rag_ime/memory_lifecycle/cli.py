"""Local lifecycle entry points. Run `python -m rag_ime.memory_lifecycle --help`."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .common import MAX_BUNDLE_BYTES, LifecycleError, canonical_json, connect, identifier, now_ms, transaction
from .daily import generate
from .forget import forget_source, preview_source_forget
from .portability import export_project, import_bundle, records_bundle
from .refresh import RefreshJobs


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise LifecycleError("duplicate_json_key")
        result[key] = value
    return result


def read_json(path: str) -> Any:
    with open(path, "rb") as stream:
        raw = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise LifecycleError("bundle_too_large")
    try:
        return json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(LifecycleError("invalid_json_number")))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise LifecycleError("invalid_json_file") from None


def write_private(path: str, text: str, *, overwrite: bool = False) -> None:
    """Atomic 0600 output, no partial bundle and no implicit overwrite."""
    dest = Path(path).expanduser().absolute()
    fd, temp = tempfile.mkstemp(prefix=".memory-", dir=dest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temp, dest)
        else:
            os.link(temp, dest)  # Fails atomically if the destination exists.
            os.unlink(temp)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="PAW Memory lifecycle; imports default to dry-run and never approve facts.")
    root.add_argument("--db", required=True, help="Existing migrated PAW SQLite database")
    commands = root.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--project", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--overwrite", action="store_true")
    imp = commands.add_parser("import")
    imp.add_argument("--input", required=True)
    imp.add_argument("--target-project", required=True)
    imp.add_argument("--commit", action="store_true")
    record = commands.add_parser("import-record")
    record.add_argument("--text-file", required=True)
    record.add_argument("--external-id", required=True)
    record.add_argument("--namespace", required=True)
    record.add_argument("--occurred-at", required=True, help="ISO8601 with timezone")
    record.add_argument("--target-project", required=True)
    record.add_argument("--commit", action="store_true")
    migration = commands.add_parser("migrate-project")
    migration.add_argument("--from-project", required=True)
    migration.add_argument("--to-project", required=True)
    migration.add_argument("--commit", action="store_true")
    report = commands.add_parser("report")
    report.add_argument("--project", required=True)
    report.add_argument("--date", required=True)
    report.add_argument("--timezone", required=True)
    report.add_argument("--output", required=True)
    report.add_argument("--format", choices=("json", "markdown"), default="json")
    report.add_argument("--no-timeline", action="store_true")
    report.add_argument("--overwrite", action="store_true")
    refresh = commands.add_parser("refresh")
    refresh.add_argument("--operation", choices=("daily_report", "retrieval_projection"), required=True)
    refresh.add_argument("--project", required=True)
    refresh.add_argument("--date", default="")
    refresh.add_argument("--timezone", default="UTC")
    for cmd in ("status", "continue"):
        sub = commands.add_parser(cmd)
        sub.add_argument("--job-id", required=True)
    worker = commands.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--poll-seconds", type=int, default=60)
    worker.add_argument("--schedule-daily", action="store_true")
    worker.add_argument("--project", default="")
    worker.add_argument("--timezone", default="UTC")
    worker.add_argument("--daily-hour", type=int, default=20)
    forget = commands.add_parser("forget-source")
    forget.add_argument("--project", required=True)
    forget.add_argument("--source-id", required=True)
    forget.add_argument("--commit", action="store_true")
    forget.add_argument("--expected-plan-digest", default="")
    forget.add_argument("--gateway-stopped", action="store_true", help="Required for offline erasure: no live process caches")
    exclude = commands.add_parser("exclude-session")
    exclude.add_argument("--project", required=True)
    exclude.add_argument("--session-id", required=True)
    exclude.add_argument("--remove", action="store_true")
    return root


def _schedule_daily(jobs: RefreshJobs, args: argparse.Namespace) -> None:
    local = datetime.now(ZoneInfo(args.timezone))
    if local.hour < args.daily_hour:
        return
    day = local.date().isoformat()
    with connect(args.db) as conn:
        existing = conn.execute("""SELECT 1 FROM memory_maintenance_jobs j JOIN memory_refresh_checkpoints c USING(job_id)
            WHERE c.operation='daily_report' AND json_extract(j.request_json,'$.project')=?
            AND json_extract(j.request_json,'$.date')=? AND json_extract(j.request_json,'$.timezone')=? LIMIT 1""",
            (args.project, day, args.timezone)).fetchone()
    if not existing:
        jobs.submit(operation="daily_report", project=args.project, day=day, timezone=args.timezone, scheduled=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    jobs = RefreshJobs(args.db)
    if args.command == "refresh":
        return jobs.submit(operation=args.operation, project=args.project, day=args.date, timezone=args.timezone)
    if args.command == "status":
        return jobs.status(args.job_id)
    if args.command == "continue":
        return jobs.continue_job(args.job_id)
    if args.command == "worker":
        if not 1 <= args.poll_seconds <= 3600 or not 0 <= args.daily_hour <= 23:
            raise LifecycleError("invalid_worker_schedule")
        while True:
            if args.schedule_daily:
                _schedule_daily(jobs, args)
            status = jobs.run_one()
            if args.once:
                return status or {"ok": True, "idle": True}
            if status:
                print(canonical_json(status), flush=True)
            time.sleep(args.poll_seconds)
    with connect(args.db) as conn:
        if args.command == "export":
            packet = export_project(conn, project=args.project)
            write_private(args.output, canonical_json(packet), overwrite=args.overwrite)
            return {"ok": True, "output": args.output, "sha256": packet["sha256"], "omitted": packet["omitted"]}
        if args.command == "import":
            return import_bundle(conn, read_json(args.input), target_project=args.target_project, dry_run=not args.commit)
        if args.command == "import-record":
            with open(args.text_file, "r", encoding="utf-8") as stream:
                text = stream.read(32_001)
            if len(text) > 32_000:
                raise LifecycleError("record_too_large")
            when = datetime.fromisoformat(args.occurred_at)
            if when.tzinfo is None:
                raise LifecycleError("record_timestamp_requires_timezone")
            packet = records_bundle(records=[{"id": args.external_id, "text": text, "occurredAtMs": int(when.timestamp() * 1000)}],
                                    namespace=args.namespace, project=args.target_project)
            return import_bundle(conn, packet, target_project=args.target_project, dry_run=not args.commit)
        if args.command == "migrate-project":
            if args.from_project == args.to_project:
                raise LifecycleError("migration_requires_different_projects")
            packet = export_project(conn, project=args.from_project)
            return {**import_bundle(conn, packet, target_project=args.to_project, dry_run=not args.commit), "sourceProjectUnchanged": True}
        if args.command == "report":
            result = generate(conn, project=args.project, day=args.date, timezone=args.timezone, include_timeline=not args.no_timeline)
            write_private(args.output, result["markdown"] if args.format == "markdown" else canonical_json(result), overwrite=args.overwrite)
            return {"ok": True, "output": args.output, "inputDigest": result["inputDigest"], "writesBackToMemory": False}
        if args.command == "forget-source":
            if not args.commit:
                return preview_source_forget(conn, project=args.project, source_id=args.source_id)
            if not args.gateway_stopped or not args.expected_plan_digest:
                raise LifecycleError("offline_forget_requires_stopped_gateway_and_preview_digest")
            return forget_source(conn, project=args.project, source_id=args.source_id, expected_plan_digest=args.expected_plan_digest)
        if args.command == "exclude-session":
            identifier(args.session_id)
            identifier(args.project, allow_empty=True)
            with transaction(conn):
                if args.remove:
                    conn.execute("DELETE FROM memory_capture_exclusions WHERE project=? AND target_kind='session' AND target_id=?", (args.project, args.session_id))
                else:
                    conn.execute("INSERT OR IGNORE INTO memory_capture_exclusions(project,target_kind,target_id,created_at_ms) VALUES (?,'session',?,?)", (args.project, args.session_id, now_ms()))
            return {"ok": True, "futureMemoryCaptureExcluded": not args.remove, "existingMemoryUnchanged": True}
    raise LifecycleError("unsupported_command")


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(parser().parse_args(argv))
        print(canonical_json(result))
        return 0
    except KeyboardInterrupt:
        return 130
    except LifecycleError as exc:
        print(canonical_json({"ok": False, "errorCode": str(exc)}), file=sys.stderr)
        return 2
    except Exception:
        # No source text, SQL parameters, tokens or paths in accidental traces.
        print(canonical_json({"ok": False, "errorCode": "lifecycle_operation_failed"}), file=sys.stderr)
        return 1
