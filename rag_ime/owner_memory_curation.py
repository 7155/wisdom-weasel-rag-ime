from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from .agent_memory_sources import AgentMemorySourceStore
from .contracts.json_schema import validate_contract
from .db import apply_database_migrations
from .memory_book_compiler import (
    collapse_rime_fragment_run,
    inspect_memory_book_plan,
    memory_book_plan_from_compile_output,
    rime_fragments_belong_together,
    store_memory_book_plan,
)
from .memory_evidence_ledger import backfill_input_event_evidence
from .memory_ingest import normalize_text
from .personal_context import (
    load_activity_timeline_context,
    local_date_for_timestamp,
    local_day_bounds_ms,
)
from .sensitive_content import contains_sensitive_content
from .text_utils import compact_whitespace, stable_text_hash


OWNER_CURATION_STATUS_SCHEMA_VERSION = "rag-ime.owner-memory-curation-status.v1"
OWNER_CURATION_RUN_SCHEMA_VERSION = "rag-ime.owner-memory-curation-run.v1"
DEFAULT_DAILY_INTERVAL_MS = 24 * 60 * 60 * 1000
DEFAULT_INITIAL_SETTLE_MS = 20 * 60 * 1000
DEFAULT_RUNNING_LEASE_MS = 60 * 60 * 1000
DEFAULT_MAX_SOURCES = 64

_OWNER_KINDS = frozenset({"user", "shared", "agent", "session", "room"})
_ELIGIBLE_DISPOSITIONS = ("pending", "needs_review", "remember")
_FILLER_RE = re.compile(
    r"^(?:(?:嗯+|呃+|额+|啊+|哦+|唉+|那个|这个|然后|就是|对对对|好好好|行行行)[，。！？、,.!?\s]*)+$",
    re.IGNORECASE,
)
_RANDOM_INPUT_RE = re.compile(r"^[\W_]*$|^[a-z0-9]{1,3}$", re.IGNORECASE)
_RUNTIME_PROBE_RE = re.compile(
    r"(?:测试一下|test(?:ing)?\s*(?:123)?|hello\s*world|ceshiwendang|"
    r"wait for (?:llm|model)|只回复数字|不要调用工具)",
    re.IGNORECASE,
)


class OwnerMemoryOrganizer(Protocol):
    @property
    def provider_name(self) -> str: ...

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]: ...


