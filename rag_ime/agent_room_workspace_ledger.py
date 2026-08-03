from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .db import apply_database_migrations


class RoomWorkspaceLedgerError(RuntimeError):
    pass


class RoomWorkspaceLedgerConflict(RoomWorkspaceLedgerError):
    pass


_BINDING_COLUMNS = {
    "state",
    "attention_required",
    "current_owner_participant_id",
    "current_owner_session_id",
    "delivery_revision",
    "delivery_head",
    "delivery_snapshot_sha256",
    "integration_ref",
    "integration_patch_sha256",
    "integrated_revision",
    "integrated_snapshot_sha256",
    "terminal_reason",
    "cleanup_state",
}


class RoomWorkspaceLedgerStore:
    """Permanent workspace ownership and lifecycle receipts.

    The mutable binding row is only a projection. ``room_workspace_events`` is the
    append-only authority and deliberately has no cascading Root foreign key.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def reserve_binding(
        self,
        *,
        room_id: str,
        root_id: str,
        task_id: str,
        work_item_id: str,
        dispatch_id: str,
        requirement_revision: str,
        acceptance_aliases: Sequence[str],
        participant_id: str,
        session_id: str,
        repository_id: str,
        base_root: str,
        base_commit: str,
        workspace_root: str,
        workspace_policy: str,
        creation_reason: str,
        now_ms: int,
        restore_policy: Mapping[str, object] | None = None,
    ) -> tuple[dict[str, object], bool]:
        root_id = _required_text(root_id, "root_id")
        task_id = _required_text(task_id, "task_id")
        session_id = _required_text(session_id, "session_id")
        repository_id = _sha256_text(repository_id, "repository_id")
        base_root = _required_text(base_root, "base_root")
        base_commit = _required_text(base_commit, "base_commit")
        workspace_root = _required_text(workspace_root, "workspace_root")
        creation_reason = _required_text(creation_reason, "creation_reason")
        now_ms = _non_negative_int(now_ms, "now_ms")
        if workspace_policy != "isolated_writable":
            raise RoomWorkspaceLedgerError(
                "durable workspace binding currently requires isolated_writable"
            )
        aliases = _normalized_text_list(acceptance_aliases)
        binding_id = _stable_id(
            "room-workspace-binding",
            root_id,
            task_id,
            repository_id,
            workspace_root,
        )
        immutable = {
            "room_id": str(room_id or "").strip(),
            "root_id": root_id,
            "task_id": task_id,
            "work_item_id": str(work_item_id or task_id).strip(),
            "dispatch_id": str(dispatch_id or "").strip(),
            "requirement_revision": str(requirement_revision or "").strip(),
            "acceptance_aliases_json": _json(aliases),
            "participant_id": str(participant_id or "").strip(),
            "session_id": session_id,
            "repository_id": repository_id,
            "base_root": base_root,
            "base_commit": base_commit,
            "workspace_root": workspace_root,
            "workspace_policy": workspace_policy,
        }
        with self._connect(immediate=True) as conn:
            baseline = conn.execute(
                """
                SELECT * FROM room_workspace_root_baselines
                WHERE root_id=? AND repository_id=?
                """,
                (root_id, repository_id),
            ).fetchone()
            if baseline is None:
                conn.execute(
                    """
                    INSERT INTO room_workspace_root_baselines(
                        root_id, repository_id, base_root, base_commit,
                        metadata_json, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        root_id,
                        repository_id,
                        base_root,
                        base_commit,
                        _json({"creationReason": creation_reason}),
                        now_ms,
                        now_ms,
                    ),
                )
            elif (
                str(baseline["base_root"]) != base_root
                or str(baseline["base_commit"]) != base_commit
            ):
                raise RoomWorkspaceLedgerConflict(
                    "all writable WorkItems in one Root must use the same repository baseline"
                )

            existing = conn.execute(
                """
                SELECT * FROM room_workspace_bindings
                WHERE root_id=? AND task_id=?
                """,
                (root_id, task_id),
            ).fetchone()
            if existing is not None:
                for column, expected in immutable.items():
                    if str(existing[column]) != expected:
                        raise RoomWorkspaceLedgerConflict(
                            "workspace binding identity was reused with different immutable content"
                        )
                return _binding_payload(existing), False

            conn.execute(
                """
                INSERT INTO room_workspace_bindings(
                    binding_id, room_id, root_id, task_id, work_item_id,
                    dispatch_id, requirement_revision, acceptance_aliases_json,
                    participant_id, session_id, repository_id, base_root,
                    base_commit, workspace_root, workspace_policy,
                    restore_policy_json, state,
                    attention_required, current_owner_participant_id,
                    current_owner_session_id, cleanup_policy, cleanup_state,
                    last_event_sequence, created_at_ms, updated_at_ms
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'reserved', 0, ?, ?, 'after_integrated_receipt',
                    'not_authorized', 0, ?, ?
                )
                """,
                (
                    binding_id,
                    immutable["room_id"],
                    root_id,
                    task_id,
                    immutable["work_item_id"],
                    immutable["dispatch_id"],
                    immutable["requirement_revision"],
                    immutable["acceptance_aliases_json"],
                    immutable["participant_id"],
                    session_id,
                    repository_id,
                    base_root,
                    base_commit,
                    workspace_root,
                    workspace_policy,
                    _json(dict(restore_policy or {})),
                    immutable["participant_id"],
                    session_id,
                    now_ms,
                    now_ms,
                ),
            )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="reserved",
                idempotency_key="reserve",
                actor_ref=immutable["participant_id"] or session_id,
                payload={
                    "creationReason": creation_reason,
                    "baseCommit": base_commit,
                    "repositoryId": repository_id,
                    "workspaceRoot": workspace_root,
                },
                updates={},
                now_ms=now_ms,
            )
            row = self._binding_row(conn, binding_id)
        return _binding_payload(row), True

    def mark_materialized(
        self,
        binding_id: str,
        *,
        workspace_snapshot_sha256: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        return self._transition(
            binding_id,
            event_kind="materialized",
            idempotency_key=f"materialized:{workspace_snapshot_sha256}",
            actor_ref=actor_ref,
            payload={"workspaceSnapshotSha256": _sha256_text(
                workspace_snapshot_sha256,
                "workspace_snapshot_sha256",
            )},
            updates={"state": "materialized", "attention_required": 0},
            allowed_states={"reserved", "materialized"},
            now_ms=now_ms,
        )

    def record_work_started(
        self,
        binding_id: str,
        *,
        dispatch_id: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        dispatch_id = _required_text(dispatch_id, "dispatch_id")
        return self._transition(
            binding_id,
            event_kind="work_started",
            idempotency_key=f"work-started:{dispatch_id}",
            actor_ref=actor_ref,
            payload={"dispatchId": dispatch_id},
            updates={"state": "work_started"},
            allowed_states={"materialized", "work_started", "retry_bound"},
            now_ms=now_ms,
        )

    def transfer_ownership(
        self,
        binding_id: str,
        *,
        source_session_id: str,
        target_session_id: str,
        target_participant_id: str,
        workspace_snapshot_sha256: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        source_session_id = _required_text(source_session_id, "source_session_id")
        target_session_id = _required_text(target_session_id, "target_session_id")
        snapshot = _sha256_text(workspace_snapshot_sha256, "workspace_snapshot_sha256")
        return self._transition(
            binding_id,
            event_kind="ownership_transferred",
            idempotency_key=f"ownership:{source_session_id}:{target_session_id}:{snapshot}",
            actor_ref=actor_ref,
            payload={
                "sourceSessionId": source_session_id,
                "targetSessionId": target_session_id,
                "targetParticipantId": str(target_participant_id or "").strip(),
                "workspaceSnapshotSha256": snapshot,
            },
            updates={
                "current_owner_participant_id": str(target_participant_id or "").strip(),
                "current_owner_session_id": target_session_id,
            },
            allowed_states={
                "materialized",
                "work_started",
                "delivered",
                "retry_bound",
            },
            now_ms=now_ms,
        )

    def record_delivery(
        self,
        binding_id: str,
        *,
        delivery_revision: str,
        delivery_head: str,
        workspace_snapshot_sha256: str,
        patch_sha256: str,
        manifest_sha256: str,
        artifacts: Sequence[str],
        verification_refs: Sequence[str],
        residual_risks: Sequence[str],
        actor_ref: str,
        now_ms: int,
        delivery_payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        delivery_revision = _required_text(delivery_revision, "delivery_revision")
        delivery_head = _required_text(delivery_head, "delivery_head")
        snapshot = _sha256_text(workspace_snapshot_sha256, "workspace_snapshot_sha256")
        patch_sha256 = _sha256_text(patch_sha256, "patch_sha256")
        manifest_sha256 = _sha256_text(manifest_sha256, "manifest_sha256")
        payload: dict[str, object] = {
            "deliveryRevision": delivery_revision,
            "deliveryHead": delivery_head,
            "workspaceSnapshotSha256": snapshot,
            "patchSha256": patch_sha256,
            "manifestSha256": manifest_sha256,
            "artifacts": _normalized_text_list(artifacts),
            "verificationRefs": _normalized_text_list(verification_refs),
            "residualRisks": _normalized_text_list(residual_risks),
        }
        if delivery_payload is not None:
            payload["workspaceDelivery"] = dict(delivery_payload)
        return self._transition(
            binding_id,
            event_kind="delivered",
            idempotency_key=f"delivered:{delivery_revision}:{snapshot}",
            actor_ref=actor_ref,
            payload=payload,
            updates={
                "state": "delivered",
                "attention_required": 0,
                "delivery_revision": delivery_revision,
                "delivery_head": delivery_head,
                "delivery_snapshot_sha256": snapshot,
                "cleanup_state": "not_authorized",
            },
            allowed_states={"materialized", "work_started", "delivered", "retry_bound"},
            now_ms=now_ms,
        )

    def begin_integration(
        self,
        binding_id: str,
        *,
        integration_ref: str,
        patch_sha256: str,
        target_before_snapshot_sha256: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        integration_ref = _required_text(integration_ref, "integration_ref")
        patch_sha256 = _sha256_text(patch_sha256, "patch_sha256")
        target_before = _sha256_text(
            target_before_snapshot_sha256,
            "target_before_snapshot_sha256",
        )
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            delivery = self._delivery_evidence_conn(conn, row)
            if patch_sha256 != str(delivery["patchSha256"]):
                raise RoomWorkspaceLedgerConflict(
                    "integration patch does not match the delivered patch receipt"
                )
            state = str(row["state"])
            if state in {"integrated", "cleaned"}:
                if (
                    str(row["integration_ref"]) != integration_ref
                    or str(row["integration_patch_sha256"]) != patch_sha256
                ):
                    raise RoomWorkspaceLedgerConflict(
                        "integrated workspace was replayed with different evidence"
                    )
                return _binding_payload(row)
            if state == "integration_started":
                if (
                    str(row["integration_ref"]) != integration_ref
                    or str(row["integration_patch_sha256"]) != patch_sha256
                ):
                    raise RoomWorkspaceLedgerConflict(
                        "active integration was replayed with different evidence"
                    )
                # A retry can arrive after the patch was applied but before the
                # durable integration receipt was written.  Reuse the original
                # target-before evidence so the coordinator can prove whether
                # the target is still pre-apply or already contains this exact
                # patch.  Rewriting the start event with a new target snapshot
                # would make that crash window unrecoverable.
                return _binding_payload(row)
            if state != "delivered":
                raise RoomWorkspaceLedgerError(
                    "workspace integration requires a delivered binding"
                )
            lease = conn.execute(
                """
                SELECT * FROM room_workspace_integration_leases
                WHERE root_id=? AND repository_id=?
                """,
                (str(row["root_id"]), str(row["repository_id"])),
            ).fetchone()
            if (
                lease is not None
                and str(lease["state"]) == "active"
                and str(lease["binding_id"]) != binding_id
            ):
                raise RoomWorkspaceLedgerConflict(
                    "another WorkItem owns the Root integration workspace"
                )
            lease_token = (
                str(lease["lease_token"])
                if lease is not None and str(lease["binding_id"]) == binding_id
                else str(uuid.uuid4())
            )
            conn.execute(
                """
                INSERT INTO room_workspace_integration_leases(
                    root_id, repository_id, binding_id, lease_token, state,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(root_id, repository_id) DO UPDATE SET
                    binding_id=excluded.binding_id,
                    lease_token=excluded.lease_token,
                    state='active',
                    updated_at_ms=excluded.updated_at_ms
                """,
                (
                    str(row["root_id"]),
                    str(row["repository_id"]),
                    binding_id,
                    lease_token,
                    now_ms,
                    now_ms,
                ),
            )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="integration_started",
                idempotency_key=f"integration-started:{integration_ref}:{patch_sha256}",
                actor_ref=actor_ref,
                payload={
                    "integrationRef": integration_ref,
                    "patchSha256": patch_sha256,
                    "deliveryRevision": delivery["deliveryRevision"],
                    "deliveryHead": delivery["deliveryHead"],
                    "deliverySnapshotSha256": delivery[
                        "workspaceSnapshotSha256"
                    ],
                    "deliveryManifestSha256": delivery["manifestSha256"],
                    "targetBeforeSnapshotSha256": target_before,
                    "leaseTokenSha256": hashlib.sha256(
                        lease_token.encode("utf-8")
                    ).hexdigest(),
                },
                updates={
                    "state": "integration_started",
                    "integration_ref": integration_ref,
                    "integration_patch_sha256": patch_sha256,
                    "cleanup_state": "not_authorized",
                },
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

    def record_integrated(
        self,
        binding_id: str,
        *,
        integration_ref: str,
        patch_sha256: str,
        integrated_revision: str,
        integrated_snapshot_sha256: str,
        changed_files: Sequence[str],
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        integration_ref = _required_text(integration_ref, "integration_ref")
        patch_sha256 = _sha256_text(patch_sha256, "patch_sha256")
        integrated_revision = _required_text(integrated_revision, "integrated_revision")
        integrated_snapshot = _sha256_text(
            integrated_snapshot_sha256,
            "integrated_snapshot_sha256",
        )
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            delivery = self._delivery_evidence_conn(conn, row)
            if patch_sha256 != str(delivery["patchSha256"]):
                raise RoomWorkspaceLedgerConflict(
                    "integration receipt patch does not match its delivery receipt"
                )
            if str(row["state"]) in {"integrated", "cleaned"}:
                if (
                    str(row["integration_ref"]) != integration_ref
                    or str(row["integration_patch_sha256"]) != patch_sha256
                    or str(row["integrated_snapshot_sha256"]) != integrated_snapshot
                ):
                    raise RoomWorkspaceLedgerConflict(
                        "integration receipt identity was reused with different evidence"
                    )
                return _binding_payload(row)
            if str(row["state"]) != "integration_started":
                raise RoomWorkspaceLedgerError(
                    "integration receipt requires an active integration lease"
                )
            if (
                str(row["integration_ref"]) != integration_ref
                or str(row["integration_patch_sha256"]) != patch_sha256
            ):
                raise RoomWorkspaceLedgerConflict(
                    "integration receipt does not match its start receipt"
                )
            start = self._latest_event_payload_conn(
                conn,
                binding_id=binding_id,
                event_kind="integration_started",
            )
            if start is None or any(
                str(start.get(key) or "") != str(expected)
                for key, expected in {
                    "deliveryRevision": delivery["deliveryRevision"],
                    "deliveryHead": delivery["deliveryHead"],
                    "deliverySnapshotSha256": delivery[
                        "workspaceSnapshotSha256"
                    ],
                    "patchSha256": delivery["patchSha256"],
                    "deliveryManifestSha256": delivery["manifestSha256"],
                }.items()
            ):
                raise RoomWorkspaceLedgerConflict(
                    "integration receipt is not bound to the delivered evidence"
                )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="integrated",
                idempotency_key=f"integrated:{integration_ref}:{integrated_snapshot}",
                actor_ref=actor_ref,
                payload={
                    "integrationRef": integration_ref,
                    "patchSha256": patch_sha256,
                    "integratedRevision": integrated_revision,
                    "integratedSnapshotSha256": integrated_snapshot,
                    "changedFiles": _normalized_text_list(changed_files),
                },
                updates={
                    "state": "integrated",
                    "attention_required": 0,
                    "integrated_revision": integrated_revision,
                    "integrated_snapshot_sha256": integrated_snapshot,
                    "cleanup_state": "authorized",
                },
                now_ms=now_ms,
            )
            self._release_integration_lease_conn(conn, binding_id, "integrated", now_ms)
            return _binding_payload(self._binding_row(conn, binding_id))

    def record_conflict(
        self,
        binding_id: str,
        *,
        integration_ref: str,
        patch_sha256: str,
        reason: str,
        changed_files: Sequence[str],
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        reason = _required_text(reason, "reason")
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if str(row["state"]) not in {"integration_started", "conflict"}:
                raise RoomWorkspaceLedgerError(
                    "workspace conflict requires an integration attempt"
                )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="conflict",
                idempotency_key=(
                    f"conflict:{_required_text(integration_ref, 'integration_ref')}:"
                    f"{_sha256_text(patch_sha256, 'patch_sha256')}:{hashlib.sha256(reason.encode()).hexdigest()}"
                ),
                actor_ref=actor_ref,
                payload={
                    "integrationRef": integration_ref,
                    "patchSha256": patch_sha256,
                    "reason": reason[:2000],
                    "changedFiles": _normalized_text_list(changed_files),
                },
                updates={
                    "state": "conflict",
                    "attention_required": 1,
                    "terminal_reason": reason[:2000],
                    "cleanup_state": "retained",
                },
                now_ms=now_ms,
            )
            self._release_integration_lease_conn(conn, binding_id, "conflict", now_ms)
            return _binding_payload(self._binding_row(conn, binding_id))

    def record_cleanup(
        self,
        binding_id: str,
        *,
        result: str,
        reason: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        if result not in {"cleaned", "missing", "failed"}:
            raise RoomWorkspaceLedgerError("workspace cleanup result is invalid")
        row = self.binding(binding_id)
        if str(row["workspaceLifecycleState"]) not in {
            "integrated",
            "cleaned",
            "abandoned",
            "cleanup_failed",
        }:
            raise RoomWorkspaceLedgerError(
                "workspace cleanup requires integrated or abandoned authority"
            )
        successful = result in {"cleaned", "missing"}
        return self._transition(
            binding_id,
            event_kind="cleaned" if successful else "cleanup_failed",
            idempotency_key=f"cleanup:{result}:{hashlib.sha256(str(reason).encode()).hexdigest()}",
            actor_ref=actor_ref,
            payload={"result": result, "reason": str(reason or "")[:2000]},
            updates={
                "state": "cleaned" if successful else "cleanup_failed",
                "attention_required": 0 if successful else 1,
                "cleanup_state": result,
                "terminal_reason": "" if successful else str(reason or "")[:2000],
            },
            allowed_states={"integrated", "cleaned", "abandoned", "cleanup_failed"},
            now_ms=now_ms,
        )

    def retain(
        self,
        binding_id: str,
        *,
        reason: str,
        state: str,
        workspace_snapshot_sha256: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        if state not in {
            "failed",
            "blocked",
            "cancelled",
            "conflict",
            "orphaned",
            "incomplete",
            "retained",
        }:
            raise RoomWorkspaceLedgerError("workspace retention state is invalid")
        reason = _required_text(reason, "reason")
        snapshot = (
            _sha256_text(workspace_snapshot_sha256, "workspace_snapshot_sha256")
            if workspace_snapshot_sha256
            else ""
        )
        current = self.binding(binding_id)
        if str(current["workspaceLifecycleState"]) in {
            "integrated",
            "cleaned",
            "abandoned",
        }:
            raise RoomWorkspaceLedgerError(
                "terminal workspace binding cannot be retained"
            )
        return self._transition(
            binding_id,
            event_kind="retained" if state != "orphaned" else "orphaned",
            idempotency_key=f"retain:{state}:{snapshot}:{hashlib.sha256(reason.encode()).hexdigest()}",
            actor_ref=actor_ref,
            payload={
                "retainedState": state,
                "reason": reason[:2000],
                "workspaceSnapshotSha256": snapshot,
            },
            updates={
                "state": state,
                "attention_required": 1,
                "terminal_reason": reason[:2000],
                "cleanup_state": "retained",
            },
            allowed_states=None,
            now_ms=now_ms,
        )

    def retry_binding(
        self,
        binding_id: str,
        *,
        participant_id: str,
        session_id: str,
        workspace_snapshot_sha256: str,
        reason: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        session_id = _required_text(session_id, "session_id")
        snapshot = _sha256_text(workspace_snapshot_sha256, "workspace_snapshot_sha256")
        reason = _required_text(reason, "reason")
        row = self.binding(binding_id)
        if not bool(row["attentionRequired"]):
            raise RoomWorkspaceLedgerError(
                "workspace retry requires an attention-state binding"
            )
        return self._transition(
            binding_id,
            event_kind="retry_bound",
            idempotency_key=f"retry:{session_id}:{snapshot}:{hashlib.sha256(reason.encode()).hexdigest()}",
            actor_ref=actor_ref,
            payload={
                "participantId": str(participant_id or "").strip(),
                "sessionId": session_id,
                "workspaceSnapshotSha256": snapshot,
                "reason": reason[:2000],
            },
            updates={
                "state": "retry_bound",
                "attention_required": 0,
                "current_owner_participant_id": str(participant_id or "").strip(),
                "current_owner_session_id": session_id,
                "terminal_reason": "",
                "cleanup_state": "not_authorized",
            },
            allowed_states=None,
            now_ms=now_ms,
        )

    def abandon(
        self,
        binding_id: str,
        *,
        reason: str,
        workspace_snapshot_sha256: str,
        acceptance_aliases: Sequence[str],
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        reason = _required_text(reason, "reason")
        snapshot = _sha256_text(workspace_snapshot_sha256, "workspace_snapshot_sha256")
        row = self.binding(binding_id)
        if not bool(row["attentionRequired"]):
            raise RoomWorkspaceLedgerError(
                "workspace abandonment requires an attention-state binding"
            )
        return self._transition(
            binding_id,
            event_kind="abandoned",
            idempotency_key=f"abandon:{snapshot}:{hashlib.sha256(reason.encode()).hexdigest()}",
            actor_ref=actor_ref,
            payload={
                "reason": reason[:2000],
                "workspaceSnapshotSha256": snapshot,
                "acceptanceAliases": _normalized_text_list(acceptance_aliases),
            },
            updates={
                "state": "abandoned",
                "attention_required": 0,
                "terminal_reason": reason[:2000],
                "cleanup_state": "authorized",
            },
            allowed_states=None,
            now_ms=now_ms,
        )

    def record_unclaimed_orphan(
        self,
        *,
        workspace_root: str,
        reason: str,
        observed_snapshot_sha256: str,
        now_ms: int,
    ) -> dict[str, object]:
        workspace_root = _required_text(workspace_root, "workspace_root")
        reason = _required_text(reason, "reason")
        snapshot = (
            _sha256_text(observed_snapshot_sha256, "observed_snapshot_sha256")
            if observed_snapshot_sha256
            else ""
        )
        binding_id = _stable_id("room-workspace-orphan", workspace_root)
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM room_workspace_bindings
                WHERE binding_id=? OR workspace_root=?
                ORDER BY CASE WHEN binding_id=? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (binding_id, workspace_root, binding_id),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO room_workspace_bindings(
                        binding_id, workspace_root, workspace_policy, state,
                        attention_required, cleanup_state, last_event_sequence,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, 'isolated_writable', 'orphaned', 1,
                              'retained', 0, ?, ?)
                    """,
                    (binding_id, workspace_root, now_ms, now_ms),
                )
            else:
                binding_id = str(existing["binding_id"])
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="orphaned",
                idempotency_key=f"orphan:{snapshot}:{hashlib.sha256(reason.encode()).hexdigest()}",
                actor_ref="system:workspace-recovery",
                payload={
                    "reason": reason[:2000],
                    "workspaceRoot": workspace_root,
                    "observedSnapshotSha256": snapshot,
                    "adopted": False,
                },
                updates={
                    "state": "orphaned",
                    "attention_required": 1,
                    "terminal_reason": reason[:2000],
                    "cleanup_state": "retained",
                },
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

    def binding(self, binding_id: str) -> dict[str, object]:
        with self._connect() as conn:
            return _binding_payload(self._binding_row(conn, binding_id))

    def binding_for_task(self, root_id: str, task_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM room_workspace_bindings
                WHERE root_id=? AND task_id=?
                """,
                (root_id, task_id),
            ).fetchone()
            return _binding_payload(row) if row is not None else None

    def events(self, binding_id: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM room_workspace_events
                WHERE binding_id=? ORDER BY sequence
                """,
                (binding_id,),
            ).fetchall()
        return [_event_payload(row) for row in rows]

    def recovery_candidates(self) -> list[dict[str, object]]:
        terminal = ("cleaned",)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM room_workspace_bindings
                WHERE workspace_policy='isolated_writable' AND state NOT IN (?)
                ORDER BY updated_at_ms, binding_id
                """,
                terminal,
            ).fetchall()
        return [_binding_payload(row) for row in rows]

    def attention_bindings(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM room_workspace_bindings
                WHERE attention_required=1 ORDER BY updated_at_ms, binding_id
                """
            ).fetchall()
        return [_binding_payload(row) for row in rows]

    def integration_start_payload(self, binding_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM room_workspace_events
                WHERE binding_id=? AND event_kind='integration_started'
                ORDER BY sequence DESC LIMIT 1
                """,
                (binding_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        return dict(payload) if isinstance(payload, Mapping) else None

    def delivery_payload(self, binding_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            return self._latest_event_payload_conn(
                conn,
                binding_id=binding_id,
                event_kind="delivered",
            )

    @staticmethod
    def _latest_event_payload_conn(
        conn: sqlite3.Connection,
        *,
        binding_id: str,
        event_kind: str,
    ) -> dict[str, object] | None:
        row = conn.execute(
            """
            SELECT payload_json FROM room_workspace_events
            WHERE binding_id=? AND event_kind=?
            ORDER BY sequence DESC LIMIT 1
            """,
            (binding_id, event_kind),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        return dict(payload) if isinstance(payload, Mapping) else None

    def _delivery_evidence_conn(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, object]:
        binding_id = str(row["binding_id"])
        payload = self._latest_event_payload_conn(
            conn,
            binding_id=binding_id,
            event_kind="delivered",
        )
        if payload is None:
            raise RoomWorkspaceLedgerError(
                "workspace integration requires a delivered evidence receipt"
            )
        evidence = {
            "deliveryRevision": _required_text(
                payload.get("deliveryRevision"),
                "delivery_revision",
            ),
            "deliveryHead": _required_text(
                payload.get("deliveryHead"),
                "delivery_head",
            ),
            "workspaceSnapshotSha256": _sha256_text(
                payload.get("workspaceSnapshotSha256"),
                "workspace_snapshot_sha256",
            ),
            "patchSha256": _sha256_text(
                payload.get("patchSha256"),
                "patch_sha256",
            ),
            "manifestSha256": _sha256_text(
                payload.get("manifestSha256"),
                "manifest_sha256",
            ),
        }
        if any(
            str(evidence[key]) != str(expected)
            for key, expected in {
                "deliveryRevision": row["delivery_revision"],
                "deliveryHead": row["delivery_head"],
                "workspaceSnapshotSha256": row["delivery_snapshot_sha256"],
            }.items()
        ):
            raise RoomWorkspaceLedgerConflict(
                "delivered event evidence does not match its binding projection"
            )
        return evidence

    def _transition(
        self,
        binding_id: str,
        *,
        event_kind: str,
        idempotency_key: str,
        actor_ref: str,
        payload: Mapping[str, object],
        updates: Mapping[str, object],
        allowed_states: set[str] | None,
        now_ms: int,
    ) -> dict[str, object]:
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if allowed_states is not None and str(row["state"]) not in allowed_states:
                raise RoomWorkspaceLedgerError(
                    f"workspace transition {event_kind} is invalid from {row['state']}"
                )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind=event_kind,
                idempotency_key=idempotency_key,
                actor_ref=actor_ref,
                payload=payload,
                updates=updates,
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

    def _append_event_conn(
        self,
        conn: sqlite3.Connection,
        *,
        binding_id: str,
        event_kind: str,
        idempotency_key: str,
        actor_ref: str,
        payload: Mapping[str, object],
        updates: Mapping[str, object],
        now_ms: int,
    ) -> bool:
        row = self._binding_row(conn, binding_id)
        encoded = _json(dict(payload))
        payload_sha256 = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        existing = conn.execute(
            """
            SELECT * FROM room_workspace_events
            WHERE binding_id=? AND idempotency_key=?
            """,
            (binding_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["event_kind"]) != event_kind
                or str(existing["payload_sha256"]) != payload_sha256
            ):
                raise RoomWorkspaceLedgerConflict(
                    "workspace event idempotency key was reused with different content"
                )
            return False
        unknown = set(updates) - _BINDING_COLUMNS
        if unknown:
            raise RoomWorkspaceLedgerError(
                f"workspace projection update contains unsupported fields: {sorted(unknown)}"
            )
        sequence = int(row["last_event_sequence"]) + 1
        event_id = _stable_id(
            "room-workspace-event",
            binding_id,
            str(sequence),
            event_kind,
            idempotency_key,
        )
        conn.execute(
            """
            INSERT INTO room_workspace_events(
                event_id, binding_id, sequence, event_kind, idempotency_key,
                actor_ref, payload_sha256, payload_json, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                binding_id,
                sequence,
                event_kind,
                idempotency_key,
                str(actor_ref or "").strip(),
                payload_sha256,
                encoded,
                now_ms,
            ),
        )
        assignments = [f"{column}=?" for column in updates]
        values = list(updates.values())
        assignments.extend(["last_event_sequence=?", "updated_at_ms=?"])
        values.extend([sequence, now_ms, binding_id])
        conn.execute(
            f"UPDATE room_workspace_bindings SET {', '.join(assignments)} WHERE binding_id=?",
            values,
        )
        return True

    @staticmethod
    def _release_integration_lease_conn(
        conn: sqlite3.Connection,
        binding_id: str,
        state: str,
        now_ms: int,
    ) -> None:
        conn.execute(
            """
            UPDATE room_workspace_integration_leases
            SET state=?, updated_at_ms=?
            WHERE binding_id=? AND state='active'
            """,
            (state, now_ms, binding_id),
        )

    @staticmethod
    def _binding_row(conn: sqlite3.Connection, binding_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM room_workspace_bindings WHERE binding_id=?",
            (_required_text(binding_id, "binding_id"),),
        ).fetchone()
        if row is None:
            raise RoomWorkspaceLedgerError("workspace binding does not exist")
        return row

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if immediate:
                conn.execute("COMMIT")
        except BaseException:
            if immediate and conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def _binding_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "workspaceBindingId": str(row["binding_id"]),
        "roomId": str(row["room_id"]),
        "rootId": str(row["root_id"]),
        "taskId": str(row["task_id"]),
        "workItemId": str(row["work_item_id"]),
        "dispatchId": str(row["dispatch_id"]),
        "requirementRevision": str(row["requirement_revision"]),
        "acceptanceAliases": json.loads(str(row["acceptance_aliases_json"])),
        "participantId": str(row["participant_id"]),
        "sessionId": str(row["session_id"]),
        "repositoryId": str(row["repository_id"]),
        "workspaceBaseRoot": str(row["base_root"]),
        "workspaceBaseCommit": str(row["base_commit"]),
        "workspaceRoot": str(row["workspace_root"]),
        "workspacePolicy": str(row["workspace_policy"]),
        "workspaceRestorePolicy": json.loads(str(row["restore_policy_json"])),
        "workspaceLifecycleState": str(row["state"]),
        "attentionRequired": bool(row["attention_required"]),
        "currentOwnerParticipantId": str(row["current_owner_participant_id"]),
        "currentOwnerSessionId": str(row["current_owner_session_id"]),
        "deliveryRevision": str(row["delivery_revision"]),
        "deliveryHead": str(row["delivery_head"]),
        "deliverySnapshotSha256": str(row["delivery_snapshot_sha256"]),
        "workspaceIntegrationRef": str(row["integration_ref"]) or None,
        "integrationPatchSha256": str(row["integration_patch_sha256"]),
        "integratedRevision": str(row["integrated_revision"]),
        "integratedSnapshotSha256": str(row["integrated_snapshot_sha256"]),
        "terminalReason": str(row["terminal_reason"]),
        "cleanupPolicy": str(row["cleanup_policy"]),
        "cleanupState": str(row["cleanup_state"]),
        "lastEventSequence": int(row["last_event_sequence"]),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
    }


def _event_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = json.loads(str(row["payload_json"]))
    return {
        "eventId": str(row["event_id"]),
        "workspaceBindingId": str(row["binding_id"]),
        "sequence": int(row["sequence"]),
        "eventKind": str(row["event_kind"]),
        "idempotencyKey": str(row["idempotency_key"]),
        "actorRef": str(row["actor_ref"]),
        "payloadSha256": str(row["payload_sha256"]),
        "payload": dict(payload) if isinstance(payload, Mapping) else {},
        "createdAtMs": int(row["created_at_ms"]),
    }


def _stable_id(namespace: str, *values: str) -> str:
    digest = hashlib.sha256("\0".join((namespace, *values)).encode("utf-8")).hexdigest()
    return f"{namespace}:{digest[:32]}"


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RoomWorkspaceLedgerError("workspace receipt must be JSON serializable") from exc


def _required_text(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise RoomWorkspaceLedgerError(f"{field} is required")
    return normalized


def _sha256_text(value: object, field: str) -> str:
    normalized = _required_text(value, field)
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise RoomWorkspaceLedgerError(f"{field} must be a lowercase SHA-256")
    return normalized


def _non_negative_int(value: object, field: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise RoomWorkspaceLedgerError(f"{field} must be an integer") from exc
    if normalized < 0:
        raise RoomWorkspaceLedgerError(f"{field} must be non-negative")
    return normalized


def _normalized_text_list(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = " ".join(str(value or "").split())[:1000]
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:128]
