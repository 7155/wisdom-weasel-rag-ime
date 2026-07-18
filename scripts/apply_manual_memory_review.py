#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.embeddings import embedding_provider_from_env
from rag_ime.manual_memory_application import (
    apply_manual_memory_manifest,
    verify_manual_memory_application,
)
from rag_ime.memory_projection import process_memory_projection_outbox
from rag_ime.semantic_memory_migration import verify_semantic_memory_database


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description=(
            "Build a fully reviewed memory candidate from an exact private snapshot. "
            "The reviewed snapshot is never modified."
        )
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewer", default="codex-root")
    parser.add_argument("--embedding-from-env", action="store_true")
    args = parser.parse_args()
    if not args.embedding_from_env:
        parser.error("--embedding-from-env is required for an activation-eligible candidate")

    source = _private_regular_file(args.source, label="reviewed snapshot")
    export_path = _private_regular_file(args.export, label="review export")
    manifest_path = _private_regular_file(args.manifest, label="review manifest")
    output = _new_path(args.output, label="candidate")
    if output == source:
        parser.error("candidate output must differ from the reviewed snapshot")
    report_path = output.with_suffix(output.suffix + ".manual-review-report.json")
    if os.path.lexists(report_path):
        parser.error(f"candidate report already exists: {report_path}")

    export = _read_json(export_path)
    manifest = _read_json(manifest_path)
    expected_snapshot_sha256 = str(dict(export.get("snapshot") or {}).get("sha256") or "")
    source_sha256_before = _sha256_file(source)
    if source_sha256_before != expected_snapshot_sha256:
        parser.error("reviewed snapshot hash does not match the review export")
    provider = embedding_provider_from_env()
    provider_fingerprint = str(getattr(provider, "fingerprint", "") or "").strip()
    if not provider_fingerprint or provider_fingerprint == "none":
        parser.error("configured embedding provider is disabled")

    output.parent.mkdir(parents=True, exist_ok=True)
    _online_backup(source, output)
    try:
        with sqlite3.connect(output) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            application = apply_manual_memory_manifest(
                conn,
                candidate_path=output,
                export=export,
                manifest=manifest,
                reviewer_id=str(args.reviewer),
            )
        projection_runs: list[dict[str, object]] = []
        for _ in range(16):
            with sqlite3.connect(output) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                projection = process_memory_projection_outbox(
                    conn,
                    embedding_provider=provider,
                    max_events=64,
                    max_attempts=3,
                )
            projection_runs.append(projection)
            freshness = dict(projection.get("freshness") or {})
            if int(freshness.get("backlog") or 0) == 0 and bool(freshness.get("fresh")):
                break
        else:
            raise RuntimeError("memory projection did not converge after manual review")

        with sqlite3.connect(output) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            manual_verification = verify_manual_memory_application(
                conn,
                manifest=manifest,
                project=str(manifest.get("project") or ""),
            )
            semantic_verification = verify_semantic_memory_database(
                conn,
                project=str(manifest.get("project") or ""),
                provider_fingerprint=provider_fingerprint,
                require_vector_freshness=True,
            )
            discarded_projection_count = int(
                conn.execute(
                    """SELECT COUNT(*)
                       FROM memory_retrieval_docs AS doc
                       JOIN memory_books AS book ON book.book_id = doc.source_id
                       WHERE book.archive_reason = 'discarded_by_manual_review'"""
                ).fetchone()[0]
            )
        if not bool(manual_verification.get("ok")):
            raise RuntimeError(
                "manual candidate verification failed: "
                + "; ".join(str(value) for value in manual_verification.get("errors") or ())
            )
        if discarded_projection_count:
            raise RuntimeError(
                f"discarded books remain retrievable: {discarded_projection_count}"
            )
        if not bool(semantic_verification.get("ok")):
            raise RuntimeError(
                "semantic candidate verification failed: "
                + "; ".join(str(value) for value in semantic_verification.get("errors") or ())
            )
        source_sha256_after = _sha256_file(source)
        if source_sha256_after != source_sha256_before:
            raise RuntimeError("reviewed snapshot changed while building the candidate")
        _checkpoint(output)
        candidate_sha256 = _sha256_file(output)
        report = {
            "schemaVersion": "rag-ime.manual-memory-candidate-report.v1",
            "ok": True,
            "sourcePath": str(source),
            "sourceSha256": source_sha256_after,
            "exportPath": str(export_path),
            "manifestPath": str(manifest_path),
            "candidatePath": str(output),
            "candidateSha256": candidate_sha256,
            "candidateMode": oct(stat.S_IMODE(output.stat().st_mode)),
            "providerFingerprint": provider_fingerprint,
            "beforeState": dict(application["beforeState"]),
            "application": application,
            "projectionRuns": projection_runs,
            "manualVerification": manual_verification,
            "semanticVerification": semantic_verification,
            "discardedBookProjectionCount": discarded_projection_count,
        }
        _write_json(report_path, report)
        print(json.dumps({**report, "reportPath": str(report_path)}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        _remove_sqlite_files(output)
        report_path.unlink(missing_ok=True)
        raise


def _online_backup(source: Path, output: Path) -> None:
    _reserve(output)
    try:
        with sqlite3.connect(
            f"file:{quote(str(source))}?mode=ro", uri=True
        ) as source_conn, sqlite3.connect(output) as target_conn:
            source_conn.backup(target_conn, pages=2048, sleep=0.01)
            target_conn.execute("PRAGMA journal_mode = DELETE")
            target_conn.execute("PRAGMA synchronous = FULL")
            target_conn.commit()
        os.chmod(output, 0o600)
        _checkpoint(output)
    except Exception:
        _remove_sqlite_files(output)
        raise


def _private_regular_file(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    metadata = expanded.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular non-symlink file: {expanded}")
    if int(metadata.st_nlink) != 1:
        raise ValueError(f"{label} must have exactly one hard link: {expanded}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PermissionError(f"{label} must have private permissions: {expanded}")
    return expanded.resolve(strict=True)


def _new_path(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if os.path.lexists(expanded):
        raise FileExistsError(f"{label} already exists: {expanded}")
    return expanded.resolve(strict=False)


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _reserve(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)
    _fsync_directory(path.parent)


def _reserve(path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.close(descriptor)


def _checkpoint(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is not None and int(row[0] or 0) != 0:
            raise RuntimeError("candidate database has an active writer")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.commit()
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