class OwnerMemoryCurator:
    """Daily owner-scoped curation over final user text, receipts and compactions."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        organizer: OwnerMemoryOrganizer,
        project: str = "",
        clock_ms: Callable[[], int] | None = None,
        daily_interval_ms: int = DEFAULT_DAILY_INTERVAL_MS,
        initial_settle_ms: int = DEFAULT_INITIAL_SETTLE_MS,
        running_lease_ms: int = DEFAULT_RUNNING_LEASE_MS,
        max_sources: int = DEFAULT_MAX_SOURCES,
    ) -> None:
        self.db_path = Path(db_path)
        self.organizer = organizer
        self.project = compact_whitespace(project)
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.daily_interval_ms = max(60_000, int(daily_interval_ms))
        self.initial_settle_ms = max(0, int(initial_settle_ms))
        self.running_lease_ms = max(60_000, int(running_lease_ms))
        # The provider projection has a hard 64-input contract. Rime commits
        # are coalesced before this limit is applied, so this is a logical
        # utterance cap rather than a low-level event cap.
        self.max_sources = max(1, min(int(max_sources), 64))
        self.sources = AgentMemorySourceStore(self.db_path, project=self.project)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)
            backfill_input_event_evidence(conn, project=self.project)
        self.sources.initialize()

    def status(
        self,
        *,
        owner_kind: str = "",
        owner_id: str = "",
        current_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = self.clock_ms() if current_ms is None else max(0, int(current_ms))
        with self._connect() as conn:
            return owner_memory_curation_status(
                conn,
                project=self.project,
                current_ms=timestamp,
                initial_settle_ms=self.initial_settle_ms,
                daily_interval_ms=self.daily_interval_ms,
                running_lease_ms=self.running_lease_ms,
                owner_kind=owner_kind,
                owner_id=owner_id,
            )

    def run_due(
        self,
        *,
        manual: bool = False,
        owner_kind: str = "",
        owner_id: str = "",
        instruction: str = "",
        current_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = self.clock_ms() if current_ms is None else max(0, int(current_ms))
        with self._connect() as conn:
            backfill_input_event_evidence(conn, project=self.project)
        before = self.status(
            owner_kind=owner_kind,
            owner_id=owner_id,
            current_ms=timestamp,
        )
        results: list[dict[str, object]] = []
        for scope in before["scopes"]:
            if not isinstance(scope, dict):
                continue
            if not manual and not bool(scope.get("due")):
                continue
            results.append(
                self._run_scope(
                    owner_kind=str(scope["ownerKind"]),
                    owner_id=str(scope["ownerId"]),
                    manual=manual,
                    instruction=instruction,
                    current_ms=timestamp,
                )
            )
        after = self.status(
            owner_kind=owner_kind,
            owner_id=owner_id,
            current_ms=timestamp,
        )
        return {
            "schemaVersion": OWNER_CURATION_RUN_SCHEMA_VERSION,
            "ok": all(bool(item.get("ok")) for item in results),
            "manual": bool(manual),
            "ranScopeCount": len(results),
            "results": results,
            "status": after,
        }

    def _run_scope(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        manual: bool,
        instruction: str,
        current_ms: int,
    ) -> dict[str, object]:
        owner = _owner(owner_kind, owner_id)
        claim = self._claim_scope(
            owner_kind=owner[0],
            owner_id=owner[1],
            manual=manual,
            current_ms=current_ms,
        )
        if not claim["claimed"]:
            return {
                "ok": True,
                "ownerKind": owner[0],
                "ownerId": owner[1],
                "skipped": True,
                "reason": claim["reason"],
            }

        run_id = _owner_run_id(owner[0], owner[1], current_ms)
        try:
            with self._connect() as conn:
                bundle = _build_owner_source_bundle(
                    conn,
                    owner_kind=owner[0],
                    owner_id=owner[1],
                    project=self.project,
                    limit=self.max_sources,
                )
            inputs = [
                dict(item)
                for item in bundle.get("inputs") or []
                if isinstance(item, dict)
            ]
            if not inputs:
                self._finish_scope(
                    owner_kind=owner[0],
                    owner_id=owner[1],
                    run_id="",
                    boundary=None,
                    status="idle",
                    next_due_at_ms=current_ms + self.daily_interval_ms,
                    current_ms=current_ms,
                )
                return {
                    "ok": True,
                    "ownerKind": owner[0],
                    "ownerId": owner[1],
                    "skipped": True,
                    "reason": "no_sources",
                }

            boundary = (
                int(inputs[-1]["createdAtMs"]),
                str(inputs[-1]["sourceId"]),
            )
            deterministic: list[dict[str, object]] = []
            model_inputs: list[dict[str, object]] = []
            for item in inputs:
                rule = _deterministic_disposition(item)
                if rule is None:
                    model_inputs.append(item)
                    continue
                source_ids = _input_source_ids(item)
                transitions = [
                    self.sources.set_disposition(
                        source_id,
                        disposition="not_for_memory",
                        reason_code=rule,
                        actor_kind="rule",
                        run_id=run_id,
                        created_at_ms=current_ms,
                    )
                    for source_id in source_ids
                ]
                deterministic.append(
                    {
                        "sourceRef": item["sourceRef"],
                        "sourceId": item["sourceId"],
                        "sourceIds": source_ids,
                        "disposition": "not_for_memory",
                        "reasonCode": rule,
                        "changed": any(
                            bool(transition["changed"])
                            for transition in transitions
                        ),
                    }
                )

            compile_output: dict[str, object] = {}
            model_decisions: list[dict[str, object]] = []
            plan: dict[str, object] | None = None
            if model_inputs:
                model_bundle = {
                    **bundle,
                    "inputs": model_inputs,
                    "cursor": {
                        **dict(bundle.get("cursor") or {}),
                        "batchSourceCount": len(model_inputs),
                    },
                }
                compile_output = self.organizer.curate_owner_memory(
                    bundle=model_bundle,
                    project=self.project,
                    owner_kind=owner[0],
                    owner_id=owner[1],
                    instruction=instruction,
                )
                model_decisions = self._apply_model_decisions(
                    compile_output,
                    model_inputs=model_inputs,
                    run_id=run_id,
                    current_ms=current_ms,
                )
                needs_review_source_ids = [
                    source_id
                    for decision in model_decisions
                    if decision.get("disposition") == "needs_review"
                    for source_id in decision.get("sourceIds") or []
                    if compact_whitespace(str(source_id or ""))
                ]
                if needs_review_source_ids:
                    with self._connect() as conn:
                        boundary = _boundary_before_sources(
                            conn,
                            owner_kind=owner[0],
                            owner_id=owner[1],
                            project=self.project,
                            source_ids=needs_review_source_ids,
                            fallback=(
                                int(
                                    dict(bundle.get("cursor") or {}).get(
                                        "fromSourceCreatedAtMs"
                                    )
                                    or 0
                                ),
                                str(
                                    dict(bundle.get("cursor") or {}).get(
                                        "fromSourceId"
                                    )
                                    or ""
                                ),
                            ),
                        )
                governed = _govern_owner_compile_output(
                    {
                        **compile_output,
                        # Durable writes follow the fail-closed decisions that
                        # were actually applied to evidence, not unchecked
                        # organizer output.
                        "sourceDecisions": model_decisions,
                    },
                    bundle=model_bundle,
                    owner_kind=owner[0],
                    owner_id=owner[1],
                )
                if _has_durable_memory(governed):
                    plan = memory_book_plan_from_compile_output(
                        governed,
                        project=self.project,
                        provider=str(
                            compile_output.get("provider")
                            or getattr(self.organizer, "provider_name", "")
                        ),
                        model=str(compile_output.get("model") or ""),
                        source_bundle=model_bundle,
                        owner_kind=owner[0],
                        owner_id=owner[1],
                        run_kind="manual_curation" if manual else "daily_curation",
                    )
                    plan["runId"] = run_id
                    metadata = dict(plan.get("metadata") or {})
                    metadata.update(
                        {
                            "ownerKind": owner[0],
                            "ownerId": owner[1],
                            "runKind": (
                                "manual_curation" if manual else "daily_curation"
                            ),
                            "sourceIds": _all_input_source_ids(model_inputs),
                            "sourceDecisionCount": len(model_decisions),
                            "sourceDecisions": model_decisions,
                            "deterministicDispositionCount": len(deterministic),
                        }
                    )
                    plan["metadata"] = metadata
                    validation = inspect_memory_book_plan(plan)
                    if not validation.get("ok"):
                        raise ValueError(
                            "owner memory curation produced an invalid review plan: "
                            + json.dumps(
                                validation.get("errors") or [],
                                ensure_ascii=False,
                                sort_keys=True,
                            )[:1200]
                        )
                    with self._connect() as conn:
                        stored = store_memory_book_plan(
                            conn,
                            plan,
                            supersede_project_drafts=True,
                        )
                    run_status = "waiting_review"
                    stored_run_id = str(stored.get("runId") or run_id)
                else:
                    with self._connect() as conn:
                        _store_empty_owner_run(
                            conn,
                            run_id=run_id,
                            owner_kind=owner[0],
                            owner_id=owner[1],
                            project=self.project,
                            provider=str(
                                compile_output.get("provider")
                                or getattr(self.organizer, "provider_name", "")
                            ),
                            model=str(compile_output.get("model") or ""),
                            source_ids=_all_input_source_ids(model_inputs),
                            source_decisions=model_decisions,
                            created_at_ms=current_ms,
                            run_kind="manual_curation" if manual else "daily_curation",
                        )
                    run_status = "idle"
                    stored_run_id = run_id
            else:
                with self._connect() as conn:
                    _store_empty_owner_run(
                        conn,
                        run_id=run_id,
                        owner_kind=owner[0],
                        owner_id=owner[1],
                        project=self.project,
                        provider="rules",
                        model="",
                        source_ids=_all_input_source_ids(inputs),
                        source_decisions=deterministic,
                        created_at_ms=current_ms,
                        run_kind="manual_curation" if manual else "daily_curation",
                    )
                run_status = "idle"
                stored_run_id = run_id

            self._finish_scope(
                owner_kind=owner[0],
                owner_id=owner[1],
                run_id=stored_run_id,
                boundary=boundary,
                status=run_status,
                next_due_at_ms=current_ms + self.daily_interval_ms,
                current_ms=current_ms,
            )
            return {
                "ok": True,
                "ownerKind": owner[0],
                "ownerId": owner[1],
                "skipped": False,
                "runId": stored_run_id,
                "runStatus": run_status,
                "sourceCount": len(_all_input_source_ids(inputs)),
                "logicalInputCount": len(inputs),
                "modelSourceCount": len(_all_input_source_ids(model_inputs)),
                "deterministicDecisions": deterministic,
                "modelDecisions": model_decisions,
                "reviewRequired": run_status == "waiting_review",
                "diffCount": len(plan.get("diffs") or []) if plan is not None else 0,
            }
        except Exception as exc:
            self._fail_scope(
                owner_kind=owner[0],
                owner_id=owner[1],
                error=exc,
                current_ms=current_ms,
            )
            return {
                "ok": False,
                "ownerKind": owner[0],
                "ownerId": owner[1],
                "skipped": False,
                "error": _public_error(exc),
            }

    def _apply_model_decisions(
        self,
        compile_output: Mapping[str, object],
        *,
        model_inputs: list[dict[str, object]],
        run_id: str,
        current_ms: int,
    ) -> list[dict[str, object]]:
        sources_by_ref = {
            str(item["sourceRef"]): _input_source_ids(item)
            for item in model_inputs
        }
        decisions_by_ref: dict[str, dict[str, object]] = {}
        decisions = compile_output.get("sourceDecisions")
        for decision in decisions if isinstance(decisions, list) else []:
            if not isinstance(decision, dict):
                continue
            source_ref = compact_whitespace(str(decision.get("sourceRef") or ""))
            if source_ref not in sources_by_ref or source_ref in decisions_by_ref:
                continue
            decisions_by_ref[source_ref] = decision

        results: list[dict[str, object]] = []
        for item in model_inputs:
            source_ref = compact_whitespace(str(item.get("sourceRef") or ""))
            source_ids = sources_by_ref.get(source_ref, [])
            if not source_ids:
                continue
            decision = decisions_by_ref.get(source_ref)
            if decision is None:
                disposition = "needs_review"
                confidence = 0.0
                effective = "needs_review"
                reason = "model_decision_missing"
            else:
                disposition = compact_whitespace(
                    str(decision.get("disposition") or "")
                )
                confidence = _bounded_float(
                    decision.get("confidence"),
                    default=0.0,
                )
                if disposition == "not_for_memory" and confidence < 0.9:
                    effective = "needs_review"
                    reason = "low_confidence_not_for_memory"
                elif disposition == "remember" and confidence < 0.55:
                    effective = "needs_review"
                    reason = "low_confidence_remember"
                elif disposition in {
                    "remember",
                    "not_for_memory",
                    "needs_review",
                }:
                    effective = disposition
                    reason = compact_whitespace(
                        str(decision.get("reasonCode") or "")
                    )[:120]
                else:
                    effective = "needs_review"
                    reason = "invalid_model_disposition"
            transitions = [
                self.sources.set_disposition(
                    source_id,
                    disposition=effective,
                    reason_code=reason or "model_curation",
                    actor_kind="model",
                    run_id=run_id,
                    metadata={
                        "sourceRef": source_ref,
                        "modelDisposition": disposition,
                        "confidence": confidence,
                    },
                    created_at_ms=current_ms,
                )
                for source_id in source_ids
            ]
            results.append(
                {
                    "sourceRef": source_ref,
                    "sourceId": source_ids[-1],
                    "sourceIds": source_ids,
                    "disposition": effective,
                    "reasonCode": reason or "model_curation",
                    "confidence": confidence,
                    "changed": any(
                        bool(transition["changed"])
                        for transition in transitions
                    ),
                }
            )
        return results

    def _claim_scope(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        manual: bool,
        current_ms: int,
    ) -> dict[str, object]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT *
                FROM memory_curation_cursors
                WHERE owner_kind = ? AND owner_id = ? AND project = ? AND lane = 'daily'
                """,
                (owner_kind, owner_id, self.project),
            ).fetchone()
            run_status = _run_status(
                conn,
                str(row["last_run_id"] or "") if row is not None else "",
            )
            if row is not None and str(row["status"]) == "waiting_review" and run_status == "draft":
                conn.commit()
                return {"claimed": False, "reason": "draft_pending_review"}
            if (
                row is not None
                and str(row["status"]) == "running"
                and current_ms - int(row["updated_at_ms"] or 0) < self.running_lease_ms
            ):
                conn.commit()
                return {"claimed": False, "reason": "already_running"}
            if (
                not manual
                and row is not None
                and int(row["next_due_at_ms"] or 0) > current_ms
            ):
                conn.commit()
                return {"claimed": False, "reason": "not_due"}
            conn.execute(
                """
                INSERT INTO memory_curation_cursors(
                    owner_kind, owner_id, project, lane, status, updated_at_ms
                ) VALUES (?, ?, ?, 'daily', 'running', ?)
                ON CONFLICT(owner_kind, owner_id, project, lane) DO UPDATE SET
                    status = 'running',
                    last_error = '',
                    updated_at_ms = excluded.updated_at_ms
                """,
                (owner_kind, owner_id, self.project, current_ms),
            )
            conn.commit()
        return {"claimed": True, "reason": "manual" if manual else "due"}

    def _finish_scope(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        run_id: str,
        boundary: tuple[int, str] | None,
        status: str,
        next_due_at_ms: int,
        current_ms: int,
    ) -> None:
        boundary_ms, boundary_id = boundary or (0, "")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_curation_cursors(
                    owner_kind, owner_id, project, lane,
                    last_source_created_at_ms, last_source_id, last_run_ms,
                    last_run_id, next_due_at_ms, status, consecutive_failures,
                    last_error, updated_at_ms
                ) VALUES (?, ?, ?, 'daily', ?, ?, ?, ?, ?, ?, 0, '', ?)
                ON CONFLICT(owner_kind, owner_id, project, lane) DO UPDATE SET
                    last_source_created_at_ms = CASE
                        WHEN excluded.last_source_created_at_ms > 0
                        THEN excluded.last_source_created_at_ms
                        ELSE memory_curation_cursors.last_source_created_at_ms
                    END,
                    last_source_id = CASE
                        WHEN excluded.last_source_created_at_ms > 0
                        THEN excluded.last_source_id
                        ELSE memory_curation_cursors.last_source_id
                    END,
                    last_run_ms = excluded.last_run_ms,
                    last_run_id = excluded.last_run_id,
                    next_due_at_ms = excluded.next_due_at_ms,
                    status = excluded.status,
                    consecutive_failures = 0,
                    last_error = '',
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    owner_kind,
                    owner_id,
                    self.project,
                    boundary_ms,
                    boundary_id,
                    current_ms,
                    run_id,
                    next_due_at_ms,
                    status,
                    current_ms,
                ),
            )

    def _fail_scope(
        self,
        *,
        owner_kind: str,
        owner_id: str,
        error: BaseException,
        current_ms: int,
    ) -> None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT consecutive_failures
                FROM memory_curation_cursors
                WHERE owner_kind = ? AND owner_id = ? AND project = ? AND lane = 'daily'
                """,
                (owner_kind, owner_id, self.project),
            ).fetchone()
            failures = int(row["consecutive_failures"] or 0) + 1 if row is not None else 1
            backoff_ms = min(
                self.daily_interval_ms,
                15 * 60 * 1000 * (2 ** min(failures - 1, 6)),
            )
            conn.execute(
                """
                INSERT INTO memory_curation_cursors(
                    owner_kind, owner_id, project, lane, next_due_at_ms,
                    status, consecutive_failures, last_error, updated_at_ms
                ) VALUES (?, ?, ?, 'daily', ?, 'backoff', ?, ?, ?)
                ON CONFLICT(owner_kind, owner_id, project, lane) DO UPDATE SET
                    next_due_at_ms = excluded.next_due_at_ms,
                    status = 'backoff',
                    consecutive_failures = excluded.consecutive_failures,
                    last_error = excluded.last_error,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    owner_kind,
                    owner_id,
                    self.project,
                    current_ms + backoff_ms,
                    failures,
                    _public_error(error),
                    current_ms,
                ),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
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


