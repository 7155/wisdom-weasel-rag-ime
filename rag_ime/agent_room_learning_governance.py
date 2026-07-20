from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .db import apply_database_migrations


class LearningGovernanceError(RuntimeError):
    pass


_TAXONOMY = {"loop_detected", "cancel_leak", "stale_write", "delivery_regression", "tool_failure", "context_corruption", "security_boundary", "user_correction", "rollback", "unknown"}
_CONDITION_EVENTS = {"dispatch_enqueue", "dispatch_settle", "tool_call", "delivery_gate", "context_compile"}
_OPERATORS = {"eq", "in", "gte", "lte", "exists", "matches_taxonomy"}
_ACTIONS = {"block", "cancel", "warn", "require_review", "run_eval"}


class RoomLearningGovernanceStore:
    """Candidate-only learning and approval/eval-fenced Guard activation."""

    def __init__(self, db_path: str | Path, *, authority_secrets: Mapping[str, bytes | str] | None = None, config_secret: bytes | str | None = None, evidence_ttl_ms: int = 86_400_000) -> None:
        self.db_path = Path(db_path)
        self._authority_secrets = {str(key): value if isinstance(value, bytes) else str(value).encode() for key, value in (authority_secrets or {}).items()}
        self._config_secret = config_secret if isinstance(config_secret, bytes) else str(config_secret or "").encode()
        self.evidence_ttl_ms = int(evidence_ttl_ms)

    def initialize(self) -> int:
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def record_incident(self, *, incident_id: str, occurrence_id: str, binding_id: str | None, root_id: str, dispatch_id: str, kernel_receipt_id: str, evidence_refs: Sequence[str], taxonomy: str, failure_signature: str, observed_at_ms: int) -> tuple[dict[str, object] | None, bool]:
        """No RoomBinding means no-op; an ordinary Agent cannot enter governance."""
        if not binding_id:
            return None, False
        if taxonomy not in _TAXONOMY or not failure_signature.strip():
            raise LearningGovernanceError("Incident requires failure taxonomy and signature")
        refs = _refs(evidence_refs)
        if not refs:
            raise LearningGovernanceError("Incident requires durable evidence refs")
        with self._connect(immediate=True) as conn:
            binding = conn.execute("SELECT 1 FROM room_v2_capability_manifests WHERE binding_id=? AND root_id=? AND dispatch_id=?", (binding_id, root_id, dispatch_id)).fetchone()
            if binding is None:
                return None, False
            dispatch = conn.execute("SELECT 1 FROM room_kernel_dispatches WHERE dispatch_id=? AND root_id=?", (dispatch_id, root_id)).fetchone()
            receipt = conn.execute("SELECT 1 FROM room_kernel_receipts WHERE receipt_id=? AND root_id=?", (kernel_receipt_id, root_id)).fetchone()
            if dispatch is None or receipt is None:
                raise LearningGovernanceError("Incident Root/Dispatch/receipt lineage is invalid")
            for ref in refs:
                found = conn.execute("SELECT 1 FROM room_kernel_receipts WHERE receipt_id=? AND root_id=? UNION ALL SELECT 1 FROM room_v2_verification_receipts WHERE receipt_id=? AND root_id=?", (ref, root_id, ref, root_id)).fetchone()
                if found is None:
                    raise LearningGovernanceError("Incident evidence is missing or foreign")
            dedupe = _hash_json({"taxonomy": taxonomy, "failureSignature": failure_signature.strip(), "rootId": root_id})
            existing = conn.execute("SELECT * FROM room_v2_incidents WHERE dedupe_hash=?", (dedupe,)).fetchone()
            created = existing is None
            if created:
                material = {"incidentId": incident_id, "rootId": root_id, "dispatchId": dispatch_id, "kernelReceiptId": kernel_receipt_id, "taxonomy": taxonomy, "failureSignature": failure_signature.strip(), "evidenceRefs": refs, "createdAtMs": observed_at_ms}
                conn.execute("INSERT INTO room_v2_incidents VALUES (?,?,?,?,?,?,?,?,?,?)", (incident_id, root_id, dispatch_id, kernel_receipt_id, taxonomy, failure_signature.strip(), dedupe, _json(refs), _hash_json(material), observed_at_ms))
                canonical_id = incident_id
            else:
                canonical_id = str(existing["incident_id"])
            existing_occurrence = conn.execute(
                "SELECT incident_id FROM room_v2_incident_occurrences WHERE occurrence_id=?",
                (occurrence_id,),
            ).fetchone()
            if existing_occurrence is None:
                conn.execute("INSERT INTO room_v2_incident_occurrences VALUES (?,?,?,?,?,?,?)", (occurrence_id, canonical_id, root_id, dispatch_id, kernel_receipt_id, _json(refs), observed_at_ms))
            elif str(existing_occurrence[0]) != canonical_id:
                raise LearningGovernanceError("Incident occurrence identity changed")
        return {"incidentId": canonical_id, "dedupeHash": dedupe, "occurrenceId": occurrence_id}, created

    def nominate_lesson(self, *, lesson_candidate_id: str, incident_id: str, facts: Sequence[str], causes: Sequence[str], applicability_boundary: Mapping[str, object], counterexamples: Sequence[str], provenance: Sequence[str], nominated_by: str, created_at_ms: int) -> dict[str, object]:
        facts_n, causes_n, examples, sources = map(_nonempty_refs, (facts, causes, counterexamples, provenance))
        boundary = dict(applicability_boundary)
        if not boundary.get("scope") or not boundary.get("exclusions"):
            raise LearningGovernanceError("Lesson applicability boundary needs scope and exclusions")
        with self._connect(immediate=True) as conn:
            incident = conn.execute("SELECT evidence_refs_json FROM room_v2_incidents WHERE incident_id=?", (incident_id,)).fetchone()
            if incident is None:
                raise KeyError(incident_id)
            known = set(json.loads(str(incident[0]))) | {incident_id}
            if not set(sources) <= known:
                raise LearningGovernanceError("Lesson provenance exceeds Incident evidence")
            material = {"lessonCandidateId": lesson_candidate_id, "incidentId": incident_id, "facts": facts_n, "causes": causes_n, "applicabilityBoundary": boundary, "counterexamples": examples, "provenance": sources, "nominatedBy": nominated_by, "createdAtMs": created_at_ms}
            candidate_hash = _hash_json(material)
            existing = conn.execute(
                "SELECT candidate_hash FROM room_v2_lesson_candidates WHERE lesson_candidate_id=?",
                (lesson_candidate_id,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != candidate_hash:
                    raise LearningGovernanceError("Lesson candidate identity changed")
                return {**material, "candidateHash": candidate_hash, "state": "candidate_only"}
            conn.execute("INSERT INTO room_v2_lesson_candidates VALUES (?,?,?,?,?,?,?,?,?,?)", (lesson_candidate_id, incident_id, _json(facts_n), _json(causes_n), _json(boundary), _json(examples), _json(sources), candidate_hash, nominated_by, created_at_ms))
        return {**material, "candidateHash": candidate_hash, "state": "candidate_only"}

    def nominate_guard(self, *, guard_candidate_id: str, lesson_candidate_id: str, guard_version: int, condition: Mapping[str, object], action: Mapping[str, object], scope: Mapping[str, object], risk: str, thresholds: Mapping[str, object], owner: str, sunset_at_ms: int, nominated_by: str, created_at_ms: int) -> dict[str, object]:
        if any(key.lower() in {"rule", "ruletext", "prompt", "code", "script"} for key in {*condition.keys(), *action.keys()}):
            raise LearningGovernanceError("Guard cannot contain free-text executable rules")
        condition_n = _condition(condition); action_n = _action(action); scope_n = _scope(scope)
        thresholds_n = _thresholds(thresholds)
        if risk not in {"low", "medium", "high", "critical"} or guard_version < 1 or sunset_at_ms <= created_at_ms:
            raise LearningGovernanceError("Guard risk/version/sunset is invalid")
        with self._connect(immediate=True) as conn:
            lesson = conn.execute("SELECT candidate_hash FROM room_v2_lesson_candidates WHERE lesson_candidate_id=?", (lesson_candidate_id,)).fetchone()
            if lesson is None: raise KeyError(lesson_candidate_id)
            material = {"guardCandidateId": guard_candidate_id, "lessonCandidateId": lesson_candidate_id, "guardVersion": guard_version, "condition": condition_n, "action": action_n, "scope": scope_n, "risk": risk, "thresholds": thresholds_n, "owner": owner, "sunsetAtMs": sunset_at_ms, "nominatedBy": nominated_by, "createdAtMs": created_at_ms}
            candidate_hash = _hash_json(material)
            conn.execute("INSERT INTO room_v2_guard_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (guard_candidate_id, lesson_candidate_id, guard_version, _json(condition_n), _json(action_n), _json(scope_n), risk, _json(thresholds_n), owner, sunset_at_ms, candidate_hash, nominated_by, created_at_ms))
        return {**material, "candidateHash": candidate_hash, "state": "candidate_only"}

    def record_eval(self, *, eval_run_id: str, guard_candidate_id: str, mode: str, dataset_hash: str, positive_fixture_count: int, negative_fixture_count: int, metrics: Mapping[str, object], runner_receipt_id: str, created_at_ms: int) -> dict[str, object]:
        if mode not in {"offline", "shadow", "canary"} or positive_fixture_count < 1 or negative_fixture_count < 1 or positive_fixture_count + negative_fixture_count < 4:
            raise LearningGovernanceError("Eval must include sufficient incident and normal counterexamples")
        with self._connect(immediate=True) as conn:
            guard = self._guard(conn, guard_candidate_id); self._assert_guard_hash(guard)
            receipt = conn.execute("SELECT * FROM room_v2_verification_receipts WHERE receipt_id=?", (runner_receipt_id,)).fetchone()
            if receipt is None or receipt["issuer_trust"] != "runner_signed" or int(receipt["exit_status"]) != 0 or created_at_ms - int(receipt["created_at_ms"]) > self.evidence_ttl_ms:
                raise LearningGovernanceError("Eval evidence is unsigned, failed, or expired")
            metric = _metrics(metrics, positive_fixture_count + negative_fixture_count)
            threshold = json.loads(str(guard["thresholds_json"]))
            passed = metric["incidentRecall"] >= threshold["minIncidentRecall"] and metric["falsePositiveRate"] <= threshold["maxFalsePositiveRate"] and metric["regressionRate"] <= threshold["maxRegressionRate"]
            material = {"evalRunId": eval_run_id, "guardCandidateId": guard_candidate_id, "candidateHash": guard["candidate_hash"], "mode": mode, "datasetHash": dataset_hash, "positiveFixtureCount": positive_fixture_count, "negativeFixtureCount": negative_fixture_count, "metrics": metric, "runnerReceiptId": runner_receipt_id, "status": "passed" if passed else "failed", "createdAtMs": created_at_ms}
            conn.execute("INSERT INTO room_v2_guard_eval_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (eval_run_id, guard_candidate_id, guard["candidate_hash"], mode, dataset_hash, positive_fixture_count, negative_fixture_count, _json(metric), runner_receipt_id, material["status"], _hash_json(material), created_at_ms))
        return material

    def approve_guard(self, *, approval_receipt_id: str, guard_candidate_id: str, authority_ref: str, decision: str, created_at_ms: int, authority_secret: bytes | str) -> dict[str, object]:
        if decision not in {"approve", "reject"} or not (authority_ref.startswith("admin:") or authority_ref.startswith("user:")):
            raise LearningGovernanceError("Guard approval requires administrator or user authority")
        with self._connect(immediate=True) as conn:
            guard = self._guard(conn, guard_candidate_id); self._assert_guard_hash(guard)
            if authority_ref == str(guard["nominated_by"]):
                raise LearningGovernanceError("Guard nominator cannot self-approve")
            configured = self._authority_secrets.get(authority_ref)
            supplied = authority_secret if isinstance(authority_secret, bytes) else authority_secret.encode()
            if configured is None or not hmac.compare_digest(configured, supplied):
                raise LearningGovernanceError("Approval authority secret is not trusted")
            material = {"approvalReceiptId": approval_receipt_id, "guardCandidateId": guard_candidate_id, "candidateHash": guard["candidate_hash"], "authorityRef": authority_ref, "decision": decision, "createdAtMs": created_at_ms}
            content_hash = _hash_json(material); signature = hmac.new(configured, content_hash.encode(), hashlib.sha256).hexdigest()
            conn.execute("INSERT INTO room_v2_guard_approval_receipts VALUES (?,?,?,?,?,?,?,?)", (approval_receipt_id, guard_candidate_id, guard["candidate_hash"], authority_ref, decision, content_hash, signature, created_at_ms))
        return {**material, "contentHash": content_hash, "authoritySignature": signature}

    def activate_guard(self, *, activation_receipt_id: str, guard_candidate_id: str, approval_receipt_id: str, eval_run_ids: Sequence[str], now_ms: int, config_signature: str, automatic: bool = False) -> dict[str, object]:
        if automatic:
            raise LearningGovernanceError("automatic reflection cannot activate a Guard")
        with self._connect(immediate=True) as conn:
            guard = self._guard(conn, guard_candidate_id); self._assert_guard_hash(guard)
            if now_ms >= int(guard["sunset_at_ms"]): raise LearningGovernanceError("Guard candidate is expired")
            approval = conn.execute("SELECT * FROM room_v2_guard_approval_receipts WHERE approval_receipt_id=? AND guard_candidate_id=? AND decision='approve'", (approval_receipt_id, guard_candidate_id)).fetchone()
            if approval is None or str(approval["candidate_hash"]) != str(guard["candidate_hash"]): raise LearningGovernanceError("Activation lacks matching approval receipt")
            secret = self._authority_secrets.get(str(approval["authority_ref"])); approval_material = {"approvalReceiptId": approval["approval_receipt_id"], "guardCandidateId": guard_candidate_id, "candidateHash": approval["candidate_hash"], "authorityRef": approval["authority_ref"], "decision": approval["decision"], "createdAtMs": approval["created_at_ms"]}
            if secret is None or _hash_json(approval_material) != approval["content_hash"] or not hmac.compare_digest(str(approval["authority_signature"]), hmac.new(secret, str(approval["content_hash"]).encode(), hashlib.sha256).hexdigest()): raise LearningGovernanceError("Approval receipt was tampered")
            ids = _refs(eval_run_ids)
            evals = conn.execute(
                f"""SELECT eval.*, receipt.created_at_ms AS runner_created_at_ms,
                    receipt.issuer_trust AS runner_issuer_trust, receipt.exit_status AS runner_exit_status
                    FROM room_v2_guard_eval_runs eval
                    JOIN room_v2_verification_receipts receipt ON receipt.receipt_id=eval.runner_receipt_id
                    WHERE eval.eval_run_id IN ({','.join('?' for _ in ids)})""", ids,
            ).fetchall() if ids else []
            if len(evals) != len(ids) or any(row["guard_candidate_id"] != guard_candidate_id or row["candidate_hash"] != guard["candidate_hash"] or row["status"] != "passed" or row["runner_issuer_trust"] != "runner_signed" or int(row["runner_exit_status"]) != 0 or now_ms - int(row["created_at_ms"]) > self.evidence_ttl_ms or now_ms - int(row["runner_created_at_ms"]) > self.evidence_ttl_ms for row in evals): raise LearningGovernanceError("Activation eval set failed, expired, or mismatched")
            modes = {str(row["mode"]) for row in evals}
            required_modes = {"shadow", "canary"} if guard["risk"] in {"high", "critical"} else {"offline"}
            if not required_modes <= modes: raise LearningGovernanceError("Guard lacks required offline/shadow/canary evaluation")
            if len({str(row["dataset_hash"]) for row in evals if str(row["mode"]) in required_modes}) < len(required_modes): raise LearningGovernanceError("Guard eval modes must use independent datasets")
            scope_key = _scope_key(json.loads(str(guard["scope_json"])))
            pointer = conn.execute("SELECT * FROM room_v2_guard_active_pointers WHERE scope_key=?", (scope_key,)).fetchone()
            epoch = (int(pointer["guard_epoch"]) if pointer else 0) + 1
            previous = str(pointer["active_guard_candidate_id"]) if pointer and pointer["active_guard_candidate_id"] else None
            previous_activation = str(pointer["activation_receipt_id"]) if pointer and pointer["activation_receipt_id"] else None
            config_material = {"scopeKey": scope_key, "guardCandidateId": guard_candidate_id, "candidateHash": guard["candidate_hash"], "guardEpoch": epoch, "appliesAfterMs": now_ms, "evalRunIds": ids}
            signed_hash = _hash_json(config_material); expected_signature = hmac.new(self._config_secret, signed_hash.encode(), hashlib.sha256).hexdigest()
            if not self._config_secret or not hmac.compare_digest(config_signature, expected_signature): raise LearningGovernanceError("signed config hash is invalid")
            conn.execute("INSERT INTO room_v2_guard_activation_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (activation_receipt_id, scope_key, guard_candidate_id, guard["candidate_hash"], previous, previous_activation, epoch, now_ms, approval_receipt_id, _json(ids), signed_hash, config_signature, now_ms))
            conn.execute("INSERT INTO room_v2_guard_active_pointers VALUES (?,?,?,?,?,?) ON CONFLICT(scope_key) DO UPDATE SET guard_epoch=excluded.guard_epoch,active_guard_candidate_id=excluded.active_guard_candidate_id,active_candidate_hash=excluded.active_candidate_hash,activation_receipt_id=excluded.activation_receipt_id,updated_at_ms=excluded.updated_at_ms", (scope_key, epoch, guard_candidate_id, guard["candidate_hash"], activation_receipt_id, now_ms))
            conn.execute(
                """INSERT INTO room_v2_guard_materialization_outbox(
                   outbox_id,scope_key,guard_candidate_id,guard_epoch,candidate_hash,
                   action,state,created_at_ms,updated_at_ms)
                   VALUES (?,?,?,?,?,'materialize','pending',?,?)""",
                (f"guard-materialize:{activation_receipt_id}", scope_key, guard_candidate_id, epoch, guard["candidate_hash"], now_ms, now_ms),
            )
        return {**config_material, "activationReceiptId": activation_receipt_id, "signedConfigHash": signed_hash}

    def expected_config_signature(self, *, scope: Mapping[str, object], guard_candidate_id: str, candidate_hash: str, guard_epoch: int, applies_after_ms: int, eval_run_ids: Sequence[str]) -> str:
        material = {"scopeKey": _scope_key(_scope(scope)), "guardCandidateId": guard_candidate_id, "candidateHash": candidate_hash, "guardEpoch": guard_epoch, "appliesAfterMs": applies_after_ms, "evalRunIds": _refs(eval_run_ids)}
        return hmac.new(self._config_secret, _hash_json(material).encode(), hashlib.sha256).hexdigest()

    def guard_for_root(self, *, binding_id: str | None, root_id: str, scope_key: str) -> dict[str, object] | None:
        if not binding_id or not binding_id.startswith("participant-binding:"): return None
        dispatch_id = binding_id.removeprefix("participant-binding:")
        with self._connect() as conn:
            dispatch = conn.execute(
                "SELECT 1 FROM room_kernel_dispatches WHERE dispatch_id=? AND root_id=?",
                (dispatch_id, root_id),
            ).fetchone()
            root = conn.execute("SELECT created_at_ms FROM room_kernel_roots WHERE root_id=?", (root_id,)).fetchone()
            pointer = conn.execute("SELECT * FROM room_v2_guard_active_pointers WHERE scope_key=?", (scope_key,)).fetchone()
            if dispatch is None or root is None or pointer is None or not pointer["active_guard_candidate_id"]: return None
            activation = conn.execute("SELECT * FROM room_v2_guard_activation_receipts WHERE activation_receipt_id=?", (pointer["activation_receipt_id"],)).fetchone()
            if activation is None or int(root[0]) <= int(activation["applies_to_roots_created_after_ms"]): return None
            guard = self._guard(conn, str(pointer["active_guard_candidate_id"])); self._assert_guard_hash(guard)
            if (
                str(pointer["active_candidate_hash"]) != str(guard["candidate_hash"])
                or str(activation["candidate_hash"]) != str(guard["candidate_hash"])
                or int(activation["guard_epoch"]) != int(pointer["guard_epoch"])
                or str(activation["signed_config_hash"]) != _hash_json({
                    "scopeKey": scope_key,
                    "guardCandidateId": str(guard["guard_candidate_id"]),
                    "candidateHash": str(guard["candidate_hash"]),
                    "guardEpoch": int(pointer["guard_epoch"]),
                    "appliesAfterMs": int(activation["applies_to_roots_created_after_ms"]),
                    "evalRunIds": json.loads(str(activation["eval_run_ids_json"])),
                })
            ):
                raise LearningGovernanceError("active Guard pointer hash/epoch mismatch")
            expected = hmac.new(self._config_secret, str(activation["signed_config_hash"]).encode(), hashlib.sha256).hexdigest()
            if not self._config_secret or not hmac.compare_digest(str(activation["config_signature"]), expected):
                raise LearningGovernanceError("active Guard config signature mismatch")
            return {
                "guardCandidateId": str(pointer["active_guard_candidate_id"]),
                "guardEpoch": int(pointer["guard_epoch"]),
                "scopeKey": scope_key,
                "candidateHash": str(guard["candidate_hash"]),
                "configHash": str(activation["signed_config_hash"]),
                "activationReceiptId": str(pointer["activation_receipt_id"]),
            }

    def materialized_guard(self, *, scope_key: str, guard_epoch: int, config_hash: str) -> dict[str, object]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT surface,payload_json,candidate_hash,guard_epoch,config_hash,
                          guard_candidate_id
                   FROM room_v2_guard_materializations
                   WHERE scope_key=? AND state='active' ORDER BY surface""",
                (scope_key,),
            ).fetchall()
        if len(rows) != 4 or any(int(row["guard_epoch"]) != guard_epoch or str(row["config_hash"]) != config_hash for row in rows):
            raise LearningGovernanceError("Guard materialization hash/epoch mismatch")
        candidate_ids = {str(row["guard_candidate_id"]) for row in rows}
        if len(candidate_ids) != 1:
            raise LearningGovernanceError("Guard materialization candidate mismatch")
        with self._connect() as conn:
            guard = self._guard(conn, candidate_ids.pop())
            self._assert_guard_hash(guard)
        base = {
            "guardCandidateId": str(guard["guard_candidate_id"]),
            "guardEpoch": guard_epoch,
            "candidateHash": str(guard["candidate_hash"]),
            "scope": json.loads(str(guard["scope_json"])),
            "condition": json.loads(str(guard["condition_json"])),
            "action": json.loads(str(guard["action_json"])),
        }
        expected = {
            "prompt": {**base, "policyKind": "structured_prompt_guard"},
            "skill": {**base, "policyKind": "skill_admission_guard"},
            "tool": {**base, "policyKind": "tool_authorization_guard"},
            "test_fixture": {
                **base,
                "policyKind": "regression_fixture",
                "thresholds": json.loads(str(guard["thresholds_json"])),
            },
        }
        materialized = {str(row["surface"]): json.loads(str(row["payload_json"])) for row in rows}
        if materialized != expected:
            raise LearningGovernanceError("Guard materialization payload mismatch")
        return materialized

    def bind_execution(self, *, dispatch_id: str, root_id: str, scope_key: str, guard_epoch: int, config_hash: str = "", now_ms: int) -> None:
        with self._connect(immediate=True) as conn:
            pointer = conn.execute("SELECT * FROM room_v2_guard_active_pointers WHERE scope_key=?", (scope_key,)).fetchone()
            dispatch = conn.execute("SELECT 1 FROM room_kernel_dispatches WHERE dispatch_id=? AND root_id=?", (dispatch_id, root_id)).fetchone()
            root = conn.execute("SELECT created_at_ms FROM room_kernel_roots WHERE root_id=?", (root_id,)).fetchone()
            activation = conn.execute("SELECT * FROM room_v2_guard_activation_receipts WHERE activation_receipt_id=?", (pointer["activation_receipt_id"],)).fetchone() if pointer and pointer["activation_receipt_id"] else None
            if pointer is None or dispatch is None or root is None or activation is None or int(root[0]) <= int(activation["applies_to_roots_created_after_ms"]) or int(pointer["guard_epoch"]) != guard_epoch or not pointer["active_guard_candidate_id"]: raise LearningGovernanceError("stale Guard epoch binding")
            guard = self._guard(conn, str(pointer["active_guard_candidate_id"])); self._assert_guard_hash(guard)
            pinned_hash = str(activation["signed_config_hash"])
            if config_hash and config_hash != pinned_hash: raise LearningGovernanceError("Guard config hash binding mismatch")
            conn.execute(
                """INSERT INTO room_v2_guard_execution_bindings(
                   dispatch_id,root_id,scope_key,guard_candidate_id,guard_epoch,state,
                   bound_at_ms,updated_at_ms,guard_config_hash,guard_candidate_hash,
                   activation_receipt_id) VALUES (?,?,?,?,?,'active',?,?,?,?,?)""",
                (dispatch_id, root_id, scope_key, pointer["active_guard_candidate_id"], guard_epoch, now_ms, now_ms, pinned_hash, guard["candidate_hash"], pointer["activation_receipt_id"]),
            )

    def accept_writeback(self, *, dispatch_id: str, guard_epoch: int, config_hash: str = "") -> None:
        with self._connect() as conn:
            binding = conn.execute("SELECT * FROM room_v2_guard_execution_bindings WHERE dispatch_id=?", (dispatch_id,)).fetchone()
        if binding is None or binding["state"] != "active" or int(binding["guard_epoch"]) != guard_epoch or (config_hash and str(binding["guard_config_hash"]) != config_hash): raise LearningGovernanceError("old Guard epoch writeback rejected")

    def execution_pin(self, dispatch_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_guard_execution_bindings WHERE dispatch_id=?",
                (dispatch_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "dispatchId": str(row["dispatch_id"]),
            "rootId": str(row["root_id"]),
            "scopeKey": str(row["scope_key"]),
            "guardCandidateId": str(row["guard_candidate_id"]),
            "guardEpoch": int(row["guard_epoch"]),
            "configHash": str(row["guard_config_hash"]),
            "candidateHash": str(row["guard_candidate_hash"]),
            "activationReceiptId": str(row["activation_receipt_id"]),
            "state": str(row["state"]),
        }

    def complete_writeback(self, *, dispatch_id: str, now_ms: int) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                """UPDATE room_v2_guard_execution_bindings
                   SET state='terminal',updated_at_ms=?
                   WHERE dispatch_id=? AND state='active'""",
                (now_ms, dispatch_id),
            )

    def rollback(self, *, rollback_receipt_id: str, scope_key: str, authority_ref: str, authority_secret: bytes | str, reason: str, now_ms: int, fail_before_pointer: bool = False) -> dict[str, object]:
        if not (authority_ref.startswith("admin:") or authority_ref.startswith("user:")): raise LearningGovernanceError("Rollback requires administrator or user")
        configured = self._authority_secrets.get(authority_ref); supplied = authority_secret if isinstance(authority_secret, bytes) else authority_secret.encode()
        if configured is None or not hmac.compare_digest(configured, supplied): raise LearningGovernanceError("Rollback authority secret is not trusted")
        with self._connect(immediate=True) as conn:
            pointer = conn.execute("SELECT * FROM room_v2_guard_active_pointers WHERE scope_key=?", (scope_key,)).fetchone()
            if pointer is None or not pointer["active_guard_candidate_id"]: raise LearningGovernanceError("No active Guard to rollback")
            activation = conn.execute("SELECT * FROM room_v2_guard_activation_receipts WHERE activation_receipt_id=?", (pointer["activation_receipt_id"],)).fetchone()
            restored = str(activation["previous_guard_candidate_id"]) if activation and activation["previous_guard_candidate_id"] else None; epoch = int(pointer["guard_epoch"]) + 1
            restored_source_activation_id = str(activation["previous_activation_receipt_id"]) if activation and activation["previous_activation_receipt_id"] else None
            restored_activation = None
            dispatches = [str(row[0]) for row in conn.execute("SELECT dispatch_id FROM room_v2_guard_execution_bindings WHERE scope_key=? AND guard_epoch=? AND state='active'", (scope_key, pointer["guard_epoch"])).fetchall()]
            conn.execute("UPDATE room_v2_guard_execution_bindings SET state='cancel_requested',updated_at_ms=? WHERE scope_key=? AND guard_epoch=? AND state='active'", (now_ms, scope_key, pointer["guard_epoch"]))
            if fail_before_pointer: raise LearningGovernanceError("injected rollback crash")
            restored_hash = ""
            if restored:
                restored_row = self._guard(conn, restored); restored_hash = str(restored_row["candidate_hash"])
                source_activation = conn.execute(
                    "SELECT * FROM room_v2_guard_activation_receipts WHERE activation_receipt_id=?",
                    (restored_source_activation_id,),
                ).fetchone()
                if source_activation is None:
                    raise LearningGovernanceError("Rollback restore activation disappeared")
                restored_activation = f"rollback-activation:{rollback_receipt_id}"
                eval_ids = json.loads(str(source_activation["eval_run_ids_json"]))
                config_material = {
                    "scopeKey": scope_key,
                    "guardCandidateId": restored,
                    "candidateHash": restored_hash,
                    "guardEpoch": epoch,
                    "appliesAfterMs": now_ms,
                    "evalRunIds": eval_ids,
                }
                signed_hash = _hash_json(config_material)
                config_signature = hmac.new(self._config_secret, signed_hash.encode(), hashlib.sha256).hexdigest()
                conn.execute(
                    """INSERT INTO room_v2_guard_activation_receipts VALUES
                       (?,?,?,?,NULL,NULL,?,?,?,?,?,?,?)""",
                    (
                        restored_activation, scope_key, restored, restored_hash, epoch,
                        now_ms, source_activation["approval_receipt_id"], _json(eval_ids),
                        signed_hash, config_signature, now_ms,
                    ),
                )
            material = {"rollbackReceiptId": rollback_receipt_id, "scopeKey": scope_key, "fromGuardCandidateId": pointer["active_guard_candidate_id"], "restoredGuardCandidateId": restored, "guardEpoch": epoch, "cancelledDispatchIds": dispatches, "authorityRef": authority_ref, "reason": reason, "createdAtMs": now_ms}
            content_hash = _hash_json(material); signature = hmac.new(configured, content_hash.encode(), hashlib.sha256).hexdigest()
            conn.execute("INSERT INTO room_v2_guard_rollback_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (rollback_receipt_id, scope_key, pointer["active_guard_candidate_id"], restored, epoch, _json(dispatches), authority_ref, reason, content_hash, signature, content_hash, now_ms))
            conn.execute("UPDATE room_v2_guard_active_pointers SET guard_epoch=?,active_guard_candidate_id=?,active_candidate_hash=?,activation_receipt_id=?,updated_at_ms=? WHERE scope_key=?", (epoch, restored, restored_hash, restored_activation, now_ms, scope_key))
            conn.execute(
                """INSERT INTO room_v2_guard_materialization_outbox(
                   outbox_id,scope_key,guard_candidate_id,guard_epoch,candidate_hash,
                   action,state,created_at_ms,updated_at_ms)
                   VALUES (?,?,?,?,?,'cleanup','pending',?,?)""",
                (f"guard-cleanup:{rollback_receipt_id}", scope_key, pointer["active_guard_candidate_id"], epoch, str(pointer["active_candidate_hash"]), now_ms, now_ms),
            )
            if restored:
                conn.execute(
                    """INSERT INTO room_v2_guard_materialization_outbox(
                       outbox_id,scope_key,guard_candidate_id,guard_epoch,candidate_hash,
                       action,state,created_at_ms,updated_at_ms)
                       VALUES (?,?,?,?,?,'materialize','pending',?,?)""",
                    (
                        f"guard-materialize:{rollback_receipt_id}", scope_key, restored,
                        epoch, restored_hash, now_ms, now_ms,
                    ),
                )
            for dispatch_id in dispatches:
                root_row = conn.execute("SELECT root_id FROM room_kernel_dispatches WHERE dispatch_id=?", (dispatch_id,)).fetchone()
                if root_row is None: continue
                conn.execute(
                    """INSERT OR IGNORE INTO room_v2_managed_cancel_outbox(
                       cancel_id,source_kind,source_receipt_id,root_id,dispatch_id,state,
                       created_at_ms,updated_at_ms) VALUES (?,?,?,?,?,'pending',?,?)""",
                    (f"guard-cancel:{rollback_receipt_id}:{dispatch_id}", "guard_rollback", rollback_receipt_id, root_row[0], dispatch_id, now_ms, now_ms),
                )
        return material

    @staticmethod
    def _guard(conn: sqlite3.Connection, guard_candidate_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM room_v2_guard_candidates WHERE guard_candidate_id=?", (guard_candidate_id,)).fetchone()
        if row is None: raise KeyError(guard_candidate_id)
        return row

    @staticmethod
    def _assert_guard_hash(row: sqlite3.Row) -> None:
        material = {"guardCandidateId": row["guard_candidate_id"], "lessonCandidateId": row["lesson_candidate_id"], "guardVersion": row["guard_version"], "condition": json.loads(row["condition_json"]), "action": json.loads(row["action_json"]), "scope": json.loads(row["scope_json"]), "risk": row["risk"], "thresholds": json.loads(row["thresholds_json"]), "owner": row["owner"], "sunsetAtMs": row["sunset_at_ms"], "nominatedBy": row["nominated_by"], "createdAtMs": row["created_at_ms"]}
        if _hash_json(material) != row["candidate_hash"]: raise LearningGovernanceError("Guard candidate was tampered")

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path, timeout=10); conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            if immediate: conn.execute("BEGIN IMMEDIATE")
            yield conn; conn.commit()
        except BaseException:
            conn.rollback(); raise
        finally: conn.close()


def _condition(value: Mapping[str, object]) -> dict[str, object]:
    result = {"event": str(value.get("event") or ""), "field": str(value.get("field") or ""), "operator": str(value.get("operator") or ""), "value": value.get("value")}
    if set(value) != set(result) or result["event"] not in _CONDITION_EVENTS or result["operator"] not in _OPERATORS or not result["field"]: raise LearningGovernanceError("Guard condition must be structured")
    return result


def _action(value: Mapping[str, object]) -> dict[str, str]:
    result = {"kind": str(value.get("kind") or ""), "target": str(value.get("target") or "")}
    if set(value) != set(result) or result["kind"] not in _ACTIONS or not result["target"]: raise LearningGovernanceError("Guard action must be structured")
    return result


def _scope(value: Mapping[str, object]) -> dict[str, str]:
    result = {"kind": str(value.get("kind") or ""), "selector": str(value.get("selector") or "")}
    if set(value) != set(result) or result["kind"] not in {"room", "project", "global"} or not result["selector"]: raise LearningGovernanceError("Guard scope must be structured")
    return result


def _thresholds(value: Mapping[str, object]) -> dict[str, float]:
    result = {"minIncidentRecall": float(value.get("minIncidentRecall", -1)), "maxFalsePositiveRate": float(value.get("maxFalsePositiveRate", -1)), "maxRegressionRate": float(value.get("maxRegressionRate", -1))}
    if set(value) != set(result) or not 0 <= result["minIncidentRecall"] <= 1 or not 0 <= result["maxFalsePositiveRate"] <= 1 or not 0 <= result["maxRegressionRate"] <= 1: raise LearningGovernanceError("Guard eval thresholds are invalid")
    return result


def _metrics(value: Mapping[str, object], expected_samples: int) -> dict[str, float | int]:
    result = {"incidentRecall": float(value.get("incidentRecall", -1)), "falsePositiveRate": float(value.get("falsePositiveRate", -1)), "regressionRate": float(value.get("regressionRate", -1)), "sampleCount": int(value.get("sampleCount", -1))}
    if set(value) != set(result) or result["sampleCount"] != expected_samples or any(not 0 <= float(result[key]) <= 1 for key in ("incidentRecall", "falsePositiveRate", "regressionRate")): raise LearningGovernanceError("Eval metrics/sample count may be gamed or malformed")
    return result


def _scope_key(scope: Mapping[str, object]) -> str:
    return f"{scope['kind']}:{scope['selector']}"


def _nonempty_refs(values: Sequence[object]) -> list[str]:
    result = _refs(values)
    if not result: raise LearningGovernanceError("Lesson fields cannot be empty")
    return result


def _refs(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()
