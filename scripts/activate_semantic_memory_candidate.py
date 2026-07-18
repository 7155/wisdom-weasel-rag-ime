#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.semantic_memory_migration import verify_semantic_memory_database
from rag_ime.manual_memory_review import (
    memory_review_catalog_fingerprint,
    memory_review_evidence_fingerprint,
    memory_review_governance_fingerprint,
)


CONFIRM_TEXT = "ACTIVATE_SEMANTIC_MEMORY_V2"
MANUAL_REPORT_SCHEMA_VERSION = "rag-ime.manual-memory-candidate-report.v1"


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description=(
            "Atomically activate a verified semantic-memory-v2 candidate. "
            "Stop every RAG-IME writer before running this command."
        )
    )
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--rollback", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != CONFIRM_TEXT:
        parser.error(f"--confirm must equal {CONFIRM_TEXT}")
    result = activate_candidate(
        target=args.target,
        candidate=args.candidate,
        report_path=args.report,
        rollback=args.rollback,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def activate_candidate(
    *,
    target: str | Path,
    candidate: str | Path,
    rollback: str | Path,
    report_path: str | Path | None = None,
) -> dict[str, object]:
    os.umask(0o077)
    target_path = _existing_regular_path(target, label="target database")
    candidate_path = _existing_regular_path(candidate, label="candidate database")
    _require_single_link(target_path, label="target database")
    _require_single_link(candidate_path, label="candidate database")
    raw_rollback = Path(rollback).expanduser()
    if _lexists(raw_rollback):
        if raw_rollback.is_symlink():
            raise ValueError(f"rollback path must not be a symlink: {raw_rollback}")
        raise FileExistsError(raw_rollback)
    rollback_path = raw_rollback.resolve(strict=False)
    raw_report = _candidate_report_path(candidate, report_path=report_path)
    resolved_report = _existing_regular_path(raw_report, label="migration report")
    _require_single_link(resolved_report, label="migration report")
    if target_path in {candidate_path, rollback_path} or candidate_path == rollback_path:
        raise ValueError("target, candidate, and rollback paths must be distinct")
    if os.path.samefile(target_path, candidate_path):
        raise ValueError("target and candidate databases must not be hard links")
    if os.path.samefile(resolved_report, target_path) or os.path.samefile(
        resolved_report, candidate_path
    ):
        raise ValueError("migration report must be a distinct regular file")
    for candidate_sidecar in (
        Path(str(candidate_path) + "-wal"),
        Path(str(candidate_path) + "-shm"),
    ):
        if _lexists(candidate_sidecar):
            raise ValueError(
                f"candidate database must not have SQLite sidecars: {candidate_sidecar}"
            )
    _require_private_file(target_path, label="target database", writable=True)
    _require_private_file(candidate_path, label="candidate database", writable=True)
    _require_private_file(resolved_report, label="migration report", writable=False)
    receipt = rollback_path.with_suffix(rollback_path.suffix + ".activation.json")
    for rollback_reserved in (
        rollback_path,
        Path(str(rollback_path) + "-wal"),
        Path(str(rollback_path) + "-shm"),
        receipt,
    ):
        if _lexists(rollback_reserved):
            if rollback_reserved == rollback_path and rollback_reserved.is_symlink():
                raise ValueError(
                    f"rollback path must not be a symlink: {rollback_reserved}"
                )
            raise FileExistsError(rollback_reserved)
    report = json.loads(resolved_report.read_text(encoding="utf-8"))
    report_state = _regular_file_state(resolved_report)
    report_sha256 = _sha256_file(resolved_report)
    report_schema = str(report.get("schemaVersion") or "")
    manual_report = report_schema == MANUAL_REPORT_SCHEMA_VERSION
    if manual_report:
        report_contract = _validate_manual_report(
            report,
            candidate_path=candidate_path,
        )
        verification = dict(report_contract["verification"])
        provider_fingerprint = str(report_contract["providerFingerprint"])
        project = str(report_contract["project"])
        expected_source_state: dict[str, object] | None = None
        expected_before_state = dict(report_contract["beforeState"])
    else:
        verification = _validate_semantic_migration_report(report)
        provider_fingerprint = str(
            verification.get("vectorProviderFingerprint") or ""
        ).strip()
        project = str(report.get("project") or "")
        expected_source_state = dict(report.get("sourceState") or {})
        expected_before_state = None
    if Path(
        str(report.get("candidatePath") or "")
    ).expanduser().resolve() != candidate_path:
        raise ValueError("candidate path does not match its migration report")
    if not manual_report and Path(
        str(report.get("sourcePath") or "")
    ).expanduser().resolve() != target_path:
        raise ValueError("target path does not match the migration source")
    reported_runtime_stop = dict(report.get("runtimeStopVerification") or {})
    default_database = (
        Path.home() / "Library/Application Support/RagIme/rag-ime.sqlite"
    ).resolve(strict=False)
    runtime_stop_required = manual_report or bool(
        reported_runtime_stop.get("required")
    ) or (target_path == default_database)
    if (
        not manual_report
        and runtime_stop_required
        and not bool(reported_runtime_stop.get("ok"))
    ):
        raise ValueError(
            "candidate report does not prove that the source runtime was stopped"
        )
    current_runtime_stop = _runtime_stop_verification(
        target_path,
        required=runtime_stop_required,
    )
    if runtime_stop_required and not bool(current_runtime_stop["ok"]):
        raise RuntimeError(
            "target runtime restarted before activation: "
            + "; ".join(str(value) for value in current_runtime_stop["errors"])
        )
    expected_candidate_sha256 = str(report.get("candidateSha256") or "").strip()
    candidate_sha256 = _sha256_file(candidate_path)
    if not expected_candidate_sha256 or candidate_sha256 != expected_candidate_sha256:
        raise ValueError("candidate content does not match its migration report")
    candidate_state = _regular_file_state(candidate_path)
    if expected_before_state is not None:
        _assert_manual_before_state(
            target_path,
            project=project,
            expected=expected_before_state,
        )
    else:
        current_source_state = _source_state(target_path)
        if expected_source_state != current_source_state:
            raise RuntimeError(
                "target database changed after candidate creation; "
                "rebuild from the stopped target"
            )
    live_verification = _verify_semantic_database(
        candidate_path,
        project=project,
        provider_fingerprint=provider_fingerprint,
    )
    _checkpoint_stopped_target(target_path)
    # A successful WAL checkpoint can legitimately change file statistics while
    # preserving the exact logical database used to build the candidate. From
    # this point onward, any further state change indicates a restarted writer.
    stopped_source_state = _source_state(target_path)
    if expected_before_state is not None:
        _assert_manual_before_state(
            target_path,
            project=project,
            expected=expected_before_state,
        )

    rollback_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _copy_database(target_path, rollback_path)
    if _source_state(target_path) != stopped_source_state:
        raise RuntimeError("target database changed while creating the rollback copy")
    if _regular_file_state(candidate_path) != candidate_state or _sha256_file(
        candidate_path
    ) != expected_candidate_sha256:
        raise RuntimeError("candidate database changed during activation preflight")
    if _regular_file_state(resolved_report) != report_state or _sha256_file(
        resolved_report
    ) != report_sha256:
        raise RuntimeError("candidate report changed during activation preflight")
    if expected_before_state is not None:
        _assert_manual_before_state(
            target_path,
            project=project,
            expected=expected_before_state,
        )
    staging = target_path.with_name(
        f".{target_path.name}.semantic-v2-{os.getpid()}-{time.time_ns()}.tmp"
    )
    if _lexists(staging):
        raise FileExistsError(staging)
    payload: dict[str, object] | None = None
    try:
        _copy_database(candidate_path, staging)
        if _source_state(target_path) != stopped_source_state:
            raise RuntimeError("target database changed immediately before activation")
        os.replace(staging, target_path)
        _remove_sidecars(target_path)
        _fsync_directory(target_path.parent)
        live_verification = _verify_semantic_database(
            target_path,
            project=project,
            provider_fingerprint=provider_fingerprint,
        )
        payload = {
            "schemaVersion": "rag-ime.semantic-memory-activation.v1",
            "activatedAtMs": int(time.time() * 1000),
            "targetPath": str(target_path),
            "candidatePath": str(candidate_path),
            "candidateSha256": expected_candidate_sha256,
            "rollbackPath": str(rollback_path),
            "rollbackSha256": _sha256_file(rollback_path),
            "migrationReportPath": str(resolved_report),
            "migrationReportSha256": report_sha256,
            "candidateReportSchemaVersion": report_schema or "legacy-semantic-migration",
            "runtimeStopVerification": current_runtime_stop,
            "verification": live_verification,
        }
        if expected_before_state is not None:
            payload["beforeState"] = expected_before_state
        _write_json_exclusive(receipt, payload)
    except Exception as activation_error:
        _remove_sqlite_files(staging)
        restore = target_path.with_name(f".{target_path.name}.rollback-{os.getpid()}.tmp")
        _remove_sqlite_files(restore)
        receipt.unlink(missing_ok=True)
        try:
            _copy_database(rollback_path, restore)
            os.replace(restore, target_path)
            _remove_sidecars(target_path)
            _fsync_directory(target_path.parent)
        except Exception as restore_error:
            raise RuntimeError(
                "activation failed and automatic rollback restoration also failed"
            ) from restore_error
        raise activation_error

    assert payload is not None
    return {**payload, "activationReceiptPath": str(receipt)}


def _candidate_report_path(
    candidate: str | Path,
    *,
    report_path: str | Path | None,
) -> Path:
    if report_path is not None:
        return Path(report_path).expanduser()
    candidate_path = Path(candidate).expanduser()
    semantic_report = candidate_path.with_suffix(
        candidate_path.suffix + ".semantic-v2-report.json"
    )
    manual_report = candidate_path.with_suffix(
        candidate_path.suffix + ".manual-review-report.json"
    )
    # Keep the established semantic migration path authoritative when both
    # files exist.  Manual candidates use their own suffix only when the legacy
    # path is absent.
    if _lexists(semantic_report) or not _lexists(manual_report):
        return semantic_report
    return manual_report


def _validate_semantic_migration_report(
    report: dict[str, object],
) -> dict[str, object]:
    verification = dict(report.get("verification") or {})
    if not bool(verification.get("ok")):
        raise ValueError("candidate report does not contain a successful verification")
    _require_production_vector_gate(verification)
    return verification


def _validate_manual_report(
    report: dict[str, object],
    *,
    candidate_path: Path,
) -> dict[str, object]:
    if not bool(report.get("ok")):
        raise ValueError("manual candidate report is not successful")
    if Path(str(report.get("candidatePath") or "")).expanduser().resolve() != candidate_path:
        raise ValueError("candidate path does not match its manual review report")
    before_state = dict(report.get("beforeState") or {})
    required_before_fields = (
        "project",
        "evidenceFingerprint",
        "memoryCatalogFingerprint",
        "governanceFingerprint",
        "inputEventsFingerprint",
    )
    missing_before = [
        field
        for field in required_before_fields
        if not str(before_state.get(field) or "").strip()
    ]
    if missing_before:
        raise ValueError(
            "manual candidate report is missing strict beforeState fields: "
            + ",".join(missing_before)
        )
    project = str(before_state["project"]).strip()
    application = dict(report.get("application") or {})
    manual_verification = dict(report.get("manualVerification") or {})
    semantic_verification = dict(report.get("semanticVerification") or {})
    if not bool(application.get("ok")):
        raise ValueError("manual candidate application is not successful")
    if str(application.get("project") or "").strip() != project:
        raise ValueError("manual candidate project does not match beforeState")
    if Path(
        str(application.get("candidatePath") or "")
    ).expanduser().resolve() != candidate_path:
        raise ValueError("manual application is bound to a different candidate")
    if dict(application.get("beforeState") or {}) != before_state:
        raise ValueError("manual application beforeState does not match its report")
    application_verification = dict(application.get("verification") or {})
    if not bool(application_verification.get("ok")):
        raise ValueError("manual candidate application verification is not successful")
    if not bool(manual_verification.get("ok")):
        raise ValueError(
            "manual candidate report does not contain a successful manual verification"
        )
    if not bool(semantic_verification.get("ok")):
        raise ValueError(
            "manual candidate report does not contain a successful semantic verification"
        )
    if str(semantic_verification.get("integrityCheck") or "") != "ok":
        raise ValueError(
            "manual candidate report does not contain a successful integrity check"
        )
    if int(semantic_verification.get("foreignKeyViolationCount") or 0) != 0:
        raise ValueError("manual candidate report contains foreign-key violations")
    _require_production_vector_gate(semantic_verification)
    provider_fingerprint = str(
        semantic_verification.get("vectorProviderFingerprint")
        or report.get("providerFingerprint")
        or ""
    ).strip()
    if provider_fingerprint != str(report.get("providerFingerprint") or "").strip():
        raise ValueError(
            "manual candidate embedding provider fingerprints do not match"
        )
    expected_application_fields = {
        "evidenceFingerprint": "evidenceFingerprint",
        "memoryCatalogFingerprintBefore": "memoryCatalogFingerprint",
        "governanceFingerprintBefore": "governanceFingerprint",
        "inputEventsFingerprint": "inputEventsFingerprint",
    }
    for application_field, before_field in expected_application_fields.items():
        if str(application.get(application_field) or "") != str(
            before_state.get(before_field) or ""
        ):
            raise ValueError(
                "manual candidate application is not bound to beforeState: "
                + application_field
            )
    return {
        "project": project,
        "providerFingerprint": provider_fingerprint,
        "beforeState": before_state,
        "verification": semantic_verification,
    }


def _require_production_vector_gate(verification: dict[str, object]) -> None:
    if not bool(verification.get("vectorGateRequired")) or not bool(
        verification.get("activationEligible")
    ):
        raise ValueError(
            "candidate report was not produced with the production vector gate"
        )
    provider_fingerprint = str(
        verification.get("vectorProviderFingerprint") or ""
    ).strip()
    if not provider_fingerprint or provider_fingerprint == "none":
        raise ValueError("candidate report does not identify an enabled embedding provider")


def _assert_manual_before_state(
    path: Path,
    *,
    project: str,
    expected: dict[str, object],
) -> None:
    current = _manual_before_state(path, project=project)
    for field in (
        "project",
        "evidenceFingerprint",
        "memoryCatalogFingerprint",
        "governanceFingerprint",
        "inputEventsFingerprint",
    ):
        if str(current.get(field) or "") != str(expected.get(field) or ""):
            raise RuntimeError(
                "target database manual review state drifted before activation: " + field
            )


def _manual_before_state(path: Path, *, project: str) -> dict[str, str]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return {
            "project": project,
            "evidenceFingerprint": memory_review_evidence_fingerprint(
                conn,
                project=project,
            ),
            "memoryCatalogFingerprint": memory_review_catalog_fingerprint(
                conn,
                project=project,
            ),
            "governanceFingerprint": memory_review_governance_fingerprint(
                conn,
                project=project,
            ),
            "inputEventsFingerprint": _table_fingerprint(conn, "input_events"),
        }


def _table_fingerprint(conn: sqlite3.Connection, table: str) -> str:
    columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]
    if not columns:
        raise RuntimeError(f"required table is missing: {table}")
    digest = hashlib.sha256()
    for row in conn.execute(
        f"SELECT {', '.join(columns)} FROM {table} ORDER BY {columns[0]}"
    ):
        digest.update(
            json.dumps(
                [row[column] for column in columns],
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def _checkpoint_stopped_target(path: Path) -> None:
    with sqlite3.connect(path, timeout=1.0) as conn:
        conn.execute("PRAGMA busy_timeout = 1000")
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row is not None and len(row) >= 1 and int(row[0] or 0) != 0:
            raise RuntimeError("target database still has an active writer")


def _verify_semantic_database(
    path: Path,
    *,
    project: str,
    provider_fingerprint: str,
) -> dict[str, object]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        verification = verify_semantic_memory_database(
            conn,
            project=project,
            provider_fingerprint=provider_fingerprint,
            require_vector_freshness=True,
        )
    if not bool(verification.get("ok")):
        raise RuntimeError(
            "semantic memory candidate verification failed: "
            + "; ".join(str(value) for value in verification.get("errors") or ())
        )
    return verification


def _copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reserve_private_file(destination)
    try:
        with sqlite3.connect(
            f"file:{source}?mode=ro", uri=True
        ) as source_conn, sqlite3.connect(destination) as target_conn:
            source_conn.backup(target_conn, pages=2048, sleep=0.01)
            target_conn.execute("PRAGMA journal_mode = DELETE")
            target_conn.execute("PRAGMA synchronous = FULL")
            target_conn.commit()
        os.chmod(destination, 0o600)
        _fsync_file(destination)
    except Exception:
        _remove_sqlite_files(destination)
        raise


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


def _remove_sidecars(path: Path) -> None:
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    _remove_sidecars(path)


def _existing_regular_path(path: str | Path, *, label: str) -> Path:
    expanded = Path(path).expanduser()
    try:
        metadata = expanded.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(f"{label} does not exist: {expanded}") from None
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} must not be a symlink: {expanded}")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular file: {expanded}")
    return expanded.resolve(strict=True)


