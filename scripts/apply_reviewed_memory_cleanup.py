#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.embeddings import embedding_provider_from_env
from rag_ime.hybrid_rag_models import HybridRagQuery
from rag_ime.hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from rag_ime.memory_projection import process_memory_projection_outbox
from rag_ime.reviewed_memory_cleanup import (
    apply_reviewed_memory_cleanup,
    verify_reviewed_memory_cleanup,
)
from rag_ime.semantic_memory_migration import verify_semantic_memory_database


DEFAULT_PRODUCTION_DB = (
    Path.home() / "Library/Application Support/RagIme/rag-ime.sqlite"
).resolve(strict=False)


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        description=(
            "Build a private, fully projected memory candidate from a reviewed "
            "cleanup plan. The source database is never modified."
        )
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewer", default="codex-root")
    parser.add_argument("--embedding-from-env", action="store_true")
    parser.add_argument("--runtime-stopped", action="store_true")
    args = parser.parse_args()
    if not args.embedding_from_env:
        parser.error("--embedding-from-env is required for an activation-eligible candidate")

    source = _private_regular_file(args.source, label="source database")
    plan_path = _private_regular_file(args.plan, label="reviewed cleanup plan")
    output = _new_path(args.output, label="candidate database")
    if output == source:
        parser.error("candidate output must differ from source")
    report_path = output.with_suffix(output.suffix + ".semantic-v2-report.json")
    if os.path.lexists(report_path):
        parser.error(f"candidate report already exists: {report_path}")
    plan = _read_json(plan_path)
    source_state = _source_state(source)
    source_sha256 = _sha256_file(source)
    production = source == DEFAULT_PRODUCTION_DB
    if production and not args.runtime_stopped:
        parser.error("--runtime-stopped is required when the source is the production database")
    runtime_stop = _runtime_stop_verification(source, required=production)
    if production and not bool(runtime_stop["ok"]):
        raise RuntimeError(
            "production runtime is not stopped: "
            + "; ".join(str(value) for value in runtime_stop["errors"])
        )

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
            application = apply_reviewed_memory_cleanup(
                conn,
                plan=plan,
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
                    max_events=128,
                    max_attempts=3,
                )
            projection_runs.append(projection)
            freshness = dict(projection.get("freshness") or {})
            if int(freshness.get("backlog") or 0) == 0 and bool(freshness.get("fresh")):
                break
            if (
                int(freshness.get("backlog") or 0) > 0
                and int(freshness.get("readyBacklog") or 0) == 0
            ):
                time.sleep(1.1)
        else:
            with sqlite3.connect(output) as conn:
                conn.row_factory = sqlite3.Row
                projection_errors = [
                    dict(row)
                    for row in conn.execute(
                        """SELECT outbox_id, projection_kind, state, attempts, last_error
                           FROM memory_projection_outbox
                           WHERE state IN ('failed', 'dead')
                           ORDER BY outbox_id DESC LIMIT 8"""
                    ).fetchall()
                ]
            raise RuntimeError(
                "memory projections did not converge: "
                + json.dumps(
                    {
                        "freshness": dict(projection_runs[-1].get("freshness") or {}),
                        "errors": projection_errors,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

        with sqlite3.connect(output) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            cleanup_verification = verify_reviewed_memory_cleanup(conn, plan=plan)
            semantic_verification = verify_semantic_memory_database(
                conn,
                project=str(plan.get("project") or ""),
                provider_fingerprint=provider_fingerprint,
                require_vector_freshness=True,
            )
            smoke = _run_smoke_queries(
                conn,
                plan=plan,
                embedding_provider=provider,
            )
        if not bool(cleanup_verification["ok"]):
            raise RuntimeError(
                "cleanup verification failed: "
                + "; ".join(str(value) for value in cleanup_verification["errors"])
            )
        if not bool(semantic_verification["ok"]):
            raise RuntimeError(
                "semantic verification failed: "
                + "; ".join(str(value) for value in semantic_verification["errors"])
            )
        if not bool(smoke["ok"]):
            raise RuntimeError(
                "retrieval smoke verification failed: "
                + "; ".join(str(value) for value in smoke["errors"])
            )
        if _source_state(source) != source_state or _sha256_file(source) != source_sha256:
            raise RuntimeError("source database changed while candidate was being built")

        _checkpoint(output)
        candidate_sha256 = _sha256_file(output)
        report = {
            "schemaVersion": "rag-ime.reviewed-memory-cleanup-candidate.v1",
            "ok": True,
            "sourcePath": str(source),
            "sourceState": source_state,
            "sourceSha256": source_sha256,
            "planPath": str(plan_path),
            "planSha256": _sha256_file(plan_path),
            "candidatePath": str(output),
            "candidateSha256": candidate_sha256,
            "providerFingerprint": provider_fingerprint,
            "project": str(plan.get("project") or ""),
            "runtimeStopVerification": runtime_stop,
            "application": application,
            "projectionRuns": projection_runs,
            "cleanupVerification": cleanup_verification,
            "verification": semantic_verification,
            "retrievalSmoke": smoke,
        }
        _write_json(report_path, report)
        print(
            json.dumps(
                {
                    "ok": True,
                    "sourcePath": str(source),
                    "candidatePath": str(output),
                    "reportPath": str(report_path),
                    "candidateSha256": candidate_sha256,
                    "beforeCounts": application["beforeCounts"],
                    "afterCounts": application["afterCounts"],
                    "sourceDispositions": application["sourceDispositions"],
                    "verification": {
                        "ok": semantic_verification["ok"],
                        "activationEligible": semantic_verification[
                            "activationEligible"
                        ],
                        "expectedRetrievalDocuments": semantic_verification[
                            "expectedRetrievalDocuments"
                        ],
                        "activeRetrievalDocuments": semantic_verification[
                            "activeRetrievalDocuments"
                        ],
                        "projectionFreshness": semantic_verification[
                            "projectionFreshness"
                        ],
                    },
                    "retrievalSmoke": smoke,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception:
        _remove_sqlite_files(output)
        report_path.unlink(missing_ok=True)
        raise


def _run_smoke_queries(
    conn: sqlite3.Connection,
    *,
    plan: dict[str, object],
    embedding_provider: object,
) -> dict[str, object]:
    errors: list[str] = []
    results: list[dict[str, object]] = []
    query_count = 0
    for item in plan.get("smokeQueries") or []:
        if not isinstance(item, dict):
            continue
        query_count += 1
        query_text = str(item.get("query") or "").strip()
        expected = {str(value) for value in item.get("expectedAnySourceIds") or []}
        if not query_text:
            errors.append(f"smoke query #{query_count} has no query text")
            continue
        if not expected:
            errors.append(f"{query_text}: expectedAnySourceIds must not be empty")
            continue
        payload = retrieve_hybrid_rag_candidates(
            conn,
            HybridRagQuery(
                query_text=query_text,
                project=str(plan.get("project") or ""),
                top_k=max(5, int(item.get("topK") or 10)),
                latency_budget_ms=3_000,
            ),
            embedding_provider=embedding_provider,
        )
        top_k = max(5, int(item.get("topK") or 10))
        # ``hits`` contains every per-lane recall candidate and may include the
        # same document several times. The Agent consumes ranked ``memoryHits``;
        # validate that bounded final list instead of accepting a match hidden
        # anywhere in the much larger diagnostic recall pool.
        hits = list(payload.get("memoryHits") or [])[:top_k]
        source_ids = [str(hit.get("source_id") or "") for hit in hits]
        matched = not expected or bool(expected.intersection(source_ids))
        if not matched:
            errors.append(f"{query_text}: expected one of {sorted(expected)}, got {source_ids}")
        results.append(
            {
                "query": query_text,
                "ok": matched,
                "expectedAnySourceIds": sorted(expected),
                "sourceIds": source_ids,
                "docIds": [str(hit.get("doc_id") or "") for hit in hits],
                "scores": [float(hit.get("score") or 0.0) for hit in hits],
                "elapsedMs": int(payload.get("elapsedMs") or 0),
            }
        )
    if query_count == 0:
        errors.append("at least one retrieval smoke query is required")
    return {
        "schemaVersion": "rag-ime.reviewed-memory-cleanup-smoke.v1",
        "ok": not errors,
        "errors": errors,
        "queries": results,
    }


def _process_targets_runtime(command: str, *, database_path: Path) -> bool:
    if any(
        executable in command
        for executable in (
            "/Contents/MacOS/RagImeDesktopBridge",
            "/Contents/MacOS/RagImeVoice",
            "/Contents/MacOS/RagImeControl",
        )
    ):
        return True
    managed_paths = (
        database_path,
        database_path.parent / "app",
        database_path.parent / "components",
    )
    return any(str(candidate) in command for candidate in managed_paths)


def _runtime_stop_verification(path: Path, *, required: bool) -> dict[str, object]:
    labels = (
        "com.rag-ime.sidecar",
        "com.rag-ime.agent-gateway",
        "com.rag-ime.memory-book-maintenance",
        "com.rag-ime.mlx-predictor",
        "com.rag-ime.desktop-bridge",
        "com.rag-ime.voice",
    )
    loaded: list[str] = []
    ports: list[int] = []
    handles: list[str] = []
    processes: list[str] = []
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
                loaded.append(label)
        if shutil.which("lsof"):
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
                    ports.append(port)
            result = subprocess.run(
                ["lsof", "-nP", "--", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            handles = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()][:20]
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
            processes.extend(
                line
                for raw_line in result.stdout.splitlines()
                if (line := raw_line.strip())
                and _process_targets_runtime(line, database_path=path)
            )
    errors: list[str] = []
    if loaded:
        errors.append("loaded_launch_agents=" + ",".join(loaded))
    if ports:
        errors.append("listening_runtime_ports=" + ",".join(str(value) for value in ports))
    if handles:
        errors.append(f"database_open_handles={len(handles)}")
    if processes:
        errors.append(f"orphan_runtime_processes={len(processes)}")
    return {
        "schemaVersion": "rag-ime.runtime-stop-verification.v1",
        "required": required,
        "ok": not errors,
        "targetPath": str(path),
        "loadedLaunchAgents": loaded,
        "listeningPorts": ports,
        "databaseOpenHandles": handles,
        "orphanRuntimeProcesses": processes[:20],
        "errors": errors,
    }


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


def _checkpoint(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA synchronous = FULL")
        conn.commit()
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


def _source_state(path: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for label, candidate in (("database", path), ("wal", Path(str(path) + "-wal"))):
        if candidate.exists():
            metadata = candidate.stat()
            result[label] = {
                "size": metadata.st_size,
                "mtimeNs": metadata.st_mtime_ns,
                "inode": metadata.st_ino,
            }
        else:
            result[label] = None
    return result


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


def _reserve(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.close(descriptor)


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