def owner_memory_curation_status(
    conn: sqlite3.Connection,
    *,
    project: str,
    current_ms: int | None = None,
    initial_settle_ms: int = DEFAULT_INITIAL_SETTLE_MS,
    daily_interval_ms: int = DEFAULT_DAILY_INTERVAL_MS,
    running_lease_ms: int = DEFAULT_RUNNING_LEASE_MS,
    owner_kind: str = "",
    owner_id: str = "",
) -> dict[str, object]:
    timestamp = int(time.time() * 1000) if current_ms is None else max(0, int(current_ms))
    scopes = _owner_scope_statuses(
        conn,
        project=compact_whitespace(project),
        current_ms=timestamp,
        initial_settle_ms=max(0, int(initial_settle_ms)),
        running_lease_ms=max(60_000, int(running_lease_ms)),
        owner_kind=owner_kind,
        owner_id=owner_id,
    )
    return {
        "schemaVersion": OWNER_CURATION_STATUS_SCHEMA_VERSION,
        "ok": True,
        "project": compact_whitespace(project),
        "policy": {
            "cadence": "daily",
            "dailyIntervalMs": max(60_000, int(daily_interval_ms)),
            "sourceKinds": [
                "user_final",
                "explicit_memory",
                "tool_receipt",
                "session_compaction",
            ],
            "assistantTurnsRead": True,
            "assistantTurnsAreContextOnly": True,
            "rawScreenshotsRead": False,
            "semanticWritesRequireReview": True,
            "sourceForgettingReversible": True,
        },
        "due": any(bool(item["due"]) for item in scopes),
        "pendingSourceCount": sum(int(item["pendingSourceCount"]) for item in scopes),
        "needsReviewSourceCount": sum(
            int(item["needsReviewSourceCount"]) for item in scopes
        ),
        "scopes": scopes,
    }