def _require_private_file(path: Path, *, label: str, writable: bool) -> None:
    metadata = path.stat(follow_symlinks=False)
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & 0o077:
        raise PermissionError(f"{label} must not be accessible by group or others: {path}")
    required = stat.S_IRUSR | (stat.S_IWUSR if writable else 0)
    if mode & required != required:
        requirement = "owner-readable and owner-writable" if writable else "owner-readable"
        raise PermissionError(f"{label} must be {requirement}: {path}")


def _require_single_link(path: Path, *, label: str) -> None:
    # A second hard-link is an unobservable write alias. Reject it so the
    # inode/mtime/SHA checks cannot be raced through another pathname.
    links = int(path.stat(follow_symlinks=False).st_nlink)
    if links != 1:
        raise ValueError(f"{label} must have exactly one hard link: {path}")


def _regular_file_state(path: Path) -> dict[str, int]:
    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"path stopped being a regular file: {path}")
    return {
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "size": int(metadata.st_size),
        "mtimeNs": int(metadata.st_mtime_ns),
        "mode": int(stat.S_IMODE(metadata.st_mode)),
    }


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _reserve_private_file(path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.close(descriptor)


def _write_json_exclusive(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _runtime_stop_verification(path: Path, *, required: bool) -> dict[str, object]:
    labels = (
        "com.rag-ime.sidecar",
        "com.rag-ime.agent-gateway",
        "com.rag-ime.memory-book-maintenance",
        "com.rag-ime.mlx-predictor",
        "com.rag-ime.desktop-bridge",
        "com.rag-ime.voice",
    )
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
        if _command_available("lsof"):
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
                ["lsof", "-nP", "--", str(path)],
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
        "targetPath": str(path),
        "loadedLaunchAgents": loaded_labels,
        "listeningPorts": listening_ports,
        "databaseOpenHandles": open_processes,
        "orphanRuntimeProcesses": orphan_processes[:20],
        "errors": errors,
    }


def _command_available(command: str) -> bool:
    return any(
        (Path(directory) / command).is_file()
        and os.access(Path(directory) / command, os.X_OK)
        for directory in os.environ.get("PATH", "").split(os.pathsep)
    )


if __name__ == "__main__":
    raise SystemExit(main())
