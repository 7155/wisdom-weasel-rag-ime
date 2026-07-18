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

from rag_ime.manual_memory_review import (
    assemble_manual_memory_manifest,
    export_manual_memory_review,
    validate_manual_memory_manifest,
)


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description=(
            "Export and validate a local-only, fail-closed historical memory review. "
            "This command never writes the production database."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    export_parser = commands.add_parser("export")
    export_parser.add_argument("--source", type=Path, required=True)
    export_parser.add_argument("--snapshot", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--project", default="wisdom-weasel-rag-ime")
    export_parser.add_argument("--timezone", default="Asia/Shanghai")

    assemble_parser = commands.add_parser("assemble")
    assemble_parser.add_argument("--export", type=Path, required=True)
    assemble_parser.add_argument("--part", type=Path, action="append", required=True)
    assemble_parser.add_argument("--existing-audit", type=Path, required=True)
    assemble_parser.add_argument("--output", type=Path, required=True)
    assemble_parser.add_argument("--reviewer", default="codex-root")

    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("--export", type=Path, required=True)
    validate_parser.add_argument("--manifest", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "export":
        result = _export(
            source=args.source,
            snapshot=args.snapshot,
            output=args.output,
            project=str(args.project),
            timezone_name=str(args.timezone),
        )
    elif args.command == "assemble":
        result = _assemble(
            export_path=args.export,
            part_paths=args.part,
            existing_audit_path=args.existing_audit,
            output=args.output,
            reviewer=str(args.reviewer),
        )
    else:
        result = _validate(
            export_path=args.export,
            manifest_path=args.manifest,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _export(
    *,
    source: Path,
    snapshot: Path,
    output: Path,
    project: str,
    timezone_name: str,
) -> dict[str, object]:
    source_path = _existing_regular_file(source, label="source database")
    snapshot_path = _new_private_path(snapshot, label="snapshot")
    output_path = _new_private_path(output, label="review export")
    if source_path in {snapshot_path, output_path} or snapshot_path == output_path:
        raise ValueError("source, snapshot and export paths must differ")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _online_backup(source_path, snapshot_path)
        with _read_only_connection(snapshot_path) as conn:
            payload = export_manual_memory_review(
                conn,
                project=project,
                timezone_name=timezone_name,
            )
            payload["snapshot"] = {
                "path": str(snapshot_path),
                "sha256": _sha256_file(snapshot_path),
                "integrityCheck": str(conn.execute("PRAGMA integrity_check").fetchone()[0]),
                "foreignKeyViolationCount": len(
                    conn.execute("PRAGMA foreign_key_check").fetchall()
                ),
            }
        _write_private_json(output_path, payload)
    except Exception:
        _remove_sqlite_files(snapshot_path)
        output_path.unlink(missing_ok=True)
        raise
    return {
        "ok": True,
        "sourcePath": str(source_path),
        "snapshotPath": str(snapshot_path),
        "outputPath": str(output_path),
        "counts": payload["counts"],
        "evidenceFingerprint": payload["evidenceFingerprint"],
        "memoryCatalogFingerprint": payload["memoryCatalogFingerprint"],
        "snapshotSha256": payload["snapshot"]["sha256"],
    }


def _assemble(
    *,
    export_path: Path,
    part_paths: list[Path],
    existing_audit_path: Path,
    output: Path,
    reviewer: str,
) -> dict[str, object]:
    resolved_export = _existing_private_json(export_path, label="review export")
    resolved_parts = [
        _existing_private_json(path, label="review part") for path in part_paths
    ]
    resolved_audit = _existing_private_json(
        existing_audit_path,
        label="existing memory audit",
    )
    output_path = _new_private_path(output, label="review manifest")
    export = _read_json(resolved_export)
    parts = [_read_json(path) for path in resolved_parts]
    audit = _read_json(resolved_audit)
    manifest = assemble_manual_memory_manifest(
        export,
        parts=parts,
        existing_audit=audit,
        reviewer_id=reviewer,
    )
    _write_private_json(output_path, manifest)
    return {
        "ok": True,
        "outputPath": str(output_path),
        "validation": manifest["validation"],
    }


def _validate(*, export_path: Path, manifest_path: Path) -> dict[str, object]:
    resolved_export = _existing_private_json(export_path, label="review export")
    resolved_manifest = _existing_private_json(manifest_path, label="review manifest")
    validation = validate_manual_memory_manifest(
        _read_json(resolved_export),
        manifest=_read_json(resolved_manifest),
    )
    if not bool(validation["ok"]):
        raise ValueError(
            "manual memory manifest failed validation: "
            + "; ".join(str(value) for value in validation["errors"][:20])
        )
    return validation


def _online_backup(source: Path, output: Path) -> None:
    _reserve_private_file(output)
    try:
        with _read_only_connection(source) as source_conn, sqlite3.connect(output) as target:
            source_conn.backup(target, pages=2048, sleep=0.01)
            target.execute("PRAGMA journal_mode = DELETE")
            target.execute("PRAGMA synchronous = FULL")
            target.commit()
        os.chmod(output, 0o600)
        _fsync_file(output)
    except Exception:
        _remove_sqlite_files(output)
        raise


def _read_only_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    _reserve_private_file(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return payload


def _existing_private_json(path: Path, *, label: str) -> Path:
    resolved = _existing_regular_file(path, label=label)
    _require_private_file(resolved, label=label)
    return resolved


def _existing_regular_file(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    metadata = expanded.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular non-symlink file: {expanded}")
    if int(metadata.st_nlink) != 1:
        raise ValueError(f"{label} must have exactly one hard link: {expanded}")
    return expanded.resolve(strict=True)


def _new_private_path(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if os.path.lexists(expanded):
        raise FileExistsError(f"{label} already exists: {expanded}")
    return expanded.resolve(strict=False)


def _require_private_file(path: Path, *, label: str) -> None:
    mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
    if mode & 0o077:
        raise PermissionError(f"{label} must have mode 0600: {path}")
    if mode & stat.S_IRUSR != stat.S_IRUSR:
        raise PermissionError(f"{label} must be owner-readable: {path}")


def _reserve_private_file(path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.close(descriptor)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY)
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