def _owner_scope_statuses(
    conn: sqlite3.Connection,
    *,
    project: str,
    current_ms: int,
    initial_settle_ms: int,
    running_lease_ms: int,
    owner_kind: str = "",
    owner_id: str = "",
) -> list[dict[str, object]]:
    clauses = [
        "s.status = 'active'",
        "(? = '' OR e.project = ? OR e.project = '')",
    ]
    values: list[object] = [project, project]
    normalized_kind = compact_whitespace(owner_kind)
    normalized_id = compact_whitespace(owner_id)
    if normalized_kind:
        if normalized_kind not in _OWNER_KINDS:
            raise ValueError("unsupported memory owner kind")
        clauses.append("s.owner_kind = ?")
        values.append(normalized_kind)
    if normalized_id:
        clauses.append("s.owner_id = ?")
        values.append(normalized_id)
    rows = conn.execute(
        f"""
        SELECT s.owner_kind, s.owner_id,
               MIN(s.created_at_ms) AS first_source_ms,
               MAX(s.created_at_ms) AS last_source_ms,
               COUNT(*) AS total_source_count,
               SUM(CASE WHEN s.disposition = 'needs_review' THEN 1 ELSE 0 END)
                   AS needs_review_source_count
        FROM agent_memory_sources AS s
        JOIN input_events AS e ON e.id = s.input_event_id
        WHERE {' AND '.join(clauses)}
        GROUP BY s.owner_kind, s.owner_id
        ORDER BY s.owner_kind, s.owner_id
        """,  # noqa: S608 - clauses are fixed above.
        tuple(values),
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        kind = str(row["owner_kind"])
        identity = str(row["owner_id"])
        cursor = conn.execute(
            """
            SELECT *
            FROM memory_curation_cursors
            WHERE owner_kind = ? AND owner_id = ? AND project = ? AND lane = 'daily'
            """,
            (kind, identity, project),
        ).fetchone()
        cursor_ms = int(cursor["last_source_created_at_ms"] or 0) if cursor is not None else 0
        cursor_id = str(cursor["last_source_id"] or "") if cursor is not None else ""
        pending = _pending_source_count(
            conn,
            owner_kind=kind,
            owner_id=identity,
            project=project,
            cursor_ms=cursor_ms,
            cursor_id=cursor_id,
        )
        last_run_id = str(cursor["last_run_id"] or "") if cursor is not None else ""
        last_run_status = _run_status(conn, last_run_id)
        stored_status = str(cursor["status"] or "idle") if cursor is not None else "idle"
        waiting_review = stored_status == "waiting_review" and last_run_status == "draft"
        running = (
            stored_status == "running"
            and current_ms - int(cursor["updated_at_ms"] or 0) < running_lease_ms
            if cursor is not None
            else False
        )
        next_due = int(cursor["next_due_at_ms"] or 0) if cursor is not None else 0
        if next_due <= 0:
            next_due = int(row["first_source_ms"] or 0) + initial_settle_ms
        due = pending > 0 and not waiting_review and not running and current_ms >= next_due
        if waiting_review:
            reason = "draft_pending_review"
        elif running:
            reason = "running"
        elif pending <= 0:
            reason = "no_sources"
        elif current_ms >= next_due:
            reason = "daily"
        else:
            reason = "not_due"
        result.append(
            {
                "ownerKind": kind,
                "ownerId": identity,
                "pendingSourceCount": pending,
                "needsReviewSourceCount": int(
                    row["needs_review_source_count"] or 0
                ),
                "totalSourceCount": int(row["total_source_count"] or 0),
                "firstSourceAtMs": int(row["first_source_ms"] or 0),
                "lastSourceAtMs": int(row["last_source_ms"] or 0),
                "lastSourceCursor": {
                    "createdAtMs": cursor_ms,
                    "sourceId": cursor_id,
                },
                "lastRunAtMs": int(cursor["last_run_ms"] or 0) if cursor is not None else 0,
                "lastRunId": last_run_id,
                "lastRunStatus": last_run_status,
                "nextDueAtMs": next_due,
                "status": stored_status,
                "due": due,
                "dueReason": reason,
                "consecutiveFailures": (
                    int(cursor["consecutive_failures"] or 0) if cursor is not None else 0
                ),
                "lastError": str(cursor["last_error"] or "") if cursor is not None else "",
            }
        )
    return result


def _agent_conversation_context(
    conn: sqlite3.Connection,
    *,
    project: str,
    owner_kind: str,
    owner_id: str,
    session_ids: list[str],
    timeline_date: str,
    max_messages: int = 24,
    max_chars: int = 4_000,
) -> dict[str, object]:
    """Return bounded dialogue context without exposing evidence identifiers."""

    bounded_messages = max(1, min(int(max_messages), 24))
    char_budget = max(600, min(int(max_chars), 4_000))
    start_ms, end_ms = local_day_bounds_ms(timeline_date)
    clauses = [
        "project = ?",
        "status = 'active'",
        "occurred_at_ms >= ?",
        "occurred_at_ms < ?",
        "source_kind IN ('user_message', 'assistant_message', 'room_event')",
    ]
    params: list[object] = [project, start_ms, end_ms]
    if owner_kind == "agent":
        clauses.append("role_id = ?")
        params.append(owner_id)
    elif session_ids:
        scoped_sessions = session_ids[:64]
        clauses.append(
            f"session_id IN ({','.join('?' for _ in scoped_sessions)})"
        )
        params.extend(scoped_sessions)
    else:
        payload = _empty_agent_conversation_context(timeline_date)
        validate_contract(payload, "agent-conversation-context.v1.json")
        return payload
    params.append(80)
    rows = conn.execute(
        f"""
        SELECT source_kind, content_text, occurred_at_ms
        FROM agent_memory_evidence
        WHERE {' AND '.join(clauses)}
        ORDER BY occurred_at_ms DESC, evidence_id DESC
        LIMIT ?
        """,  # noqa: S608 - placeholders are generated, never values
        tuple(params),
    ).fetchall()
    rows = list(reversed(rows))

    messages: list[dict[str, object]] = []
    deduplicated = 0
    redacted = 0
    remaining_chars = char_budget
    last_seen: dict[tuple[str, str], int] = {}
    for row in rows:
        if len(messages) >= bounded_messages or remaining_chars <= 0:
            break
        text = compact_whitespace(str(row["content_text"] or ""))
        if not text:
            continue
        if contains_sensitive_content(text):
            redacted += 1
            continue
        source_kind = str(row["source_kind"])
        role = "assistant" if source_kind == "assistant_message" else "user"
        occurred_at_ms = int(row["occurred_at_ms"] or 0)
        key = (role, normalize_text(text))
        previous = last_seen.get(key)
        if previous is not None and occurred_at_ms - previous <= 5 * 60 * 1_000:
            deduplicated += 1
            continue
        last_seen[key] = occurred_at_ms
        bounded_text = text[: min(600, remaining_chars)]
        if not bounded_text:
            continue
        messages.append(
            {
                "role": role,
                "sourceKind": source_kind,
                "text": bounded_text,
                "occurredAtMs": occurred_at_ms,
            }
        )
        remaining_chars -= len(bounded_text)

    payload = {
        "schemaVersion": "rag-ime.agent-conversation-context.v1",
        "available": bool(messages),
        "date": timeline_date,
        "messages": messages,
        "messageCount": len(messages),
        "deduplicatedMessageCount": deduplicated,
        "redactedMessageCount": redacted,
        "corroborationOnly": True,
        "maySupportFacts": False,
    }
    validate_contract(payload, "agent-conversation-context.v1.json")
    return payload


def _empty_agent_conversation_context(timeline_date: str) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-conversation-context.v1",
        "available": False,
        "date": timeline_date,
        "messages": [],
        "messageCount": 0,
        "deduplicatedMessageCount": 0,
        "redactedMessageCount": 0,
        "corroborationOnly": True,
        "maySupportFacts": False,
    }


