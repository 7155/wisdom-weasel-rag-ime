from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from typing import Protocol

from .agent_room_learning_governance import (
    LearningGovernanceError,
    RoomLearningGovernanceStore,
)


class ReflectionProvider(Protocol):
    def reflect(self, incident: Mapping[str, object], *, timeout_ms: int) -> Mapping[str, object]: ...


class RoomLearningRuntime:
    """Idempotent workers connecting Kernel evidence to candidate-only learning."""

    def __init__(
        self,
        store: RoomLearningGovernanceStore,
        *,
        reflection_provider: ReflectionProvider | None = None,
        reflection_timeout_ms: int = 5_000,
    ) -> None:
        self.store = store
        self.reflection_provider = reflection_provider
        self.reflection_timeout_ms = max(1, int(reflection_timeout_ms))

    def record_signal(
        self,
        *,
        root_id: str,
        dispatch_id: str,
        kernel_receipt_id: str,
        taxonomy: str,
        failure_signature: str,
        evidence_refs: list[str],
        observed_at_ms: int,
    ) -> dict[str, object] | None:
        with self.store._connect() as conn:
            manifest = conn.execute(
                """SELECT binding_id FROM room_v2_capability_manifests
                   WHERE root_id=? AND dispatch_id=? ORDER BY created_at_ms DESC LIMIT 1""",
                (root_id, dispatch_id),
            ).fetchone()
        binding_id = str(manifest[0]) if manifest is not None else None
        occurrence_id = _stable_id("incident-occurrence", kernel_receipt_id)
        result, created = self.store.record_incident(
            incident_id=_stable_id("incident", taxonomy, root_id, failure_signature),
            occurrence_id=occurrence_id,
            binding_id=binding_id,
            root_id=root_id,
            dispatch_id=dispatch_id,
            kernel_receipt_id=kernel_receipt_id,
            evidence_refs=evidence_refs,
            taxonomy=taxonomy,
            failure_signature=failure_signature,
            observed_at_ms=observed_at_ms,
        )
        if result is not None:
            self.enqueue_reflection(str(result["incidentId"]), now_ms=observed_at_ms)
            with self.store._connect(immediate=True) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO room_v2_incident_ingest_receipts
                       VALUES (?,?,?,?,?)""",
                    (
                        kernel_receipt_id, result["incidentId"], result["occurrenceId"],
                        "recorded", observed_at_ms,
                    ),
                )
        return {**result, "created": created} if result is not None else None

    def ingest_kernel_receipts(self, *, now_ms: int, limit: int = 50) -> int:
        with self.store._connect() as conn:
            rows = conn.execute(
                """SELECT r.*, d.dispatch_id, d.state AS dispatch_state
                   FROM room_kernel_receipts r
                   LEFT JOIN room_kernel_dispatches d
                     ON d.root_id=r.root_id
                    AND instr(r.payload_json, d.dispatch_id)>0
                   LEFT JOIN room_v2_incident_ingest_receipts seen
                     ON seen.kernel_receipt_id=r.receipt_id
                   WHERE seen.kernel_receipt_id IS NULL AND r.root_id IS NOT NULL
                   ORDER BY r.created_at_ms,r.receipt_id LIMIT ?""",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        processed = 0
        for row in rows:
            payload = _object(row["payload_json"])
            details = payload.get("details") if isinstance(payload.get("details"), Mapping) else {}
            dispatch_id = str(details.get("dispatchId") or row["dispatch_id"] or "")
            classification = _classify_receipt(str(row["receipt_kind"]), str(row["status"]), details)
            disposition = "ignored"
            incident_id: str | None = None
            occurrence_id: str | None = None
            if classification is not None and dispatch_id:
                taxonomy, signature = classification
                result = self.record_signal(
                    root_id=str(row["root_id"]), dispatch_id=dispatch_id,
                    kernel_receipt_id=str(row["receipt_id"]), taxonomy=taxonomy,
                    failure_signature=signature, evidence_refs=[str(row["receipt_id"])],
                    observed_at_ms=int(row["created_at_ms"]),
                )
                disposition = "recorded" if result is not None else "no_binding"
                if result is not None:
                    incident_id = str(result["incidentId"]); occurrence_id = str(result["occurrenceId"])
            with self.store._connect(immediate=True) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO room_v2_incident_ingest_receipts
                       VALUES (?,?,?,?,?)""",
                    (row["receipt_id"], incident_id, occurrence_id, disposition, now_ms),
                )
            processed += 1
        return processed

    def enqueue_reflection(self, incident_id: str, *, now_ms: int, max_attempts: int = 3) -> None:
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO room_v2_reflection_jobs(
                   job_id,incident_id,state,max_attempts,available_at_ms,created_at_ms,updated_at_ms)
                   VALUES (?,?,'pending',?,?,?,?)""",
                (_stable_id("reflection-job", incident_id), incident_id, max(1, min(max_attempts, 5)), now_ms, now_ms, now_ms),
            )

    def run_reflection_once(self, *, now_ms: int) -> dict[str, object] | None:
        if self.reflection_provider is None:
            return None
        with self.store._connect(immediate=True) as conn:
            job = conn.execute(
                """SELECT * FROM room_v2_reflection_jobs
                   WHERE state IN ('pending','retry_wait') AND available_at_ms<=?
                   ORDER BY created_at_ms,job_id LIMIT 1""", (now_ms,),
            ).fetchone()
            if job is None: return None
            incident = conn.execute("SELECT * FROM room_v2_incidents WHERE incident_id=?", (job["incident_id"],)).fetchone()
            if incident is None: raise LearningGovernanceError("Reflection Incident disappeared")
            incident_payload = {key: incident[key] for key in incident.keys()}
            job_payload = {key: job[key] for key in job.keys()}
            claimed_attempt = int(job["attempt_count"]) + 1
            conn.execute(
                """UPDATE room_v2_reflection_jobs
                   SET state='retry_wait',attempt_count=?,available_at_ms=?,updated_at_ms=?
                   WHERE job_id=?""",
                (
                    claimed_attempt,
                    now_ms + max(1_000, self.reflection_timeout_ms * 2),
                    now_ms,
                    job["job_id"],
                ),
            )
            job_payload["attempt_count"] = claimed_attempt
        started = time.monotonic()
        try:
            response = self.reflection_provider.reflect(incident_payload, timeout_ms=self.reflection_timeout_ms)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if elapsed_ms > self.reflection_timeout_ms: raise TimeoutError("reflection provider timeout")
            lesson = _reflection_payload(response, incident_payload)
            candidate_id = _stable_id("lesson", str(job_payload["incident_id"]), _json(lesson))
            result = self.store.nominate_lesson(
                lesson_candidate_id=candidate_id, incident_id=str(job_payload["incident_id"]),
                facts=lesson["facts"], causes=lesson["causes"],
                applicability_boundary=lesson["applicabilityBoundary"],
                counterexamples=lesson["counterexamples"], provenance=lesson["provenance"],
                nominated_by="agent:bounded-reflection",
                created_at_ms=int(job_payload["created_at_ms"]),
            )
        except Exception as exc:
            attempts = int(job_payload["attempt_count"])
            dead = attempts >= int(job_payload["max_attempts"])
            with self.store._connect(immediate=True) as conn:
                conn.execute(
                    """UPDATE room_v2_reflection_jobs SET state=?,attempt_count=?,
                       available_at_ms=?,last_error=?,updated_at_ms=? WHERE job_id=?""",
                    ("dead_letter" if dead else "retry_wait", attempts, now_ms + min(60_000, 1000 * (2 ** attempts)), f"{type(exc).__name__}: {exc}"[:500], now_ms, job_payload["job_id"]),
                )
            return {"jobId": job_payload["job_id"], "state": "dead_letter" if dead else "retry_wait", "error": str(exc)}
        with self.store._connect(immediate=True) as conn:
            conn.execute(
                """UPDATE room_v2_reflection_jobs SET state='completed',
                   lesson_candidate_id=?,last_error='',updated_at_ms=? WHERE job_id=?""",
                (result["lessonCandidateId"], now_ms, job_payload["job_id"]),
            )
        return {"jobId": job_payload["job_id"], "state": "completed", "lesson": result}

    def materialize_once(self, *, now_ms: int, fail_after_projection: bool = False) -> dict[str, object] | None:
        outbox_id = ""
        try:
            with self.store._connect(immediate=True) as conn:
                row = conn.execute(
                    """SELECT * FROM room_v2_guard_materialization_outbox
                       WHERE state='pending' ORDER BY created_at_ms,outbox_id LIMIT 1"""
                ).fetchone()
                if row is None: return None
                outbox_id = str(row["outbox_id"])
                if row["action"] == "cleanup":
                    conn.execute(
                        """UPDATE room_v2_guard_materializations SET state='tombstoned',updated_at_ms=?
                           WHERE scope_key=? AND state='active'""", (now_ms, row["scope_key"]),
                    )
                else:
                    pointer = conn.execute("SELECT * FROM room_v2_guard_active_pointers WHERE scope_key=?", (row["scope_key"],)).fetchone()
                    guard = conn.execute("SELECT * FROM room_v2_guard_candidates WHERE guard_candidate_id=?", (row["guard_candidate_id"],)).fetchone()
                    activation = conn.execute("SELECT * FROM room_v2_guard_activation_receipts WHERE activation_receipt_id=?", (pointer["activation_receipt_id"],)).fetchone() if pointer else None
                    approval = conn.execute("SELECT decision FROM room_v2_guard_approval_receipts WHERE approval_receipt_id=?", (activation["approval_receipt_id"],)).fetchone() if activation else None
                    if pointer is None or guard is None or activation is None or approval is None or approval[0] != "approve" or int(pointer["guard_epoch"]) != int(row["guard_epoch"]) or str(pointer["active_candidate_hash"]) != str(row["candidate_hash"]) or str(guard["candidate_hash"]) != str(row["candidate_hash"]):
                        raise LearningGovernanceError("Guard materialization pointer/hash/approval mismatch")
                    base = {"guardCandidateId": row["guard_candidate_id"], "guardEpoch": row["guard_epoch"], "candidateHash": row["candidate_hash"], "scope": _object(guard["scope_json"]), "condition": _object(guard["condition_json"]), "action": _object(guard["action_json"])}
                    config_hash = str(activation["signed_config_hash"])
                    surfaces = {
                        "prompt": {**base, "policyKind": "structured_prompt_guard"},
                        "skill": {**base, "policyKind": "skill_admission_guard"},
                        "tool": {**base, "policyKind": "tool_authorization_guard"},
                        "test_fixture": {**base, "policyKind": "regression_fixture", "thresholds": _object(guard["thresholds_json"])},
                    }
                    for surface, payload in surfaces.items():
                        conn.execute(
                            """INSERT INTO room_v2_guard_materializations VALUES (?,?,?,?,?,?,?,'active',?)
                               ON CONFLICT(scope_key,surface) DO UPDATE SET
                               guard_candidate_id=excluded.guard_candidate_id,guard_epoch=excluded.guard_epoch,
                               candidate_hash=excluded.candidate_hash,config_hash=excluded.config_hash,
                               payload_json=excluded.payload_json,state='active',updated_at_ms=excluded.updated_at_ms""",
                            (row["scope_key"], surface, row["guard_candidate_id"], row["guard_epoch"], row["candidate_hash"], config_hash, _json(payload), now_ms),
                        )
                if fail_after_projection: raise RuntimeError("injected materialization crash")
                conn.execute("UPDATE room_v2_guard_materialization_outbox SET state='applied',updated_at_ms=? WHERE outbox_id=?", (now_ms, row["outbox_id"]))
                return {"outboxId": str(row["outbox_id"]), "action": str(row["action"]), "state": "applied"}
        except Exception as exc:
            if outbox_id:
                with self.store._connect(immediate=True) as conn:
                    conn.execute(
                        """UPDATE room_v2_guard_materialization_outbox
                           SET attempt_count=attempt_count+1,
                               state=CASE WHEN attempt_count+1>=5 THEN 'dead_letter' ELSE state END,
                               last_error=?,updated_at_ms=? WHERE outbox_id=?""",
                        (f"{type(exc).__name__}: {exc}"[:500], now_ms, outbox_id),
                    )
            raise

    def drain_cancel_once(
        self,
        cancel_root: Callable[[Mapping[str, object]], Mapping[str, object]],
        *,
        now_ms: int,
        fail_after_effect: bool = False,
    ) -> dict[str, object] | None:
        with self.store._connect(immediate=True) as conn:
            row = conn.execute(
                """SELECT * FROM room_v2_managed_cancel_outbox
                   WHERE state='pending' OR (state='processing' AND lease_until_ms<=?)
                   ORDER BY created_at_ms,cancel_id LIMIT 1""",
                (now_ms,),
            ).fetchone()
            if row is None: return None
            item = {key: row[key] for key in row.keys()}
            conn.execute(
                """UPDATE room_v2_managed_cancel_outbox
                   SET state='processing',attempt_count=attempt_count+1,
                       lease_until_ms=?,updated_at_ms=? WHERE cancel_id=?""",
                (now_ms + 30_000, now_ms, row["cancel_id"]),
            )
        try:
            result = dict(cancel_root(item))
            if fail_after_effect:
                raise RuntimeError("injected cancel outbox crash")
            kernel = result.get("kernelReceipt") if isinstance(result.get("kernelReceipt"), Mapping) else result
            kernel_receipt_id = str(kernel.get("receiptId") or "") if isinstance(kernel, Mapping) else ""
            runtime_receipts = result.get("runtimeReceipts") if isinstance(result.get("runtimeReceipts"), list) else []
            runtime_failures = result.get("runtimeCancelFailures") if isinstance(result.get("runtimeCancelFailures"), Mapping) else {}
            kernel_details = kernel.get("details") if isinstance(kernel, Mapping) and isinstance(kernel.get("details"), Mapping) else {}
            lost_effect_receipt = bool(kernel_details.get("cancelledDispatches")) and not runtime_receipts and not runtime_failures
            final_state = "unknown" if any(runtime_failures.values()) or lost_effect_receipt else "applied"
            runtime_result = runtime_receipts or ([{"failures": dict(runtime_failures)}] if runtime_failures else [])
            with self.store._connect(immediate=True) as conn:
                conn.execute(
                    """UPDATE room_v2_managed_cancel_outbox SET state=?,lease_until_ms=0,
                       kernel_receipt_id=?,runtime_receipts_json=?,last_error='',updated_at_ms=? WHERE cancel_id=? AND state='processing'""",
                    (final_state, kernel_receipt_id, _json(runtime_result), now_ms, item["cancel_id"]),
                )
            return {"cancelId": item["cancel_id"], "state": final_state, "kernelReceiptId": kernel_receipt_id}
        except Exception as exc:
            with self.store._connect(immediate=True) as conn:
                conn.execute(
                    """UPDATE room_v2_managed_cancel_outbox SET state='pending',lease_until_ms=0,
                       last_error=?,updated_at_ms=? WHERE cancel_id=?""",
                    (f"{type(exc).__name__}: {exc}"[:500], now_ms, item["cancel_id"]),
                )
            return {"cancelId": item["cancel_id"], "state": "pending", "error": str(exc)}


def _classify_receipt(kind: str, status: str, details: Mapping[str, object]) -> tuple[str, str] | None:
    reason = str(details.get("reason") or "")
    if reason.startswith("runtime_failed:"): return "tool_failure", reason
    if status == "unknown" or kind == "dispatch_unknown": return "unknown", f"{kind}:{reason or 'runtime_result_unknown'}"
    if status == "failed" or "failed" in kind: return "tool_failure", f"{kind}:{reason or 'runtime_failure'}"
    if kind == "rollback" or "rollback" in reason: return "rollback", f"{kind}:{reason or 'rollback'}"
    if "user_correction" in kind or reason == "user_correction": return "user_correction", f"{kind}:user_correction"
    if status == "rejected": return "delivery_regression", f"near_miss:{kind}:{reason or 'rejected'}"
    return None


def _reflection_payload(value: Mapping[str, object], incident: Mapping[str, object]) -> dict[str, object]:
    expected = {"facts", "causes", "applicabilityBoundary", "counterexamples", "provenance"}
    if set(value) != expected: raise ValueError("reflection schema error")
    result = dict(value)
    for key in ("facts", "causes", "counterexamples", "provenance"):
        if not isinstance(result[key], list) or not result[key] or not all(isinstance(item, str) and item.strip() for item in result[key]): raise ValueError("reflection schema error")
    if not isinstance(result["applicabilityBoundary"], Mapping): raise ValueError("reflection schema error")
    evidence = set(json.loads(str(incident["evidence_refs_json"]))) | {str(incident["incident_id"])}
    if not set(result["provenance"]) <= evidence: raise ValueError("reflection provenance exceeds Incident evidence")
    return result


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}:" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


def _object(value: object) -> dict[str, object]:
    parsed = json.loads(str(value)) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping): raise ValueError("stored governance JSON is not an object")
    return dict(parsed)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
