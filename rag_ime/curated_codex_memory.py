from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path

from .agent_governed_memory_tools import MemoryGovernanceProposalStore
from .db import sqlite_connection
from .agent_memory_sources import AgentMemorySourceStore
from .agent_sessions import AgentSessionStore
from .agent_tools import _approval_payload_digest
from .memory_book_lifecycle import set_memory_book_archive_status
from .memory_projection import (
    RETRIEVAL_DOCS_PROJECTION,
    enqueue_memory_projection,
    process_memory_projection_outbox,
)
from .personal_context import AgentMemoryEvidenceStore
from .retrieval_docs import rebuild_retrieval_docs
from .settings_store import ManagementSettingsStore, record_management_audit
from .text_utils import compact_whitespace


CURATED_CODEX_MEMORY_SCHEMA_VERSION = "rag-ime.curated-codex-memory.v1"
_CONFIRM_TEXT = "APPLY CURATED CODEX MEMORY"
_MEMORY_KINDS = frozenset(
    {"fact", "preference", "decision", "commitment", "project_state"}
)


def load_curated_bundle(path: str | Path) -> dict[str, object]:
    bundle_path = Path(path).expanduser()
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("curated Codex memory bundle must be a JSON object")
    if str(payload.get("schemaVersion") or "") != CURATED_CODEX_MEMORY_SCHEMA_VERSION:
        raise ValueError("unsupported curated Codex memory bundle schema")
    bundle_id = _identifier(payload.get("bundleId"), field="bundleId", maximum=180)
    project = _identifier(payload.get("project"), field="project", maximum=200)
    period = payload.get("period")
    if not isinstance(period, Mapping):
        raise ValueError("curated Codex memory bundle period is required")
    period_start = _identifier(period.get("start"), field="period.start", maximum=32)
    period_end = _identifier(period.get("end"), field="period.end", maximum=32)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 20:
        raise ValueError("curated Codex memory bundle must contain 1 to 20 items")

    items: list[dict[str, object]] = []
    seen_claims: set[str] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, Mapping):
            raise ValueError(f"curated item {index} must be an object")
        claim_key = _identifier(
            raw.get("claimKey"),
            field=f"items[{index}].claimKey",
            maximum=240,
        )
        if claim_key in seen_claims:
            raise ValueError(f"duplicate curated claimKey: {claim_key}")
        seen_claims.add(claim_key)
        memory_kind = str(raw.get("memoryKind") or "").strip().lower()
        if memory_kind not in _MEMORY_KINDS:
            raise ValueError(f"unsupported memoryKind for {claim_key}")
        text = compact_whitespace(str(raw.get("text") or ""))
        if not text or len(text) > 1_200:
            raise ValueError(f"curated memory text is invalid for {claim_key}")
        source_refs = _source_refs(raw.get("sourceRefs"), claim_key=claim_key)
        items.append(
            {
                "claimKey": claim_key,
                "memoryKind": memory_kind,
                "text": text,
                "sourceRefs": source_refs,
            }
        )
    normalized = {
        "schemaVersion": CURATED_CODEX_MEMORY_SCHEMA_VERSION,
        "bundleId": bundle_id,
        "project": project,
        "period": {"start": period_start, "end": period_end},
        "items": items,
    }
    normalized["bundleSha256"] = _sha256_json(normalized)
    return normalized