def _build_owner_source_bundle(
    conn: sqlite3.Connection,
    *,
    owner_kind: str,
    owner_id: str,
    project: str,
    limit: int,
) -> dict[str, object]:
    cursor = conn.execute(
        """
        SELECT last_source_created_at_ms, last_source_id
        FROM memory_curation_cursors
        WHERE owner_kind = ? AND owner_id = ? AND project = ? AND lane = 'daily'
        """,
        (owner_kind, owner_id, project),
    ).fetchone()
    cursor_ms = int(cursor["last_source_created_at_ms"] or 0) if cursor is not None else 0
    cursor_id = str(cursor["last_source_id"] or "") if cursor is not None else ""
    logical_limit = max(1, min(int(limit), 64))
    physical_limit = min(50_000, max(2_048, logical_limit * 128))
    rows = conn.execute(
        f"""
        SELECT s.*, e.committed_text, e.source AS event_source,
               e.recent_context, e.app, e.project AS event_project,
               e.context_group_id, e.context_group_level, e.tags_json
        FROM agent_memory_sources AS s
        JOIN input_events AS e ON e.id = s.input_event_id
        WHERE s.owner_kind = ? AND s.owner_id = ? AND s.status = 'active'
          AND (? = '' OR e.project = ? OR e.project = '')
          AND s.disposition IN ({','.join('?' for _ in _ELIGIBLE_DISPOSITIONS)})
          AND (
              s.created_at_ms > ?
              OR (s.created_at_ms = ? AND s.source_id > ?)
          )
        ORDER BY s.created_at_ms ASC, s.source_id ASC
        LIMIT ?
        """,
        (
            owner_kind,
            owner_id,
            project,
            project,
            *_ELIGIBLE_DISPOSITIONS,
            cursor_ms,
            cursor_ms,
            cursor_id,
            physical_limit,
        ),
    ).fetchall()
    raw_inputs: list[dict[str, object]] = []
    for row in rows:
        raw_inputs.append(
            {
                "sourceId": str(row["source_id"]),
                "sourceIds": [str(row["source_id"])],
                "sourceKind": str(row["source_kind"]),
                "trustClass": str(row["trust_class"]),
                "createdAtMs": int(row["created_at_ms"] or 0),
                "sourceEventIds": [int(row["input_event_id"])],
                "text": compact_whitespace(str(row["committed_text"] or ""))[:4000],
                "disposition": str(row["disposition"]),
                "source": str(row["event_source"] or ""),
                "recentContext": compact_whitespace(
                    str(row["recent_context"] or "")
                )[:4000],
                "app": str(row["app"] or ""),
                "project": str(row["event_project"] or ""),
                "contextGroupId": str(row["context_group_id"] or ""),
                "contextGroupLevel": str(row["context_group_level"] or "app"),
                "sourceMetadataTags": _json_strings(row["tags_json"]),
                "sessionId": str(row["session_id"] or ""),
            }
        )
    curation_date = (
        local_date_for_timestamp(int(raw_inputs[0]["createdAtMs"]))
        if raw_inputs
        else local_date_for_timestamp(0)
    )
    raw_inputs = [
        item
        for item in raw_inputs
        if local_date_for_timestamp(int(item["createdAtMs"])) == curation_date
    ]
    inputs = _coalesce_owner_inputs(raw_inputs)[:logical_limit]
    session_ids = list(
        dict.fromkeys(
            str(item.get("sessionId") or "")
            for item in raw_inputs
            if str(item.get("sessionId") or "")
        )
    )
    activity_context = load_activity_timeline_context(
        conn,
        project=project,
        timeline_date=curation_date,
    )
    conversation_context = _agent_conversation_context(
        conn,
        project=project,
        owner_kind=owner_kind,
        owner_id=owner_id,
        session_ids=session_ids,
        timeline_date=curation_date,
    )

    books = [
        {
            "bookId": str(row["book_id"]),
            "bookKey": str(row["book_key"]),
            "title": str(row["title"]),
            "summary": str(row["summary"]),
            "tags": _json_strings(row["tags_json"]),
            "sourceEventIds": _json_ints(row["source_event_ids_json"]),
            "memoryAtomIds": _json_strings(row["memory_atom_ids_json"]),
            "status": str(row["status"]),
        }
        for row in conn.execute(
            """
            SELECT *
            FROM memory_books
            WHERE owner_kind = ? AND owner_id = ?
              AND status IN ('active', 'approved', 'archived')
              AND (? = '' OR project = ? OR project = '')
            ORDER BY updated_at_ms DESC
            LIMIT 4
            """,
            (owner_kind, owner_id, project, project),
        ).fetchall()
    ]
    atoms = [
        {
            "atomId": str(row["id"]),
            "kind": str(row["kind"]),
            "canonicalText": str(row["canonical_text"] or row["text"]),
            "summary": "",
            "tags": [],
            "sourceEventIds": _json_ints(row["source_event_ids_json"]),
            "status": str(row["status"]),
        }
        for row in conn.execute(
            """
            SELECT *
            FROM memory_atoms
            WHERE owner_kind = ? AND owner_id = ? AND status = 'active'
              AND (? = '' OR scope_project = ? OR scope_project = '')
            ORDER BY updated_at_ms DESC
            LIMIT 80
            """,
            (owner_kind, owner_id, project, project),
        ).fetchall()
    ]
    display_name = owner_id
    if owner_kind == "agent":
        display_row = conn.execute(
            """
            SELECT display_name
            FROM agent_personas
            WHERE role_id = ? AND status = 'active'
            ORDER BY updated_at_ms DESC
            LIMIT 1
            """,
            (owner_id,),
        ).fetchone()
        if display_row is not None:
            display_name = compact_whitespace(str(display_row["display_name"] or "")) or owner_id
    event_ids = [
        event_id
        for item in inputs
        for event_id in item["sourceEventIds"]
        if isinstance(event_id, int)
    ]
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.owner-memory-source-bundle.v1",
        "project": project,
        "owner": {
            "kind": owner_kind,
            "id": owner_id,
            "displayName": display_name,
        },
        "inputs": inputs,
        "recentEvents": [
            {
                "eventId": int(item["sourceEventIds"][0]),
                "sourceEventIds": list(item["sourceEventIds"]),
                "createdAtMs": item["createdAtMs"],
                "text": item["text"],
                "source": item["sourceKind"],
                "project": project,
                "app": "RagImeControl",
                "contextGroupId": "",
            }
            for item in inputs
        ],
        "existingMemoryBooks": books,
        "existingMemoryAtoms": atoms,
        "activityContext": activity_context,
        "agentConversationContext": conversation_context,
        "legalContextGroupIds": [],
        # Only immutable owner inputs are legal fact evidence. Timeline and
        # conversation context intentionally expose no event/evidence ids.
        "legalSourceEventIds": event_ids,
        "cursor": {
            "fromSourceCreatedAtMs": cursor_ms,
            "fromSourceId": cursor_id,
            "toSourceCreatedAtMs": int(inputs[-1]["createdAtMs"]) if inputs else cursor_ms,
            "toSourceId": str(inputs[-1]["sourceId"]) if inputs else cursor_id,
            "fromEventId": min(event_ids, default=0),
            "toEventId": max(event_ids, default=0),
            "pendingEventCount": len(inputs),
        },
    }
    hash_payload = dict(payload)
    payload["bundleHash"] = stable_text_hash(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True)
    )
    return payload


