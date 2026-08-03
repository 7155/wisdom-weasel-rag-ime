from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import urllib.parse
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .activity_timeline import DailyActivityTimelineStore
from .agent_memory_sources import AgentMemorySourceStore
from .db import apply_database_migrations
from .embeddings import EmbeddingProvider
from .knowledge_scope import quarantine_scope_issue
from .memory_book_compiler import (
    apply_stored_memory_book_run,
    memory_book_run_is_stale,
    memory_book_run_payload,
    update_stored_memory_book_diff,
)
from .memory_evidence_admission import (
    admitted_personal_evidence_sql,
    transition_evidence_admission,
)
from .memory_ingest import looks_sensitive
from .memory_projection import memory_projection_freshness, process_memory_projection_outbox
from .memory_projection_consistency import invalidate_superseded_atom_dependencies
from .owner_memory_curation import OwnerMemoryCurator, OwnerMemoryOrganizer
from .text_utils import compact_whitespace, now_ms


HISTORICAL_MEMORY_CURATION_SCHEMA_VERSION = "rag-ime.historical-memory-curation.v1"
HISTORICAL_PROMOTION_AUTHORIZATION = "user_authorized_full_history_v1"
HISTORICAL_MEMORY_WINDOW_MS = 24 * 60 * 60 * 1_000
DEFAULT_HISTORICAL_CURATION_INSTRUCTION = (
    "这是 Agent 记忆系统的一次完整历史迁移。用户最终发送的内容、Agent/Room 对话摘要、"
    "已应用工具回执，以及输入法或语音形成的最终输入都只是候选证据；模型输出和 Room 私有过程"
    "不能自行成为用户事实。只保留跨会话仍有价值的个人事实、稳定偏好、明确决定、长期约束、"
    "持续项目状态与仍有效计划；临时运行状态、单次按钮或页面操作、调试探针、重复残句和一次性问答"
    "不得进入长期记忆。新旧事实冲突时必须复用稳定 claimKey 让旧版本失效，不能让相互矛盾的当前"
    "Atom 并存。主题书应少而稳定，所有结论必须引用本批真实证据，并继续经过现有审核与应用流程。"
)
ATOM_FIRST_HISTORICAL_INSTRUCTION = (
    "完整重整这批已经降噪、还原成最终表达的历史 Evidence。只用一套 Evidence→Atom→Book "
    "流程：一句 Evidence 可以拆成多个彼此独立、可长期复用的 Atom，同一个 Atom 只存一次并可加入"
    "多个稳定 Book。不要先把内容分成个人记忆和工作记忆；Atom 记录最小事实、偏好、原则、要求、"
    "决定或约束，Book 自然组织主题。临时状态、一次性命令、未解决问题、重复片段和仅由时间、应用、"
    "频率推断出的内容一律忽略。新证据确实更新旧结论时使用稳定目标做 update/supersede；语义等价"
    "才 merge。只有用户明确要求忘记并且目标语义匹配时才 retract。每个保留结论必须逐字受到本批"
    " Evidence 支持，不得补写助手推断。不要因为一条输入曾被旧整理器判为非长期内容就沿用旧结论，"
    "这次要基于原 Evidence 重新判断。Book 要少而稳定，优先复用已有 Book。"
)

_TRANSIENT_STATE_RE = re.compile(
    r"(?:已暂停|已恢复|已停止|已启动|已重启|暂停成功|恢复成功|停止成功|启动成功|重启成功)",
    re.IGNORECASE,
)
_ALLOWED_DIFF_OPERATIONS = frozenset(
    {"upsert_memory_atom", "upsert_memory_book", "supersede_memory"}
)


class HistoricalMemoryCurationError(RuntimeError):
    pass


def prepare_atom_first_historical_recuration(
    db_path: str | Path,
    *,
    project: str,
    reset_run_id: str,
    preverified_schema: bool = False,
) -> dict[str, object]:
    """Return active canonical Evidence to the candidate lane, audibly.

    This is for a disposable offline candidate only. It never deletes source
    text or old Atoms. Every admission change goes through the canonical
    transition API so source projections, cursor rewinds, receipts, and a
    later forensic review remain available.
    """

    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    normalized_project = compact_whitespace(project)
    normalized_run_id = compact_whitespace(reset_run_id)
    if not normalized_run_id:
        raise ValueError("reset_run_id is required")
    with _connect(path) as conn:
        if preverified_schema:
            _verify_preverified_candidate_schema(conn)
        else:
            apply_database_migrations(conn)
        input_events_sha256_before = _table_content_sha256(conn, "input_events")
        legacy_evidence_sha256_before = _legacy_evidence_state_sha256(conn)
        promotion = _promote_recovered_user_inputs(
            conn,
            project=normalized_project,
            authorization_run_id=normalized_run_id,
            created_at_ms=now_ms(),
        )
        rows = conn.execute(
            """
            SELECT evidence.evidence_id, evidence.admission_state
            FROM agent_memory_evidence AS evidence
            WHERE evidence.status = 'active'
              AND evidence.owner_kind = 'user'
              AND evidence.owner_id = 'default'
              AND evidence.scope_mode = 'authoritative'
              AND evidence.evidence_domain = 'personal_memory'
              AND evidence.knowledge_domain = 'personal_memory'
              AND COALESCE(evidence.forgotten_at_ms, 0) = 0
              AND (? = '' OR evidence.project = ? OR evidence.project = '')
            ORDER BY evidence.occurred_at_ms, evidence.evidence_id
            """,
            (normalized_project, normalized_project),
        ).fetchall()
        before = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                """
                SELECT admission_state, COUNT(*)
                FROM agent_memory_evidence
                WHERE status = 'active' AND owner_kind = 'user'
                  AND owner_id = 'default'
                  AND evidence_domain = 'personal_memory'
                GROUP BY admission_state ORDER BY admission_state
                """
            ).fetchall()
        }
        changed = 0
        for row in rows:
            transition = transition_evidence_admission(
                conn,
                str(row["evidence_id"]),
                new_state="candidate",
                reason_code="full_history_atom_first_recuration",
                actor_kind="user",
                run_id=normalized_run_id,
                created_at_ms=now_ms(),
                metadata={
                    "source": HISTORICAL_MEMORY_CURATION_SCHEMA_VERSION,
                    "candidateOnly": True,
                },
            )
            changed += int(bool(transition.get("changed")))
        after = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                """
                SELECT admission_state, COUNT(*)
                FROM agent_memory_evidence
                WHERE status = 'active' AND owner_kind = 'user'
                  AND owner_id = 'default'
                  AND evidence_domain = 'personal_memory'
                GROUP BY admission_state ORDER BY admission_state
                """
            ).fetchall()
        }
        input_events_sha256_after = _table_content_sha256(conn, "input_events")
        if input_events_sha256_after != input_events_sha256_before:
            raise HistoricalMemoryCurationError(
                "historical reset changed immutable input_events"
            )
        legacy_evidence_sha256_after = _legacy_evidence_state_sha256(conn)
        if legacy_evidence_sha256_after != legacy_evidence_sha256_before:
            raise HistoricalMemoryCurationError(
                "historical promotion mutated recovered audit Evidence"
            )
    return {
        "schemaVersion": "rag-ime.atom-first-historical-reset.v1",
        "ok": True,
        "candidateOnly": True,
        "rawInputEventsMutated": False,
        "inputEventsSha256": input_events_sha256_after,
        "legacyEvidenceSha256": legacy_evidence_sha256_after,
        "legacyEvidenceMutated": False,
        "historicalPromotion": promotion,
        "eligibleEvidenceCount": len(rows),
        "changedEvidenceCount": changed,
        "beforeAdmissionStates": before,
        "afterAdmissionStates": after,
        "resetRunId": normalized_run_id,
    }