def plan_curated_replacement(
    db_path: str | Path,
    bundle: Mapping[str, object],
) -> dict[str, object]:
    project = str(bundle["project"])
    with _connect(db_path) as conn:
        provider_events = {
            int(row[0])
            for row in conn.execute(
                """
                SELECT input_event_id
                FROM agent_memory_sources
                WHERE json_extract(metadata_json, '$.externalProvider') = 'codex'
                """
            ).fetchall()
        }
        active_sources = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT source_id
                FROM agent_memory_sources
                WHERE status = 'active'
                  AND json_extract(metadata_json, '$.externalProvider') = 'codex'
                ORDER BY source_id
                """
            ).fetchall()
        ]
        atom_rows = conn.execute(
            """
            SELECT id, source_event_ids_json
            FROM memory_atoms
            WHERE COALESCE(scope_project, '') = ?
              AND status IN ('active', 'approved')
              AND claim_state = 'current'
            ORDER BY id
            """,
            (project,),
        ).fetchall()
        retiring_atoms: list[str] = []
        current_atom_ids = {str(row["id"]) for row in atom_rows}
        for row in atom_rows:
            event_ids = _positive_ints(row["source_event_ids_json"])
            if (
                event_ids
                and event_ids.issubset(provider_events)
                and not _atom_has_governed_evidence(conn, str(row["id"]))
            ):
                retiring_atoms.append(str(row["id"]))
        retiring_atom_set = set(retiring_atoms)
        surviving_current_atom_ids = current_atom_ids - retiring_atom_set
        book_rows = conn.execute(
            """
            SELECT book_id, source_event_ids_json, memory_atom_ids_json
            FROM memory_books
            WHERE project = ? AND status IN ('active', 'approved')
            ORDER BY book_id
            """,
            (project,),
        ).fetchall()
        retiring_books: list[str] = []
        for row in book_rows:
            event_ids = _positive_ints(row["source_event_ids_json"])
            atom_ids = _strings(row["memory_atom_ids_json"])
            if (
                event_ids
                and event_ids.issubset(provider_events)
                and not atom_ids.intersection(surviving_current_atom_ids)
            ):
                retiring_books.append(str(row["book_id"]))
        existing_claims = {
            str(row["claim_key"]): {
                "id": str(row["id"]),
                "kind": str(row["kind"]),
                "text": str(row["text"]),
            }
            for row in conn.execute(
                """
                SELECT id, kind, text, claim_key
                FROM memory_atoms
                WHERE COALESCE(scope_project, '') = ?
                  AND status IN ('active', 'approved')
                  AND claim_state = 'current' AND claim_key <> ''
                """,
                (project,),
            ).fetchall()
        }
    additions = 0
    corrections = 0
    unchanged = 0
    for item in _bundle_items(bundle):
        current = existing_claims.get(str(item["claimKey"]))
        if current is None:
            additions += 1
        elif _canonical(str(current["text"])) == _canonical(str(item["text"])):
            unchanged += 1
        else:
            corrections += 1
    return {
        "schemaVersion": CURATED_CODEX_MEMORY_SCHEMA_VERSION,
        "ok": True,
        "bundleId": str(bundle["bundleId"]),
        "bundleSha256": str(bundle["bundleSha256"]),
        "project": project,
        "activeDirectSourceCount": len(active_sources),
        "retiringAtomCount": len(retiring_atoms),
        "retiringBookCount": len(retiring_books),
        "curatedItemCount": len(_bundle_items(bundle)),
        "additionCount": additions,
        "correctionCount": corrections,
        "unchangedCount": unchanged,
        "activeDirectSourceIds": active_sources,
        "retiringAtomIds": retiring_atoms,
        "retiringBookIds": retiring_books,
    }


def backup_sqlite_database(db_path: str | Path, backup_path: str | Path) -> dict[str, object]:
    source_path = Path(db_path).expanduser()
    target_path = Path(backup_path).expanduser()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        raise FileExistsError(f"backup already exists: {target_path}")
    with sqlite_connection(source_path) as source, sqlite_connection(target_path) as target:
        source.backup(target)
        integrity = str(target.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = int(target.execute("PRAGMA foreign_key_check").fetchone() is not None)
    if integrity != "ok" or foreign_keys:
        target_path.unlink(missing_ok=True)
        raise RuntimeError("SQLite backup verification failed")
    return {
        "path": str(target_path),
        "bytes": target_path.stat().st_size,
        "sha256": _sha256_file(target_path),
        "integrity": integrity,
        "foreignKeyViolations": foreign_keys,
    }


def apply_curated_replacement(
    db_path: str | Path,
    bundle: Mapping[str, object],
    *,
    backup_path: str | Path,
    confirm_text: str,
) -> dict[str, object]:
    if confirm_text != _CONFIRM_TEXT:
        raise ValueError(f"apply requires confirmText={_CONFIRM_TEXT}")
    db = Path(db_path).expanduser()
    plan = plan_curated_replacement(db, bundle)
    backup = backup_sqlite_database(db, backup_path)
    project = str(bundle["project"])
    timestamp = int(time.time() * 1_000)

    sessions = AgentSessionStore(db)
    sessions.initialize()
    session = sessions.create(
        title="Codex 人工归纳记忆导入",
        role_id="memory-curator",
        model_profile="manual-curation",
        project_context_enabled=False,
        session_kind="subagent_runtime",
        created_at_ms=timestamp,
    )
    session_id = str(session["id"])
    evidence_store = AgentMemoryEvidenceStore(db, project=project)
    evidence_store.initialize()
    governance = MemoryGovernanceProposalStore(db, project=project)
    governance.initialize()

    cleanup_evidence = evidence_store.record(
        source_kind="user_message",
        source_id=f"curated-codex-cleanup:{bundle['bundleId']}",
        idempotency_key=f"curated-codex-cleanup:{bundle['bundleId']}",
        text=(
            "用户明确要求停止将 Codex Session 摘要直接写入长期记忆，"
            "退役由该链路独占支持的旧原子与主题书，并以人工去重后的摘要替换。"
        ),
        session_id=session_id,
        role_id="memory-curator",
        occurred_at_ms=timestamp,
        provenance={
            "sourceType": "manual_user_authorization",
            "sourceId": str(bundle["bundleId"]),
            "bundleSha256": str(bundle["bundleSha256"]),
        },
        metadata={"manualCurated": True, "cleanup": True},
    )
    cleanup_evidence_id = _stored_evidence_id(cleanup_evidence)

    source_store = AgentMemorySourceStore(db, project=project)
    expired_sources: list[str] = []
    with _connect(db) as conn:
        tiers = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT DISTINCT json_extract(metadata_json, '$.externalTier')
                FROM agent_memory_sources
                WHERE status = 'active'
                  AND json_extract(metadata_json, '$.externalProvider') = 'codex'
                ORDER BY 1
                """
            ).fetchall()
            if str(row[0] or "")
        ]
    for tier in tiers:
        expired_sources.extend(
            source_store.expire_external_summaries_not_in_refs(
                provider="codex",
                retained_external_refs=set(),
                tier=tier,
                reason_code="direct_codex_memory_import_retired",
                created_at_ms=timestamp,
            )
        )

    archived_books: list[str] = []
    with _connect(db) as conn:
        for book_id in plan["retiringBookIds"]:
            result = set_memory_book_archive_status(
                conn,
                book_id=str(book_id),
                archived=True,
                reason="direct_codex_memory_import_retired",
                actor="curated_codex_memory",
                current_ms=timestamp,
            )
            archived_books.append(str(result["book"]["id"]))
            enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="memory_book",
                aggregate_id=str(book_id),
                operation="archive_direct_codex_memory",
                project=project,
                payload={"bundleId": str(bundle["bundleId"])},
            )
        record_management_audit(
            conn,
            action="curated_codex_memory_retire_books",
            target_type="memory_book",
            target_id=str(bundle["bundleId"]),
            payload={
                "bundleSha256": str(bundle["bundleSha256"]),
                "bookIds": archived_books,
            },
            result={"archivedCount": len(archived_books)},
        )

    forgotten_atoms: list[str] = []
    for atom_id in plan["retiringAtomIds"]:
        preview = governance.preview(
            "forget_preview",
            {
                "targetId": str(atom_id),
                "reason": "旧记忆仅由已取消的 Codex 逐 Session 直灌链路支持",
                "evidenceIds": [cleanup_evidence_id],
                "idempotencyKey": (
                    f"curated-codex-retire:{bundle['bundleId']}:{atom_id}"
                )[:240],
            },
            session_id=session_id,
        )
        receipt = _approve_and_apply(
            sessions,
            governance,
            operation="forget_apply",
            proposal_id=str(preview["proposalId"]),
            session_id=session_id,
        )
        forgotten_atoms.append(str(receipt["memoryId"]))

    added_atoms: list[str] = []
    corrected_atoms: list[str] = []
    unchanged_claims: list[str] = []
    for item in _bundle_items(bundle):
        claim_key = str(item["claimKey"])
        evidence_result = evidence_store.record(
            source_kind="session_digest",
            source_id=f"curated-codex:{bundle['bundleId']}:{claim_key}",
            idempotency_key=f"curated-codex:{bundle['bundleId']}:{claim_key}",
            text=str(item["text"]),
            session_id=session_id,
            role_id="memory-curator",
            occurred_at_ms=timestamp,
            provenance={
                "sourceType": "manual_codex_memory_synthesis",
                "sourceId": str(bundle["bundleId"]),
                "sourceRefs": list(item["sourceRefs"]),
                "periodStart": str(bundle["period"]["start"]),
                "periodEnd": str(bundle["period"]["end"]),
                "bundleSha256": str(bundle["bundleSha256"]),
            },
            metadata={
                "manualCurated": True,
                "factCandidate": True,
                "claimKey": claim_key,
            },
        )
        evidence_id = _stored_evidence_id(evidence_result)
        current = _current_claim(db, project=project, claim_key=claim_key)
        if current and _canonical(str(current["text"])) == _canonical(str(item["text"])):
            unchanged_claims.append(claim_key)
            continue
        if current:
            operation = "correct_preview"
            preview_args: dict[str, object] = {
                "targetId": str(current["id"]),
                "text": str(item["text"]),
                "memoryKind": str(item["memoryKind"]),
                "reason": "人工复核后的 Codex 跨 Session 摘要更新",
                "evidenceIds": [evidence_id],
                "idempotencyKey": (
                    f"curated-codex-correct:{bundle['bundleId']}:{claim_key}"
                )[:240],
            }
            apply_operation = "correct_apply"
        else:
            operation = "remember_preview"
            preview_args = {
                "text": str(item["text"]),
                "memoryKind": str(item["memoryKind"]),
                "claimKey": claim_key,
                "reason": "人工复核后的 Codex 跨 Session 摘要",
                "evidenceIds": [evidence_id],
                "idempotencyKey": (
                    f"curated-codex-remember:{bundle['bundleId']}:{claim_key}"
                )[:240],
            }
            apply_operation = "remember_apply"
        preview = governance.preview(
            operation,
            preview_args,
            session_id=session_id,
        )
        receipt = _approve_and_apply(
            sessions,
            governance,
            operation=apply_operation,
            proposal_id=str(preview["proposalId"]),
            session_id=session_id,
        )
        if current:
            corrected_atoms.append(str(receipt["memoryId"]))
        else:
            added_atoms.append(str(receipt["memoryId"]))

    sessions.archive(session_id, updated_at_ms=int(time.time() * 1_000))
    settings_store = ManagementSettingsStore(db)
    settings = settings_store.get_settings(include_sensitive=True)
    memory = settings.get("memory") if isinstance(settings.get("memory"), Mapping) else {}
    settings_store.update_settings(
        {"memory.enabled": bool(memory.get("enabled", True))},
        updated_by="curated-codex-memory",
    )

    projection_runs: list[dict[str, object]] = []
    with _connect(db) as conn:
        rebuild_retrieval_docs(conn, project=project)
    for _ in range(16):
        with _connect(db) as conn:
            projection = process_memory_projection_outbox(conn, max_events=128)
        projection_runs.append(projection)
        if int(projection["freshness"]["readyBacklog"]) == 0:
            break
    with _connect(db) as conn:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        remaining_direct = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM agent_memory_sources
                WHERE status = 'active'
                  AND json_extract(metadata_json, '$.externalProvider') = 'codex'
                """
            ).fetchone()[0]
        )
        remaining_legacy_setting = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM management_settings
                WHERE key = 'memory' AND value_json LIKE '%codexMemory%'
                """
            ).fetchone()[0]
        )
    return {
        "schemaVersion": CURATED_CODEX_MEMORY_SCHEMA_VERSION,
        "ok": integrity == "ok" and foreign_key_violations == 0,
        "bundleId": str(bundle["bundleId"]),
        "bundleSha256": str(bundle["bundleSha256"]),
        "backup": backup,
        "plan": plan,
        "expiredDirectSourceCount": len(expired_sources),
        "archivedBookCount": len(archived_books),
        "forgottenAtomCount": len(forgotten_atoms),
        "addedAtomCount": len(added_atoms),
        "correctedAtomCount": len(corrected_atoms),
        "unchangedClaimCount": len(unchanged_claims),
        "expiredDirectSourceIds": expired_sources,
        "archivedBookIds": archived_books,
        "forgottenAtomIds": forgotten_atoms,
        "addedAtomIds": added_atoms,
        "correctedAtomIds": corrected_atoms,
        "unchangedClaimKeys": unchanged_claims,
        "remainingActiveDirectSourceCount": remaining_direct,
        "legacyCodexSettingRowCount": remaining_legacy_setting,
        "projectionRuns": projection_runs,
        "integrity": integrity,
        "foreignKeyViolations": foreign_key_violations,
    }