def _coalesce_owner_inputs(
    raw_inputs: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Project low-level Rime commits into one model-facing user utterance."""

    projected: list[dict[str, object]] = []
    fragment_run: list[dict[str, object]] = []

    def flush_fragments() -> None:
        if not fragment_run:
            return
        projected.append(collapse_rime_fragment_run(fragment_run))
        fragment_run.clear()

    for item in raw_inputs:
        if str(item.get("source") or "") == "squirrel_rime_commit_burst":
            if fragment_run and not rime_fragments_belong_together(
                fragment_run[-1],
                item,
            ):
                flush_fragments()
            fragment_run.append(item)
            continue
        flush_fragments()
        projected.append(dict(item))
    flush_fragments()

    result: list[dict[str, object]] = []
    for index, item in enumerate(projected, start=1):
        source_ids = _input_source_ids(item)
        if not source_ids:
            continue
        result.append(
            {
                **item,
                "sourceRef": f"S{index}",
                # The cursor uses the last physical source in a reconstructed
                # utterance, while review/apply keeps every source id.
                "sourceId": source_ids[-1],
                "sourceIds": source_ids,
            }
        )
    return result


def _input_source_ids(item: Mapping[str, object]) -> list[str]:
    candidates = item.get("sourceIds")
    values = candidates if isinstance(candidates, list) else [item.get("sourceId")]
    return list(
        dict.fromkeys(
            compact_whitespace(str(value or ""))
            for value in values
            if compact_whitespace(str(value or ""))
        )
    )


def _all_input_source_ids(inputs: list[dict[str, object]]) -> list[str]:
    return list(
        dict.fromkeys(
            source_id
            for item in inputs
            for source_id in _input_source_ids(item)
        )
    )


def _govern_owner_compile_output(
    compile_output: Mapping[str, object],
    *,
    bundle: Mapping[str, object],
    owner_kind: str,
    owner_id: str,
) -> dict[str, object]:
    result = dict(compile_output)
    legal_event_ids = {
        int(value)
        for value in bundle.get("legalSourceEventIds") or []
        if str(value).isdigit() and int(value) > 0
    }
    remembered_refs = {
        str(item.get("sourceRef") or "")
        for item in compile_output.get("sourceDecisions") or []
        if isinstance(item, dict)
        and str(item.get("disposition") or "") == "remember"
        and _bounded_float(item.get("confidence"), default=0.0) >= 0.55
    }
    remembered_event_ids = {
        int(event_id)
        for item in bundle.get("inputs") or []
        if isinstance(item, dict) and str(item.get("sourceRef") or "") in remembered_refs
        for event_id in item.get("sourceEventIds") or []
        if str(event_id).isdigit() and int(event_id) in legal_event_ids
    }
    project = compact_whitespace(str(bundle.get("project") or ""))
    owner_hash = hashlib.sha256(
        f"{owner_kind}\0{owner_id}\0{project}".encode("utf-8")
    ).hexdigest()[:16]
    owner_book_id = f"book:owner:{owner_hash}"
    owner_book_key = f"owner-{owner_hash}"
    atoms: list[dict[str, object]] = []
    atom_ids: list[str] = []
    for item in compile_output.get("memoryAtoms") or []:
        if not isinstance(item, dict):
            continue
        canonical = compact_whitespace(
            str(item.get("canonicalText") or item.get("text") or "")
        )
        source_ids = _legal_ints(item.get("sourceEventIds"), remembered_event_ids)
        if not canonical or not source_ids:
            continue
        atom_id = (
            f"atom:{owner_hash}:"
            f"{stable_text_hash(normalize_text(canonical)).removeprefix('sha256:')[:24]}"
        )
        atom_ids.append(atom_id)
        atoms.append(
            {
                **item,
                "atomId": atom_id,
                "canonicalText": canonical,
                "summary": compact_whitespace(str(item.get("summary") or ""))[:500],
                "sourceEventIds": source_ids,
                "tags": [],
                "semanticGroupIds": [],
                "directCandidateAllowed": False,
                "ownerKind": owner_kind,
                "ownerId": owner_id,
            }
        )

    owner = bundle.get("owner") if isinstance(bundle.get("owner"), Mapping) else {}
    display_name = compact_whitespace(str(owner.get("displayName") or owner_id))
    existing_books = [
        dict(item)
        for item in bundle.get("existingMemoryBooks") or []
        if isinstance(item, dict)
    ]
    proposed_books = [
        dict(item)
        for item in compile_output.get("topicBooks") or []
        if isinstance(item, dict)
    ]
    existing_owner_book = next(
        (
            item
            for item in existing_books
            if compact_whitespace(str(item.get("bookId") or "")) == owner_book_id
            or compact_whitespace(str(item.get("bookKey") or "")) == owner_book_key
        ),
        None,
    )
    owner_book_archived = (
        compact_whitespace(str((existing_owner_book or {}).get("status") or ""))
        == "archived"
    )
    books: list[dict[str, object]] = []
    if proposed_books and not owner_book_archived:
        proposed = proposed_books[0]
        source_ids = _legal_ints(
            proposed.get("sourceEventIds"),
            remembered_event_ids,
        ) or sorted(remembered_event_ids)
        if source_ids:
            books.append(
                {
                    **proposed,
                    "bookId": owner_book_id,
                    "bookType": "topic",
                    "bookKey": owner_book_key,
                    "title": (
                        "个人长期记忆"
                        if owner_kind == "user"
                        else "共享长期记忆"
                        if owner_kind == "shared"
                        else f"{display_name} 的长期记忆"
                    ),
                    "summary": compact_whitespace(str(proposed.get("summary") or ""))[:2400],
                    "sourceEventIds": source_ids,
                    "memoryAtomIds": atom_ids,
                    "tags": [],
                    "semanticGroupIds": [],
                    "ownerKind": owner_kind,
                    "ownerId": owner_id,
                }
            )
    elif atoms and not owner_book_archived:
        source_ids = sorted(
            {
                source_id
                for atom in atoms
                for source_id in atom.get("sourceEventIds") or []
                if isinstance(source_id, int)
            }
        )
        previous_summary = compact_whitespace(
            str((existing_owner_book or {}).get("summary") or "")
        )
        atom_summary = "；".join(
            str(item["canonicalText"])
            for item in atoms
            if normalize_text(str(item["canonicalText"]))
            not in normalize_text(previous_summary)
        )
        merged_summary = "；".join(
            part
            for part in (previous_summary, atom_summary)
            if part
        )[:2400]
        books.append(
            {
                "bookId": owner_book_id,
                "bookType": "topic",
                "bookKey": owner_book_key,
                "title": (
                    "个人长期记忆"
                    if owner_kind == "user"
                    else "共享长期记忆"
                    if owner_kind == "shared"
                    else f"{display_name} 的长期记忆"
                ),
                "summary": merged_summary,
                "sourceEventIds": source_ids,
                "memoryAtomIds": atom_ids,
                "tags": [],
                "queryExpansions": [],
                "semanticGroupIds": [],
                "confidence": min(
                    (_bounded_float(item.get("confidence"), default=0.5) for item in atoms),
                    default=0.5,
                ),
                "qualityScore": 0.7,
                "ownerKind": owner_kind,
                "ownerId": owner_id,
            }
        )

    result.update(
        {
            "dailyBooks": [],
            "topicBooks": books,
            "memoryAtoms": atoms,
            "semanticGroups": [],
            "semanticTags": [],
            "tagMerges": [],
            "tagEdges": [],
            "phraseCandidates": [],
            "negativePhrases": [],
            "supersedes": [],
        }
    )
    return result


def _has_durable_memory(compile_output: Mapping[str, object]) -> bool:
    return bool(compile_output.get("topicBooks") or compile_output.get("memoryAtoms"))


def _deterministic_disposition(item: Mapping[str, object]) -> str | None:
    if compact_whitespace(str(item.get("sourceKind") or "")) != "user_final":
        return None
    text = compact_whitespace(str(item.get("text") or ""))
    if not text:
        return "empty_input"
    if _FILLER_RE.fullmatch(text):
        return "input_noise_filler"
    if len(text) <= 8 and _RANDOM_INPUT_RE.fullmatch(text):
        return "random_key_input"
    if len(text) <= 80 and _RUNTIME_PROBE_RE.search(text):
        return "runtime_probe"
    return None


def _pending_source_count(
    conn: sqlite3.Connection,
    *,
    owner_kind: str,
    owner_id: str,
    project: str,
    cursor_ms: int,
    cursor_id: str,
) -> int:
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM agent_memory_sources AS s
            JOIN input_events AS e ON e.id = s.input_event_id
            WHERE s.owner_kind = ? AND s.owner_id = ? AND s.status = 'active'
              AND (? = '' OR e.project = ? OR e.project = '')
              AND s.disposition IN ({','.join('?' for _ in _ELIGIBLE_DISPOSITIONS)})
              AND (
                  s.created_at_ms > ?
                  OR (s.created_at_ms = ? AND s.source_id > ?)
              )
            """,
            (
                owner_kind,
                owner_id,
                project,
                project,
                *_ELIGIBLE_DISPOSITIONS,
                cursor_ms,
                cursor_ms,
                cursor_id,
            ),
        ).fetchone()[0]
    )


