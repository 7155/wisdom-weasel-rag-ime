from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from rag_ime.db import apply_database_migrations


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

_EXACT_AUTHORITY_EVENT_KINDS = frozenset(
    {
        "cleanup_removal_authorized",
        "vaulted",
        "cleaned",
    }
)


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
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            state = str(row["state"])
            if state == "delivered":
                prior = self._latest_event_payload_conn(
                    conn,
                    binding_id=binding_id,
                    event_kind="delivered",
                )
                if prior == payload:
                    return _binding_payload(row)
                raise RoomWorkspaceLedgerConflict(
                    "delivered workspace is sealed; a new delivery requires an "
                    "explicit retry lease"
                )
            if state not in {"materialized", "work_started", "retry_bound"}:
                raise RoomWorkspaceLedgerError(
                    f"workspace transition delivered is invalid from {state}"
                )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
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
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

    def mark_delivery_seal_uncertain(
        self,
        binding_id: str,
        *,
        reason: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Persist the fail-closed state for a delivered but unsealed child.

        This is intentionally distinct from generic retention: the delivered
        generation stays sealed and can only be completed by the explicit
        delivery-seal resume CAS below.
        """

        reason = _required_text(reason, "reason")
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="source_lease_revoked",
            ) is not None:
                return _binding_payload(row)
            if str(row["state"]) not in {
                "delivered",
                "delivery_seal_uncertain",
                "delivery_seal_resuming",
            }:
                raise RoomWorkspaceLedgerError(
                    "delivery-seal uncertainty requires a delivered binding"
                )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="delivery_seal_uncertain",
                idempotency_key=(
                    "delivery-seal-uncertain:"
                    + hashlib.sha256(reason.encode("utf-8")).hexdigest()
                ),
                actor_ref=actor_ref,
                payload={
                    "deliveryRevision": str(row["delivery_revision"]),
                    "ownerSessionId": str(row["current_owner_session_id"]),
                    "reason": reason[:2000],
                },
                updates={
                    "state": "delivery_seal_uncertain",
                    "attention_required": 1,
                    "terminal_reason": reason[:2000],
                    "cleanup_state": "retained",
                },
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

    def claim_delivery_seal_resume(
        self,
        binding_id: str,
        *,
        resume_ref: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Acquire the one durable CAS lease allowed to finish a sealed delivery."""

        resume_ref = _required_text(resume_ref, "resume_ref")
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="source_lease_revoked",
            ) is not None:
                raise RoomWorkspaceLedgerConflict(
                    "delivery source lease is already durably revoked"
                )
            state = str(row["state"])
            prior = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="delivery_seal_resume_started",
            )
            if state == "delivery_seal_resuming":
                if prior is None:
                    raise RoomWorkspaceLedgerConflict(
                        "delivery-seal resume projection lacks its CAS receipt"
                    )
                prior_payload = self._event_payload_json(prior)
                if str(prior_payload.get("resumeRef") or "") != resume_ref:
                    raise RoomWorkspaceLedgerConflict(
                        "delivery-seal resume already has a different owner"
                    )
                result = _binding_payload(row)
                result["deliverySealResumeToken"] = str(
                    prior_payload.get("resumeToken") or ""
                )
                return result
            if state not in {"delivered", "delivery_seal_uncertain"}:
                raise RoomWorkspaceLedgerError(
                    "delivery-seal resume requires sealed uncertainty"
                )
            token = str(uuid.uuid4())
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="delivery_seal_resume_started",
                idempotency_key=(
                    f"delivery-seal-resume:{resume_ref}:"
                    f"{int(row['last_event_sequence']) + 1}"
                ),
                actor_ref=actor_ref,
                payload={
                    "deliveryRevision": str(row["delivery_revision"]),
                    "ownerSessionId": str(row["current_owner_session_id"]),
                    "resumeRef": resume_ref,
                    "resumeToken": token,
                    "resumeTokenSha256": hashlib.sha256(
                        token.encode("utf-8")
                    ).hexdigest(),
                },
                updates={
                    "state": "delivery_seal_resuming",
                    "attention_required": 1,
                    "cleanup_state": "retained",
                },
                now_ms=now_ms,
            )
            result = _binding_payload(self._binding_row(conn, binding_id))
            result["deliverySealResumeToken"] = token
            return result

    def record_source_lease_revoked(
        self,
        binding_id: str,
        *,
        delivery_revision: str,
        workspace_snapshot_sha256: str,
        patch_sha256: str,
        patch_artifact_path: str,
        patch_artifact_size: int,
        owner_session_id: str,
        revoked_policy_sha256: str,
        workspace_content_sha256: str,
        changed_files: Sequence[str],
        actor_ref: str,
        now_ms: int,
        delivery_seal_resume_token: str = "",
    ) -> dict[str, object]:
        """Receipt the coordinator's durable withdrawal of worker write access.

        The sealed patch belongs to the coordinator, not to the still-present
        child worktree.  Integration and cleanup both require this receipt so a
        delivered-but-not-quiesced worker can never authorize target mutation or
        destructive cleanup.
        """

        delivery_revision = _required_text(
            delivery_revision,
            "delivery_revision",
        )
        workspace_snapshot = _sha256_text(
            workspace_snapshot_sha256,
            "workspace_snapshot_sha256",
        )
        patch_sha256 = _sha256_text(patch_sha256, "patch_sha256")
        patch_artifact_path = _required_text(
            patch_artifact_path,
            "patch_artifact_path",
        )
        patch_artifact_size = _non_negative_int(
            patch_artifact_size,
            "patch_artifact_size",
        )
        owner_session_id = _required_text(owner_session_id, "owner_session_id")
        revoked_policy_sha256 = _sha256_text(
            revoked_policy_sha256,
            "revoked_policy_sha256",
        )
        workspace_content_sha256 = _sha256_text(
            workspace_content_sha256,
            "workspace_content_sha256",
        )
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            state = str(row["state"])
            if state not in {"delivered", "delivery_seal_resuming"}:
                raise RoomWorkspaceLedgerError(
                    "source write-lease revocation requires a delivered binding"
                )
            resume_receipt_id = ""
            resume_receipt_sha256 = ""
            if state == "delivery_seal_resuming":
                resume = self._latest_event_row_conn(
                    conn,
                    binding_id=binding_id,
                    event_kind="delivery_seal_resume_started",
                )
                if resume is None:
                    raise RoomWorkspaceLedgerConflict(
                        "delivery-seal resume receipt is missing"
                    )
                resume_payload = self._event_payload_json(resume)
                if (
                    not delivery_seal_resume_token
                    or str(resume_payload.get("resumeToken") or "")
                    != delivery_seal_resume_token
                ):
                    raise RoomWorkspaceLedgerConflict(
                        "delivery-seal resume lost its CAS token"
                    )
                resume_receipt_id = str(resume["event_id"])
                resume_receipt_sha256 = str(resume["payload_sha256"])
            delivery = self._delivery_evidence_conn(conn, row)
            expected = {
                "deliveryRevision": delivery["deliveryRevision"],
                "workspaceSnapshotSha256": delivery["workspaceSnapshotSha256"],
                "patchSha256": delivery["patchSha256"],
            }
            supplied = {
                "deliveryRevision": delivery_revision,
                "workspaceSnapshotSha256": workspace_snapshot,
                "patchSha256": patch_sha256,
            }
            if supplied != expected:
                raise RoomWorkspaceLedgerConflict(
                    "source write-lease receipt does not match delivered evidence"
                )
            if owner_session_id != str(row["current_owner_session_id"]):
                raise RoomWorkspaceLedgerConflict(
                    "source write-lease receipt does not match the current owner Session"
                )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="source_lease_revoked",
                idempotency_key=f"source-lease-revoked:{delivery_revision}",
                actor_ref=actor_ref,
                payload={
                    **supplied,
                    "patchArtifactPath": patch_artifact_path,
                    "patchArtifactSize": patch_artifact_size,
                    "ownerSessionId": owner_session_id,
                    "revokedPolicySha256": revoked_policy_sha256,
                    "workspaceContentSha256": workspace_content_sha256,
                    "changedFiles": _normalized_text_list(changed_files),
                    "deliverySealResumeReceiptId": resume_receipt_id,
                    "deliverySealResumeReceiptSha256": resume_receipt_sha256,
                },
                updates={
                    "state": "delivered",
                    "attention_required": 0,
                    "terminal_reason": "",
                    "cleanup_state": "not_authorized",
                },
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

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
            source_lease = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="source_lease_revoked",
            )
            if source_lease is None:
                raise RoomWorkspaceLedgerError(
                    "integration requires a durable source write-lease revocation receipt"
                )
            source_lease_payload = self._event_payload_json(source_lease)
            if patch_sha256 != str(delivery["patchSha256"]):
                raise RoomWorkspaceLedgerConflict(
                    "integration patch does not match the delivered patch receipt"
                )
            if any(
                str(source_lease_payload.get(key) or "") != str(expected)
                for key, expected in {
                    "deliveryRevision": delivery["deliveryRevision"],
                    "workspaceSnapshotSha256": delivery[
                        "workspaceSnapshotSha256"
                    ],
                    "patchSha256": delivery["patchSha256"],
                }.items()
            ):
                raise RoomWorkspaceLedgerConflict(
                    "integration source lease is not bound to delivered evidence"
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
                    "sourceLeaseReceiptId": str(source_lease["event_id"]),
                    "sourceLeaseReceiptSha256": str(
                        source_lease["payload_sha256"]
                    ),
                    "patchArtifactPath": source_lease_payload[
                        "patchArtifactPath"
                    ],
                    "patchArtifactSize": source_lease_payload[
                        "patchArtifactSize"
                    ],
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

    def record_target_applied(
        self,
        binding_id: str,
        *,
        integration_ref: str,
        patch_sha256: str,
        target_before_snapshot_sha256: str,
        target_after_snapshot_sha256: str,
        target_snapshot_provider: Callable[[], str],
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Persist the exact target transition while rechecking it in-transaction."""

        integration_ref = _required_text(integration_ref, "integration_ref")
        patch_sha256 = _sha256_text(patch_sha256, "patch_sha256")
        target_before = _sha256_text(
            target_before_snapshot_sha256,
            "target_before_snapshot_sha256",
        )
        target_after = _sha256_text(
            target_after_snapshot_sha256,
            "target_after_snapshot_sha256",
        )
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if str(row["state"]) != "integration_started":
                raise RoomWorkspaceLedgerError(
                    "target-applied receipt requires an active integration lease"
                )
            if (
                str(row["integration_ref"]) != integration_ref
                or str(row["integration_patch_sha256"]) != patch_sha256
            ):
                raise RoomWorkspaceLedgerConflict(
                    "target-applied receipt does not match its integration lease"
                )
            start = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="integration_started",
            )
            source_lease = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="source_lease_revoked",
            )
            if start is None or source_lease is None:
                raise RoomWorkspaceLedgerError(
                    "target-applied receipt requires source and integration receipts"
                )
            start_payload = self._event_payload_json(start)
            source_payload = self._event_payload_json(source_lease)
            if target_before != str(
                start_payload.get("targetBeforeSnapshotSha256") or ""
            ):
                raise RoomWorkspaceLedgerConflict(
                    "target-applied receipt changed the receipted target-before snapshot"
                )
            if (
                str(start_payload.get("sourceLeaseReceiptId") or "")
                != str(source_lease["event_id"])
                or str(start_payload.get("sourceLeaseReceiptSha256") or "")
                != str(source_lease["payload_sha256"])
                or str(source_payload.get("patchSha256") or "") != patch_sha256
            ):
                raise RoomWorkspaceLedgerConflict(
                    "target-applied receipt is not bound to the source lease"
                )
            observed = _sha256_text(
                target_snapshot_provider(),
                "observed_target_snapshot_sha256",
            )
            if observed != target_after:
                raise RoomWorkspaceLedgerConflict(
                    "integration target changed before target-applied receipt"
                )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="target_applied",
                idempotency_key=f"target-applied:{integration_ref}:{target_after}",
                actor_ref=actor_ref,
                payload={
                    "integrationRef": integration_ref,
                    "patchSha256": patch_sha256,
                    "targetBeforeSnapshotSha256": target_before,
                    "targetAfterSnapshotSha256": target_after,
                    "sourceLeaseReceiptId": str(source_lease["event_id"]),
                    "sourceLeaseReceiptSha256": str(
                        source_lease["payload_sha256"]
                    ),
                    "patchArtifactPath": source_payload["patchArtifactPath"],
                    "patchArtifactSize": source_payload["patchArtifactSize"],
                },
                updates={},
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
        target_snapshot_provider: Callable[[], str],
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
            target_applied = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="target_applied",
            )
            source_lease = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="source_lease_revoked",
            )
            if target_applied is None or source_lease is None:
                raise RoomWorkspaceLedgerError(
                    "integration receipt requires target-applied and source-lease receipts"
                )
            target_payload = self._event_payload_json(target_applied)
            if any(
                str(target_payload.get(key) or "") != str(expected)
                for key, expected in {
                    "integrationRef": integration_ref,
                    "patchSha256": patch_sha256,
                    "targetAfterSnapshotSha256": integrated_snapshot,
                    "sourceLeaseReceiptId": source_lease["event_id"],
                    "sourceLeaseReceiptSha256": source_lease["payload_sha256"],
                }.items()
            ):
                raise RoomWorkspaceLedgerConflict(
                    "integration receipt is not bound to the exact target transition"
                )
            observed = _sha256_text(
                target_snapshot_provider(),
                "observed_target_snapshot_sha256",
            )
            if observed != integrated_snapshot:
                raise RoomWorkspaceLedgerConflict(
                    "integration target changed before its durable receipt"
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
                    "targetAppliedReceiptId": str(target_applied["event_id"]),
                    "targetAppliedReceiptSha256": str(
                        target_applied["payload_sha256"]
                    ),
                    "sourceLeaseReceiptId": str(source_lease["event_id"]),
                    "sourceLeaseReceiptSha256": str(
                        source_lease["payload_sha256"]
                    ),
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

    def record_writer_quiescence(
        self,
        binding_id: str,
        *,
        receipt: Mapping[str, object],
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Receipt exact-lineage proof that no child writer can survive cleanup."""

        now_ms = _non_negative_int(now_ms, "now_ms")
        payload = dict(receipt)
        foreground, background, managed = _writer_quiescence_evidence(payload)
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if str(row["state"]) not in {
                "integrated",
                "cleanup_failed",
            }:
                raise RoomWorkspaceLedgerError(
                    "writer quiescence requires integrated cleanup authority"
                )
            source = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="source_lease_revoked",
            )
            integrated = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="integrated",
            )
            if source is None or integrated is None:
                raise RoomWorkspaceLedgerError(
                    "writer quiescence requires source and integration receipts"
                )
            expected = {
                "workspaceBindingId": binding_id,
                "rootId": str(row["root_id"]),
                "taskId": str(row["task_id"]),
                "dispatchId": str(row["dispatch_id"]),
                "deliveryRevision": str(row["delivery_revision"]),
                "ownerSessionId": str(row["current_owner_session_id"]),
                "sourceLeaseReceiptId": str(source["event_id"]),
                "sourceLeaseReceiptSha256": str(source["payload_sha256"]),
                "integratedReceiptId": str(integrated["event_id"]),
                "integratedReceiptSha256": str(integrated["payload_sha256"]),
            }
            if any(
                str(payload.get(key) or "") != value
                for key, value in expected.items()
            ):
                raise RoomWorkspaceLedgerConflict(
                    "writer-quiescence receipt does not match exact workspace lineage"
                )
            if str(managed.get("sessionId") or "") != expected[
                "ownerSessionId"
            ] or str(managed.get("dispatchId") or "") != expected[
                "dispatchId"
            ]:
                raise RoomWorkspaceLedgerConflict(
                    "managed Pi settlement does not match the workspace owner lineage"
                )
            encoded = _json(payload)
            receipt_sha256 = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="writer_quiescent",
                idempotency_key=f"writer-quiescent:{receipt_sha256}",
                actor_ref=actor_ref,
                payload=payload,
                updates={},
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

    def record_abandonment_quiescence(
        self,
        binding_id: str,
        *,
        workspace_content_sha256: str,
        revoked_policy_sha256: str,
        receipt: Mapping[str, object],
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Receipt lease revocation and exact writer settlement before abandon."""

        workspace_content = _sha256_text(
            workspace_content_sha256,
            "workspace_content_sha256",
        )
        revoked_policy = _sha256_text(
            revoked_policy_sha256,
            "revoked_policy_sha256",
        )
        now_ms = _non_negative_int(now_ms, "now_ms")
        payload = dict(receipt)
        _foreground, _background, managed = _writer_quiescence_evidence(payload)
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if not bool(row["attention_required"]) or str(row["state"]) in {
                "integrated",
                "cleaned",
                "abandoned",
                "cleanup_failed",
            }:
                raise RoomWorkspaceLedgerError(
                    "abandonment quiescence requires a retained attention-state binding"
                )
            expected = {
                "workspaceBindingId": binding_id,
                "rootId": str(row["root_id"]),
                "taskId": str(row["task_id"]),
                "dispatchId": str(row["dispatch_id"]),
                "ownerSessionId": str(row["current_owner_session_id"]),
                "workspaceContentSha256": workspace_content,
                "revokedPolicySha256": revoked_policy,
            }
            if any(
                str(payload.get(key) or "") != value
                for key, value in expected.items()
            ):
                raise RoomWorkspaceLedgerConflict(
                    "abandonment writer-quiescence receipt does not match exact workspace lineage"
                )
            if (
                str(managed.get("sessionId") or "") != expected["ownerSessionId"]
                or str(managed.get("dispatchId") or "") != expected["dispatchId"]
            ):
                raise RoomWorkspaceLedgerConflict(
                    "abandonment managed Pi settlement does not match the owner lineage"
                )
            encoded = _json(payload)
            receipt_sha256 = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="abandonment_writer_quiescent",
                idempotency_key=f"abandonment-writer-quiescent:{receipt_sha256}",
                actor_ref=actor_ref,
                payload=payload,
                updates={},
                now_ms=now_ms,
            )
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

    def record_quarantined(
        self,
        binding_id: str,
        *,
        quarantined_workspace_root: str,
        workspace_content_sha256: str,
        target_snapshot_sha256: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        quarantined_workspace_root = _required_text(
            quarantined_workspace_root,
            "quarantined_workspace_root",
        )
        workspace_content_sha256 = _sha256_text(
            workspace_content_sha256,
            "workspace_content_sha256",
        )
        target_snapshot_sha256 = _sha256_text(
            target_snapshot_sha256,
            "target_snapshot_sha256",
        )
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if str(row["state"]) not in {
                "integrated",
                "cleanup_failed",
                "abandoned",
            }:
                raise RoomWorkspaceLedgerError(
                    "workspace quarantine requires integration or abandonment authority"
                )
            source = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="source_lease_revoked",
            )
            quiescence = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="writer_quiescent",
            )
            integrated = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="integrated",
            )
            payload: dict[str, object] = {
                "originalWorkspaceRoot": str(row["workspace_root"]),
                "quarantinedWorkspaceRoot": quarantined_workspace_root,
                "workspaceContentSha256": workspace_content_sha256,
                "targetSnapshotSha256": target_snapshot_sha256,
            }
            if str(row["state"]) in {"integrated", "cleanup_failed"} and integrated is not None:
                if source is None or quiescence is None:
                    raise RoomWorkspaceLedgerError(
                        "workspace quarantine requires source, integration, and "
                        "writer-quiescence receipts"
                    )
                source_payload = self._event_payload_json(source)
                if str(source_payload.get("workspaceContentSha256") or "") != (
                    workspace_content_sha256
                ):
                    raise RoomWorkspaceLedgerConflict(
                        "workspace quarantine content does not match source authority"
                    )
                if target_snapshot_sha256 != str(row["integrated_snapshot_sha256"]):
                    raise RoomWorkspaceLedgerConflict(
                        "workspace quarantine target does not match integrated authority"
                    )
                payload.update(
                    {
                        "authorityKind": "integration",
                        "sourceLeaseReceiptId": str(source["event_id"]),
                        "sourceLeaseReceiptSha256": str(source["payload_sha256"]),
                        "integratedReceiptId": str(integrated["event_id"]),
                        "integratedReceiptSha256": str(integrated["payload_sha256"]),
                        "writerQuiescenceReceiptId": str(quiescence["event_id"]),
                        "writerQuiescenceReceiptSha256": str(
                            quiescence["payload_sha256"]
                        ),
                    }
                )
            else:
                abandonment_quiescence = self._latest_event_row_conn(
                    conn,
                    binding_id=binding_id,
                    event_kind="abandonment_writer_quiescent",
                )
                abandonment = self._latest_event_row_conn(
                    conn,
                    binding_id=binding_id,
                    event_kind="abandoned",
                )
                if abandonment_quiescence is None or abandonment is None:
                    raise RoomWorkspaceLedgerError(
                        "workspace quarantine requires abandonment and writer-quiescence receipts"
                    )
                abandonment_quiescence_payload = self._event_payload_json(
                    abandonment_quiescence
                )
                if str(
                    abandonment_quiescence_payload.get("workspaceContentSha256") or ""
                ) != workspace_content_sha256:
                    raise RoomWorkspaceLedgerConflict(
                        "workspace quarantine content does not match abandonment authority"
                    )
                payload.update(
                    {
                        "authorityKind": "abandonment",
                        "abandonmentReceiptId": str(abandonment["event_id"]),
                        "abandonmentReceiptSha256": str(abandonment["payload_sha256"]),
                        "writerQuiescenceReceiptId": str(
                            abandonment_quiescence["event_id"]
                        ),
                        "writerQuiescenceReceiptSha256": str(
                            abandonment_quiescence["payload_sha256"]
                        ),
                    }
                )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="quarantined",
                idempotency_key=(
                    f"quarantined:{workspace_content_sha256}:"
                    f"{target_snapshot_sha256}"
                ),
                actor_ref=actor_ref,
                payload=payload,
                updates={},
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

    def authorize_cleanup_removal(
        self,
        binding_id: str,
        *,
        quarantined_workspace_root: str,
        vault_workspace_root: str,
        workspace_content_sha256: str,
        target_snapshot_sha256: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        """CAS exact cleanup lineage and its recoverable vault destination."""

        quarantined_root = _required_text(
            quarantined_workspace_root,
            "quarantined_workspace_root",
        )
        vault_root = _required_text(vault_workspace_root, "vault_workspace_root")
        workspace_content = _sha256_text(
            workspace_content_sha256,
            "workspace_content_sha256",
        )
        target_snapshot = _sha256_text(
            target_snapshot_sha256,
            "target_snapshot_sha256",
        )
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if str(row["state"]) not in {
                "integrated",
                "cleanup_failed",
                "abandoned",
            }:
                raise RoomWorkspaceLedgerError(
                    "cleanup removal authorization requires terminal workspace authority"
                )
            quarantine = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="quarantined",
            )
            if quarantine is None:
                raise RoomWorkspaceLedgerError(
                    "cleanup removal authorization requires a quarantine receipt"
                )
            quarantine_payload = self._event_payload_json(quarantine)
            if any(
                str(quarantine_payload.get(key) or "") != expected
                for key, expected in {
                    "quarantinedWorkspaceRoot": quarantined_root,
                    "workspaceContentSha256": workspace_content,
                    "targetSnapshotSha256": target_snapshot,
                }.items()
            ):
                raise RoomWorkspaceLedgerConflict(
                    "cleanup removal authorization changed quarantined evidence"
                )
            writer_id = str(
                quarantine_payload.get("writerQuiescenceReceiptId") or ""
            )
            writer_sha = str(
                quarantine_payload.get("writerQuiescenceReceiptSha256") or ""
            )
            writer = conn.execute(
                "SELECT * FROM room_workspace_events WHERE event_id=? AND binding_id=?",
                (writer_id, binding_id),
            ).fetchone()
            if (
                writer is None
                or str(writer["payload_sha256"]) != writer_sha
                or str(writer["event_kind"])
                not in {"writer_quiescent", "abandonment_writer_quiescent"}
            ):
                raise RoomWorkspaceLedgerConflict(
                    "cleanup removal authorization lost writer-quiescence lineage"
                )
            payload = {
                "quarantinedWorkspaceRoot": quarantined_root,
                "vaultWorkspaceRoot": vault_root,
                "workspaceContentSha256": workspace_content,
                "targetSnapshotSha256": target_snapshot,
                "quarantineReceiptId": str(quarantine["event_id"]),
                "quarantineReceiptSha256": str(quarantine["payload_sha256"]),
                "writerQuiescenceReceiptId": writer_id,
                "writerQuiescenceReceiptSha256": writer_sha,
            }
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="cleanup_removal_authorized",
                idempotency_key=(
                    f"cleanup-removal-authorized:{quarantine['event_id']}:"
                    f"{workspace_content}:{target_snapshot}"
                ),
                actor_ref=actor_ref,
                payload=payload,
                updates={},
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

    def record_vaulted(
        self,
        binding_id: str,
        *,
        removal_authorization_receipt_id: str,
        removal_authorization_receipt_sha256: str,
        quarantined_workspace_root: str,
        vault_workspace_root: str,
        authorized_workspace_content_sha256: str,
        vault_content_sha256: str,
        target_snapshot_sha256: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        """Receipt bytes after the atomic active-path-to-vault rename."""

        authorization_id = _required_text(
            removal_authorization_receipt_id,
            "removal_authorization_receipt_id",
        )
        authorization_sha256 = _sha256_text(
            removal_authorization_receipt_sha256,
            "removal_authorization_receipt_sha256",
        )
        quarantined_root = _required_text(
            quarantined_workspace_root,
            "quarantined_workspace_root",
        )
        vault_root = _required_text(vault_workspace_root, "vault_workspace_root")
        authorized_content = _sha256_text(
            authorized_workspace_content_sha256,
            "authorized_workspace_content_sha256",
        )
        vaulted_content = _sha256_text(
            vault_content_sha256,
            "vault_content_sha256",
        )
        target_snapshot = _sha256_text(
            target_snapshot_sha256,
            "target_snapshot_sha256",
        )
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if str(row["state"]) not in {
                "integrated",
                "cleanup_failed",
                "abandoned",
            }:
                raise RoomWorkspaceLedgerError(
                    "workspace vault receipt requires terminal workspace authority"
                )
            authorization = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="cleanup_removal_authorized",
            )
            if authorization is None or any(
                str(actual) != str(expected)
                for actual, expected in (
                    (authorization["event_id"], authorization_id),
                    (authorization["payload_sha256"], authorization_sha256),
                )
            ):
                raise RoomWorkspaceLedgerConflict(
                    "workspace vault receipt lost its cleanup CAS authority"
                )
            authorization_payload = self._event_payload_json(authorization)
            if any(
                str(authorization_payload.get(key) or "") != str(expected)
                for key, expected in {
                    "quarantinedWorkspaceRoot": quarantined_root,
                    "vaultWorkspaceRoot": vault_root,
                    "workspaceContentSha256": authorized_content,
                    "targetSnapshotSha256": target_snapshot,
                }.items()
            ):
                raise RoomWorkspaceLedgerConflict(
                    "workspace vault receipt changed its authorized source, target, or destination"
                )
            payload = {
                "quarantinedWorkspaceRoot": quarantined_root,
                "vaultWorkspaceRoot": vault_root,
                "authorizedWorkspaceContentSha256": authorized_content,
                "vaultContentSha256": vaulted_content,
                "targetSnapshotSha256": target_snapshot,
                "removalAuthorizationReceiptId": authorization_id,
                "removalAuthorizationReceiptSha256": authorization_sha256,
                "quarantineReceiptId": str(
                    authorization_payload.get("quarantineReceiptId") or ""
                ),
                "quarantineReceiptSha256": str(
                    authorization_payload.get("quarantineReceiptSha256") or ""
                ),
                "writerQuiescenceReceiptId": str(
                    authorization_payload.get("writerQuiescenceReceiptId") or ""
                ),
                "writerQuiescenceReceiptSha256": str(
                    authorization_payload.get("writerQuiescenceReceiptSha256") or ""
                ),
                "rootId": str(row["root_id"]),
                "taskId": str(row["task_id"]),
                "dispatchId": str(row["dispatch_id"]),
                "ownerParticipantId": str(row["current_owner_participant_id"]),
                "ownerSessionId": str(row["current_owner_session_id"]),
                "authoritySequence": int(authorization["sequence"]),
            }
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="vaulted",
                idempotency_key=f"vaulted:{authorization_id}",
                actor_ref=actor_ref,
                payload=payload,
                updates={},
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

    def record_cleanup(
        self,
        binding_id: str,
        *,
        result: str,
        reason: str,
        actor_ref: str,
        now_ms: int,
        retained_workspace_root: str = "",
    ) -> dict[str, object]:
        if result not in {"cleaned", "missing", "failed"}:
            raise RoomWorkspaceLedgerError("workspace cleanup result is invalid")
        successful = result in {"cleaned", "missing"}
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if str(row["state"]) not in {
                "integrated",
                "cleaned",
                "abandoned",
                "cleanup_failed",
            }:
                raise RoomWorkspaceLedgerError(
                    "workspace cleanup requires integrated or abandoned authority"
                )
            payload: dict[str, object] = {
                "result": result,
                "reason": str(reason or "")[:2000],
                "retainedWorkspaceRoot": str(
                    retained_workspace_root or ""
                ).strip(),
            }
            if successful:
                authorization = self._latest_event_row_conn(
                    conn,
                    binding_id=binding_id,
                    event_kind="cleanup_removal_authorized",
                )
                if authorization is None:
                    raise RoomWorkspaceLedgerError(
                        "successful cleanup requires exact removal authorization"
                    )
                authorization_payload = self._event_payload_json(authorization)
                payload.update(
                    {
                        "removalAuthorizationReceiptId": str(
                            authorization["event_id"]
                        ),
                        "removalAuthorizationReceiptSha256": str(
                            authorization["payload_sha256"]
                        ),
                        "quarantineReceiptId": str(
                            authorization_payload.get("quarantineReceiptId") or ""
                        ),
                        "quarantineReceiptSha256": str(
                            authorization_payload.get("quarantineReceiptSha256") or ""
                        ),
                        "writerQuiescenceReceiptId": str(
                            authorization_payload.get(
                                "writerQuiescenceReceiptId"
                            )
                            or ""
                        ),
                        "writerQuiescenceReceiptSha256": str(
                            authorization_payload.get(
                                "writerQuiescenceReceiptSha256"
                            )
                            or ""
                        ),
                    }
                )
                if result == "cleaned":
                    vault = self._latest_event_row_conn(
                        conn,
                        binding_id=binding_id,
                        event_kind="vaulted",
                    )
                    if vault is None:
                        raise RoomWorkspaceLedgerError(
                            "cleaned workspace requires a recoverable vault receipt"
                        )
                    vault_payload = self._event_payload_json(vault)
                    if any(
                        str(vault_payload.get(key) or "") != str(expected)
                        for key, expected in {
                            "removalAuthorizationReceiptId": authorization[
                                "event_id"
                            ],
                            "removalAuthorizationReceiptSha256": authorization[
                                "payload_sha256"
                            ],
                        }.items()
                    ):
                        raise RoomWorkspaceLedgerConflict(
                            "cleaned workspace vault is outside its removal authority"
                        )
                    vault_root = str(vault_payload.get("vaultWorkspaceRoot") or "")
                    if (
                        not vault_root
                        or str(retained_workspace_root or "").strip() != vault_root
                    ):
                        raise RoomWorkspaceLedgerConflict(
                            "cleaned workspace must retain its exact recoverable vault path"
                        )
                    payload.update(
                        {
                            "retainedWorkspaceRoot": vault_root,
                            "vaultWorkspaceRoot": vault_root,
                            "vaultContentSha256": str(
                                vault_payload.get("vaultContentSha256") or ""
                            ),
                            "vaultReceiptId": str(vault["event_id"]),
                            "vaultReceiptSha256": str(vault["payload_sha256"]),
                        }
                    )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="cleaned" if successful else "cleanup_failed",
                idempotency_key=(
                    f"cleanup:{result}:"
                    f"{hashlib.sha256(str(reason).encode()).hexdigest()}"
                ),
                actor_ref=actor_ref,
                payload=payload,
                updates={
                    "state": "cleaned" if successful else "cleanup_failed",
                    "attention_required": 0 if successful else 1,
                    "cleanup_state": result,
                    "terminal_reason": (
                        "" if successful else str(reason or "")[:2000]
                    ),
                },
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

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
        participant_ref: str,
        session_id: str,
        workspace_snapshot_sha256: str,
        reason: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        participant_id = _required_text(participant_id, "participant_id")
        participant_ref = _required_text(participant_ref, "participant_ref")
        session_id = _required_text(session_id, "session_id")
        snapshot = _sha256_text(workspace_snapshot_sha256, "workspace_snapshot_sha256")
        reason = _required_text(reason, "reason")
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="integrated",
            ) is not None or str(row["state"]) in {
                "integrated",
                "cleaned",
                "abandoned",
                "cleanup_failed",
            }:
                raise RoomWorkspaceLedgerError(
                    "integrated or cleanup-terminal workspace can never receive a "
                    "new write lease"
                )
            if not bool(row["attention_required"]):
                raise RoomWorkspaceLedgerConflict(
                    "workspace retry lost its attention-state compare-and-swap"
                )
            retry_token = str(uuid.uuid4())
            retry_epoch = int(row["last_event_sequence"]) + 1
            payload = {
                "participantId": participant_id,
                "participantRef": participant_ref,
                "sessionId": session_id,
                "workspaceSnapshotSha256": snapshot,
                "reason": reason[:2000],
                "retryEpoch": retry_epoch,
                "retryLeaseToken": retry_token,
                "retryLeaseTokenSha256": hashlib.sha256(
                    retry_token.encode("utf-8")
                ).hexdigest(),
            }
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="retry_bound",
                idempotency_key=(
                    f"retry:{retry_epoch}:{session_id}:{snapshot}:"
                    f"{hashlib.sha256(reason.encode()).hexdigest()}"
                ),
                actor_ref=actor_ref,
                payload=payload,
                updates={
                    "state": "retry_bound",
                    "attention_required": 0,
                    "current_owner_participant_id": participant_id,
                    "current_owner_session_id": session_id,
                    "terminal_reason": "",
                    "cleanup_state": "not_authorized",
                },
                now_ms=now_ms,
            )
            result = _binding_payload(self._binding_row(conn, binding_id))
            result["retryEpoch"] = retry_epoch
            result["retryLeaseToken"] = retry_token
            result["retryLeaseTokenSha256"] = payload[
                "retryLeaseTokenSha256"
            ]
            retry_receipt = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="retry_bound",
            )
            assert retry_receipt is not None
            result["retryBoundReceiptId"] = str(retry_receipt["event_id"])
            result["retryBoundReceiptSha256"] = str(
                retry_receipt["payload_sha256"]
            )
            result["targetParticipantRef"] = participant_ref
            return result

    def assert_retry_lease(
        self,
        binding_id: str,
        *,
        participant_id: str,
        participant_ref: str,
        session_id: str,
        retry_lease_token: str,
    ) -> dict[str, object]:
        participant_id = _required_text(participant_id, "participant_id")
        participant_ref = _required_text(participant_ref, "participant_ref")
        session_id = _required_text(session_id, "session_id")
        retry_lease_token = _required_text(
            retry_lease_token,
            "retry_lease_token",
        )
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            event = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="retry_bound",
            )
            if event is None:
                raise RoomWorkspaceLedgerConflict(
                    "workspace retry lease receipt is missing"
                )
            payload = self._event_payload_json(event)
            if (
                str(row["state"]) != "retry_bound"
                or bool(row["attention_required"])
                or str(row["current_owner_participant_id"]) != participant_id
                or str(row["current_owner_session_id"]) != session_id
                or str(payload.get("participantId") or "") != participant_id
                or str(payload.get("participantRef") or "") != participant_ref
                or str(payload.get("sessionId") or "") != session_id
                or str(payload.get("retryLeaseToken") or "")
                != retry_lease_token
            ):
                raise RoomWorkspaceLedgerConflict(
                    "workspace retry lease lost its owner or epoch fence"
                )
            return _binding_payload(row)

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
        now_ms = _non_negative_int(now_ms, "now_ms")
        with self._connect(immediate=True) as conn:
            row = self._binding_row(conn, binding_id)
            if not bool(row["attention_required"]):
                raise RoomWorkspaceLedgerError(
                    "workspace abandonment requires an attention-state binding"
                )
            quiescence = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="abandonment_writer_quiescent",
            )
            if quiescence is None:
                raise RoomWorkspaceLedgerError(
                    "workspace abandonment requires durable writer quiescence"
                )
            quiescence_payload = self._event_payload_json(quiescence)
            if str(quiescence_payload.get("workspaceContentSha256") or "") != snapshot:
                raise RoomWorkspaceLedgerConflict(
                    "workspace abandonment snapshot changed after writer quiescence"
                )
            self._append_event_conn(
                conn,
                binding_id=binding_id,
                event_kind="abandoned",
                idempotency_key=(
                    f"abandon:{snapshot}:"
                    f"{hashlib.sha256(reason.encode()).hexdigest()}"
                ),
                actor_ref=actor_ref,
                payload={
                    "reason": reason[:2000],
                    "workspaceSnapshotSha256": snapshot,
                    "acceptanceAliases": _normalized_text_list(
                        acceptance_aliases
                    ),
                    "writerQuiescenceReceiptId": str(quiescence["event_id"]),
                    "writerQuiescenceReceiptSha256": str(
                        quiescence["payload_sha256"]
                    ),
                    "revokedPolicySha256": str(
                        quiescence_payload.get("revokedPolicySha256") or ""
                    ),
                },
                updates={
                    "state": "abandoned",
                    "attention_required": 0,
                    "terminal_reason": reason[:2000],
                    "cleanup_state": "authorized",
                },
                now_ms=now_ms,
            )
            return _binding_payload(self._binding_row(conn, binding_id))

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

    def active_binding_for_session(
        self,
        session_id: str,
    ) -> dict[str, object] | None:
        """Return the exact isolated write lease currently owned by a Session."""

        session_id = _required_text(session_id, "session_id")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM room_workspace_bindings
                WHERE current_owner_session_id=?
                  AND workspace_policy='isolated_writable'
                  AND state IN ('reserved','materialized','work_started','retry_bound')
                ORDER BY updated_at_ms DESC, binding_id
                """,
                (session_id,),
            ).fetchall()
        if len(rows) > 1:
            raise RoomWorkspaceLedgerConflict(
                "Session owns more than one active isolated workspace lease"
            )
        return _binding_payload(rows[0]) if rows else None

    def events(self, binding_id: str) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM room_workspace_events
                WHERE binding_id=? ORDER BY sequence
                """,
                (binding_id,),
            ).fetchall()
        _assert_event_rows_integrity(rows)
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

    def cleaned_integration_projection_candidates(
        self,
    ) -> list[dict[str, object]]:
        """Read terminal integrations that may need a legacy Kernel backfill."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM room_workspace_bindings
                WHERE workspace_policy='isolated_writable'
                  AND state='cleaned'
                  AND cleanup_state='cleaned'
                  AND attention_required=0
                ORDER BY updated_at_ms, binding_id
                """
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
                SELECT * FROM room_workspace_events
                WHERE binding_id=? AND event_kind='integration_started'
                ORDER BY sequence DESC LIMIT 1
                """,
                (binding_id,),
            ).fetchone()
        if row is None:
            return None
        return self._event_payload_json(row)

    def delivery_payload(self, binding_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            return self._latest_event_payload_conn(
                conn,
                binding_id=binding_id,
                event_kind="delivered",
            )

    def delivery_receipt(self, binding_id: str) -> dict[str, object] | None:
        return self._latest_event_receipt(binding_id, "delivered")

    def source_lease_receipt(self, binding_id: str) -> dict[str, object] | None:
        return self._latest_event_receipt(binding_id, "source_lease_revoked")

    def target_applied_receipt(self, binding_id: str) -> dict[str, object] | None:
        return self._latest_event_receipt(binding_id, "target_applied")

    def integrated_receipt(self, binding_id: str) -> dict[str, object] | None:
        return self._latest_event_receipt(binding_id, "integrated")

    def writer_quiescence_receipt(
        self,
        binding_id: str,
    ) -> dict[str, object] | None:
        return self._latest_event_receipt(binding_id, "writer_quiescent")

    def abandonment_quiescence_receipt(
        self,
        binding_id: str,
    ) -> dict[str, object] | None:
        return self._latest_event_receipt(
            binding_id,
            "abandonment_writer_quiescent",
        )

    def retry_bound_receipt(self, binding_id: str) -> dict[str, object] | None:
        return self._latest_event_receipt(binding_id, "retry_bound")

    def quarantine_receipt(self, binding_id: str) -> dict[str, object] | None:
        return self._latest_event_receipt(binding_id, "quarantined")

    def cleanup_removal_authorization_receipt(
        self,
        binding_id: str,
    ) -> dict[str, object] | None:
        return self._latest_event_receipt(
            binding_id,
            "cleanup_removal_authorized",
        )

    def vault_receipt(self, binding_id: str) -> dict[str, object] | None:
        return self._latest_event_receipt(binding_id, "vaulted")

    def vaulted_workspace_roots(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM room_workspace_events
                WHERE event_kind='vaulted' ORDER BY created_at_ms, event_id
                """
            ).fetchall()
        _assert_event_rows_integrity(rows)
        roots: list[str] = []
        for row in rows:
            payload = self._event_payload_json(row)
            root = str(payload.get("vaultWorkspaceRoot") or "").strip()
            if root and root not in roots:
                roots.append(root)
        return roots

    def assert_cleanup_removal_authority(
        self,
        binding_id: str,
        *,
        receipt_id: str,
        receipt_sha256: str,
        quarantined_workspace_root: str,
        vault_workspace_root: str,
        workspace_content_sha256: str,
        target_snapshot_sha256: str,
    ) -> dict[str, object]:
        """Fail closed unless the latest removal CAS still owns exact evidence."""

        with self._connect() as conn:
            row = self._binding_row(conn, binding_id)
            if str(row["state"]) not in {
                "integrated",
                "cleanup_failed",
                "abandoned",
            }:
                raise RoomWorkspaceLedgerConflict(
                    "cleanup removal authority is no longer active"
                )
            event = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind="cleanup_removal_authorized",
            )
            if event is None or any(
                str(actual) != str(expected)
                for actual, expected in (
                    (event["event_id"], _required_text(receipt_id, "receipt_id")),
                    (
                        event["payload_sha256"],
                        _sha256_text(receipt_sha256, "receipt_sha256"),
                    ),
                )
            ):
                raise RoomWorkspaceLedgerConflict(
                    "cleanup removal receipt is stale or mismatched"
                )
            payload = self._event_payload_json(event)
            if any(
                str(payload.get(key) or "") != str(expected)
                for key, expected in {
                    "quarantinedWorkspaceRoot": _required_text(
                        quarantined_workspace_root,
                        "quarantined_workspace_root",
                    ),
                    "vaultWorkspaceRoot": _required_text(
                        vault_workspace_root,
                        "vault_workspace_root",
                    ),
                    "workspaceContentSha256": _sha256_text(
                        workspace_content_sha256,
                        "workspace_content_sha256",
                    ),
                    "targetSnapshotSha256": _sha256_text(
                        target_snapshot_sha256,
                        "target_snapshot_sha256",
                    ),
                }.items()
            ):
                raise RoomWorkspaceLedgerConflict(
                    "cleanup removal receipt changed exact source or target evidence"
                )
            return _event_payload(event)

    def cleanup_receipt(self, binding_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM room_workspace_events
                WHERE binding_id=? AND event_kind IN ('cleaned','cleanup_failed')
                ORDER BY sequence DESC LIMIT 1
                """,
                (binding_id,),
            ).fetchone()
        return _event_payload(row) if row is not None else None

    def _latest_event_receipt(
        self,
        binding_id: str,
        event_kind: str,
    ) -> dict[str, object] | None:
        with self._connect() as conn:
            row = self._latest_event_row_conn(
                conn,
                binding_id=binding_id,
                event_kind=event_kind,
            )
            return _event_payload(row) if row is not None else None

    @staticmethod
    def _latest_event_row_conn(
        conn: sqlite3.Connection,
        *,
        binding_id: str,
        event_kind: str,
    ) -> sqlite3.Row | None:
        rows = conn.execute(
            """
            SELECT * FROM room_workspace_events
            WHERE binding_id=? AND event_kind=?
            ORDER BY sequence DESC
            """,
            (binding_id, event_kind),
        ).fetchall()
        _assert_event_rows_integrity(rows)
        return rows[0] if rows else None

    @staticmethod
    def _event_payload_json(row: sqlite3.Row) -> dict[str, object]:
        return _validated_event_payload_json(row)

    @staticmethod
    def _latest_event_payload_conn(
        conn: sqlite3.Connection,
        *,
        binding_id: str,
        event_kind: str,
    ) -> dict[str, object] | None:
        row = RoomWorkspaceLedgerStore._latest_event_row_conn(
            conn,
            binding_id=binding_id,
            event_kind=event_kind,
        )
        if row is None:
            return None
        return RoomWorkspaceLedgerStore._event_payload_json(row)

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
            self._event_payload_json(existing)
            if (
                str(existing["event_kind"]) != event_kind
                or str(existing["payload_sha256"]) != payload_sha256
            ):
                raise RoomWorkspaceLedgerConflict(
                    "workspace event idempotency key was reused with different content"
                )
            return False
        if event_kind in _EXACT_AUTHORITY_EVENT_KINDS:
            exact_rows = conn.execute(
                """
                SELECT * FROM room_workspace_events
                WHERE binding_id=? AND event_kind=? AND payload_sha256=?
                """,
                (binding_id, event_kind, payload_sha256),
            ).fetchall()
            _assert_event_rows_integrity(exact_rows)
            if exact_rows:
                raise RoomWorkspaceLedgerConflict(
                    "workspace ledger contains duplicate exact authority"
                )
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
    payload = _validated_event_payload_json(row)
    return {
        "eventId": str(row["event_id"]),
        "workspaceBindingId": str(row["binding_id"]),
        "sequence": int(row["sequence"]),
        "eventKind": str(row["event_kind"]),
        "idempotencyKey": str(row["idempotency_key"]),
        "actorRef": str(row["actor_ref"]),
        "payloadSha256": str(row["payload_sha256"]),
        "payload": payload,
        "createdAtMs": int(row["created_at_ms"]),
    }


def _validated_event_payload_json(row: sqlite3.Row) -> dict[str, object]:
    try:
        binding_id = _required_text(row["binding_id"], "event binding_id")
        event_kind = _required_text(row["event_kind"], "event kind")
        idempotency_key = _required_text(
            row["idempotency_key"],
            "event idempotency_key",
        )
        event_id = _required_text(row["event_id"], "event id")
        sequence = int(row["sequence"])
        if sequence < 1:
            raise RoomWorkspaceLedgerError(
                "workspace event sequence must be positive"
            )
        raw_payload_json = str(row["payload_json"])
        payload = json.loads(raw_payload_json)
        if not isinstance(payload, Mapping):
            raise RoomWorkspaceLedgerError(
                "workspace event payload is not an object"
            )
        canonical_payload_json = _json(dict(payload))
        payload_sha256 = _sha256_text(
            row["payload_sha256"],
            "event payload_sha256",
        )
    except (
        IndexError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        RoomWorkspaceLedgerError,
    ) as exc:
        raise RoomWorkspaceLedgerConflict(
            "workspace event integrity check failed"
        ) from exc

    expected_event_id = _stable_id(
        "room-workspace-event",
        binding_id,
        str(sequence),
        event_kind,
        idempotency_key,
    )
    canonical_sha256 = hashlib.sha256(
        canonical_payload_json.encode("utf-8")
    ).hexdigest()
    if (
        str(row["binding_id"]) != binding_id
        or str(row["event_kind"]) != event_kind
        or str(row["idempotency_key"]) != idempotency_key
        or raw_payload_json != canonical_payload_json
        or payload_sha256 != canonical_sha256
        or event_id != expected_event_id
    ):
        raise RoomWorkspaceLedgerConflict(
            "workspace event integrity check failed"
        )
    return dict(payload)


def _assert_event_rows_integrity(rows: Sequence[sqlite3.Row]) -> None:
    exact_authorities: set[tuple[str, str, str]] = set()
    for row in rows:
        _validated_event_payload_json(row)
        event_kind = str(row["event_kind"])
        if event_kind not in _EXACT_AUTHORITY_EVENT_KINDS:
            continue
        identity = (
            str(row["binding_id"]),
            event_kind,
            str(row["payload_sha256"]),
        )
        if identity in exact_authorities:
            raise RoomWorkspaceLedgerConflict(
                "workspace ledger contains duplicate exact authority"
            )
        exact_authorities.add(identity)


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


def _writer_quiescence_evidence(
    payload: Mapping[str, object],
) -> tuple[Mapping[str, object], Mapping[str, object], Mapping[str, object]]:
    if payload.get("schemaVersion") != (
        "wisdom-weasel.room-workspace-writer-quiescence.v1"
    ):
        raise RoomWorkspaceLedgerError(
            "writer-quiescence receipt schema is invalid"
        )
    _required_text(payload.get("receiptRevision"), "receipt_revision")
    evidence_items: list[Mapping[str, object]] = []
    for field in (
        "foregroundMutatingInvocations",
        "backgroundWork",
        "managedPiTurn",
    ):
        evidence = payload.get(field)
        if not isinstance(evidence, Mapping):
            raise RoomWorkspaceLedgerError(
                f"writer-quiescence {field} evidence is missing"
            )
        if evidence.get("known") is not True:
            raise RoomWorkspaceLedgerConflict(
                f"writer-quiescence {field} evidence is unknown"
            )
        evidence_items.append(evidence)
    foreground, background, managed = evidence_items
    if foreground.get("activeCount") != 0:
        raise RoomWorkspaceLedgerConflict(
            "foreground mutating invocation registry is not quiescent"
        )
    if background.get("activeCount") != 0:
        raise RoomWorkspaceLedgerConflict(
            "background child registry is not quiescent"
        )
    if managed.get("settled") is not True:
        raise RoomWorkspaceLedgerConflict("managed Pi turn is not settled")
    return foreground, background, managed