def resume_atom_first_historical_recuration(
    db_path: str | Path,
    *,
    source_db_path: str | Path,
    project: str,
    reset_run_id: str,
    preverified_schema: bool = False,
) -> dict[str, object]:
    """Verify an interrupted reset and resume without reopening decided Evidence.

    Historical curation can take many governed model calls.  Re-running the
    destructive reset after one accepted batch would silently discard its
    admission decisions and cursor progress.  This receipt-based path verifies
    the original reset plus both immutable source ledgers, then leaves every
    current admission state untouched.
    """

    path = Path(db_path).expanduser().resolve()
    source_path = Path(source_db_path).expanduser().resolve()
    if not path.is_file() or not source_path.is_file():
        raise FileNotFoundError(path if not path.is_file() else source_path)
    normalized_run_id = compact_whitespace(reset_run_id)
    if not normalized_run_id:
        raise ValueError("reset_run_id is required")
    with _connect(path) as conn:
        if preverified_schema:
            _verify_preverified_candidate_schema(conn)
        else:
            apply_database_migrations(conn)
        reset_rows = conn.execute(
            """
            SELECT event_id, evidence_id, previous_state, new_state,
                   reason_code, run_id, created_at_ms
            FROM memory_evidence_admission_events
            WHERE run_id = ?
              AND reason_code = 'full_history_atom_first_recuration'
            ORDER BY created_at_ms, event_id
            """,
            (normalized_run_id,),
        ).fetchall()
        if not reset_rows:
            raise HistoricalMemoryCurationError(
                "historical resume has no auditable reset receipt"
            )
        reset_events_by_evidence: dict[str, list[sqlite3.Row]] = {}
        for row in reset_rows:
            if str(row["new_state"] or "") != "candidate":
                raise HistoricalMemoryCurationError(
                    "historical reset contains a non-candidate transition"
                )
            reset_events_by_evidence.setdefault(
                str(row["evidence_id"]), []
            ).append(row)
        duplicate_reset_ids = sorted(
            evidence_id
            for evidence_id, rows in reset_events_by_evidence.items()
            if len(rows) > 1
        )
        recovered_retry_count = 0
        if duplicate_reset_ids:
            placeholders = ",".join("?" for _ in duplicate_reset_ids)
            event_rows = conn.execute(
                f"""
                SELECT event_id, evidence_id, previous_state, new_state,
                       reason_code, run_id, created_at_ms
                FROM memory_evidence_admission_events
                WHERE evidence_id IN ({placeholders})
                ORDER BY evidence_id, created_at_ms, event_id
                """,
                tuple(duplicate_reset_ids),
            ).fetchall()
            all_events_by_evidence: dict[str, list[sqlite3.Row]] = {}
            for row in event_rows:
                all_events_by_evidence.setdefault(
                    str(row["evidence_id"]), []
                ).append(row)
            current_states = {
                str(row["evidence_id"]): str(row["admission_state"] or "")
                for row in conn.execute(
                    f"""
                    SELECT evidence_id, admission_state
                    FROM agent_memory_evidence
                    WHERE evidence_id IN ({placeholders})
                    """,
                    tuple(duplicate_reset_ids),
                ).fetchall()
            }
            for evidence_id in duplicate_reset_ids:
                reset_events = reset_events_by_evidence[evidence_id]
                first_reset_key = _admission_event_order_key(reset_events[0])
                latest_reset_key = _admission_event_order_key(reset_events[-1])
                evidence_events = all_events_by_evidence.get(evidence_id, [])
                non_reset_between = [
                    row
                    for row in evidence_events
                    if first_reset_key < _admission_event_order_key(row) < latest_reset_key
                    and not _is_historical_reset_event(
                        row,
                        reset_run_id=normalized_run_id,
                    )
                ]
                if any(
                    str(row["new_state"] or "") == "admitted"
                    for row in non_reset_between
                ):
                    raise HistoricalMemoryCurationError(
                        "historical retry reopened an already admitted Evidence"
                    )
                non_reset_after = [
                    row
                    for row in evidence_events
                    if _admission_event_order_key(row) > latest_reset_key
                    and not _is_historical_reset_event(
                        row,
                        reset_run_id=normalized_run_id,
                    )
                ]
                if non_reset_between and not non_reset_after:
                    raise HistoricalMemoryCurationError(
                        "historical retry did not restore the prior Evidence decision"
                    )
                if evidence_events:
                    latest_event = evidence_events[-1]
                    if current_states.get(evidence_id, "") != str(
                        latest_event["new_state"] or ""
                    ):
                        raise HistoricalMemoryCurationError(
                            "historical Evidence state does not match its latest receipt"
                        )
                recovered_retry_count += int(bool(non_reset_between))
        promotion_receipt_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_evidence_historical_promotion_receipts AS promotion
                JOIN agent_memory_evidence AS evidence
                  ON evidence.evidence_id = promotion.promoted_evidence_id
                 AND evidence.content_sha256 = promotion.content_sha256
                WHERE promotion.authorization_run_id = ?
                """,
                (normalized_run_id,),
            ).fetchone()[0]
        )
        promotion_event_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_evidence_admission_events
                WHERE run_id = ? AND reason_code = 'historical_promotion_created'
                """,
                (normalized_run_id,),
            ).fetchone()[0]
        )
        if promotion_receipt_count != promotion_event_count:
            raise HistoricalMemoryCurationError(
                "historical promotion receipts do not match admission receipts"
            )
        input_events_sha256 = _table_content_sha256(conn, "input_events")
        legacy_evidence_sha256 = _legacy_evidence_state_sha256(conn)

    source_uri = "file:" + urllib.parse.quote(str(source_path)) + "?mode=ro&immutable=1"
    source_conn = sqlite3.connect(source_uri, uri=True)
    source_conn.row_factory = sqlite3.Row
    try:
        source_input_events_sha256 = _table_content_sha256(
            source_conn,
            "input_events",
        )
        source_legacy_evidence_sha256 = _legacy_evidence_state_sha256(source_conn)
    finally:
        source_conn.close()
    if input_events_sha256 != source_input_events_sha256:
        raise HistoricalMemoryCurationError(
            "historical candidate input_events no longer match the recovery source"
        )
    if legacy_evidence_sha256 != source_legacy_evidence_sha256:
        raise HistoricalMemoryCurationError(
            "historical candidate legacy Evidence no longer matches the recovery source"
        )

    before: dict[str, int] = {}
    reset_after: dict[str, int] = {}
    changed = 0
    for rows in reset_events_by_evidence.values():
        row = rows[0]
        previous_state = str(row["previous_state"] or "")
        new_state = str(row["new_state"] or "")
        before[previous_state] = before.get(previous_state, 0) + 1
        reset_after[new_state] = reset_after.get(new_state, 0) + 1
        changed += int(previous_state != new_state)
    return {
        "schemaVersion": "rag-ime.atom-first-historical-reset.v1",
        "ok": True,
        "candidateOnly": True,
        "resumed": True,
        "rawInputEventsMutated": False,
        "inputEventsSha256": input_events_sha256,
        "legacyEvidenceSha256": legacy_evidence_sha256,
        "legacyEvidenceMutated": False,
        "sourceImmutableStateMatched": True,
        "historicalPromotion": {
            "schemaVersion": "rag-ime.historical-evidence-promotion.v1",
            "authorizationKind": HISTORICAL_PROMOTION_AUTHORIZATION,
            "receiptCount": promotion_receipt_count,
            "legacyEvidencePreserved": True,
            "resumed": True,
        },
        "eligibleEvidenceCount": len(reset_events_by_evidence),
        "changedEvidenceCount": changed,
        "resetReceiptCount": len(reset_rows),
        "duplicateResetEvidenceCount": len(duplicate_reset_ids),
        "recoveredRetryEvidenceCount": recovered_retry_count,
        "beforeAdmissionStates": before,
        "afterAdmissionStatesAtReset": reset_after,
        "resetRunId": normalized_run_id,
    }