def _boundary_before_sources(
    conn: sqlite3.Connection,
    *,
    owner_kind: str,
    owner_id: str,
    project: str,
    source_ids: list[str],
    fallback: tuple[int, str],
) -> tuple[int, str]:
    normalized_ids = list(
        dict.fromkeys(
            compact_whitespace(str(source_id or ""))
            for source_id in source_ids
            if compact_whitespace(str(source_id or ""))
        )
    )
    if not normalized_ids:
        return fallback
    target = conn.execute(
        """
        WITH selected_source_ids(source_id) AS (
            SELECT DISTINCT CAST(value AS TEXT)
            FROM json_each(?)
        )
        SELECT s.created_at_ms, s.source_id
        FROM agent_memory_sources AS s
        JOIN input_events AS e ON e.id = s.input_event_id
        JOIN selected_source_ids AS selected
          ON selected.source_id = s.source_id
        WHERE s.owner_kind = ? AND s.owner_id = ?
          AND (? = '' OR e.project = ? OR e.project = '')
        ORDER BY s.created_at_ms ASC, s.source_id ASC
        LIMIT 1
        """,
        (
            json.dumps(
                normalized_ids,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            owner_kind,
            owner_id,
            project,
            project,
        ),
    ).fetchone()
    if target is None:
        return fallback
    target_ms = int(target["created_at_ms"] or 0)
    target_id = str(target["source_id"] or "")
    previous = conn.execute(
        f"""
        SELECT s.created_at_ms, s.source_id
        FROM agent_memory_sources AS s
        JOIN input_events AS e ON e.id = s.input_event_id
        WHERE s.owner_kind = ? AND s.owner_id = ? AND s.status = 'active'
          AND (? = '' OR e.project = ? OR e.project = '')
          AND s.disposition IN ({','.join('?' for _ in _ELIGIBLE_DISPOSITIONS)})
          AND (
              s.created_at_ms < ?
              OR (s.created_at_ms = ? AND s.source_id < ?)
          )
        ORDER BY s.created_at_ms DESC, s.source_id DESC
        LIMIT 1
        """,
        (
            owner_kind,
            owner_id,
            project,
            project,
            *_ELIGIBLE_DISPOSITIONS,
            target_ms,
            target_ms,
            target_id,
        ),
    ).fetchone()
    candidate = (
        (int(previous["created_at_ms"] or 0), str(previous["source_id"] or ""))
        if previous is not None
        else (0, "")
    )
    return max(fallback, candidate)


def _store_empty_owner_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    owner_kind: str,
    owner_id: str,
    project: str,
    provider: str,
    model: str,
    source_ids: list[str],
    source_decisions: list[dict[str, object]],
    created_at_ms: int,
    run_kind: str,
) -> None:
    metadata = {
        "ownerKind": owner_kind,
        "ownerId": owner_id,
        "project": project,
        "runKind": run_kind,
        "sourceIds": source_ids,
        "sourceDecisions": source_decisions,
        "needsReviewSourceCount": sum(
            len(decision.get("sourceIds") or [decision.get("sourceId")])
            for decision in source_decisions
            if decision.get("disposition") == "needs_review"
        ),
        "curationOutcome": "no_durable_memory_changes",
    }
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_cleanup_runs(
            run_id, created_at_ms, provider, model, status, summary, metadata_json,
            owner_kind, owner_id, run_kind
        ) VALUES (?, ?, ?, ?, 'empty', ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            created_at_ms,
            provider,
            model,
            "整理完成：没有需要写入长期记忆的变更",
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            owner_kind,
            owner_id,
            run_kind,
        ),
    )


