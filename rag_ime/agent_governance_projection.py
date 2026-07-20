from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


class GovernanceProjectionStore:
    """Canonical sanitized governance read model; active state comes only from pointers."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def record_reflection_dead_letter(self, *, dead_letter_id: str, incident_id: str, owner_ref: str, reason_code: str, last_evidence_refs: Sequence[str], next_action: str, attempt_count: int, created_at_ms: int) -> None:
        if attempt_count < 1 or not owner_ref or not reason_code or not next_action:
            raise ValueError("Reflection dead-letter requires owner, reason, evidence, and next action")
        with self._connect(immediate=True) as conn:
            conn.execute("INSERT INTO room_v2_reflection_dead_letters VALUES (?,?,?,?,?,?,?,?)", (dead_letter_id, incident_id, owner_ref, reason_code, _json(_refs(last_evidence_refs)), next_action, attempt_count, created_at_ms))

    def record_materialization(self, *, materialization_receipt_id: str, guard_candidate_id: str, guard_epoch: int, artifact_kind: str, status: str, artifact_hash: str, projection_ref: str, error_code: str, created_at_ms: int) -> None:
        material = {"materializationReceiptId": materialization_receipt_id, "guardCandidateId": guard_candidate_id, "guardEpoch": guard_epoch, "artifactKind": artifact_kind, "status": status, "artifactHash": artifact_hash, "projectionRef": projection_ref, "errorCode": error_code, "createdAtMs": created_at_ms}
        with self._connect(immediate=True) as conn:
            conn.execute("INSERT INTO room_v2_guard_materialization_receipts VALUES (?,?,?,?,?,?,?,?,?,?)", (materialization_receipt_id, guard_candidate_id, guard_epoch, artifact_kind, status, artifact_hash, projection_ref, error_code, _hash_json(material), created_at_ms))

    def snapshot(self, *, scope_key: str | None = None) -> dict[str, list[dict[str, object]]]:
        with self._connect() as conn:
            incidents = conn.execute("""SELECT incident.*,COUNT(occurrence.occurrence_id) occurrence_count,MAX(occurrence.observed_at_ms) last_observed_at_ms FROM room_v2_incidents incident JOIN room_v2_incident_occurrences occurrence ON occurrence.incident_id=incident.incident_id GROUP BY incident.incident_id ORDER BY last_observed_at_ms DESC""").fetchall()
            lessons = conn.execute("SELECT * FROM room_v2_lesson_candidates ORDER BY created_at_ms DESC").fetchall()
            guards = conn.execute("SELECT * FROM room_v2_guard_candidates ORDER BY created_at_ms DESC").fetchall()
            evals = conn.execute("SELECT * FROM room_v2_guard_eval_runs ORDER BY created_at_ms DESC").fetchall()
            approvals = conn.execute("SELECT * FROM room_v2_guard_approval_receipts ORDER BY created_at_ms DESC").fetchall()
            activations = conn.execute("SELECT * FROM room_v2_guard_activation_receipts WHERE (? IS NULL OR scope_key=?) ORDER BY created_at_ms DESC", (scope_key, scope_key)).fetchall()
            rollbacks = conn.execute("SELECT * FROM room_v2_guard_rollback_receipts WHERE (? IS NULL OR scope_key=?) ORDER BY created_at_ms DESC", (scope_key, scope_key)).fetchall()
            pointers = conn.execute("SELECT * FROM room_v2_guard_active_pointers WHERE (? IS NULL OR scope_key=?) ORDER BY scope_key", (scope_key, scope_key)).fetchall()
            dead_letters = conn.execute("SELECT * FROM room_v2_reflection_dead_letters ORDER BY created_at_ms DESC").fetchall()
            materializations = conn.execute("SELECT * FROM room_v2_guard_materialization_receipts ORDER BY created_at_ms DESC").fetchall()
        return {
            "incidents": [self._incident(row) for row in incidents],
            "lessons": [self._lesson(row) for row in lessons],
            "guardCandidates": [self._guard(row) for row in guards],
            "evalRuns": [self._eval(row) for row in evals],
            "approvals": [self._approval(row) for row in approvals],
            "activations": [self._activation(row) for row in activations],
            "rollbacks": [self._rollback(row) for row in rollbacks],
            "activePointers": [self._pointer(row) for row in pointers],
            "deadLetters": [self._dead_letter(row) for row in dead_letters],
            "materializations": [self._materialization(row) for row in materializations],
        }

    @staticmethod
    def _validated(payload: dict[str, object], schema: str) -> dict[str, object]:
        validate_contract(payload, schema)
        return payload

    def _incident(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.incident-occurrence-projection.v1", "incidentId": str(row["incident_id"]), "taxonomy": str(row["taxonomy"]), "failureSignature": str(row["failure_signature"]), "evidenceRefs": json.loads(str(row["evidence_refs_json"])), "occurrenceCount": int(row["occurrence_count"]), "lastObservedAtMs": int(row["last_observed_at_ms"])}, "incident-occurrence-projection.v1.json")

    def _lesson(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.lesson-candidate-projection.v1", "lessonCandidateId": str(row["lesson_candidate_id"]), "incidentId": str(row["incident_id"]), "facts": json.loads(str(row["facts_json"])), "causes": json.loads(str(row["causes_json"])), "applicabilityBoundary": json.loads(str(row["applicability_boundary_json"])), "counterexamples": json.loads(str(row["counterexamples_json"])), "provenance": json.loads(str(row["provenance_json"])), "candidateHash": str(row["candidate_hash"]), "state": "candidate_only", "createdAtMs": int(row["created_at_ms"])}, "lesson-candidate-projection.v1.json")

    def _guard(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.guard-candidate-projection.v1", "guardCandidateId": str(row["guard_candidate_id"]), "lessonCandidateId": str(row["lesson_candidate_id"]), "version": int(row["guard_version"]), "condition": json.loads(str(row["condition_json"])), "action": json.loads(str(row["action_json"])), "scope": json.loads(str(row["scope_json"])), "risk": str(row["risk"]), "thresholds": json.loads(str(row["thresholds_json"])), "owner": str(row["owner"]), "sunsetAtMs": int(row["sunset_at_ms"]), "candidateHash": str(row["candidate_hash"]), "state": "candidate_only", "createdAtMs": int(row["created_at_ms"])}, "guard-candidate-projection.v1.json")

    def _eval(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.guard-eval-run-projection.v1", "evalRunId": str(row["eval_run_id"]), "guardCandidateId": str(row["guard_candidate_id"]), "mode": str(row["mode"]), "datasetHash": str(row["dataset_hash"]), "metrics": json.loads(str(row["metrics_json"])), "status": str(row["status"]), "createdAtMs": int(row["created_at_ms"])}, "guard-eval-run-projection.v1.json")

    def _approval(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.guard-approval-projection.v1", "approvalReceiptId": str(row["approval_receipt_id"]), "guardCandidateId": str(row["guard_candidate_id"]), "authorityRef": str(row["authority_ref"]), "decision": str(row["decision"]), "candidateHash": str(row["candidate_hash"]), "createdAtMs": int(row["created_at_ms"])}, "guard-approval-projection.v1.json")

    def _activation(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.guard-activation-projection.v1", "activationReceiptId": str(row["activation_receipt_id"]), "scopeKey": str(row["scope_key"]), "guardCandidateId": str(row["guard_candidate_id"]), "guardEpoch": int(row["guard_epoch"]), "appliesToNewRootsAfterMs": int(row["applies_to_roots_created_after_ms"]), "evalRunIds": json.loads(str(row["eval_run_ids_json"])), "createdAtMs": int(row["created_at_ms"])}, "guard-activation-projection.v1.json")

    def _rollback(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.guard-rollback-projection.v1", "rollbackReceiptId": str(row["rollback_receipt_id"]), "scopeKey": str(row["scope_key"]), "fromGuardCandidateId": str(row["from_guard_candidate_id"]), "restoredGuardCandidateId": str(row["restored_guard_candidate_id"]) if row["restored_guard_candidate_id"] else None, "guardEpoch": int(row["guard_epoch"]), "cancelledDispatchIds": json.loads(str(row["cancelled_dispatch_ids_json"])), "authorityRef": str(row["authority_ref"]), "reason": str(row["reason"]), "createdAtMs": int(row["created_at_ms"])}, "guard-rollback-projection.v1.json")

    def _pointer(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.guard-active-pointer-projection.v1", "scopeKey": str(row["scope_key"]), "guardEpoch": int(row["guard_epoch"]), "activeGuardCandidateId": str(row["active_guard_candidate_id"]) if row["active_guard_candidate_id"] else None, "activationReceiptId": str(row["activation_receipt_id"]) if row["activation_receipt_id"] else None, "updatedAtMs": int(row["updated_at_ms"])}, "guard-active-pointer-projection.v1.json")

    def _dead_letter(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.reflection-dead-letter-projection.v1", "deadLetterId": str(row["dead_letter_id"]), "incidentId": str(row["incident_id"]), "ownerRef": str(row["owner_ref"]), "reasonCode": str(row["reason_code"]), "lastEvidenceRefs": json.loads(str(row["last_evidence_refs_json"])), "nextAction": str(row["next_action"]), "attemptCount": int(row["attempt_count"]), "createdAtMs": int(row["created_at_ms"])}, "reflection-dead-letter-projection.v1.json")

    def _materialization(self, row: sqlite3.Row) -> dict[str, object]:
        return self._validated({"schemaVersion": "wisdom-weasel.guard-materialization-status-projection.v1", "materializationReceiptId": str(row["materialization_receipt_id"]), "guardCandidateId": str(row["guard_candidate_id"]), "guardEpoch": int(row["guard_epoch"]), "artifactKind": str(row["artifact_kind"]), "status": str(row["status"]), "artifactHash": str(row["artifact_hash"]), "projectionRef": str(row["projection_ref"]), "errorCode": str(row["error_code"]), "createdAtMs": int(row["created_at_ms"])}, "guard-materialization-status-projection.v1.json")

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            if immediate: conn.execute("BEGIN IMMEDIATE")
            yield conn; conn.commit()
        except BaseException:
            conn.rollback(); raise
        finally: conn.close()


def _refs(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()
