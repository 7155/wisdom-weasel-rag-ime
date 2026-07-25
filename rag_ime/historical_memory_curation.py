from __future__ import annotations

import json
import re
import sqlite3
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
from .memory_book_compiler import (
    apply_stored_memory_book_run,
    memory_book_run_is_stale,
    memory_book_run_payload,
    update_stored_memory_book_diff,
)
from .memory_projection import memory_projection_freshness, process_memory_projection_outbox
from .owner_memory_curation import OwnerMemoryCurator, OwnerMemoryOrganizer
from .text_utils import compact_whitespace, now_ms


HISTORICAL_MEMORY_CURATION_SCHEMA_VERSION = "rag-ime.historical-memory-curation.v1"
DEFAULT_HISTORICAL_CURATION_INSTRUCTION = (
    "这是 Agent 记忆系统的一次完整历史迁移。用户最终发送的内容、Agent/Room 对话摘要、"
    "已应用工具回执，以及输入法或语音形成的最终输入都只是候选证据；模型输出和 Room 私有过程"
    "不能自行成为用户事实。只保留跨会话仍有价值的个人事实、稳定偏好、明确决定、长期约束、"
    "持续项目状态与仍有效计划；临时运行状态、单次按钮或页面操作、调试探针、重复残句和一次性问答"
    "不得进入长期记忆。新旧事实冲突时必须复用稳定 claimKey 让旧版本失效，不能让相互矛盾的当前"
    "Atom 并存。主题书应少而稳定，所有结论必须引用本批真实证据，并继续经过现有审核与应用流程。"
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


def curate_historical_memory_database(
    db_path: str | Path,
    *,
    organizer: OwnerMemoryOrganizer,
    project: str,
    timezone_name: str = "Asia/Shanghai",
    embedding_provider: EmbeddingProvider | None = None,
    max_batches: int = 512,
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
    normalized_project = compact_whitespace(project)
    started_at_ms = now_ms()
    with _connect(path) as conn:
        apply_database_migrations(conn)
        before = _database_counts(conn, project=normalized_project)

    source_store = AgentMemorySourceStore(path, project=normalized_project)
    curator = OwnerMemoryCurator(
        path,
        organizer=organizer,
        project=normalized_project,
        initial_settle_ms=0,
        daily_interval_ms=60_000,
        max_sources=64,
    )
    curator.initialize()

    timeline_report = _organize_historical_timelines(
        path,
        project=normalized_project,
        timezone_name=timezone_name,
        approve=approve_timelines,
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
    for batch_index in range(max_batches):
        status = curator.status(current_ms=started_at_ms + batch_index + 1)
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
                current_ms=started_at_ms + batch_index + 1,
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

    projection_report = _drain_projections(
        path,
        embedding_provider=embedding_provider,
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
        },
    }


def _organize_historical_timelines(
    path: Path,
    *,
    project: str,
    timezone_name: str,
    approve: bool,
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
) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    with _connect(path) as conn:
        for _ in range(32):
            report = process_memory_projection_outbox(
                conn,
                embedding_provider=embedding_provider,
                max_events=512,
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