def _admission_event_order_key(row: Mapping[str, object]) -> tuple[int, str]:
    return (int(row["created_at_ms"] or 0), str(row["event_id"] or ""))


def _is_historical_reset_event(
    row: Mapping[str, object],
    *,
    reset_run_id: str,
) -> bool:
    return (
        str(row["run_id"] or "") == reset_run_id
        and str(row["reason_code"] or "")
        == "full_history_atom_first_recuration"
    )


def curate_historical_memory_database(
    db_path: str | Path,
    *,
    organizer: OwnerMemoryOrganizer,
    project: str,
    timezone_name: str = "Asia/Shanghai",
    embedding_provider: EmbeddingProvider | None = None,
    max_batches: int = 512,
    max_sources: int = 64,
    auto_apply: bool = False,
    include_agent_dialogue: bool = False,
    preverified_schema: bool = False,
    approve_timelines: bool = True,
    instruction: str = DEFAULT_HISTORICAL_CURATION_INSTRUCTION,
) -> dict[str, object]:
    """Completely organize historical evidence inside an offline candidate DB.

    The caller must pass a disposable, stopped-runtime candidate. Raw input events
    remain immutable. The function only changes governed dispositions, reviewed
    Atom/Book runs, derived Timelines, and their projection outbox.
    """

    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if max_batches < 1:
        raise ValueError("max_batches must be positive")
    if max_sources < 1:
        raise ValueError("max_sources must be positive")
    normalized_project = compact_whitespace(project)
    started_at_ms = now_ms()
    with _connect(path) as conn:
        if preverified_schema:
            _verify_preverified_candidate_schema(conn)
        else:
            apply_database_migrations(conn)
        before = _database_counts(conn, project=normalized_project)

    source_store = AgentMemorySourceStore(path, project=normalized_project)
    curator = OwnerMemoryCurator(
        path,
        organizer=organizer,
        project=normalized_project,
        initial_settle_ms=0,
        daily_interval_ms=60_000,
        # This runner owns a stopped, disposable candidate.  Advancing its
        # synthetic clock by one lease per batch lets a restarted evaluation
        # reclaim a cursor left in ``running`` by SIGTERM or a lost terminal,
        # without weakening the one-hour production lease.
        running_lease_ms=60_000,
        max_sources=max_sources,
        auto_apply=auto_apply,
        include_agent_dialogue=include_agent_dialogue,
        embedding_provider=embedding_provider,
        personal_window_ms=HISTORICAL_MEMORY_WINDOW_MS,
    )
    if not preverified_schema:
        curator.initialize()

    timeline_report = _organize_historical_timelines(
        path,
        project=normalized_project,
        timezone_name=timezone_name,
        approve=approve_timelines,
        preverified_schema=preverified_schema,
    )
    reviewed_runs: list[dict[str, object]] = []
    for run_id in _draft_owner_run_ids(path, project=normalized_project):
        reviewed_runs.append(
            _review_and_apply_run(
                path,
                run_id=run_id,
                source_store=source_store,
                review_actor="historical-migration",
            )
        )

    batch_reports: list[dict[str, object]] = []
    previous_signature: tuple[object, ...] | None = None
    stalled_rounds = 0
    historical_clock_step_ms = curator.running_lease_ms + 1
    for batch_index in range(max_batches):
        batch_time_ms = started_at_ms + batch_index * historical_clock_step_ms + 1
        status = curator.status(current_ms=batch_time_ms)
        scopes = [
            dict(item)
            for item in status.get("scopes") or []
            if isinstance(item, Mapping) and int(item.get("pendingSourceCount") or 0) > 0
        ]
        if not scopes:
            break
        signature = tuple(
            (
                str(scope.get("ownerKind") or ""),
                str(scope.get("ownerId") or ""),
                int(scope.get("pendingSourceCount") or 0),
                int(dict(scope.get("lastSourceCursor") or {}).get("createdAtMs") or 0),
                str(dict(scope.get("lastSourceCursor") or {}).get("sourceId") or ""),
                str(scope.get("lastRunId") or ""),
                str(scope.get("lastRunStatus") or ""),
            )
            for scope in scopes
        )
        stalled_rounds = stalled_rounds + 1 if signature == previous_signature else 0
        previous_signature = signature
        if stalled_rounds >= 3:
            raise HistoricalMemoryCurationError(
                "historical owner curation made no progress for three rounds"
            )

        for scope in scopes:
            owner_kind = str(scope["ownerKind"])
            owner_id = str(scope["ownerId"])
            if str(scope.get("lastRunStatus") or "") == "draft":
                run_id = compact_whitespace(str(scope.get("lastRunId") or ""))
                if not run_id:
                    raise HistoricalMemoryCurationError(
                        f"owner {owner_kind}/{owner_id} has a draft without runId"
                    )
                review = _review_and_apply_run(
                    path,
                    run_id=run_id,
                    source_store=source_store,
                    review_actor="historical-migration",
                )
                reviewed_runs.append(review)
                batch_reports.append(
                    {
                        "batch": batch_index + 1,
                        "ownerKind": owner_kind,
                        "ownerId": owner_id,
                        "reusedDraft": True,
                        "review": review,
                    }
                )
                continue

            run_report = curator.run_due(
                manual=True,
                owner_kind=owner_kind,
                owner_id=owner_id,
                instruction=instruction,
                current_ms=batch_time_ms,
            )
            if not bool(run_report.get("ok")):
                raise HistoricalMemoryCurationError(
                    "historical owner curation failed: "
                    + json.dumps(run_report.get("results") or [], ensure_ascii=False)[:1200]
                )
            results = [
                dict(item)
                for item in run_report.get("results") or []
                if isinstance(item, Mapping)
            ]
            result = next(
                (
                    item
                    for item in results
                    if str(item.get("ownerKind") or "") == owner_kind
                    and str(item.get("ownerId") or "") == owner_id
                ),
                {},
            )
            _resolve_ambiguous_sources(
                source_store,
                decisions=result.get("modelDecisions"),
                run_id=str(result.get("runId") or ""),
            )
            review: dict[str, object] = {}
            if bool(result.get("reviewRequired")):
                run_id = compact_whitespace(str(result.get("runId") or ""))
                if not run_id:
                    raise HistoricalMemoryCurationError(
                        f"owner {owner_kind}/{owner_id} returned a draft without runId"
                    )
                review = _review_and_apply_run(
                    path,
                    run_id=run_id,
                    source_store=source_store,
                    review_actor="historical-migration",
                )
                reviewed_runs.append(review)
            batch_reports.append(
                {
                    "batch": batch_index + 1,
                    "ownerKind": owner_kind,
                    "ownerId": owner_id,
                    "sourceCount": int(result.get("sourceCount") or 0),
                    "logicalInputCount": int(result.get("logicalInputCount") or 0),
                    "modelSourceCount": int(result.get("modelSourceCount") or 0),
                    "runId": str(result.get("runId") or ""),
                    "reviewRequired": bool(result.get("reviewRequired")),
                    "review": review,
                }
            )
    ambiguous_report = _resolve_remaining_ambiguous_sources(
        path,
        project=normalized_project,
        source_store=source_store,
    )
    final_status = curator.status(current_ms=now_ms())
    pending_sources = int(final_status.get("pendingSourceCount") or 0)
    waiting_drafts = _draft_owner_run_ids(path, project=normalized_project)
    if pending_sources or waiting_drafts:
        raise HistoricalMemoryCurationError(
            f"historical curation incomplete: pendingSources={pending_sources}, "
            f"draftRuns={len(waiting_drafts)}"
        )

    lineage_quarantine = _quarantine_noncanonical_legacy_atoms(
        path,
        project=normalized_project,
    )
    projection_report = _drain_projections(
        path,
        embedding_provider=embedding_provider,
        preverified_schema=preverified_schema,
    )
    with _connect(path) as conn:
        after = _database_counts(conn, project=normalized_project)
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok" or foreign_keys:
        raise HistoricalMemoryCurationError(
            f"historical candidate integrity failed: {integrity}, foreignKeys={foreign_keys}"
        )

    return {
        "schemaVersion": HISTORICAL_MEMORY_CURATION_SCHEMA_VERSION,
        "ok": True,
        "databasePath": str(path),
        "project": normalized_project,
        "startedAtMs": started_at_ms,
        "finishedAtMs": now_ms(),
        "before": before,
        "after": after,
        "timelines": timeline_report,
        "batches": batch_reports,
        "reviewedRuns": reviewed_runs,
        "ambiguousSources": ambiguous_report,
        "lineageQuarantine": lineage_quarantine,
        "ownerCuration": final_status,
        "projections": projection_report,
        "integrityCheck": integrity,
        "foreignKeyViolationCount": foreign_keys,
        "policy": {
            "rawInputEventsImmutable": True,
            "candidateOnly": True,
            "reviewActor": "historical-migration",
            "transientRuntimeReceiptsRejected": True,
            "ambiguousEvidenceRetainedButNotPromoted": True,
            "automaticTimelineApproval": bool(approve_timelines),
            "autoApplyVerifiedAtomFirstRuns": bool(auto_apply),
            "agentDialogueExcluded": not bool(include_agent_dialogue),
            "preverifiedSchema": bool(preverified_schema),
        },
    }


