#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.embeddings import embedding_provider_from_env
from rag_ime.semantic_memory_migration import (
    migrate_semantic_memory_database,
    preview_semantic_memory_migration,
)


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description=(
            "Preview or build a verified semantic-memory-v2 SQLite candidate. "
            "The source database is never modified or replaced."
        )
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--project", default="")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument(
        "--embedding-from-env",
        action="store_true",
        help="Rebuild retrieval vectors with the configured provider inside the candidate",
    )
    args = parser.parse_args()

    try:
        source = _existing_regular_path(args.source, label="source database")
        _require_single_link(source, label="source database")
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    if not args.apply:
        with _read_only_connection(source) as conn:
            report = preview_semantic_memory_migration(
                conn,
                project=str(args.project),
            )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.output is None:
        parser.error("--output is required with --apply")
    if not args.embedding_from_env:
        parser.error(
            "--apply requires --embedding-from-env; production candidates "
            "must include a complete retrieval vector projection"
        )
    provider = embedding_provider_from_env()
    provider_fingerprint = str(
        getattr(provider, "fingerprint", "") or ""
    ).strip()
    if not provider_fingerprint or provider_fingerprint == "none":
        parser.error(
            "--embedding-from-env resolved to a disabled provider; set "
            "RAG_IME_EMBEDDING_PROVIDER before building a candidate"
        )
    raw_output = args.output.expanduser()
    if _lexists(raw_output):
        parser.error(f"output path already exists or is a symlink: {raw_output}")
    output = raw_output.resolve(strict=False)
    if output == source:
        parser.error("in-place migration is unsupported; activate a verified copy separately")
    report_path = output.with_suffix(output.suffix + ".semantic-v2-report.json")
    reserved_paths = (
        output,
        Path(str(output) + "-wal"),
        Path(str(output) + "-shm"),
        report_path,
    )
    existing_reserved = next((path for path in reserved_paths if _lexists(path)), None)
    if existing_reserved is not None:
        parser.error(f"candidate output path is already reserved: {existing_reserved}")
    output.parent.mkdir(parents=True, exist_ok=True)

    runtime_stop_verification = _runtime_stop_verification(source)
    if bool(runtime_stop_verification["required"]) and not bool(
        runtime_stop_verification["ok"]
    ):
        parser.error(
            "source runtime is still active; run scripts/stop_rag_ime_runtime.sh "
            "before building the production candidate: "
            + "; ".join(str(value) for value in runtime_stop_verification["errors"])
        )
    _online_backup(source, output)
    # Opening a stopped WAL database read-only can materialize empty -wal/-shm
    # sidecars.  _online_backup already proves the source stayed stable while
    # copying, so bind the long-running migration guard to the settled state
    # after that copy rather than treating SQLite's own sidecar creation as a
    # writer restart.
    source_state_before = _source_state(source)
    os.chmod(output, 0o600)
    try:
        report = migrate_semantic_memory_database(
            output,
            project=str(args.project),
            timezone_name=str(args.timezone),
            embedding_provider=provider,
            require_vector_freshness=True,
        )
        source_state_after = _source_state(source)
        if source_state_after != source_state_before:
            raise RuntimeError("source database changed while the candidate was being migrated")
        _fsync_file(output)
        candidate_sha256 = _sha256_file(output)
        report.update(
            {
                "sourcePath": str(source),
                "candidatePath": str(output),
                "rollbackPath": str(source),
                "sourceState": source_state_after,
                "candidateMode": oct(output.stat().st_mode & 0o777),
                "candidateSha256": candidate_sha256,
                "runtimeStopVerification": runtime_stop_verification,
            }
        )
        with report_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_file(report_path)
        print(
            json.dumps(
                {**report, "reportPath": str(report_path)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception:
        _remove_sqlite_files(output)
        output.with_suffix(output.suffix + ".semantic-v2-report.json").unlink(
            missing_ok=True
        )
        raise


def _read_only_connection(path: Path) -> sqlite3.Connection:
    # Do not use immutable=1: a live WAL can contain committed rows that are not
    # present in the main file yet. SQLite's read-only WAL view is authoritative.
    uri = f"file:{quote(str(path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _online_backup(source: Path, output: Path) -> None:
    for _ in range(3):
        before = _source_state(source)
        _reserve_private_file(output)
        try:
            with _read_only_connection(source) as source_conn, sqlite3.connect(output) as target:
                source_conn.backup(target, pages=2048, sleep=0.01)
                target.execute("PRAGMA journal_mode = DELETE")
                target.execute("PRAGMA synchronous = FULL")
                target.commit()
        except Exception:
            _remove_sqlite_files(output)
            raise
        after = _source_state(source)
        if before == after:
            return
        _remove_sqlite_files(output)
    raise RuntimeError("source database changed during all three online backup attempts")


def _source_state(path: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for label, candidate in (
        ("database", path),
        ("wal", Path(str(path) + "-wal")),
    ):
        if candidate.exists():
            stat = candidate.stat()
            result[label] = {
                "size": stat.st_size,
                "mtimeNs": stat.st_mtime_ns,
                "inode": stat.st_ino,
            }
        else:
            result[label] = None
    return result


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


def _existing_regular_path(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    try:
        metadata = expanded.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(f"{label} does not exist: {expanded}") from None
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} must not be a symlink: {expanded}")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular file: {expanded}")
    return expanded.resolve(strict=True)


def _require_single_link(path: Path, *, label: str) -> None:
    # A source alias could later be presented as a different activation target.
    # Require one pathname so the migration report binds an unambiguous file.
    links = int(path.stat(follow_symlinks=False).st_nlink)
    if links != 1:
        raise ValueError(f"{label} must have exactly one hard link: {path}")


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _reserve_private_file(path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.close(descriptor)


def _runtime_stop_verification(source: Path) -> dict[str, object]:
    labels = (
        "com.rag-ime.sidecar",
        "com.rag-ime.agent-gateway",
        "com.rag-ime.memory-book-maintenance",
        "com.rag-ime.mlx-predictor",
        "com.rag-ime.desktop-bridge",
        "com.rag-ime.voice",
    )
    default_database = (
        Path.home() / "Library/Application Support/RagIme/rag-ime.sqlite"
    ).resolve(strict=False)
    referenced_labels: list[str] = []
    for label in labels:
        plist_path = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
        if not plist_path.is_file() or plist_path.is_symlink():
            continue
        try:
            with plist_path.open("rb") as handle:
                payload = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException):
            continue
        environment = payload.get("EnvironmentVariables") or {}
        arguments = [str(value) for value in payload.get("ProgramArguments") or ()]
        configured_database = str(environment.get("RAG_IME_DB_PATH") or "")
        if not configured_database and "--db-path" in arguments:
            index = arguments.index("--db-path")
            if index + 1 < len(arguments):
                configured_database = arguments[index + 1]
        if configured_database and Path(configured_database).expanduser().resolve(
            strict=False
        ) == source:
            referenced_labels.append(label)

    required = source == default_database or bool(referenced_labels)
    errors: list[str] = []
    loaded_labels: list[str] = []
    listening_ports: list[int] = []
    open_processes: list[str] = []
    orphan_processes: list[str] = []
    if required:
        domain = f"gui/{os.getuid()}"
        for label in labels:
            result = subprocess.run(
                ["launchctl", "print", f"{domain}/{label}"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                loaded_labels.append(label)
        if shutil_which("lsof"):
            for port in (
                int(os.environ.get("RAG_IME_SIDECAR_PORT", "8766")),
                int(os.environ.get("RAG_IME_MLX_PORT", "8767")),
                int(os.environ.get("RAG_IME_AGENT_GATEWAY_PORT", "8768")),
            ):
                result = subprocess.run(
                    ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.stdout.strip():
                    listening_ports.append(port)
            result = subprocess.run(
                ["lsof", "-nP", "--", str(source)],
                check=False,
                capture_output=True,
                text=True,
            )
            open_processes = [
                line.strip()
                for line in result.stdout.splitlines()[1:]
                if line.strip()
            ][:20]
        for pattern in (
            "[s]idecar_launch.py.*(sidecar-server|agent-gateway|mlx-predictor-server)",
            "[m]emory_book_maintenance_launch.py",
            "[r]ag_ime\\.cli .*(sidecar-server|agent-gateway|mlx-predictor-server)",
            "/Contents/MacOS/[R]agImeDesktopBridge([[:space:]]|$)",
            "/Contents/MacOS/[R]agImeVoice([[:space:]]|$)",
            "/Contents/MacOS/[R]agImeControl([[:space:]]|$)",
            "/Library/Input Methods/[S]quirrel\\.app/Contents/MacOS/Squirrel",
        ):
            result = subprocess.run(
                ["pgrep", "-fl", pattern],
                check=False,
                capture_output=True,
                text=True,
            )
            orphan_processes.extend(
                line.strip() for line in result.stdout.splitlines() if line.strip()
            )
        if loaded_labels:
            errors.append("loaded_launch_agents=" + ",".join(loaded_labels))
        if listening_ports:
            errors.append(
                "listening_runtime_ports="
                + ",".join(str(value) for value in listening_ports)
            )
        if open_processes:
            errors.append(f"database_open_handles={len(open_processes)}")
        if orphan_processes:
            errors.append(f"orphan_runtime_processes={len(orphan_processes)}")
    return {
        "schemaVersion": "rag-ime.runtime-stop-verification.v1",
        "required": required,
        "ok": not errors,
        "sourcePath": str(source),
        "referencedByLaunchAgents": referenced_labels,
        "loadedLaunchAgents": loaded_labels,
        "listeningPorts": listening_ports,
        "databaseOpenHandles": open_processes,
        "orphanRuntimeProcesses": orphan_processes[:20],
        "errors": errors,
    }


def shutil_which(command: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
