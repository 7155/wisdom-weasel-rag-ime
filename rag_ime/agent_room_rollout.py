from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path

from .db import apply_database_migrations

STAGES = ("off", "shadow", "named_canary", "production_cohort", "kernel_only")
READINESS_COMPONENTS = ("product", "pi", "migration", "schema", "routes", "prompt", "skills", "tools", "knowledge", "profile", "governance", "frontend")


class RoomRolloutError(RuntimeError):
    pass


class RoomRolloutStore:
    """Signed, monotonic rollout ledger with immutable per-Root ownership."""

    def __init__(self, db_path: str | Path, *, admin_secrets: Mapping[str, bytes | str]) -> None:
        self.db_path = Path(db_path)
        self._secrets = {str(k): v if isinstance(v, bytes) else str(v).encode() for k, v in admin_secrets.items()}

    def initialize(self) -> int:
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    @staticmethod
    def readiness_hash(readiness: Mapping[str, object]) -> str:
        if set(readiness) != set(READINESS_COMPONENTS) or any(not str(readiness[k]).strip() for k in READINESS_COMPONENTS):
            raise RoomRolloutError("readiness must cover every non-empty runtime component exactly once")
        return _hash(readiness)

    def sign(self, *, admin_ref: str, material: Mapping[str, object]) -> str:
        secret = self._secrets.get(admin_ref)
        if secret is None or not admin_ref.startswith("admin:"):
            raise RoomRolloutError("configured administrator authority is required")
        return hmac.new(secret, _json(material).encode(), hashlib.sha256).hexdigest()

    def promotion_material(self, *, policy_id: str, previous_policy_id: str | None, stage: str, cohort_id: str,
                           readiness_hash: str, canary_metrics: Mapping[str, object], rollback_target: str,
                           admin_ref: str, created_at_ms: int) -> dict[str, object]:
        return {"policyId": policy_id, "previousPolicyId": previous_policy_id, "stage": stage, "cohortId": cohort_id,
                "readinessHash": readiness_hash, "canaryMetrics": dict(canary_metrics), "rollbackTarget": rollback_target,
                "adminRef": admin_ref, "createdAtMs": int(created_at_ms)}

    def promote(self, *, policy_id: str, receipt_id: str, stage: str, cohort_id: str, readiness: Mapping[str, object],
                canary_metrics: Mapping[str, object], rollback_target: str, admin_ref: str,
                approval_signature: str, created_at_ms: int) -> dict[str, object]:
        if stage not in STAGES or rollback_target not in STAGES:
            raise RoomRolloutError("unknown rollout stage")
        readiness_hash = self.readiness_hash(readiness)
        with self._connect(immediate=True) as conn:
            previous = conn.execute("SELECT * FROM room_v2_rollout_policies WHERE active=1").fetchone()
            from_stage = str(previous["stage"]) if previous else "off"
            if STAGES.index(stage) < STAGES.index(from_stage) or STAGES.index(stage) > STAGES.index(from_stage) + (0 if previous is None else 1):
                raise RoomRolloutError("promotion must start at off and then advance exactly one stage")
            if stage in STAGES[2:] and not cohort_id.strip():
                raise RoomRolloutError("managed rollout requires a named cohort")
            if stage in STAGES[2:] and rollback_target in STAGES[:2]:
                raise RoomRolloutError("managed cohorts cannot configure a legacy rollback target")
            if previous and from_stage in STAGES[2:] and cohort_id != previous["cohort_id"]:
                raise RoomRolloutError("named cohort identity is immutable")
            _assert_metrics(stage, canary_metrics)
            material = self.promotion_material(policy_id=policy_id, previous_policy_id=str(previous["policy_id"]) if previous else None,
                stage=stage, cohort_id=cohort_id, readiness_hash=readiness_hash, canary_metrics=canary_metrics,
                rollback_target=rollback_target, admin_ref=admin_ref, created_at_ms=created_at_ms)
            if not hmac.compare_digest(self.sign(admin_ref=admin_ref, material=material), approval_signature):
                raise RoomRolloutError("rollout approval signature is invalid")
            if previous:
                conn.execute("UPDATE room_v2_rollout_policies SET active=0 WHERE policy_id=?", (previous["policy_id"],))
            conn.execute("INSERT INTO room_v2_rollout_policies VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                (policy_id, material["previousPolicyId"], stage, cohort_id, readiness_hash, _json(readiness), _json(canary_metrics), rollback_target, admin_ref, approval_signature, int(created_at_ms)))
            ledger = {**material, "receiptId": receipt_id, "action": "promote"}
            conn.execute("INSERT INTO room_v2_rollout_receipts VALUES (?,?,'promote',?,?,?,?,?)",
                (receipt_id, policy_id, from_stage, stage, "[]", _hash(ledger), int(created_at_ms)))
        return {**material, "receiptId": receipt_id, "ledgerHash": _hash(ledger)}

    def assign_root(self, *, root_id: str, created_at_ms: int) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            policy = conn.execute("SELECT * FROM room_v2_rollout_policies WHERE active=1").fetchone()
            if policy is None:
                raise RoomRolloutError("explicit signed off policy is required")
            owner = "kernel" if str(policy["stage"]) in STAGES[2:] else "legacy"
            existing = conn.execute("SELECT execution_owner FROM room_v2_root_execution_owners WHERE root_id=?", (root_id,)).fetchone()
            if existing and str(existing[0]) != owner:
                raise RoomRolloutError("Root owner is immutable; dual execution is forbidden")
            if existing is None:
                conn.execute("INSERT INTO room_v2_root_execution_owners VALUES (?,?,?,?,?,0)", (root_id, owner, policy["policy_id"], policy["cohort_id"], int(created_at_ms)))
        return {"rootId": root_id, "owner": owner, "policyId": str(policy["policy_id"]), "cohortId": str(policy["cohort_id"])}

    def rollback(self, *, receipt_id: str, target_stage: str, admin_ref: str, approval_signature: str,
                 created_at_ms: int, cancel_root: Callable[[str], None]) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            current = conn.execute("SELECT * FROM room_v2_rollout_policies WHERE active=1").fetchone()
            if current is None or target_stage != current["rollback_target"]:
                raise RoomRolloutError("rollback target does not match signed policy")
            if str(current["stage"]) in STAGES[2:] and target_stage in STAGES[:2]:
                raise RoomRolloutError("a created managed cohort cannot downgrade to legacy")
            roots = [str(row[0]) for row in conn.execute("SELECT root_id FROM room_v2_root_execution_owners WHERE execution_owner='kernel' AND cancelled_at_ms=0")]
            material = {"policyId": current["policy_id"], "targetStage": target_stage, "rootIds": roots, "adminRef": admin_ref, "createdAtMs": int(created_at_ms)}
            if not hmac.compare_digest(self.sign(admin_ref=admin_ref, material=material), approval_signature):
                raise RoomRolloutError("rollback approval signature is invalid")
            for root_id in roots:
                cancel_root(root_id)
            conn.executemany("UPDATE room_v2_root_execution_owners SET cancelled_at_ms=? WHERE root_id=?", [(int(created_at_ms), root_id) for root_id in roots])
            conn.execute("UPDATE room_v2_rollout_policies SET active=0 WHERE policy_id=?", (current["policy_id"],))
            conn.execute("INSERT INTO room_v2_rollout_receipts VALUES (?,?,'rollback',?,?,?,?,?)",
                (receipt_id, current["policy_id"], current["stage"], target_stage, _json(roots), _hash(material), int(created_at_ms)))
        return {**material, "receiptId": receipt_id, "newRootsStopped": True, "ledgerPreserved": True}

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        try:
            if immediate: conn.execute("BEGIN IMMEDIATE")
            yield conn; conn.commit()
        except BaseException:
            conn.rollback(); raise
        finally:
            conn.close()


def _assert_metrics(stage: str, metrics: Mapping[str, object]) -> None:
    keys = {"unknown", "deadLetter", "authorizationLeakage", "canaryPassed"}
    if set(metrics) != keys:
        raise RoomRolloutError("canary metrics are incomplete")
    if stage in STAGES[2:] and (not bool(metrics["canaryPassed"]) or any(int(metrics[k]) for k in ("unknown", "deadLetter", "authorizationLeakage"))):
        raise RoomRolloutError("managed rollout is blocked by canary failures")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()