def _verify_preverified_candidate_schema(conn: sqlite3.Connection) -> None:
    required = {
        "agent_memory_evidence",
        "agent_memory_sources",
        "input_events",
        "memory_atoms",
        "memory_books",
        "memory_curation_cursors",
        "memory_projection_outbox",
        "memory_evidence_historical_promotion_receipts",
    }
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing = sorted(required - tables)
    if missing:
        raise HistoricalMemoryCurationError(
            "preverified candidate is missing required tables: "
            + ",".join(missing)
        )
    quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
    if quick_check != "ok":
        raise HistoricalMemoryCurationError(
            f"preverified candidate quick_check failed: {quick_check}"
        )


def _quarantine_noncanonical_legacy_atoms(
    path: Path,
    *,
    project: str,
) -> dict[str, object]:
    """Retire only legacy Atoms that cannot satisfy canonical Evidence policy.

    A completed Atom-first migration cannot leave the old role-book projection
    active beside the new Evidence -> Atom -> Book owner. This candidate-only
    cutover is deliberately narrow: an Atom qualifies only when it remains in
    the legacy domain and every linked Evidence row is legacy role-book data.
    Any unsupported canonical Atom remains visible to the final invariant and
    fails acceptance instead of being hidden here.
    """

    reason_code = "historical_atom_first_noncanonical_legacy_lineage"
    timestamp = now_ms()
    with _connect(path) as conn:
        rows = conn.execute(
            f"""
            SELECT atom.id, atom.kind, atom.owner_kind, atom.owner_id,
                   atom.knowledge_domain, atom.scope_kind, atom.scope_id,
                   atom.visibility, atom.scope_mode
            FROM memory_atoms AS atom
            WHERE atom.status IN ('active', 'approved')
              AND atom.claim_state = 'current'
              AND atom.owner_kind = 'user' AND atom.owner_id = 'default'
              AND atom.knowledge_domain = 'legacy'
              AND (? = '' OR atom.scope_project = ? OR atom.scope_project = '')
              AND NOT EXISTS (
                  SELECT 1
                  FROM memory_atom_evidence_links AS legal_link
                  JOIN agent_memory_evidence AS evidence
                    ON evidence.evidence_id = legal_link.evidence_id
                  WHERE legal_link.memory_atom_id = atom.id
                    AND legal_link.relation IN ('supports', 'corrects')
                    AND {admitted_personal_evidence_sql('evidence')}
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM memory_atom_evidence_links AS legacy_link
                  JOIN agent_memory_evidence AS legacy_evidence
                    ON legacy_evidence.evidence_id = legacy_link.evidence_id
                  WHERE legacy_link.memory_atom_id = atom.id
                    AND legacy_link.relation IN ('supports', 'corrects')
                    AND NOT (
                        legacy_evidence.evidence_domain = 'role_book'
                        AND legacy_evidence.origin_kind = 'legacy_agent_event'
                        AND legacy_evidence.scope_mode = 'legacy'
                    )
              )
            ORDER BY atom.id
            """,
            (compact_whitespace(project), compact_whitespace(project)),
        ).fetchall()
        atom_ids = [str(row["id"]) for row in rows]
        if atom_ids:
            placeholders = ",".join("?" for _ in atom_ids)
            active_memberships = int(
                conn.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM memory_books AS book
                    JOIN json_each(book.memory_atom_ids_json) AS member
                      ON CAST(member.value AS TEXT) IN ({placeholders})
                    WHERE book.status IN ('active', 'approved')
                    """,
                    tuple(atom_ids),
                ).fetchone()[0]
            )
            if active_memberships:
                raise HistoricalMemoryCurationError(
                    "noncanonical legacy Atoms still belong to active Books"
                )
            for row in rows:
                quarantine_scope_issue(
                    conn,
                    source_table="memory_atoms",
                    source_id=str(row["id"]),
                    reason_code=reason_code,
                    observed_scope={
                        "kind": str(row["kind"] or ""),
                        "ownerKind": str(row["owner_kind"] or ""),
                        "ownerId": str(row["owner_id"] or ""),
                        "knowledgeDomain": str(row["knowledge_domain"] or ""),
                        "scopeKind": str(row["scope_kind"] or ""),
                        "scopeId": str(row["scope_id"] or ""),
                        "visibility": str(row["visibility"] or ""),
                        "scopeMode": str(row["scope_mode"] or ""),
                    },
                    observed_at_ms=timestamp,
                )
            conn.execute(
                f"""
                UPDATE memory_atoms
                SET status = 'hidden', claim_state = 'retracted',
                    valid_to_ms = COALESCE(valid_to_ms, ?), updated_at_ms = ?
                WHERE id IN ({placeholders})
                  AND status IN ('active', 'approved')
                  AND claim_state = 'current'
                """,
                (timestamp, timestamp, *atom_ids),
            )
            if int(conn.execute("SELECT changes()").fetchone()[0]) != len(atom_ids):
                raise HistoricalMemoryCurationError(
                    "legacy Atom lineage changed during candidate quarantine"
                )
            invalidation = invalidate_superseded_atom_dependencies(
                conn,
                atom_ids,
                timestamp=timestamp,
            )
        else:
            invalidation = {}
        total_receipts = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM knowledge_scope_quarantine
                WHERE source_table = 'memory_atoms' AND reason_code = ?
                """,
                (reason_code,),
            ).fetchone()[0]
        )
        conn.commit()
    return {
        "reasonCode": reason_code,
        "quarantinedNow": len(atom_ids),
        "totalQuarantineReceipts": total_receipts,
        "staleBookCount": len(invalidation.get("staleBookIds") or []),
        "suppressedPhraseCount": len(invalidation.get("suppressedPhraseIds") or []),
        "removedRetrievalDocumentCount": len(invalidation.get("removedDocIds") or []),
    }