def _approve_and_apply(
    sessions: AgentSessionStore,
    governance: MemoryGovernanceProposalStore,
    *,
    operation: str,
    proposal_id: str,
    session_id: str,
) -> dict[str, object]:
    prepared = governance.prepare_apply(
        operation,
        proposal_id=proposal_id,
        session_id=session_id,
    )
    action_payload = dict(prepared["actionPayload"])
    base_state = dict(prepared["baseState"])
    digest = _approval_payload_digest(
        session_id=session_id,
        tool="memory",
        operation=operation,
        action_payload=action_payload,
        base_state=base_state,
    )
    approval = sessions.create_approval(
        session_id=session_id,
        tool_name="memory",
        operation=operation,
        payload_sha256=digest,
        preview={
            "title": str(prepared["title"]),
            "summary": str(prepared["summary"]),
            "operationLabel": str(prepared["operationLabel"]),
            "changes": prepared["changes"],
            "actionPayload": action_payload,
            "baseState": base_state,
        },
        risk_level="R1",
        ttl_ms=5 * 60_000,
    )
    decided = sessions.decide_approval(
        str(approval["approvalId"]),
        approved=True,
        payload_sha256=str(approval["payloadSha256"]),
        decided_by="curated-codex-memory",
    )
    receipt = governance.apply(
        operation,
        proposal_id=proposal_id,
        session_id=session_id,
        approval_id=str(decided["approvalId"]),
    )
    sessions.complete_approval(
        str(decided["approvalId"]),
        state="applied",
        receipt=receipt,
    )
    return receipt