def _run_status(conn: sqlite3.Connection, run_id: str) -> str:
    if not run_id:
        return ""
    row = conn.execute(
        "SELECT status FROM memory_cleanup_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return str(row["status"] or "") if row is not None else ""


def _owner(owner_kind: object, owner_id: object) -> tuple[str, str]:
    kind = compact_whitespace(str(owner_kind or ""))
    identity = compact_whitespace(str(owner_id or ""))
    if kind not in _OWNER_KINDS:
        raise ValueError("unsupported memory owner kind")
    if not identity:
        raise ValueError("memory owner id must not be empty")
    return kind, identity


def _owner_run_id(owner_kind: str, owner_id: str, current_ms: int) -> str:
    owner_hash = hashlib.sha256(f"{owner_kind}\0{owner_id}".encode("utf-8")).hexdigest()[:10]
    return f"memory_book_owner_{current_ms}_{owner_hash}_{uuid.uuid4().hex[:8]}"


def _legal_ints(value: object, legal: set[int]) -> list[int]:
    result: list[int] = []
    for item in value if isinstance(value, list) else []:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed in legal and parsed not in result:
            result.append(parsed)
    return result


def _json_strings(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [
        compact_whitespace(str(item))
        for item in parsed
        if compact_whitespace(str(item))
    ]


def _json_ints(value: object) -> list[int]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    result: list[int] = []
    for item in parsed:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result


def _bounded_float(value: object, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _public_error(error: BaseException) -> str:
    text = compact_whitespace(str(error))
    return (text or error.__class__.__name__)[:500]