def _promote_recovered_user_inputs(
    conn: sqlite3.Connection,
    *,
    project: str,
    authorization_run_id: str,
    created_at_ms: int,
) -> dict[str, object]:
    """Project recovered user inputs into canonical Evidence with receipts.

    Recovery Evidence remains audit-owned and unchanged. A prior
    ``not_for_memory`` disposition is deliberately not reused because the user
    asked Luna/max to reconsider the complete denoised history.
    """

    rows = conn.execute(
        """
        SELECT legacy.evidence_id AS legacy_evidence_id,
               legacy.project, legacy.content_text, legacy.content_sha256,
               legacy.occurred_at_ms, source.source_id,
               source.input_event_id, source.canonical_text_sha256,
               source.disposition, source.disposition_reason,
               event.committed_text
        FROM agent_memory_evidence AS legacy
        JOIN agent_memory_sources AS source
          ON source.source_id = legacy.source_id
        JOIN memory_evidence_input_event_links AS source_link
          ON source_link.evidence_id = legacy.evidence_id
         AND source_link.input_event_id = source.input_event_id
         AND source_link.relation = 'source'
        JOIN input_events AS event ON event.id = source.input_event_id
        WHERE legacy.status = 'active'
          AND legacy.origin_kind = 'legacy_untyped_input'
          AND legacy.scope_mode = 'legacy'
          AND legacy.knowledge_domain = 'legacy'
          AND legacy.trust_class = 'user_claim'
          AND COALESCE(legacy.forgotten_at_ms, 0) = 0
          AND source.status = 'active'
          AND source.owner_kind = 'user' AND source.owner_id = 'default'
          AND source.source_role = 'user'
          AND source.source_kind = 'user_final'
          AND source.trust_class = 'user_claim'
          AND (? = '' OR legacy.project = ? OR legacy.project = '')
          AND NOT EXISTS (
              SELECT 1 FROM memory_tombstones AS tombstone
              WHERE tombstone.active = 1
                AND (
                    (tombstone.target_type = 'memory_id'
                     AND tombstone.target_value IN (
                         legacy.evidence_id,
                         ('event:' || source.input_event_id)
                     ))
                    OR
                    (tombstone.target_type = 'source_event_id'
                     AND tombstone.target_value = CAST(source.input_event_id AS TEXT))
                )
          )
        ORDER BY source.created_at_ms, source.source_id
        """,
        (project, project),
    ).fetchall()
    created = 0
    reused = 0
    skipped_sensitive = 0
    timestamp = max(0, int(created_at_ms))
    for row in rows:
        canonical = str(row["committed_text"] or "")
        content_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if (
            compact_whitespace(str(row["disposition_reason"] or ""))
            == "sensitive_input"
            or looks_sensitive(canonical)
        ):
            skipped_sensitive += 1
            continue
        if not compact_whitespace(canonical):
            continue
        if (
            content_sha256 != str(row["content_sha256"])
            or content_sha256 != str(row["canonical_text_sha256"])
            or canonical != str(row["content_text"])
        ):
            raise HistoricalMemoryCurationError(
                "recovered Evidence content no longer matches its immutable source"
            )
        legacy_evidence_id = str(row["legacy_evidence_id"])
        source_id = str(row["source_id"])
        input_event_id = int(row["input_event_id"])
        identity_sha256 = hashlib.sha256(
            (
                legacy_evidence_id
                + "\0"
                + source_id
                + "\0"
                + str(input_event_id)
                + "\0"
                + content_sha256
            ).encode("utf-8")
        ).hexdigest()
        promoted_evidence_id = f"evidence:historical:{identity_sha256[:48]}"
        receipt_id = f"historical-promotion:{identity_sha256}"
        existing = conn.execute(
            """
            SELECT promotion.promoted_evidence_id, promotion.source_id,
                   promotion.input_event_id, promotion.content_sha256,
                   evidence.content_sha256 AS promoted_content_sha256
            FROM memory_evidence_historical_promotion_receipts AS promotion
            JOIN agent_memory_evidence AS evidence
              ON evidence.evidence_id = promotion.promoted_evidence_id
            WHERE promotion.legacy_evidence_id = ?
            """,
            (legacy_evidence_id,),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["promoted_evidence_id"]) != promoted_evidence_id
                or str(existing["source_id"]) != source_id
                or int(existing["input_event_id"]) != input_event_id
                or str(existing["content_sha256"]) != content_sha256
                or str(existing["promoted_content_sha256"]) != content_sha256
            ):
                raise HistoricalMemoryCurationError(
                    "existing historical promotion receipt conflicts with its source"
                )
            reused += 1
            continue

        provenance_json = json.dumps(
            {
                "sourceType": "historical_reconstructed_input",
                "legacyEvidenceId": legacy_evidence_id,
                "sourceId": source_id,
                "inputEventId": input_event_id,
                "promotionReceiptId": receipt_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        metadata_json = json.dumps(
            {
                "historicalPromotion": True,
                "previousDisposition": str(row["disposition"] or ""),
                "previousDispositionReason": str(row["disposition_reason"] or ""),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        conn.execute(
            """
            INSERT INTO agent_memory_evidence(
                evidence_id, project, role_id, session_id, source_kind,
                source_id, idempotency_key, content_text, content_sha256,
                provenance_json, metadata_json, privacy_class, status,
                occurred_at_ms, recorded_at_ms, owner_kind, owner_id,
                knowledge_domain, scope_kind, scope_id, visibility,
                authorization_revision, binding_id, scope_mode,
                evidence_domain, origin_kind, admission_state, admission_reason,
                trust_class, boundary_kind, admission_revision,
                admission_updated_at_ms
            ) VALUES (
                ?, ?, '', '', 'user_message', ?, ?, ?, ?, ?, ?, 'local',
                'active', ?, ?, 'user', 'default', 'personal_memory', 'user',
                'default', 'private', 'historical-full-history-v1', ?,
                'authoritative', 'personal_memory', 'legacy_untyped_input',
                'candidate', 'historical_promotion_created', 'user_claim',
                'historical_reconstruction', 1, ?
            )
            """,
            (
                promoted_evidence_id,
                str(row["project"] or project),
                source_id,
                f"historical-promotion:{legacy_evidence_id}",
                canonical,
                content_sha256,
                provenance_json,
                metadata_json,
                int(row["occurred_at_ms"] or 0),
                timestamp,
                receipt_id,
                timestamp,
            ),
        )
        conn.execute(
            """
            INSERT INTO memory_evidence_input_event_links(
                evidence_id, input_event_id, ordinal, relation,
                content_sha256, created_at_ms
            ) VALUES (?, ?, 0, 'source', ?, ?)
            """,
            (promoted_evidence_id, input_event_id, content_sha256, timestamp),
        )
        conn.execute(
            """
            INSERT INTO memory_evidence_historical_promotion_receipts(
                receipt_id, promoted_evidence_id, legacy_evidence_id,
                source_id, input_event_id, content_sha256,
                authorization_kind, authorization_run_id, created_at_ms,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                promoted_evidence_id,
                legacy_evidence_id,
                source_id,
                input_event_id,
                content_sha256,
                HISTORICAL_PROMOTION_AUTHORIZATION,
                authorization_run_id,
                timestamp,
                json.dumps(
                    {
                        "candidateOnly": True,
                        "legacyEvidencePreserved": True,
                        "rawInputEventsImmutable": True,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        conn.execute(
            """
            INSERT INTO memory_evidence_admission_events(
                event_id, evidence_id, previous_state, new_state, reason_code,
                actor_kind, run_id, created_at_ms, metadata_json
            ) VALUES (?, ?, '', 'candidate', 'historical_promotion_created',
                      'user', ?, ?, ?)
            """,
            (
                f"evidence-admission:historical:{identity_sha256}",
                promoted_evidence_id,
                authorization_run_id,
                timestamp,
                json.dumps(
                    {"promotionReceiptId": receipt_id},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        created += 1
    return {
        "schemaVersion": "rag-ime.historical-evidence-promotion.v1",
        "authorizationKind": HISTORICAL_PROMOTION_AUTHORIZATION,
        "scannedLegacyEvidenceCount": len(rows),
        "createdPromotedEvidenceCount": created,
        "reusedPromotedEvidenceCount": reused,
        "skippedSensitiveEvidenceCount": skipped_sensitive,
        "legacyEvidencePreserved": True,
    }


def _legacy_evidence_state_sha256(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in conn.execute(
        """
        SELECT evidence_id, project, source_id, content_sha256, status,
               owner_kind, owner_id, knowledge_domain, scope_kind, scope_id,
               visibility, authorization_revision, binding_id, scope_mode,
               evidence_domain, origin_kind, admission_state, admission_reason,
               trust_class, boundary_kind, admission_revision,
               admission_updated_at_ms, COALESCE(forgotten_at_ms, 0)
        FROM agent_memory_evidence
        WHERE origin_kind = 'legacy_untyped_input'
          AND scope_mode = 'legacy'
        ORDER BY evidence_id
        """
    ):
        digest.update(
            json.dumps(
                list(row),
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _table_content_sha256(conn: sqlite3.Connection, table: str) -> str:
    if table != "input_events":
        raise ValueError("unsupported immutable table fingerprint")
    columns = [
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(input_events)").fetchall()
    ]
    if not columns:
        raise HistoricalMemoryCurationError("input_events table is missing")
    digest = hashlib.sha256()
    for row in conn.execute(
        f"SELECT * FROM input_events ORDER BY id"  # noqa: S608 - fixed table.
    ):
        values = []
        for column in columns:
            value = row[column]
            values.append(
                {"bytes": bytes(value).hex()}
                if isinstance(value, (bytes, bytearray, memoryview))
                else value
            )
        digest.update(
            json.dumps(
                values,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _organize_historical_timelines(
    path: Path,
    *,
    project: str,
    timezone_name: str,
    approve: bool,
    preverified_schema: bool = False,
) -> dict[str, object]:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {timezone_name}") from exc
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT created_at_ms
            FROM input_events
            WHERE project = ?
            ORDER BY created_at_ms
            """,
            (project,),
        ).fetchall()
    dates = list(
        dict.fromkeys(
            datetime.fromtimestamp(int(row[0]) / 1000, timezone).date().isoformat()
            for row in rows
            if int(row[0] or 0) > 0
        )
    )
    store = DailyActivityTimelineStore(
        path,
        project=project,
        timezone_name=timezone_name,
        preverified_schema=preverified_schema,
    )
    results: list[dict[str, object]] = []
    for timeline_date in dates:
        built = store.build_draft(timeline_date)
        timeline = dict(built.get("timeline") or {})
        status = str(timeline.get("status") or built.get("status") or "")
        approved = False
        if approve and status == "draft" and timeline:
            timeline = store.approve(
                str(timeline["timelineId"]),
                expected_source_event_hash=str(timeline["sourceEventHash"]),
                approved_by="historical-migration",
                confirm_text="approve",
            )
            status = str(timeline.get("status") or "")
            approved = True
        results.append(
            {
                "date": timeline_date,
                "timelineId": str(timeline.get("timelineId") or ""),
                "status": status,
                "eventCount": int(timeline.get("eventCount") or 0),
                "taskCount": int(timeline.get("segmentCount") or 0),
                "approvedNow": approved,
            }
        )
    return {
        "dateCount": len(dates),
        "approvedNow": sum(bool(item["approvedNow"]) for item in results),
        "items": results,
    }


def _review_and_apply_run(
    path: Path,
    *,
    run_id: str,
    source_store: AgentMemorySourceStore,
    review_actor: str,
) -> dict[str, object]:
    with _connect(path) as conn:
        run = memory_book_run_payload(conn, run_id=run_id)
        if not run.get("provider"):
            raise HistoricalMemoryCurationError(f"memory run not found: {run_id}")
        if str(run.get("status") or "") != "draft":
            return {
                "runId": run_id,
                "status": str(run.get("status") or ""),
                "selectedDiffCount": 0,
                "rejectedDiffCount": 0,
                "alreadyResolved": True,
            }
        if memory_book_run_is_stale(conn, run=run):
            raise HistoricalMemoryCurationError(f"stale memory draft requires manual repair: {run_id}")
        active_atom_ids = {
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM memory_atoms WHERE status IN ('active', 'approved')"
            ).fetchall()
        }

    diffs = [dict(item) for item in run.get("diffs") or [] if isinstance(item, Mapping)]
    accepted_atom_ids = set(active_atom_ids)
    decisions: dict[int, dict[str, object]] = {}
    transient_rejected = False
    for diff in diffs:
        if str(diff.get("op") or "") != "upsert_memory_atom":
            continue
        payload = dict(diff.get("payload") or {})
        selected, reason = _review_atom_payload(payload)
        atom_id = compact_whitespace(str(payload.get("atomId") or diff.get("targetId") or ""))
        if selected and atom_id:
            accepted_atom_ids.add(atom_id)
        transient_rejected = transient_rejected or reason == "transient_runtime_state"
        decisions[int(diff["diffId"])] = {
            "selected": selected,
            "reason": reason,
            "payload": payload,
        }

    for diff in diffs:
        diff_id = int(diff["diffId"])
        if diff_id in decisions:
            continue
        operation = str(diff.get("op") or "")
        payload = dict(diff.get("payload") or {})
        if operation == "upsert_memory_book":
            selected, reason, payload = _review_book_payload(
                payload,
                accepted_atom_ids=accepted_atom_ids,
            )
        elif operation == "supersede_memory":
            selected, reason = _review_supersede_payload(
                payload,
                accepted_atom_ids=accepted_atom_ids,
            )
        else:
            selected, reason = False, "operation_not_allowed_in_owner_history"
        transient_rejected = transient_rejected or reason == "transient_runtime_state"
        decisions[diff_id] = {
            "selected": selected,
            "reason": reason,
            "payload": payload,
        }

    with _connect(path) as conn:
        for diff in diffs:
            diff_id = int(diff["diffId"])
            decision = decisions[diff_id]
            selected = bool(decision["selected"])
            payload = dict(decision["payload"])
            original_payload = dict(diff.get("payload") or {})
            if not selected or payload != original_payload:
                update_stored_memory_book_diff(
                    conn,
                    run_id=run_id,
                    diff_id=diff_id,
                    payload=payload if selected else None,
                    selected=selected,
                )
        resolved = apply_stored_memory_book_run(conn, run_id=run_id)
        metadata = dict(resolved.get("metadata") or {})
        metadata["historicalReview"] = {
            "actor": review_actor,
            "reviewedAtMs": now_ms(),
            "decisions": [
                {
                    "diffId": diff_id,
                    "selected": bool(decision["selected"]),
                    "reason": str(decision["reason"]),
                }
                for diff_id, decision in sorted(decisions.items())
            ],
        }
        conn.execute(
            "UPDATE memory_cleanup_runs SET metadata_json = ? WHERE run_id = ?",
            (json.dumps(metadata, ensure_ascii=False, sort_keys=True), run_id),
        )

    if transient_rejected:
        _mark_transient_run_sources(
            path,
            run=run,
            source_store=source_store,
            run_id=run_id,
        )
    selected_count = sum(bool(item["selected"]) for item in decisions.values())
    return {
        "runId": run_id,
        "ownerKind": str(run.get("ownerKind") or ""),
        "ownerId": str(run.get("ownerId") or ""),
        "status": str(resolved.get("status") or ""),
        "selectedDiffCount": selected_count,
        "rejectedDiffCount": len(decisions) - selected_count,
        "transientSourcesRejected": transient_rejected,
        "decisions": [
            {
                "diffId": diff_id,
                "selected": bool(decision["selected"]),
                "reason": str(decision["reason"]),
            }
            for diff_id, decision in sorted(decisions.items())
        ],
    }


def _review_atom_payload(payload: Mapping[str, object]) -> tuple[bool, str]:
    text = compact_whitespace(
        str(payload.get("canonicalText") or payload.get("text") or "")
    )
    if _TRANSIENT_STATE_RE.search(text):
        return False, "transient_runtime_state"
    if len(text) < 6:
        return False, "atom_text_too_short"
    if not _positive_ints(payload.get("sourceEventIds")):
        return False, "atom_missing_evidence"
    if _float(payload.get("confidence"), default=0.0) < 0.7:
        return False, "atom_confidence_below_0.7"
    if _float(payload.get("qualityScore"), default=0.0) < 0.65:
        return False, "atom_quality_below_0.65"
    if bool(payload.get("directCandidateAllowed")):
        return False, "atom_direct_candidate_forbidden"
    return True, "evidence_backed_stable_atom"


def _review_book_payload(
    payload: Mapping[str, object],
    *,
    accepted_atom_ids: set[str],
) -> tuple[bool, str, dict[str, object]]:
    result = dict(payload)
    text = compact_whitespace(
        " ".join(
            str(payload.get(key) or "")
            for key in ("title", "summary")
        )
    )
    if _TRANSIENT_STATE_RE.search(text):
        return False, "transient_runtime_state", result
    source_ids = _positive_ints(payload.get("sourceEventIds"))
    if not source_ids:
        return False, "book_missing_evidence", result
    if _float(payload.get("confidence"), default=0.0) < 0.7:
        return False, "book_confidence_below_0.7", result
    if _float(payload.get("qualityScore"), default=0.0) < 0.65:
        return False, "book_quality_below_0.65", result
    atom_ids = [
        atom_id
        for atom_id in _strings(payload.get("memoryAtomIds"))
        if atom_id in accepted_atom_ids
    ]
    if not atom_ids:
        return False, "book_has_no_accepted_atoms", result
    result["memoryAtomIds"] = atom_ids
    return True, "book_links_reviewed_atoms", result


def _review_supersede_payload(
    payload: Mapping[str, object],
    *,
    accepted_atom_ids: set[str],
) -> tuple[bool, str]:
    old_id = compact_whitespace(str(payload.get("oldId") or ""))
    new_id = compact_whitespace(str(payload.get("newId") or ""))
    if not old_id or not new_id or old_id == new_id:
        return False, "invalid_supersession"
    if new_id not in accepted_atom_ids:
        return False, "superseding_atom_not_accepted"
    if not _positive_ints(payload.get("sourceEventIds")):
        return False, "supersession_missing_evidence"
    return True, "evidence_backed_supersession"


def _mark_transient_run_sources(
    path: Path,
    *,
    run: Mapping[str, object],
    source_store: AgentMemorySourceStore,
    run_id: str,
) -> None:
    metadata = dict(run.get("metadata") or {})
    source_ids = _strings(metadata.get("sourceIds"))
    if not source_ids:
        return
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT s.source_id, e.committed_text
            FROM agent_memory_sources AS s
            JOIN input_events AS e ON e.id = s.input_event_id
            WHERE s.source_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
            """,
            (json.dumps(source_ids, ensure_ascii=False),),
        ).fetchall()
    for row in rows:
        if not _TRANSIENT_STATE_RE.search(compact_whitespace(str(row["committed_text"] or ""))):
            continue
        source_store.set_disposition(
            str(row["source_id"]),
            disposition="not_for_memory",
            reason_code="transient_runtime_receipt",
            actor_kind="system",
            run_id=run_id,
            metadata={"source": HISTORICAL_MEMORY_CURATION_SCHEMA_VERSION},
        )


def _resolve_ambiguous_sources(
    source_store: AgentMemorySourceStore,
    *,
    decisions: object,
    run_id: str,
) -> int:
    changed = 0
    for decision in decisions if isinstance(decisions, list) else []:
        if not isinstance(decision, Mapping) or decision.get("disposition") != "needs_review":
            continue
        for source_id in _strings(decision.get("sourceIds") or [decision.get("sourceId")]):
            transition = source_store.set_disposition(
                source_id,
                disposition="not_for_memory",
                reason_code="historical_migration_ambiguous",
                actor_kind="system",
                run_id=run_id,
                metadata={"source": HISTORICAL_MEMORY_CURATION_SCHEMA_VERSION},
            )
            changed += int(bool(transition.get("changed")))
    return changed


def _resolve_remaining_ambiguous_sources(
    path: Path,
    *,
    project: str,
    source_store: AgentMemorySourceStore,
) -> dict[str, object]:
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT s.source_id
            FROM agent_memory_sources AS s
            JOIN input_events AS e ON e.id = s.input_event_id
            WHERE s.status = 'active' AND s.disposition = 'needs_review'
              AND (? = '' OR e.project = ? OR e.project = '')
            ORDER BY s.created_at_ms, s.source_id
            """,
            (project, project),
        ).fetchall()
    changed = 0
    for row in rows:
        transition = source_store.set_disposition(
            str(row["source_id"]),
            disposition="not_for_memory",
            reason_code="historical_migration_unresolved_ambiguity",
            actor_kind="system",
            run_id="historical-migration-finalize",
            metadata={"source": HISTORICAL_MEMORY_CURATION_SCHEMA_VERSION},
        )
        changed += int(bool(transition.get("changed")))
    return {"found": len(rows), "changed": changed}


def _draft_owner_run_ids(path: Path, *, project: str) -> list[str]:
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT run_id, metadata_json
            FROM memory_cleanup_runs
            WHERE status = 'draft'
              AND run_kind IN ('daily_curation', 'manual_curation')
            ORDER BY created_at_ms, id
            """
        ).fetchall()
    result: list[str] = []
    for row in rows:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        if compact_whitespace(str(metadata.get("project") or "")) == project:
            result.append(str(row["run_id"]))
    return result


def _drain_projections(
    path: Path,
    *,
    embedding_provider: EmbeddingProvider | None,
    preverified_schema: bool = False,
) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    with _connect(path) as conn:
        for _ in range(32):
            report = process_memory_projection_outbox(
                conn,
                embedding_provider=embedding_provider,
                max_events=512,
                preverified_schema=preverified_schema,
            )
            reports.append(report)
            if int(report.get("processed") or 0) == 0:
                break
        freshness = memory_projection_freshness(
            conn,
            provider_fingerprint=str(
                getattr(embedding_provider, "fingerprint", "") or ""
            ),
        )
    if any(bool(report.get("failed")) for report in reports):
        raise HistoricalMemoryCurationError("memory projection failed during historical curation")
    if embedding_provider is not None and not bool(freshness.get("fresh")):
        raise HistoricalMemoryCurationError("memory projection is not fresh after historical curation")
    return {"runs": reports, "freshness": freshness}


def _database_counts(conn: sqlite3.Connection, *, project: str) -> dict[str, object]:
    source_dispositions = {
        str(row["disposition"]): int(row["count"])
        for row in conn.execute(
            """
            SELECT s.disposition, COUNT(*) AS count
            FROM agent_memory_sources AS s
            JOIN input_events AS e ON e.id = s.input_event_id
            WHERE (? = '' OR e.project = ? OR e.project = '')
            GROUP BY s.disposition
            """,
            (project, project),
        ).fetchall()
    }
    return {
        "inputEvents": int(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0]),
        "sourceDispositions": source_dispositions,
        "currentAtoms": int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_atoms WHERE status IN ('active', 'approved')"
            ).fetchone()[0]
        ),
        "activeBooks": int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_books WHERE status IN ('active', 'approved')"
            ).fetchone()[0]
        ),
        "approvedTimelines": int(
            conn.execute(
                "SELECT COUNT(*) FROM daily_activity_timelines WHERE status = 'approved'"
            ).fetchone()[0]
        ),
        "draftOwnerRuns": len(_draft_run_ids_in_connection(conn, project=project)),
    }


def _draft_run_ids_in_connection(conn: sqlite3.Connection, *, project: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT run_id, metadata_json
        FROM memory_cleanup_runs
        WHERE status = 'draft'
          AND run_kind IN ('daily_curation', 'manual_curation')
        """
    ).fetchall()
    result: list[str] = []
    for row in rows:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        if isinstance(metadata, Mapping) and compact_whitespace(
            str(metadata.get("project") or "")
        ) == project:
            result.append(str(row["run_id"]))
    return result


def _positive_ints(value: object) -> list[int]:
    result: list[int] = []
    for item in value if isinstance(value, list) else []:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in result:
            result.append(parsed)
    return result


def _strings(value: object) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else []
    return list(
        dict.fromkeys(
            compact_whitespace(str(item or ""))
            for item in values
            if compact_whitespace(str(item or ""))
        )
    )


def _float(value: object, *, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