def _current_claim(
    db_path: str | Path,
    *,
    project: str,
    claim_key: str,
) -> dict[str, object] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, kind, text, claim_key
            FROM memory_atoms
            WHERE owner_kind = 'user' AND owner_id = 'default'
              AND COALESCE(scope_project, '') = ? AND claim_key = ?
              AND status IN ('active', 'approved') AND claim_state = 'current'
            ORDER BY updated_at_ms DESC, id DESC LIMIT 1
            """,
            (project, claim_key),
        ).fetchone()
    return dict(row) if row is not None else None


def _stored_evidence_id(result: Mapping[str, object]) -> str:
    evidence = result.get("evidence")
    if not isinstance(evidence, Mapping):
        raise RuntimeError("curated memory evidence was not stored")
    evidence_id = compact_whitespace(str(evidence.get("evidenceId") or ""))
    if not evidence_id:
        raise RuntimeError("curated memory evidence is missing its ID")
    return evidence_id


def _atom_has_governed_evidence(conn: sqlite3.Connection, atom_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM memory_atom_evidence_links WHERE memory_atom_id = ? LIMIT 1",
            (atom_id,),
        ).fetchone()
        is not None
    )


def _bundle_items(bundle: Mapping[str, object]) -> list[Mapping[str, object]]:
    items = bundle.get("items")
    return [item for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []


def _positive_ints(raw: object) -> set[int]:
    try:
        values = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(values, list):
        return set()
    result: set[int] = set()
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            result.add(parsed)
    return result


def _strings(raw: object) -> set[str]:
    try:
        values = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return set()
    return {
        compact_whitespace(str(value))
        for value in values
        if compact_whitespace(str(value))
    } if isinstance(values, list) else set()


def _source_refs(value: object, *, claim_key: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"sourceRefs is required for {claim_key}")
    refs = [
        compact_whitespace(str(item))[:400]
        for item in value
        if compact_whitespace(str(item))
    ]
    refs = list(dict.fromkeys(refs))
    if not refs or len(refs) > 16:
        raise ValueError(f"sourceRefs must contain 1 to 16 entries for {claim_key}")
    return refs


def _identifier(value: object, *, field: str, maximum: int) -> str:
    normalized = compact_whitespace(str(value or ""))
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must contain 1 to {maximum} characters")
    return normalized


def _canonical(value: str) -> str:
    return compact_whitespace(unicodedata.normalize("NFKC", value)).casefold()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path).expanduser())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Retire the legacy direct Codex Session import and apply a small, "
            "human-reviewed memory bundle through governed Atom writes."
        )
    )
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--backup-path")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-text", default="")
    parser.add_argument("--report-path", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bundle = load_curated_bundle(args.bundle)
    if args.apply:
        if not args.backup_path:
            raise ValueError("--backup-path is required with --apply")
        report = apply_curated_replacement(
            args.db_path,
            bundle,
            backup_path=args.backup_path,
            confirm_text=args.confirm_text,
        )
    else:
        report = plan_curated_replacement(args.db_path, bundle)
        report["dryRun"] = True
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report_path:
        report_path = Path(args.report_path).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if bool(report.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
