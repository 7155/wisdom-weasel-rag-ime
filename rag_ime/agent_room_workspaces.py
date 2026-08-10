from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .agent_sessions import AgentSessionStore
from .agent_room_workspace_ledger import (
    RoomWorkspaceLedgerConflict,
    RoomWorkspaceLedgerError,
    RoomWorkspaceLedgerStore,
)


class RoomWorkspaceError(RuntimeError):
    pass


_DELIVERY_MAX_FILES = 512
_DELIVERY_MAX_PATH_BYTES = 4_096
_DELIVERY_MAX_MANIFEST_BYTES = 256 * 1_024
_DELIVERY_SENSITIVE_NAMES = frozenset(
    {
        ".env",
        ".git-credentials",
        ".netrc",
        "auth.json",
        "credentials.json",
        "cookies.sqlite",
        "id_rsa",
        "id_ed25519",
    }
)
_DELIVERY_SENSITIVE_PARTS = frozenset(
    {".git", ".ssh", ".gnupg", ".aws", ".azure", ".keychain"}
)
_DELIVERY_SENSITIVE_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".sqlite",
    ".sqlite3",
    ".db",
)
_DELIVERY_GENERATED_PARTS = frozenset(
    {"dist", "build", "generated", "node_modules", "coverage", ".next"}
)
_REPOSITORY_LOCKS_GUARD = threading.Lock()
_REPOSITORY_LOCKS: dict[str, threading.RLock] = {}
_SYSTEM_GIT = "/usr/bin/git"
_GUARDED_CLEANUP_SCRIPT = Path(__file__).resolve(strict=True).with_name(
    "agent_room_workspace_cleanup.py"
)


class _PreparedWorkspace(dict[str, object]):
    """Keep per-attempt ownership without adding it to the Task contract."""

    def __init__(
        self,
        values: Mapping[str, object],
        *,
        created_by_attempt: bool,
    ) -> None:
        super().__init__(values)
        self.created_by_attempt = created_by_attempt


class RoomWorkspaceCoordinator:
    """Own linked worktrees and Session root rebinding for Room child work."""

    def __init__(
        self,
        *,
        root_dir: str | Path,
        sessions: AgentSessionStore,
        ledger: RoomWorkspaceLedgerStore | None = None,
        writer_quiescence_provider: (
            Callable[[Mapping[str, object]], Mapping[str, object]] | None
        ) = None,
        handle_inspector: Callable[[Path], Mapping[str, object]] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve(strict=False)
        self.sessions = sessions
        self.ledger = ledger or RoomWorkspaceLedgerStore(sessions.db_path)
        self.ledger.initialize()
        self._writer_quiescence_provider = writer_quiescence_provider
        self._handle_inspector = handle_inspector or self._inspect_open_handles
        self._removal_guards: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()
        # Startup is the only safe moment to classify a reservation that never
        # reached materialization and physical worktrees that have no ledger
        # owner.  The scan never deletes; it only creates attention receipts.
        self.discover_orphans()

    def prepare(
        self,
        *,
        root_id: str,
        task_id: str,
        target_session_id: str,
        base_roots: Sequence[str],
        policy: str,
        room_id: str = "",
        work_item_id: str = "",
        dispatch_id: str = "",
        requirement_revision: str = "",
        acceptance_aliases: Sequence[str] = (),
        participant_id: str = "",
        creation_reason: str = "Room collaboration",
        now_ms: int | None = None,
    ) -> dict[str, object]:
        # Reserving the durable binding and materializing its physical worktree
        # are one coordinator-owned operation.  A concurrent replay must not
        # observe the brief reserved-but-not-yet-materialized window and
        # misclassify live creation as an orphan.
        with self._lock:
            return self._prepare_locked(
                root_id=root_id,
                task_id=task_id,
                target_session_id=target_session_id,
                base_roots=base_roots,
                policy=policy,
                room_id=room_id,
                work_item_id=work_item_id,
                dispatch_id=dispatch_id,
                requirement_revision=requirement_revision,
                acceptance_aliases=acceptance_aliases,
                participant_id=participant_id,
                creation_reason=creation_reason,
                now_ms=now_ms,
            )

    def _prepare_locked(
        self,
        *,
        root_id: str,
        task_id: str,
        target_session_id: str,
        base_roots: Sequence[str],
        policy: str,
        room_id: str = "",
        work_item_id: str = "",
        dispatch_id: str = "",
        requirement_revision: str = "",
        acceptance_aliases: Sequence[str] = (),
        participant_id: str = "",
        creation_reason: str = "Room collaboration",
        now_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        roots = [
            Path(value).expanduser().resolve(strict=True)
            for value in base_roots
            if str(value).strip()
        ]
        if not roots:
            raise RoomWorkspaceError("Room collaboration requires a workspace root")
        if policy not in {
            "read_only",
            "shared_single_writer",
            "isolated_writable",
        }:
            raise RoomWorkspaceError("Room workspace policy is invalid")
        if policy != "isolated_writable":
            digest = (
                self.snapshot_digest(roots)
                if policy == "read_only"
                else ""
            )
            target_session = self.sessions.get(target_session_id)
            restore_policy = self._restore_policy(target_session)
            self._set_session_roots(
                target_session_id,
                roots,
                policy=policy,
                grant_workspace_scope=True,
            )
            result: dict[str, object] = {
                "workspacePolicy": policy,
                "workspaceRoot": str(roots[0]),
                "workspaceBaseRoot": str(roots[0]),
                "workspaceIntegrationState": "not_required",
                "workspaceIntegrationRef": None,
                "workspaceRestorePolicy": restore_policy,
            }
            if policy == "read_only":
                result["workspaceSnapshotSha256"] = digest
            return result
        if len(roots) != 1:
            raise RoomWorkspaceError(
                "isolated_writable currently requires exactly one Git workspace root"
            )
        base_root = roots[0]
        git_root = self._git_text(base_root, "rev-parse", "--show-toplevel")
        if Path(git_root).resolve(strict=True) != base_root:
            raise RoomWorkspaceError(
                "isolated_writable requires the authorized root to be the Git worktree root"
            )
        status = self._git_bytes(
            base_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        if status:
            raise RoomWorkspaceError(
                "isolated_writable requires a clean base worktree; preserve current changes "
                "with shared_single_writer or finish them before parallel writers"
            )
        base_commit = self._git_text(base_root, "rev-parse", "HEAD")
        repository_id = self._repository_identity(base_root)
        with self._repository_integration_lock(
            base_root,
            expected_repository_id=repository_id,
        ):
            return self._prepare_isolated_materialization(
                base_root=base_root,
                base_commit=base_commit,
                repository_id=repository_id,
                root_id=root_id,
                task_id=task_id,
                target_session_id=target_session_id,
                policy=policy,
                room_id=room_id,
                work_item_id=work_item_id,
                dispatch_id=dispatch_id,
                requirement_revision=requirement_revision,
                acceptance_aliases=acceptance_aliases,
                participant_id=participant_id,
                creation_reason=creation_reason,
                timestamp=timestamp,
            )

    def _prepare_isolated_materialization(
        self,
        *,
        base_root: Path,
        base_commit: str,
        repository_id: str,
        root_id: str,
        task_id: str,
        target_session_id: str,
        policy: str,
        room_id: str,
        work_item_id: str,
        dispatch_id: str,
        requirement_revision: str,
        acceptance_aliases: Sequence[str],
        participant_id: str,
        creation_reason: str,
        timestamp: int,
    ) -> dict[str, object]:
        if self._git_text(base_root, "rev-parse", "HEAD") != base_commit:
            raise RoomWorkspaceError(
                "repository baseline changed while acquiring materialization lease"
            )
        if self._git_bytes(
            base_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ):
            raise RoomWorkspaceError(
                "repository changed while acquiring materialization lease"
            )
        target_session = self.sessions.get(target_session_id)
        restore_policy = self._restore_policy(target_session)
        lease_key = hashlib.sha256(
            f"{root_id}\0{task_id}\0{base_root}".encode("utf-8")
        ).hexdigest()[:24]
        workspace_root = self.root_dir / lease_key / base_root.name
        try:
            binding, created = self.ledger.reserve_binding(
                room_id=room_id,
                root_id=root_id,
                task_id=task_id,
                work_item_id=work_item_id or task_id,
                dispatch_id=dispatch_id,
                requirement_revision=requirement_revision,
                acceptance_aliases=acceptance_aliases,
                participant_id=participant_id,
                session_id=target_session_id,
                repository_id=repository_id,
                base_root=str(base_root),
                base_commit=base_commit,
                workspace_root=str(workspace_root),
                workspace_policy=policy,
                creation_reason=creation_reason,
                now_ms=timestamp,
                restore_policy=restore_policy,
            )
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            raise RoomWorkspaceError(str(exc)) from exc
        stored_restore_policy = binding.get("workspaceRestorePolicy")
        if isinstance(stored_restore_policy, Mapping):
            restore_policy = dict(stored_restore_policy)
        if not created:
            lifecycle_state = str(binding.get("workspaceLifecycleState") or "")
            binding_id = str(binding["workspaceBindingId"])
            if lifecycle_state in {
                "delivered",
                "delivery_seal_uncertain",
                "delivery_seal_resuming",
            }:
                if self.ledger.source_lease_receipt(binding_id) is None:
                    self._fail_closed_delivery_seal(
                        binding_id=binding_id,
                        source=workspace_root,
                        base=base_root,
                        reason=(
                            "prepare replay observed delivered evidence without its "
                            "source-lease revocation receipt"
                        ),
                        now_ms=timestamp,
                    )
                    raise RoomWorkspaceError(
                        "delivered workspace is sealed with uncertain writer state; "
                        "an explicit delivery-seal resume is required"
                    )
                return self._prepared_payload(
                    binding,
                    restore_policy,
                    created_by_attempt=False,
                )
            if lifecycle_state == "retry_bound":
                raise RoomWorkspaceError(
                    "workspace retry lease can only be used by its token-fenced owner"
                )
            if lifecycle_state in {"materialized", "work_started"} and workspace_root.is_dir():
                self._set_session_roots(
                    target_session_id,
                    [workspace_root],
                    policy=policy,
                    grant_workspace_scope=True,
                )
                return self._prepared_payload(
                    binding,
                    restore_policy,
                    created_by_attempt=False,
                )
            self._retain_binding(
                binding,
                state="orphaned",
                reason=(
                    "workspace reservation survived without a recoverable materialized path"
                ),
                actor_ref="system:workspace-recovery",
                now_ms=timestamp,
            )
            raise RoomWorkspaceError(
                "isolated workspace requires a receipted Facilitator retry or abandonment"
            )
        if workspace_root.exists():
            self._retain_binding(
                binding,
                state="orphaned",
                reason="reserved workspace path already existed before materialization",
                actor_ref="system:workspace-recovery",
                now_ms=timestamp,
            )
            raise RoomWorkspaceError(
                "isolated workspace path is already allocated and was retained for attention"
            )
        workspace_root.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._run(
                [
                    "git",
                    "-C",
                    str(base_root),
                    "worktree",
                    "add",
                    "--detach",
                    str(workspace_root),
                    base_commit,
                ]
            )
            self._set_session_roots(
                target_session_id,
                [workspace_root],
                policy=policy,
                grant_workspace_scope=True,
            )
            binding = self.ledger.mark_materialized(
                str(binding["workspaceBindingId"]),
                workspace_snapshot_sha256=self.snapshot_digest([workspace_root]),
                actor_ref=participant_id or target_session_id,
                now_ms=timestamp,
            )
        except BaseException as exc:
            self._retain_binding(
                binding,
                state="incomplete",
                reason=f"workspace materialization failed: {exc}",
                actor_ref="system:workspace-materializer",
                now_ms=timestamp,
            )
            raise
        return self._prepared_payload(
            binding,
            restore_policy,
            created_by_attempt=True,
        )

    def restore(
        self,
        *,
        session_id: str,
        base_roots: Sequence[str],
        restore_policy: Mapping[str, object] | None = None,
    ) -> None:
        roots = [
            Path(value).expanduser().resolve(strict=True)
            for value in base_roots
            if str(value).strip()
        ]
        if roots:
            self._set_session_roots(
                session_id,
                roots,
                policy="restore",
                grant_workspace_scope=True,
                restore_policy=restore_policy,
            )

    def transfer_isolated_ownership(
        self,
        *,
        task: Mapping[str, object],
        source_session_id: str,
        target_session_id: str,
        base_roots: Sequence[str],
    ) -> dict[str, object]:
        """Rebind an isolated Task's exact worktree to its next owner."""

        if task.get("workspacePolicy") != "isolated_writable":
            raise RoomWorkspaceError(
                "ownership transfer requires an isolated_writable Task"
            )
        if source_session_id == target_session_id:
            raise RoomWorkspaceError(
                "ownership transfer must change the Session owner"
            )
        source, base, expected_commit = self._isolated_task_roots(task)
        roots = [
            Path(value).expanduser().resolve(strict=True)
            for value in base_roots
            if str(value).strip()
        ]
        if not roots or base not in roots:
            raise RoomWorkspaceError(
                "ownership transfer base roots do not match the Task workspace"
            )
        binding_id = str(task.get("workspaceBindingId") or "").strip()
        if not binding_id:
            raise RoomWorkspaceError(
                "ownership transfer requires a durable workspace binding"
            )
        try:
            binding = self.ledger.binding(binding_id)
            self._assert_task_binding_identity(task, binding)
            if (
                str(binding.get("workspaceLifecycleState") or "") == "delivered"
                and self.ledger.source_lease_receipt(binding_id) is not None
            ):
                raise RoomWorkspaceError(
                    "delivered workspace ownership cannot transfer after its "
                    "source write lease was revoked"
                )
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            raise RoomWorkspaceError(str(exc)) from exc
        source_session = self.sessions.get(source_session_id)
        target_session = self.sessions.get(target_session_id)
        source_restore_policy = task.get("workspaceRestorePolicy")
        target_restore_policy = self._restore_policy(target_session)
        target_roots = [
            str(value)
            for value in target_session.get("workspaceRoots") or []
            if str(value).strip()
        ]
        binding_owner_session_id = str(
            binding.get("currentOwnerSessionId") or ""
        )
        if binding_owner_session_id == target_session_id:
            if str(source) not in target_roots:
                self._set_session_roots(
                    target_session_id,
                    [source],
                    policy="isolated_writable",
                    grant_workspace_scope=True,
                )
            return {
                "workspaceRoot": str(source),
                "workspaceBaseRoot": str(base),
                "workspaceBaseCommit": expected_commit,
                "sourceSessionId": source_session_id,
                "targetSessionId": target_session_id,
                "idempotent": True,
            }
        if binding_owner_session_id != source_session_id:
            raise RoomWorkspaceError(
                "ownership transfer source Session does not match the durable "
                "Task workspace owner"
            )
        with self._lock:
            self._set_session_roots(
                target_session_id,
                [source],
                policy="isolated_writable",
                grant_workspace_scope=True,
            )
            try:
                self._set_session_roots(
                    source_session_id,
                    roots,
                    policy="restore",
                    grant_workspace_scope=True,
                    restore_policy=(
                        source_restore_policy
                        if isinstance(source_restore_policy, Mapping)
                        else None
                    ),
                )
                self.ledger.transfer_ownership(
                    binding_id,
                    source_session_id=source_session_id,
                    target_session_id=target_session_id,
                    target_participant_id=str(
                        task.get("currentOwnerParticipantId") or ""
                    ),
                    workspace_snapshot_sha256=self.snapshot_digest([source]),
                    actor_ref=str(task.get("currentOwnerParticipantId") or target_session_id),
                    now_ms=int(time.time() * 1000),
                )
            except BaseException:
                self._set_session_roots(
                    target_session_id,
                    [
                        Path(value).expanduser().resolve(strict=True)
                        for value in target_roots
                        if str(value).strip()
                    ],
                    policy="restore",
                    grant_workspace_scope=bool(
                        target_session.get("workspaceScopeGranted")
                    ),
                    restore_policy=target_restore_policy,
                )
                self._set_session_roots(
                    source_session_id,
                    [source],
                    policy="isolated_writable",
                    grant_workspace_scope=True,
                )
                raise
        return {
            "workspaceBindingId": str(task.get("workspaceBindingId") or ""),
            "workspaceRoot": str(source),
            "workspaceBaseRoot": str(base),
            "workspaceBaseCommit": expected_commit,
            "sourceSessionId": source_session_id,
            "targetSessionId": target_session_id,
        }

    def record_work_started(
        self,
        task: Mapping[str, object],
        *,
        dispatch_id: str,
        actor_ref: str,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        if task.get("workspacePolicy") != "isolated_writable":
            return {
                "workspaceLifecycleState": "not_required",
                "workspaceAttentionRequired": False,
            }
        binding_id = str(task.get("workspaceBindingId") or "").strip()
        if not binding_id:
            raise RoomWorkspaceError(
                "workspace start requires a durable workspace binding"
            )
        try:
            binding = self.ledger.binding(binding_id)
            self._assert_task_binding_identity(task, binding)
            started = self.ledger.record_work_started(
                binding_id,
                dispatch_id=dispatch_id,
                actor_ref=actor_ref,
                now_ms=(
                    int(time.time() * 1000)
                    if now_ms is None
                    else int(now_ms)
                ),
            )
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            raise RoomWorkspaceError(str(exc)) from exc
        return {
            "workspaceBindingId": binding_id,
            "workspaceLifecycleState": started["workspaceLifecycleState"],
            "workspaceAttentionRequired": bool(started["attentionRequired"]),
        }

    def record_delivery(
        self,
        task: Mapping[str, object],
        *,
        artifacts: Sequence[str] = (),
        verification_refs: Sequence[str] = (),
        verification_results: Sequence[Mapping[str, object]] = (),
        residual_risks: Sequence[str] = (),
        result_summary: str = "",
        actor_ref: str = "",
        settlement_invocation_created_at_ms: int | None = None,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        source, base, expected_commit = self._isolated_task_roots(task)
        binding_id = str(task.get("workspaceBindingId") or "").strip()
        if not binding_id:
            raise RoomWorkspaceError(
                "workspace delivery requires a durable workspace binding"
            )
        try:
            binding = self.ledger.binding(binding_id)
            self._assert_task_binding_identity(task, binding)
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            raise RoomWorkspaceError(str(exc)) from exc
        patch = self._workspace_patch(source)
        # ``_workspace_patch`` registers intent-to-add entries so binary
        # untracked artifacts are included.  Hash after that deterministic
        # normalization; the delivery receipt must describe the exact state
        # that integration will consume, not the index state from one command
        # earlier.
        snapshot = self.snapshot_digest([source])
        timestamp = (
            int(time.time() * 1000)
            if now_ms is None
            else int(now_ms)
        )
        manifest = self._delivery_manifest(
            source,
            baseline_commit=expected_commit,
        )
        normalized_artifacts = self._delivery_refs(artifacts)
        normalized_verification = self._delivery_refs(verification_refs)
        normalized_verification_results = (
            self._delivery_verification_results(verification_results)
        )
        normalized_risks = self._delivery_refs(residual_risks)
        normalized_summary = " ".join(
            str(result_summary or "").split()
        )[:2_000]
        patch_sha256 = hashlib.sha256(patch).hexdigest()
        manifest_sha256 = str(manifest["manifestSha256"])
        delivery_metadata = {
            "artifactRefs": normalized_artifacts,
            "verificationRefs": normalized_verification,
            "verifications": normalized_verification_results,
            "residualRisks": normalized_risks,
            "resultSummary": normalized_summary,
        }
        delivery_revision = self._delivery_revision(
            base_commit=expected_commit,
            workspace_snapshot_sha256=snapshot,
            patch_sha256=patch_sha256,
            manifest_sha256=manifest_sha256,
            metadata=delivery_metadata,
        )
        workspace_delivery = {
            "schemaVersion": "wisdom-weasel.room-workspace-delivery.v1",
            "ownerParticipantId": str(
                binding.get("currentOwnerParticipantId")
                or task.get("currentOwnerParticipantId")
                or ""
            ),
            "ownerSessionId": str(binding.get("currentOwnerSessionId") or ""),
            "workItemId": str(binding.get("workItemId") or ""),
            "taskId": str(binding.get("taskId") or task.get("taskId") or ""),
            "deliveryRevision": delivery_revision,
            "baseCommit": expected_commit,
            "workspaceSnapshotSha256": snapshot,
            "patchSha256": patch_sha256,
            "deliveredAtMs": timestamp,
            "resultSummary": normalized_summary,
            "manifestSha256": manifest_sha256,
            "files": manifest["files"],
            "totals": manifest["totals"],
            "artifactRefs": normalized_artifacts,
            "verificationCount": len(normalized_verification),
            "verifications": normalized_verification_results,
            "verificationRefs": normalized_verification,
            "residualRisks": normalized_risks,
        }
        if str(binding.get("workspaceLifecycleState") or "") == "delivered":
            prior_event = self.ledger.delivery_payload(binding_id)
            prior_delivery = (
                prior_event.get("workspaceDelivery")
                if isinstance(prior_event, Mapping)
                else None
            )
            if (
                isinstance(prior_delivery, Mapping)
                and self.ledger.source_lease_receipt(binding_id) is not None
                and self._sealed_delivery_matches_settlement_replay(
                    prior_delivery,
                    workspace_delivery,
                    invocation_created_at_ms=(
                        int(settlement_invocation_created_at_ms)
                        if settlement_invocation_created_at_ms is not None
                        else None
                    ),
                )
            ):
                return {
                    "workspaceBindingId": binding_id,
                    "deliveryRevision": prior_event["deliveryRevision"],
                    "deliveryHead": prior_event["deliveryHead"],
                    "deliverySnapshotSha256": prior_event[
                        "workspaceSnapshotSha256"
                    ],
                    "workspaceLifecycleState": "delivered",
                    "workspaceDelivery": prior_delivery,
                    "sourceWriteLeaseRevoked": True,
                }
        patch_artifact = self._seal_patch_artifact(
            binding_id=binding_id,
            delivery_revision=delivery_revision,
            patch=patch,
        )
        changed_files = self._changed_files(source)
        delivery_committed = False
        try:
            binding = self.ledger.record_delivery(
                binding_id,
                delivery_revision=delivery_revision,
                delivery_head=expected_commit,
                workspace_snapshot_sha256=snapshot,
                patch_sha256=patch_sha256,
                manifest_sha256=manifest_sha256,
                artifacts=normalized_artifacts,
                verification_refs=normalized_verification,
                residual_risks=normalized_risks,
                actor_ref=actor_ref or str(task.get("currentOwnerParticipantId") or ""),
                now_ms=timestamp,
                delivery_payload=workspace_delivery,
            )
            delivery_committed = True
            owner_session_id = str(
                binding.get("currentOwnerSessionId") or ""
            ).strip()
            revoked_policy_sha256 = self._revoke_source_write_lease(
                owner_session_id=owner_session_id,
                source=source,
                base=base,
            )
            delivery_receipt = self.ledger.delivery_payload(binding_id)
            if delivery_receipt is None:
                raise RoomWorkspaceError(
                    "workspace delivery receipt disappeared before lease revocation"
                )
            # A worker that raced the durable policy update invalidates the
            # delivery.  The sealed artifact remains private evidence, but no
            # integration may begin without an exact source-revocation receipt.
            self._capture_delivered_workspace(
                source,
                expected_commit=expected_commit,
                delivery_payload=delivery_receipt,
            )
            workspace_content_sha256 = self._workspace_content_digest(source)
            binding = self.ledger.record_source_lease_revoked(
                binding_id,
                delivery_revision=delivery_revision,
                workspace_snapshot_sha256=snapshot,
                patch_sha256=patch_sha256,
                patch_artifact_path=str(patch_artifact),
                patch_artifact_size=len(patch),
                owner_session_id=owner_session_id,
                revoked_policy_sha256=revoked_policy_sha256,
                workspace_content_sha256=workspace_content_sha256,
                changed_files=changed_files,
                actor_ref=actor_ref or "system:room-workspace-coordinator",
                now_ms=timestamp,
            )
        except BaseException as exc:
            if delivery_committed:
                self._fail_closed_delivery_seal(
                    binding_id=binding_id,
                    source=source,
                    base=base,
                    reason=f"delivery source-lease sealing was interrupted: {exc}",
                    now_ms=timestamp,
                )
            if isinstance(
                exc,
                (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict),
            ):
                raise RoomWorkspaceError(str(exc)) from exc
            raise
        return {
            "workspaceBindingId": binding_id,
            "deliveryRevision": delivery_revision,
            "deliveryHead": expected_commit,
            "deliverySnapshotSha256": snapshot,
            "workspaceLifecycleState": binding["workspaceLifecycleState"],
            "workspaceDelivery": workspace_delivery,
            "sourceWriteLeaseRevoked": True,
        }

    def resume_delivery_seal(
        self,
        *,
        binding_id: str,
        resume_ref: str,
        actor_ref: str,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        """Explicitly finish a crash-interrupted delivered generation.

        Ordinary ``prepare`` replay is intentionally unable to enter this path.
        The ledger CAS token fences two recovery coordinators, while the source
        bytes and sealed coordinator-owned patch are revalidated before the
        missing revocation receipt is appended.
        """

        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        binding = self.ledger.binding(binding_id)
        source = self._receipted_workspace_path(binding, require_exists=True)
        base = Path(str(binding.get("workspaceBaseRoot") or "")).resolve(
            strict=True
        )
        delivery = self.ledger.delivery_payload(binding_id)
        if delivery is None:
            raise RoomWorkspaceError("delivery-seal resume lacks delivered evidence")
        try:
            claim = self.ledger.claim_delivery_seal_resume(
                binding_id,
                resume_ref=resume_ref,
                actor_ref=actor_ref,
                now_ms=timestamp,
            )
            token = str(claim.get("deliverySealResumeToken") or "")
            revoked_policy_sha256 = self._revoke_source_write_lease(
                owner_session_id=str(binding.get("currentOwnerSessionId") or ""),
                source=source,
                base=base,
            )
            self._capture_delivered_workspace(
                source,
                expected_commit=str(binding.get("workspaceBaseCommit") or ""),
                delivery_payload=delivery,
            )
            patch_sha256 = str(delivery.get("patchSha256") or "")
            artifact = self._sealed_patch_artifact_path(
                binding_id=binding_id,
                delivery_revision=str(delivery.get("deliveryRevision") or ""),
                patch_sha256=patch_sha256,
            )
            patch = self._read_patch_artifact(
                {
                    "patchArtifactPath": str(artifact),
                    "patchArtifactSize": artifact.stat().st_size,
                    "patchSha256": patch_sha256,
                }
            )
            sealed = self.ledger.record_source_lease_revoked(
                binding_id,
                delivery_revision=str(delivery.get("deliveryRevision") or ""),
                workspace_snapshot_sha256=str(
                    delivery.get("workspaceSnapshotSha256") or ""
                ),
                patch_sha256=patch_sha256,
                patch_artifact_path=str(artifact),
                patch_artifact_size=len(patch),
                owner_session_id=str(binding.get("currentOwnerSessionId") or ""),
                revoked_policy_sha256=revoked_policy_sha256,
                workspace_content_sha256=self._workspace_content_digest(source),
                changed_files=self._changed_files(source),
                actor_ref=actor_ref,
                now_ms=timestamp,
                delivery_seal_resume_token=token,
            )
        except (OSError, RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            self._fail_closed_delivery_seal(
                binding_id=binding_id,
                source=source,
                base=base,
                reason=f"delivery-seal resume failed: {exc}",
                now_ms=timestamp,
            )
            raise RoomWorkspaceError(str(exc)) from exc
        return {
            **sealed,
            "sourceWriteLeaseRevoked": True,
            "deliverySealResumed": True,
        }

    def _fail_closed_delivery_seal(
        self,
        *,
        binding_id: str,
        source: Path,
        base: Path,
        reason: str,
        now_ms: int,
    ) -> None:
        try:
            binding = self.ledger.binding(binding_id)
        except RoomWorkspaceLedgerError:
            return
        if self.ledger.source_lease_receipt(binding_id) is not None:
            return
        try:
            self._revoke_source_write_lease(
                owner_session_id=str(binding.get("currentOwnerSessionId") or ""),
                source=source,
                base=base,
            )
        except (OSError, RoomWorkspaceError):
            pass
        try:
            self.ledger.mark_delivery_seal_uncertain(
                binding_id,
                reason=reason,
                actor_ref="system:room-workspace-recovery",
                now_ms=now_ms,
            )
        except RoomWorkspaceLedgerError:
            pass

    def integrate(
        self,
        task: Mapping[str, object],
        *,
        integration_ref: str = "",
        actor_ref: str = "",
        now_ms: int | None = None,
    ) -> dict[str, object]:
        # The process lock protects this coordinator instance.  The Git-common
        # directory lock serializes every cooperating process for the physical
        # repository from target-before through the durable receipt and cleanup.
        with self._lock:
            binding_id = str(task.get("workspaceBindingId") or "").strip()
            if not binding_id:
                raise RoomWorkspaceError(
                    "workspace integration requires a durable workspace binding"
                )
            try:
                binding = self.ledger.binding(binding_id)
            except RoomWorkspaceLedgerError as exc:
                raise RoomWorkspaceError(str(exc)) from exc
            base = Path(str(binding.get("workspaceBaseRoot") or "")).resolve(
                strict=True
            )
            repository_id = str(binding.get("repositoryId") or "")
            with self._repository_integration_lock(
                base,
                expected_repository_id=repository_id,
            ):
                return self._integrate_locked(
                    task,
                    integration_ref=integration_ref,
                    actor_ref=actor_ref,
                    now_ms=now_ms,
                )

    def _integrate_locked(
        self,
        task: Mapping[str, object],
        *,
        integration_ref: str = "",
        actor_ref: str = "",
        now_ms: int | None = None,
    ) -> dict[str, object]:
        if task.get("workspacePolicy") != "isolated_writable":
            raise RoomWorkspaceError("Room task does not own an isolated worktree")
        if task.get("state") != "completed":
            raise RoomWorkspaceError(
                "workspace integration requires a completed child Task"
            )
        binding_id = str(task.get("workspaceBindingId") or "").strip()
        if not binding_id:
            raise RoomWorkspaceError(
                "workspace integration requires a durable workspace binding"
            )
        try:
            binding = self.ledger.binding(binding_id)
            self._assert_task_binding_identity(task, binding)
        except RoomWorkspaceLedgerError as exc:
            raise RoomWorkspaceError(str(exc)) from exc
        lifecycle_state = str(binding.get("workspaceLifecycleState") or "")
        integrated_receipt = self.ledger.integrated_receipt(binding_id)
        if lifecycle_state in {"integrated", "cleanup_failed"} and (
            integrated_receipt is not None
        ):
            recorded_integration_ref = str(
                binding.get("workspaceIntegrationRef") or ""
            ).strip()
            if (
                integration_ref.strip()
                and integration_ref.strip() != recorded_integration_ref
            ):
                raise RoomWorkspaceError(
                    "workspace cleanup recovery changed its integrationRef"
                )
            cleanup = self._cleanup_receipted_worktree(
                binding,
                actor_ref=actor_ref or "system:room-facilitator",
                now_ms=(
                    int(time.time() * 1000)
                    if now_ms is None
                    else int(now_ms)
                ),
            )
            return {
                "integrated": True,
                "idempotent": True,
                "changedFiles": [],
                "workspaceBindingId": binding_id,
                "integrationRef": binding.get("workspaceIntegrationRef"),
                "integrationPatchSha256": binding.get(
                    "integrationPatchSha256"
                ),
                "integratedRevision": binding.get("integratedRevision"),
                "integratedSnapshotSha256": binding.get(
                    "integratedSnapshotSha256"
                ),
                "cleanupState": cleanup.get("cleanupState"),
                "workspaceLifecycleState": cleanup.get(
                    "workspaceLifecycleState"
                ),
                "attentionRequired": cleanup.get("attentionRequired"),
                "retainedWorkspaceRoot": cleanup.get("retainedWorkspaceRoot"),
                **self._integration_receipt_refs(binding_id),
            }
        if lifecycle_state == "cleaned":
            recorded_integration_ref = str(
                binding.get("workspaceIntegrationRef") or ""
            ).strip()
            if (
                integration_ref.strip()
                and integration_ref.strip() != recorded_integration_ref
            ):
                raise RoomWorkspaceError(
                    "workspace integration replay changed its integrationRef"
                )
            return {
                "integrated": True,
                "idempotent": True,
                "changedFiles": [],
                "workspaceBindingId": binding_id,
                "integrationRef": binding.get("workspaceIntegrationRef"),
                "integrationPatchSha256": binding.get("integrationPatchSha256"),
                "integratedRevision": binding.get("integratedRevision"),
                "integratedSnapshotSha256": binding.get(
                    "integratedSnapshotSha256"
                ),
                "cleanupState": binding.get("cleanupState"),
                "workspaceLifecycleState": binding.get(
                    "workspaceLifecycleState"
                ),
                "attentionRequired": bool(binding.get("attentionRequired")),
                **self._integration_receipt_refs(binding_id),
            }
        source = Path(str(task.get("workspaceRoot") or "")).resolve(strict=True)
        base = Path(str(task.get("workspaceBaseRoot") or "")).resolve(strict=True)
        expected_commit = str(task.get("workspaceBaseCommit") or "").strip()
        if not expected_commit:
            raise RoomWorkspaceError("isolated worktree has no base commit")
        if self._git_text(source, "rev-parse", "HEAD") != expected_commit:
            raise RoomWorkspaceError(
                "isolated task changed HEAD; deliver working-tree changes without committing"
            )
        if str(binding.get("workspaceLifecycleState") or "") not in {
            "delivered",
            "integration_started",
        }:
            raise RoomWorkspaceError(
                "workspace integration requires a hash-bound delivery receipt"
            )
        delivery_payload = self.ledger.delivery_payload(binding_id)
        if delivery_payload is None:
            raise RoomWorkspaceError(
                "workspace integration requires a delivered evidence receipt"
            )
        source_lease_receipt = self.ledger.source_lease_receipt(binding_id)
        if source_lease_receipt is None:
            raise RoomWorkspaceError(
                "workspace integration requires a durable source write-lease "
                "revocation receipt"
            )
        source_lease_payload = source_lease_receipt.get("payload")
        if not isinstance(source_lease_payload, Mapping):
            raise RoomWorkspaceError(
                "source write-lease receipt lacks immutable artifact evidence"
            )
        if any(
            str(source_lease_payload.get(key) or "") != str(expected)
            for key, expected in {
                "deliveryRevision": delivery_payload.get("deliveryRevision"),
                "workspaceSnapshotSha256": delivery_payload.get(
                    "workspaceSnapshotSha256"
                ),
                "patchSha256": delivery_payload.get("patchSha256"),
            }.items()
        ):
            raise RoomWorkspaceError(
                "source write-lease receipt is not bound to delivered evidence"
            )
        patch = self._read_patch_artifact(source_lease_payload)
        patch_sha256 = hashlib.sha256(patch).hexdigest()
        changed_files = [
            str(value)
            for value in source_lease_payload.get("changedFiles") or []
            if str(value).strip()
        ]
        try:
            self._capture_delivered_workspace(
                source,
                expected_commit=expected_commit,
                delivery_payload=delivery_payload,
            )
        except RoomWorkspaceError:
            if str(binding.get("workspaceLifecycleState") or "") == "delivered":
                # A deterministic mutation observed before the integration
                # lease must not create an integration event or touch target.
                raise
            raise
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        integration_ref = integration_ref.strip() or (
            "room-workspace-integration:"
            + hashlib.sha256(
                f"{binding_id}\0{binding.get('deliveryRevision')}".encode("utf-8")
            ).hexdigest()[:32]
        )
        target_before = self.snapshot_digest([base])
        try:
            binding = self.ledger.begin_integration(
                binding_id,
                integration_ref=integration_ref,
                patch_sha256=patch_sha256,
                target_before_snapshot_sha256=target_before,
                actor_ref=actor_ref or "system:room-facilitator",
                now_ms=timestamp,
            )
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            raise RoomWorkspaceError(str(exc)) from exc

        def source_conflict(
            reason: str,
            *,
            rollback_applied_patch: bool = False,
        ) -> dict[str, object]:
            normalized_reason = reason
            if rollback_applied_patch and patch:
                reversed_patch = self._run(
                    [
                        "git",
                        "-C",
                        str(base),
                        "apply",
                        "--reverse",
                        "--whitespace=nowarn",
                        "-",
                    ],
                    input_bytes=patch,
                    check=False,
                )
                if reversed_patch.returncode != 0:
                    normalized_reason += (
                        "; exact target rollback failed: "
                        + self._bounded_error(reversed_patch.stderr)
                    )
            self.ledger.record_conflict(
                binding_id,
                integration_ref=integration_ref,
                patch_sha256=patch_sha256,
                reason=normalized_reason,
                changed_files=changed_files,
                actor_ref=actor_ref or "system:room-facilitator",
                now_ms=timestamp,
            )
            return {
                "integrated": False,
                "conflict": True,
                "changedFiles": changed_files,
                "reason": normalized_reason,
                "workspaceBindingId": binding_id,
                "integrationRef": integration_ref,
                "cleanupState": "retained",
                "workspaceLifecycleState": "conflict",
            }

        try:
            self._capture_delivered_workspace(
                source,
                expected_commit=expected_commit,
                delivery_payload=delivery_payload,
            )
        except RoomWorkspaceError:
            return source_conflict(
                "isolated workspace changed after its delivery receipt and "
                "integration lease acquisition"
            )

        prior_start = self.ledger.integration_start_payload(binding_id) or {}
        recorded_target_before = str(
            prior_start.get("targetBeforeSnapshotSha256") or ""
        )
        target_applied_receipt = self.ledger.target_applied_receipt(binding_id)
        recovered_after_apply = target_applied_receipt is not None
        if recovered_after_apply:
            target_applied_payload = target_applied_receipt.get("payload")
            if not isinstance(target_applied_payload, Mapping) or any(
                str(target_applied_payload.get(key) or "") != str(expected)
                for key, expected in {
                    "integrationRef": integration_ref,
                    "patchSha256": patch_sha256,
                    "targetBeforeSnapshotSha256": recorded_target_before,
                    "sourceLeaseReceiptId": source_lease_receipt.get("eventId"),
                    "sourceLeaseReceiptSha256": source_lease_receipt.get(
                        "payloadSha256"
                    ),
                }.items()
            ):
                return source_conflict(
                    "prior target-applied receipt does not match this integration"
                )
            target_after = str(
                target_applied_payload.get("targetAfterSnapshotSha256") or ""
            )
            if self.snapshot_digest([base]) != target_after:
                return source_conflict(
                    "integration target changed after its exact target-applied receipt"
                )
        elif self.snapshot_digest([base]) != recorded_target_before:
            return source_conflict(
                "integration target changed after its receipted start; no exact "
                "target-applied receipt exists, so the child was retained"
            )

        if patch and not recovered_after_apply:
            checked = self._run(
                [
                    "git",
                    "-C",
                    str(base),
                    "apply",
                    "--check",
                    "--whitespace=nowarn",
                    "-",
                ],
                input_bytes=patch,
                check=False,
            )
            if checked.returncode != 0:
                reason = self._bounded_error(checked.stderr)
                self.ledger.record_conflict(
                    binding_id,
                    integration_ref=integration_ref,
                    patch_sha256=patch_sha256,
                    reason=reason or "workspace patch conflicts with the integration target",
                    changed_files=changed_files,
                    actor_ref=actor_ref or "system:room-facilitator",
                    now_ms=timestamp,
                )
                return {
                    "integrated": False,
                    "conflict": True,
                    "changedFiles": changed_files,
                    "reason": reason,
                    "workspaceBindingId": binding_id,
                    "integrationRef": integration_ref,
                    "cleanupState": "retained",
                    "workspaceLifecycleState": "conflict",
                }
            try:
                self._capture_delivered_workspace(
                    source,
                    expected_commit=expected_commit,
                    delivery_payload=delivery_payload,
                )
            except RoomWorkspaceError:
                return source_conflict(
                    "isolated workspace changed after integration preflight"
                )
            applied = self._run(
                ["git", "-C", str(base), "apply", "--whitespace=nowarn", "-"],
                input_bytes=patch,
                check=False,
            )
            if applied.returncode != 0:
                reason = (
                    "workspace changed after integration preflight: "
                    + self._bounded_error(applied.stderr)
                )
                self.ledger.record_conflict(
                    binding_id,
                    integration_ref=integration_ref,
                    patch_sha256=patch_sha256,
                    reason=reason,
                    changed_files=changed_files,
                    actor_ref=actor_ref or "system:room-facilitator",
                    now_ms=timestamp,
                )
                return {
                    "integrated": False,
                    "conflict": True,
                    "changedFiles": changed_files,
                    "reason": reason,
                    "workspaceBindingId": binding_id,
                    "integrationRef": integration_ref,
                    "cleanupState": "retained",
                    "workspaceLifecycleState": "conflict",
                }
        try:
            self._capture_delivered_workspace(
                source,
                expected_commit=expected_commit,
                delivery_payload=delivery_payload,
            )
        except RoomWorkspaceError:
            return source_conflict(
                "isolated workspace changed after the receipted patch was applied",
                rollback_applied_patch=bool(patch and not recovered_after_apply),
            )
        if not recovered_after_apply:
            target_after = self.snapshot_digest([base])
            try:
                self.ledger.record_target_applied(
                    binding_id,
                    integration_ref=integration_ref,
                    patch_sha256=patch_sha256,
                    target_before_snapshot_sha256=recorded_target_before,
                    target_after_snapshot_sha256=target_after,
                    target_snapshot_provider=lambda: self.snapshot_digest([base]),
                    actor_ref=actor_ref or "system:room-facilitator",
                    now_ms=timestamp,
                )
            except RoomWorkspaceLedgerConflict as exc:
                return source_conflict(
                    str(exc),
                    rollback_applied_patch=bool(patch),
                )
            except RoomWorkspaceLedgerError as exc:
                # A storage failure before target_applied is deliberately not
                # guessed from reverse-apply on retry.  The target and source
                # remain for a Facilitator to inspect.
                raise RoomWorkspaceError(str(exc)) from exc

        integrated_snapshot = target_after
        integrated_revision = (
            f"git:{self._git_text(base, 'rev-parse', 'HEAD')}:"
            f"snapshot:{integrated_snapshot}"
        )
        try:
            binding = self.ledger.record_integrated(
                binding_id,
                integration_ref=integration_ref,
                patch_sha256=patch_sha256,
                integrated_revision=integrated_revision,
                integrated_snapshot_sha256=integrated_snapshot,
                changed_files=changed_files,
                target_snapshot_provider=lambda: self.snapshot_digest([base]),
                actor_ref=actor_ref or "system:room-facilitator",
                now_ms=timestamp,
            )
        except RoomWorkspaceLedgerConflict as exc:
            return source_conflict(
                str(exc),
                rollback_applied_patch=bool(patch),
            )
        except RoomWorkspaceLedgerError as exc:
            # The exact target-applied receipt survives.  A retry can recover
            # only from that receipt; no movable reverse-apply heuristic is used.
            raise RoomWorkspaceError(str(exc)) from exc
        cleanup = self._cleanup_receipted_worktree(
            binding,
            actor_ref=actor_ref or "system:room-facilitator",
            now_ms=timestamp,
        )
        return {
            "integrated": True,
            "idempotent": recovered_after_apply,
            "noChanges": not patch,
            "changedFiles": changed_files,
            "workspaceBindingId": binding_id,
            "integrationRef": integration_ref,
            "integrationPatchSha256": patch_sha256,
            "integratedRevision": integrated_revision,
            "integratedSnapshotSha256": integrated_snapshot,
            "cleanupState": cleanup.get("cleanupState"),
            "workspaceLifecycleState": cleanup.get("workspaceLifecycleState"),
            "attentionRequired": cleanup.get("attentionRequired"),
            "retainedWorkspaceRoot": cleanup.get("retainedWorkspaceRoot"),
            **self._integration_receipt_refs(binding_id),
        }

    def _integration_receipt_refs(self, binding_id: str) -> dict[str, object]:
        required_receipts = {
            "delivery": self.ledger.delivery_receipt(binding_id),
            "sourceLease": self.ledger.source_lease_receipt(binding_id),
            "targetApplied": self.ledger.target_applied_receipt(binding_id),
            "integrated": self.ledger.integrated_receipt(binding_id),
            "cleanup": self.ledger.cleanup_receipt(binding_id),
        }
        optional_receipts = {
            "writerQuiescence": self.ledger.writer_quiescence_receipt(binding_id),
            "quarantine": self.ledger.quarantine_receipt(binding_id),
            "removalAuthorization": (
                self.ledger.cleanup_removal_authorization_receipt(binding_id)
            ),
            "vault": self.ledger.vault_receipt(binding_id),
        }
        missing = [
            name
            for name, receipt in required_receipts.items()
            if receipt is None
        ]
        if missing:
            raise RoomWorkspaceError(
                "workspace integration result lacks durable receipts: "
                + ", ".join(missing)
            )
        result: dict[str, object] = {}
        for name, receipt in {
            **required_receipts,
            **optional_receipts,
        }.items():
            if receipt is None:
                continue
            prefix = name[0].upper() + name[1:]
            result[f"workspace{prefix}ReceiptId"] = receipt["eventId"]
            result[f"workspace{prefix}ReceiptSha256"] = receipt[
                "payloadSha256"
            ]
        return result

    def discard(self, prepared: Mapping[str, object]) -> None:
        """Retain an allocated child when enqueue fails; never erase evidence."""

        if prepared.get("workspacePolicy") != "isolated_writable":
            return
        if isinstance(prepared, _PreparedWorkspace) and not prepared.created_by_attempt:
            return
        binding_id = str(prepared.get("workspaceBindingId") or "").strip()
        if not binding_id:
            raise RoomWorkspaceError(
                "unaccepted isolated workspace has no durable binding"
            )
        binding = self.ledger.binding(binding_id)
        self._retain_binding(
            binding,
            state="incomplete",
            reason="child Task enqueue failed after workspace reservation",
            actor_ref="system:room-collaboration",
            now_ms=int(time.time() * 1000),
        )

    def retain_task(
        self,
        task: Mapping[str, object],
        *,
        state: str,
        reason: str,
        actor_ref: str,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        """Retain only an isolated Task's exact receipted worktree."""

        if task.get("workspacePolicy") != "isolated_writable":
            return {
                "workspaceLifecycleState": "not_required",
                "cleanupState": "not_authorized",
                "attentionRequired": False,
            }
        binding_id = str(task.get("workspaceBindingId") or "").strip()
        if not binding_id:
            raise RoomWorkspaceError(
                "workspace retention requires a durable workspace binding"
            )
        try:
            binding = self.ledger.binding(binding_id)
            self._assert_task_binding_identity(task, binding)
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            raise RoomWorkspaceError(str(exc)) from exc
        if str(binding.get("workspaceLifecycleState") or "") in {
            "integrated",
            "cleaned",
            "abandoned",
        }:
            return binding
        return self._retain_binding(
            binding,
            state=state,
            reason=reason,
            actor_ref=actor_ref,
            now_ms=(
                int(time.time() * 1000)
                if now_ms is None
                else int(now_ms)
            ),
        )

    def retry_retained(
        self,
        *,
        binding_id: str,
        participant_id: str,
        participant_ref: str,
        session_id: str,
        reason: str,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        binding = self.ledger.binding(binding_id)
        if (
            self.ledger.integrated_receipt(binding_id) is not None
            or str(binding.get("workspaceLifecycleState") or "")
            in {"integrated", "cleaned", "abandoned", "cleanup_failed"}
        ):
            raise RoomWorkspaceError(
                "integrated or cleanup-terminal workspace cannot be rebound for retry"
            )
        source = self._receipted_workspace_path(binding, require_exists=True)
        snapshot = self.snapshot_digest([source])
        if (
            binding.get("workspaceLifecycleState") == "retry_bound"
            and binding.get("attentionRequired") is False
        ):
            raise RoomWorkspaceError(
                "workspace retry already has a write-lease owner"
            )
        granted = False
        lease_acquired = False
        try:
            rebound = self.ledger.retry_binding(
                binding_id,
                participant_id=participant_id,
                participant_ref=participant_ref,
                session_id=session_id,
                workspace_snapshot_sha256=snapshot,
                reason=reason,
                actor_ref=participant_id or session_id,
                now_ms=timestamp,
            )
            lease_acquired = True
            retry_token = str(rebound.get("retryLeaseToken") or "")
            self.ledger.assert_retry_lease(
                binding_id,
                participant_id=participant_id,
                participant_ref=participant_ref,
                session_id=session_id,
                retry_lease_token=retry_token,
            )
            self._set_session_roots(
                session_id,
                [source],
                policy="isolated_writable",
                grant_workspace_scope=True,
            )
            granted = True
            self.ledger.assert_retry_lease(
                binding_id,
                participant_id=participant_id,
                participant_ref=participant_ref,
                session_id=session_id,
                retry_lease_token=retry_token,
            )
        except BaseException as exc:
            if lease_acquired:
                try:
                    self.ledger.retain(
                        binding_id,
                        reason=f"retry Session lease grant failed: {exc}",
                        state="incomplete",
                        workspace_snapshot_sha256=snapshot,
                        actor_ref="system:room-workspace-recovery",
                        now_ms=timestamp,
                    )
                except RoomWorkspaceLedgerError:
                    pass
            if granted or lease_acquired:
                self._set_session_roots(
                    session_id,
                    [Path(str(binding["workspaceBaseRoot"]))],
                    policy="read_only",
                    grant_workspace_scope=True,
                )
            if isinstance(exc, RoomWorkspaceError):
                raise
            raise RoomWorkspaceError(str(exc)) from exc
        return rebound

    def abandon_retained(
        self,
        *,
        binding_id: str,
        reason: str,
        acceptance_aliases: Sequence[str],
        actor_ref: str,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        binding = self.ledger.binding(binding_id)
        normalized_aliases = list(
            dict.fromkeys(
                str(value).strip()
                for value in acceptance_aliases
                if str(value).strip()
            )
        )
        prior_event = next(
            (
                event
                for event in reversed(self.ledger.events(binding_id))
                if event.get("eventKind") == "abandoned"
            ),
            None,
        )
        prior_payload = (
            prior_event.get("payload")
            if isinstance(prior_event, Mapping)
            else None
        )
        if isinstance(prior_payload, Mapping):
            if (
                prior_payload.get("reason") != reason[:2_000]
                or prior_payload.get("acceptanceAliases")
                != normalized_aliases
            ):
                raise RoomWorkspaceError(
                    "workspace abandonment was replayed with different evidence"
                )
            if self.ledger.abandonment_quiescence_receipt(binding_id) is None:
                raise RoomWorkspaceError(
                    "historical abandonment lacks durable writer quiescence; child was retained"
                )
            cleanup_state = str(binding.get("cleanupState") or "")
            cleanup_completed = cleanup_state in {"cleaned", "missing"}
            if cleanup_completed and (
                self.ledger.quarantine_receipt(binding_id) is None
                or self.ledger.cleanup_removal_authorization_receipt(binding_id)
                is None
            ):
                raise RoomWorkspaceError(
                    "historical abandonment cleanup lacks exact removal lineage"
                )
            cleanup_receipt = self.ledger.cleanup_receipt(binding_id)
            cleanup_payload = (
                cleanup_receipt.get("payload")
                if isinstance(cleanup_receipt, Mapping)
                else None
            )
            retained_workspace_root = (
                str(cleanup_payload.get("retainedWorkspaceRoot") or "")
                if isinstance(cleanup_payload, Mapping)
                else ""
            )
            return {
                **binding,
                "workspaceLifecycleState": (
                    "abandoned"
                    if cleanup_completed
                    else str(binding.get("workspaceLifecycleState") or "")
                ),
                "cleanupState": cleanup_state,
                "attentionRequired": bool(binding.get("attentionRequired")),
                "terminalReason": (
                    str(binding.get("terminalReason") or "")
                    or reason[:2_000]
                ),
                "abandonmentReason": reason[:2_000],
                "abandonmentAuthorized": True,
                "physicalCleanupCompleted": cleanup_completed,
                "retainedWorkspaceRoot": retained_workspace_root or None,
                "abandonmentSnapshotSha256": prior_payload.get(
                    "workspaceSnapshotSha256"
                ),
                "abandonmentReceiptId": prior_event.get("eventId"),
                "abandonmentReceiptSha256": prior_event.get(
                    "payloadSha256"
                ),
            }
        source = self._receipted_workspace_path(binding, require_exists=False)
        base = Path(str(binding.get("workspaceBaseRoot") or "")).resolve(
            strict=True
        )
        snapshot = (
            self._workspace_content_digest(source)
            if source.is_dir()
            else hashlib.sha256(str(source).encode("utf-8")).hexdigest()
        )
        try:
            owner_session_id = str(
                binding.get("currentOwnerSessionId") or ""
            ).strip()
            revoked_policy_sha256 = self._revoke_source_write_lease(
                owner_session_id=owner_session_id,
                source=source,
                base=base,
            )
            provider = self._writer_quiescence_provider
            if provider is None:
                raise RoomWorkspaceError(
                    "abandonment writer-quiescence provider is unavailable; child was retained"
                )
            request = {
                "workspaceBindingId": binding_id,
                "rootId": str(binding.get("rootId") or ""),
                "taskId": str(binding.get("taskId") or ""),
                "dispatchId": str(binding.get("dispatchId") or ""),
                "ownerSessionId": owner_session_id,
                "workspaceContentSha256": snapshot,
                "revokedPolicySha256": revoked_policy_sha256,
            }
            receipt = provider(request)
            if not isinstance(receipt, Mapping):
                raise RoomWorkspaceError(
                    "abandonment writer-quiescence provider returned no durable receipt"
                )
            self.ledger.record_abandonment_quiescence(
                binding_id,
                workspace_content_sha256=snapshot,
                revoked_policy_sha256=revoked_policy_sha256,
                receipt=receipt,
                actor_ref=actor_ref,
                now_ms=timestamp,
            )
            abandoned = self.ledger.abandon(
                binding_id,
                reason=reason,
                workspace_snapshot_sha256=snapshot,
                acceptance_aliases=normalized_aliases,
                actor_ref=actor_ref,
                now_ms=timestamp,
            )
        except (
            OSError,
            RoomWorkspaceError,
            RoomWorkspaceLedgerError,
            RoomWorkspaceLedgerConflict,
        ) as exc:
            raise RoomWorkspaceError(str(exc)) from exc
        abandonment_event = next(
            event
            for event in reversed(self.ledger.events(binding_id))
            if event.get("eventKind") == "abandoned"
        )
        cleanup = self._cleanup_receipted_worktree(
            abandoned,
            actor_ref=actor_ref,
            now_ms=timestamp,
        )
        cleanup_state = str(cleanup.get("cleanupState") or "")
        cleanup_completed = cleanup_state in {"cleaned", "missing"}
        return {
            **cleanup,
            "workspaceLifecycleState": (
                "abandoned"
                if cleanup_completed
                else str(cleanup.get("workspaceLifecycleState") or "")
            ),
            "attentionRequired": bool(cleanup.get("attentionRequired")),
            "terminalReason": (
                str(cleanup.get("terminalReason") or "")
                or reason[:2_000]
            ),
            "abandonmentReason": reason[:2_000],
            "abandonmentAuthorized": True,
            "physicalCleanupCompleted": cleanup_completed,
            "abandonmentSnapshotSha256": snapshot,
            "abandonmentReceiptId": abandonment_event["eventId"],
            "abandonmentReceiptSha256": abandonment_event["payloadSha256"],
        }

    def discover_orphans(self, *, now_ms: int | None = None) -> list[dict[str, object]]:
        """Mark interrupted bindings and unclaimed physical worktrees for attention."""

        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        discovered: list[dict[str, object]] = []
        claimed_paths = {
            Path(value).expanduser().resolve(strict=False)
            for value in self.ledger.vaulted_workspace_roots()
        }
        for binding in self.ledger.recovery_candidates():
            source = self._receipted_workspace_path(binding, require_exists=False)
            quarantine = self._quarantine_path(binding)
            vault = self._vault_path(binding)
            claimed_paths.add(source)
            claimed_paths.add(quarantine)
            claimed_paths.add(vault)
            base = Path(str(binding.get("workspaceBaseRoot") or "")).resolve(
                strict=False
            )
            if base.is_dir():
                try:
                    with self._repository_integration_lock(
                        base,
                        expected_repository_id=str(
                            binding.get("repositoryId") or ""
                        ),
                    ):
                        current = self.ledger.binding(
                            str(binding.get("workspaceBindingId") or "")
                        )
                        recovered = self._recover_binding_on_startup(
                            current,
                            source=source,
                            quarantine=quarantine,
                            vault=vault,
                            base=base,
                            now_ms=timestamp,
                        )
                except RoomWorkspaceError:
                    recovered = None
            else:
                current = self.ledger.binding(
                    str(binding.get("workspaceBindingId") or "")
                )
                recovered = self._recover_binding_on_startup(
                    current,
                    source=source,
                    quarantine=quarantine,
                    vault=vault,
                    base=base,
                    now_ms=timestamp,
                )
            if recovered is not None:
                discovered.append(recovered)
        if self.root_dir.is_dir():
            for candidate in sorted(self.root_dir.glob("*/*")):
                resolved = candidate.resolve(strict=False)
                if not candidate.is_dir() or resolved in claimed_paths:
                    continue
                snapshot = ""
                try:
                    snapshot = self.snapshot_digest([resolved])
                except (OSError, RoomWorkspaceError):
                    pass
                discovered.append(
                    self.ledger.record_unclaimed_orphan(
                        workspace_root=str(resolved),
                        reason="physical Room worktree has no authoritative binding",
                        observed_snapshot_sha256=snapshot,
                        now_ms=timestamp,
                    )
                )
        return discovered

    def recover_integrated_cleanups(
        self,
        *,
        now_ms: int | None = None,
    ) -> list[dict[str, object]]:
        """Resume deferred cleanup only after runtime receipt owners are bound."""

        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        recovered: list[dict[str, object]] = []
        for candidate in self.ledger.recovery_candidates():
            binding_id = str(candidate.get("workspaceBindingId") or "")
            if self.ledger.integrated_receipt(binding_id) is None:
                continue
            if str(candidate.get("workspaceLifecycleState") or "") not in {
                "integrated",
                "cleanup_failed",
            }:
                continue
            base = Path(str(candidate.get("workspaceBaseRoot") or "")).resolve(
                strict=False
            )
            if not base.is_dir():
                continue
            try:
                with self._repository_integration_lock(
                    base,
                    expected_repository_id=str(
                        candidate.get("repositoryId") or ""
                    ),
                ):
                    current = self.ledger.binding(binding_id)
                    cleanup = self._cleanup_receipted_worktree(
                        current,
                        actor_ref="system:workspace-recovery",
                        now_ms=timestamp,
                    )
                    if str(cleanup.get("cleanupState") or "") in {
                        "cleaned",
                        "missing",
                    }:
                        cleanup = {
                            **cleanup,
                            "integrated": True,
                            "idempotent": True,
                            "changedFiles": [],
                            "integrationRef": cleanup.get(
                                "workspaceIntegrationRef"
                            ),
                            **self._integration_receipt_refs(binding_id),
                        }
                    recovered.append(cleanup)
            except RoomWorkspaceError:
                continue
        return recovered

    def cleaned_integration_projection_candidates(
        self,
    ) -> list[dict[str, object]]:
        """Project only complete terminal cleanup chains from older releases."""

        candidates: list[dict[str, object]] = []
        for binding in self.ledger.cleaned_integration_projection_candidates():
            binding_id = str(binding.get("workspaceBindingId") or "")
            receipts = {
                "delivery": self.ledger.delivery_receipt(binding_id),
                "source": self.ledger.source_lease_receipt(binding_id),
                "target": self.ledger.target_applied_receipt(binding_id),
                "integrated": self.ledger.integrated_receipt(binding_id),
                "writer": self.ledger.writer_quiescence_receipt(binding_id),
                "quarantine": self.ledger.quarantine_receipt(binding_id),
                "removal": self.ledger.cleanup_removal_authorization_receipt(
                    binding_id
                ),
                "vault": self.ledger.vault_receipt(binding_id),
                "cleanup": self.ledger.cleanup_receipt(binding_id),
            }
            if any(receipt is None for receipt in receipts.values()):
                continue
            target = receipts["target"]
            integrated = receipts["integrated"]
            vault = receipts["vault"]
            cleanup = receipts["cleanup"]
            assert target is not None
            assert integrated is not None
            assert vault is not None
            assert cleanup is not None
            target_payload = target.get("payload")
            integrated_payload = integrated.get("payload")
            vault_payload = vault.get("payload")
            cleanup_payload = cleanup.get("payload")
            if not all(
                isinstance(payload, Mapping)
                for payload in (
                    target_payload,
                    integrated_payload,
                    vault_payload,
                    cleanup_payload,
                )
            ):
                continue
            assert isinstance(target_payload, Mapping)
            assert isinstance(integrated_payload, Mapping)
            assert isinstance(vault_payload, Mapping)
            assert isinstance(cleanup_payload, Mapping)
            if (
                str(cleanup.get("eventKind") or "") != "cleaned"
                or str(cleanup_payload.get("result") or "") != "cleaned"
                or str(integrated_payload.get("integrationRef") or "")
                != str(binding.get("workspaceIntegrationRef") or "")
                or str(integrated_payload.get("patchSha256") or "")
                != str(binding.get("integrationPatchSha256") or "")
                or str(integrated_payload.get("integratedRevision") or "")
                != str(binding.get("integratedRevision") or "")
                or str(
                    integrated_payload.get("integratedSnapshotSha256") or ""
                )
                != str(binding.get("integratedSnapshotSha256") or "")
                or str(integrated_payload.get("targetAppliedReceiptId") or "")
                != str(target.get("eventId") or "")
                or str(
                    integrated_payload.get("targetAppliedReceiptSha256") or ""
                )
                != str(target.get("payloadSha256") or "")
                or str(target_payload.get("integrationRef") or "")
                != str(binding.get("workspaceIntegrationRef") or "")
                or str(target_payload.get("targetAfterSnapshotSha256") or "")
                != str(binding.get("integratedSnapshotSha256") or "")
                or str(cleanup_payload.get("vaultReceiptId") or "")
                != str(vault.get("eventId") or "")
                or str(cleanup_payload.get("vaultReceiptSha256") or "")
                != str(vault.get("payloadSha256") or "")
                or str(cleanup_payload.get("vaultWorkspaceRoot") or "")
                != str(vault_payload.get("vaultWorkspaceRoot") or "")
            ):
                continue
            candidates.append(
                {
                    **binding,
                    "integrated": True,
                    "idempotent": True,
                    "changedFiles": list(
                        integrated_payload.get("changedFiles") or []
                    ),
                    "integrationRef": binding.get(
                        "workspaceIntegrationRef"
                    ),
                    **self._integration_receipt_refs(binding_id),
                }
            )
        return candidates

    def _recover_binding_on_startup(
        self,
        binding: Mapping[str, object],
        *,
        source: Path,
        quarantine: Path,
        vault: Path,
        base: Path,
        now_ms: int,
    ) -> dict[str, object] | None:
        binding_id = str(binding.get("workspaceBindingId") or "")
        state = str(binding.get("workspaceLifecycleState") or "")
        if state in {
            "delivered",
            "delivery_seal_uncertain",
            "delivery_seal_resuming",
        } and self.ledger.source_lease_receipt(binding_id) is None:
            self._fail_closed_delivery_seal(
                binding_id=binding_id,
                source=source,
                base=base,
                reason=(
                    "startup observed delivered evidence without its durable "
                    "source-lease revocation receipt"
                ),
                now_ms=now_ms,
            )
            return self.ledger.binding(binding_id)
        path_exists = source.is_dir() or quarantine.is_dir() or vault.is_dir()
        if state in {"integrated", "abandoned"} and vault.is_dir():
            vault_receipt = self.ledger.vault_receipt(binding_id)
            if vault_receipt is not None:
                evidence_error = self._vault_cleanup_evidence_error(
                    binding=binding,
                    vault=vault,
                    base=base,
                    vault_receipt=vault_receipt,
                )
                if evidence_error:
                    return self._cleanup_failed(
                        binding_id,
                        reason=evidence_error,
                        retained=vault,
                        actor_ref="system:workspace-recovery",
                        now_ms=now_ms,
                    )
                return self.ledger.record_cleanup(
                    binding_id,
                    result="cleaned",
                    reason=(
                        "startup completed the durable cleanup receipt for an exact "
                        "recoverable vault"
                    ),
                    actor_ref="system:workspace-recovery",
                    now_ms=now_ms,
                    retained_workspace_root=str(vault),
                )
        if state == "integrated":
            quarantine_receipt = self.ledger.quarantine_receipt(binding_id)
            if (
                not path_exists
                and self.ledger.writer_quiescence_receipt(binding_id) is not None
                and quarantine_receipt is not None
            ):
                quarantine_payload = quarantine_receipt.get("payload")
                expected_target = (
                    str(quarantine_payload.get("targetSnapshotSha256") or "")
                    if isinstance(quarantine_payload, Mapping)
                    else ""
                )
                try:
                    observed_target = self.snapshot_digest([base])
                except (OSError, RoomWorkspaceError):
                    observed_target = ""
                if not expected_target or observed_target != expected_target:
                    return self._cleanup_failed(
                        binding_id,
                        reason=(
                            "startup observed target drift after physical child "
                            "removal but before its cleanup receipt"
                        ),
                        retained=quarantine,
                        actor_ref="system:workspace-recovery",
                        now_ms=now_ms,
                    )
                return self.ledger.record_cleanup(
                    binding_id,
                    result="missing",
                    reason=(
                        "startup recovered cleanup after the durably authorized "
                        "quarantine path was already removed"
                    ),
                    actor_ref="system:workspace-recovery",
                    now_ms=now_ms,
                )
            return self._cleanup_failed(
                binding_id,
                reason=(
                    "integrated cleanup recovery is deferred until runtime writer "
                    "owners are bound"
                ),
                retained=(
                    vault
                    if vault.is_dir()
                    else quarantine if quarantine.is_dir() else source
                ),
                actor_ref="system:workspace-recovery",
                now_ms=now_ms,
            )
        if state == "reserved" or (
            not path_exists
            and state not in {
                "integrated",
                "abandoned",
                "cleanup_failed",
                "cleaned",
            }
        ):
            return self._retain_binding(
                binding,
                state="orphaned",
                reason=(
                    "workspace materialization was interrupted"
                    if state == "reserved"
                    else "receipted workspace path is missing before terminal cleanup"
                ),
                actor_ref="system:workspace-recovery",
                now_ms=now_ms,
            )
        return None

    def _cleanup_receipted_worktree(
        self,
        binding: Mapping[str, object],
        *,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        binding_id = str(binding.get("workspaceBindingId") or "")
        source = self._receipted_workspace_path(binding, require_exists=False)
        quarantine = self._quarantine_path(binding)
        vault = self._vault_path(binding)
        base = Path(str(binding.get("workspaceBaseRoot") or "")).resolve(
            strict=False
        )
        integrated_receipt = self.ledger.integrated_receipt(binding_id)
        abandonment_receipt = next(
            (
                event
                for event in reversed(self.ledger.events(binding_id))
                if event.get("eventKind") == "abandoned"
            ),
            None,
        )
        terminal_authority = integrated_receipt or abandonment_receipt
        existing_paths = [
            path for path in (source, quarantine, vault) if path.exists()
        ]
        if len(existing_paths) > 1:
            return self._cleanup_failed(
                binding_id,
                reason=(
                    "multiple original, quarantine, or vault child paths exist; cleanup "
                    "identity is ambiguous"
                ),
                retained=(vault if vault.exists() else existing_paths[-1]),
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        retained = existing_paths[0] if existing_paths else source
        if not base.is_dir():
            return self._cleanup_failed(
                binding_id,
                reason="integration base path is unavailable; child was retained",
                retained=retained,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        vault_receipt = self.ledger.vault_receipt(binding_id)
        if integrated_receipt is not None and retained.exists():
            evidence_error = (
                self._vault_cleanup_evidence_error(
                    binding=binding,
                    vault=retained,
                    base=base,
                    vault_receipt=vault_receipt,
                )
                if retained == vault and vault_receipt is not None
                else (
                    ""
                    if retained == vault
                    else self._integration_cleanup_evidence_error(
                        binding=binding,
                        source=retained,
                        base=base,
                        integrated_receipt=integrated_receipt,
                    )
                )
            )
            if evidence_error:
                return self._cleanup_failed(
                    binding_id,
                    reason=evidence_error,
                    retained=retained,
                    actor_ref=actor_ref,
                    now_ms=now_ms,
                )
        if integrated_receipt is not None:
            quiescence_error = self._ensure_writer_quiescence(
                binding=binding,
                integrated_receipt=integrated_receipt,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
            if quiescence_error:
                return self._cleanup_failed(
                    binding_id,
                    reason=quiescence_error,
                    retained=retained,
                    actor_ref=actor_ref,
                    now_ms=now_ms,
                )
        elif abandonment_receipt is not None and (
            self.ledger.abandonment_quiescence_receipt(binding_id) is None
        ):
            return self._cleanup_failed(
                binding_id,
                reason=(
                    "abandoned child lacks its durable writer-quiescence receipt"
                ),
                retained=retained,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        if not retained.exists():
            if (
                terminal_authority is not None
                and (
                    (
                        self.ledger.writer_quiescence_receipt(binding_id) is None
                        and self.ledger.abandonment_quiescence_receipt(binding_id)
                        is None
                    )
                    or self.ledger.quarantine_receipt(binding_id) is None
                    or self.ledger.cleanup_removal_authorization_receipt(binding_id)
                    is None
                )
            ):
                return self._cleanup_failed(
                    binding_id,
                    reason=(
                        "child path is missing without durable writer-quiescence "
                        "and quarantine authorization receipts"
                    ),
                    retained=retained,
                    actor_ref=actor_ref,
                    now_ms=now_ms,
                )
            return self.ledger.record_cleanup(
                binding_id,
                result="missing",
                reason="receipted child path was already absent",
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        if retained == source:
            quarantine.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            moved = self._move_worktree(base, source, quarantine)
            if (
                moved.returncode != 0
                or source.exists()
                or not quarantine.is_dir()
            ):
                return self._cleanup_failed(
                    binding_id,
                    reason=(
                        self._bounded_error(moved.stderr)
                        or "atomic child quarantine did not move the exact worktree"
                    ),
                    retained=quarantine if quarantine.exists() else source,
                    actor_ref=actor_ref,
                    now_ms=now_ms,
                )
            retained = quarantine
        inspection_error = self._open_handle_evidence_error(retained)
        if inspection_error:
            return self._cleanup_failed(
                binding_id,
                reason=inspection_error,
                retained=retained,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        if integrated_receipt is not None and retained != vault:
            evidence_error = self._integration_cleanup_evidence_error(
                binding=binding,
                source=retained,
                base=base,
                integrated_receipt=integrated_receipt,
            )
            if evidence_error:
                return self._cleanup_failed(
                    binding_id,
                    reason=evidence_error,
                    retained=retained,
                    actor_ref=actor_ref,
                    now_ms=now_ms,
                )
        source_receipt = self.ledger.source_lease_receipt(binding_id)
        source_payload = (
            source_receipt.get("payload")
            if isinstance(source_receipt, Mapping)
            else None
        )
        quarantine_receipt = self.ledger.quarantine_receipt(binding_id)
        quarantine_payload = (
            quarantine_receipt.get("payload")
            if isinstance(quarantine_receipt, Mapping)
            else None
        )
        abandonment_quiescence = self.ledger.abandonment_quiescence_receipt(binding_id)
        abandonment_payload = (
            abandonment_quiescence.get("payload")
            if isinstance(abandonment_quiescence, Mapping)
            else None
        )
        if isinstance(source_payload, Mapping):
            expected_source_content = str(
                source_payload.get("workspaceContentSha256") or ""
            )
        elif isinstance(quarantine_payload, Mapping):
            expected_source_content = str(
                quarantine_payload.get("workspaceContentSha256") or ""
            )
        elif isinstance(abandonment_payload, Mapping):
            expected_source_content = str(
                abandonment_payload.get("workspaceContentSha256") or ""
            )
        else:
            expected_source_content = self._workspace_content_digest(retained)
        observed_cleanup_target = self.snapshot_digest([base])
        expected_target = (
            str(binding.get("integratedSnapshotSha256") or "")
            if integrated_receipt is not None
            else observed_cleanup_target
        )
        if terminal_authority is not None and quarantine_receipt is None:
            try:
                self.ledger.record_quarantined(
                    binding_id,
                    quarantined_workspace_root=str(quarantine),
                    workspace_content_sha256=expected_source_content,
                    target_snapshot_sha256=expected_target,
                    actor_ref=actor_ref,
                    now_ms=now_ms,
                )
            except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
                return self._cleanup_failed(
                    binding_id,
                    reason=f"durable quarantine authorization failed: {exc}",
                    retained=retained,
                    actor_ref=actor_ref,
                    now_ms=now_ms,
                )
        try:
            self.ledger.authorize_cleanup_removal(
                binding_id,
                quarantined_workspace_root=str(quarantine),
                vault_workspace_root=str(vault),
                workspace_content_sha256=expected_source_content,
                target_snapshot_sha256=expected_target,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
            removal_authorization = (
                self.ledger.cleanup_removal_authorization_receipt(binding_id)
            )
            if removal_authorization is None:
                raise RoomWorkspaceLedgerError(
                    "cleanup removal authorization receipt is missing"
                )
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            return self._cleanup_failed(
                binding_id,
                reason=f"durable cleanup removal authorization failed: {exc}",
                retained=retained,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        guard_key = str(quarantine.resolve(strict=False))
        self._removal_guards[guard_key] = {
            "workspaceBindingId": binding_id,
            "workspaceContentSha256": expected_source_content,
            "targetSnapshotSha256": expected_target,
            "observedCleanupTargetSnapshotSha256": observed_cleanup_target,
            "vaultWorkspaceRoot": str(vault),
            "removalAuthorizationReceiptId": removal_authorization["eventId"],
            "removalAuthorizationReceiptSha256": removal_authorization[
                "payloadSha256"
            ],
        }
        try:
            removed = self._remove_worktree(base, quarantine)
        finally:
            self._removal_guards.pop(guard_key, None)
        recovery_path = vault if vault.exists() else quarantine
        if removed.returncode != 0 or quarantine.exists() or not vault.is_dir():
            return self._cleanup_failed(
                binding_id,
                reason=(
                    self._bounded_error(removed.stderr)
                    or "atomic vaulting did not remove the exact active Room path"
                ),
                retained=recovery_path,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        vault_receipt = self.ledger.vault_receipt(binding_id)
        vault_error = self._vault_cleanup_evidence_error(
            binding=binding,
            vault=vault,
            base=base,
            vault_receipt=vault_receipt,
        )
        if vault_error:
            return self._cleanup_failed(
                binding_id,
                reason=vault_error,
                retained=vault,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        if self.snapshot_digest([base]) != observed_cleanup_target:
            return self._cleanup_failed(
                binding_id,
                reason="integration target changed during final cleanup",
                retained=vault,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        cleaned = self.ledger.record_cleanup(
            binding_id,
            result="cleaned",
            reason=(
                "exact receipted child left active Room paths and was retained in its "
                "recoverable vault"
            ),
            actor_ref=actor_ref,
            now_ms=now_ms,
            retained_workspace_root=str(vault),
        )
        assert vault_receipt is not None
        vault_payload = vault_receipt.get("payload")
        return {
            **cleaned,
            "retainedWorkspaceRoot": str(vault),
            "vaultContentSha256": (
                str(vault_payload.get("vaultContentSha256") or "")
                if isinstance(vault_payload, Mapping)
                else ""
            ),
        }

    def _cleanup_failed(
        self,
        binding_id: str,
        *,
        reason: str,
        retained: Path,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        result = self.ledger.record_cleanup(
            binding_id,
            result="failed",
            reason=reason,
            actor_ref=actor_ref,
            now_ms=now_ms,
            retained_workspace_root=str(retained),
        )
        return {**result, "retainedWorkspaceRoot": str(retained)}

    def _ensure_writer_quiescence(
        self,
        *,
        binding: Mapping[str, object],
        integrated_receipt: Mapping[str, object],
        actor_ref: str,
        now_ms: int,
    ) -> str:
        binding_id = str(binding.get("workspaceBindingId") or "")
        if self.ledger.writer_quiescence_receipt(binding_id) is not None:
            return ""
        source_receipt = self.ledger.source_lease_receipt(binding_id)
        if source_receipt is None:
            return "writer quiescence lacks its source-lease receipt"
        provider = self._writer_quiescence_provider
        if provider is None:
            return (
                "writer-quiescence provider is unavailable; child was retained "
                "for exact-lineage inspection"
            )
        request = {
            "workspaceBindingId": binding_id,
            "rootId": str(binding.get("rootId") or ""),
            "taskId": str(binding.get("taskId") or ""),
            "dispatchId": str(binding.get("dispatchId") or ""),
            "deliveryRevision": str(binding.get("deliveryRevision") or ""),
            "ownerSessionId": str(binding.get("currentOwnerSessionId") or ""),
            "sourceLeaseReceiptId": str(source_receipt.get("eventId") or ""),
            "sourceLeaseReceiptSha256": str(
                source_receipt.get("payloadSha256") or ""
            ),
            "integratedReceiptId": str(integrated_receipt.get("eventId") or ""),
            "integratedReceiptSha256": str(
                integrated_receipt.get("payloadSha256") or ""
            ),
        }
        try:
            receipt = provider(request)
            if not isinstance(receipt, Mapping):
                return "writer-quiescence provider returned no durable receipt"
            self.ledger.record_writer_quiescence(
                binding_id,
                receipt=receipt,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        except (OSError, RoomWorkspaceError, RoomWorkspaceLedgerError) as exc:
            return f"writer-quiescence proof failed: {exc}"
        return ""

    def _open_handle_evidence_error(self, workspace: Path) -> str:
        inspector = self._handle_inspector
        if inspector is None:
            return "open-handle inspector is unavailable; quarantined child was retained"
        try:
            evidence = inspector(workspace)
        except (OSError, RoomWorkspaceError) as exc:
            return f"open-handle inspection failed: {exc}"
        if not isinstance(evidence, Mapping) or evidence.get("known") is not True:
            return "open-handle inspection is unknown; quarantined child was retained"
        active_count = evidence.get("activeCount")
        if isinstance(active_count, bool) or not isinstance(active_count, int):
            return "open-handle inspection returned an invalid active count"
        if active_count != 0:
            return (
                f"quarantined child still has {active_count} open handle(s) or cwd; "
                "child was retained"
            )
        return ""

    @staticmethod
    def _inspect_open_handles(workspace: Path) -> Mapping[str, object]:
        lsof = Path("/usr/sbin/lsof")
        if not lsof.is_file():
            return {"known": False, "activeCount": None, "reason": "lsof missing"}
        try:
            result = subprocess.run(
                [str(lsof), "-F", "pfn", "+D", str(workspace)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"known": False, "activeCount": None, "reason": str(exc)}
        if result.returncode == 1 and not result.stdout and not result.stderr:
            return {"known": True, "activeCount": 0, "inspector": "lsof"}
        if result.returncode != 0:
            return {
                "known": False,
                "activeCount": None,
                "reason": result.stderr.decode("utf-8", errors="replace")[:1000],
            }
        pids = {
            line[1:]
            for line in result.stdout.splitlines()
            if line.startswith(b"p") and line[1:]
        }
        return {"known": True, "activeCount": len(pids), "inspector": "lsof"}

    def _quarantine_path(self, binding: Mapping[str, object]) -> Path:
        binding_id = str(binding.get("workspaceBindingId") or "")
        source_name = Path(str(binding.get("workspaceRoot") or "workspace")).name
        identity = hashlib.sha256(binding_id.encode("utf-8")).hexdigest()[:24]
        return (self.root_dir / ".quarantine" / f"{identity}-{source_name}").resolve(
            strict=False
        )

    def _vault_path(self, binding: Mapping[str, object]) -> Path:
        binding_id = str(binding.get("workspaceBindingId") or "")
        source_name = Path(str(binding.get("workspaceRoot") or "workspace")).name
        identity = hashlib.sha256(binding_id.encode("utf-8")).hexdigest()[:24]
        return (self.root_dir / ".vault" / f"{identity}-{source_name}").resolve(
            strict=False
        )

    def _vault_cleanup_evidence_error(
        self,
        *,
        binding: Mapping[str, object],
        vault: Path,
        base: Path,
        vault_receipt: Mapping[str, object] | None,
    ) -> str:
        if vault_receipt is None:
            return "recoverable vault lacks its durable byte receipt"
        payload = vault_receipt.get("payload")
        if not isinstance(payload, Mapping):
            return "recoverable vault receipt payload is invalid"
        binding_id = str(binding.get("workspaceBindingId") or "")
        authorization = self.ledger.cleanup_removal_authorization_receipt(binding_id)
        if authorization is None:
            return "recoverable vault lost its cleanup CAS authority"
        authorization_payload = authorization.get("payload")
        if not isinstance(authorization_payload, Mapping):
            return "recoverable vault cleanup authority payload is invalid"
        expected_owner = {
            "rootId": binding.get("rootId"),
            "taskId": binding.get("taskId"),
            "dispatchId": binding.get("dispatchId"),
            "ownerParticipantId": binding.get("currentOwnerParticipantId"),
            "ownerSessionId": binding.get("currentOwnerSessionId"),
        }
        if any(
            str(payload.get(key) or "") != str(expected or "")
            for key, expected in expected_owner.items()
        ):
            return "recoverable vault receipt lost its exact owner or Session binding"
        if any(
            str(payload.get(key) or "") != str(expected)
            for key, expected in {
                "vaultWorkspaceRoot": str(vault),
                "authorizedWorkspaceContentSha256": authorization_payload.get(
                    "workspaceContentSha256"
                ),
                "targetSnapshotSha256": authorization_payload.get(
                    "targetSnapshotSha256"
                ),
                "removalAuthorizationReceiptId": authorization.get("eventId"),
                "removalAuthorizationReceiptSha256": authorization.get(
                    "payloadSha256"
                ),
                "authoritySequence": authorization.get("sequence"),
            }.items()
        ):
            return "recoverable vault receipt is outside its exact cleanup lineage"
        try:
            vaulted_content = self._vault_content_digest(vault)
        except (OSError, RoomWorkspaceError) as exc:
            return f"recoverable vault evidence could not be verified: {exc}"
        if vaulted_content != str(payload.get("vaultContentSha256") or ""):
            return "recoverable vault bytes changed after their durable receipt"
        return ""

    def _integration_cleanup_evidence_error(
        self,
        *,
        binding: Mapping[str, object],
        source: Path,
        base: Path,
        integrated_receipt: Mapping[str, object],
    ) -> str:
        binding_id = str(binding.get("workspaceBindingId") or "")
        source_receipt = self.ledger.source_lease_receipt(binding_id)
        target_receipt = self.ledger.target_applied_receipt(binding_id)
        if source_receipt is None or target_receipt is None:
            return (
                "integration cleanup lacks immutable source-lease or target-applied "
                "authority; child was retained"
            )
        source_payload = source_receipt.get("payload")
        target_payload = target_receipt.get("payload")
        integrated_payload = integrated_receipt.get("payload")
        if not all(
            isinstance(value, Mapping)
            for value in (source_payload, target_payload, integrated_payload)
        ):
            return "integration cleanup receipt payload is invalid; child was retained"
        assert isinstance(source_payload, Mapping)
        assert isinstance(target_payload, Mapping)
        assert isinstance(integrated_payload, Mapping)
        if any(
            str(target_payload.get(key) or "") != str(expected)
            for key, expected in {
                "patchSha256": source_payload.get("patchSha256"),
                "sourceLeaseReceiptId": source_receipt.get("eventId"),
                "sourceLeaseReceiptSha256": source_receipt.get("payloadSha256"),
                "patchArtifactPath": source_payload.get("patchArtifactPath"),
            }.items()
        ) or target_payload.get("patchArtifactSize") != source_payload.get(
            "patchArtifactSize"
        ):
            return (
                "target-applied receipt is not bound to the immutable source artifact; "
                "child was retained"
            )
        if any(
            str(integrated_payload.get(key) or "") != str(expected)
            for key, expected in {
                "patchSha256": source_payload.get("patchSha256"),
                "targetAppliedReceiptId": target_receipt.get("eventId"),
                "targetAppliedReceiptSha256": target_receipt.get("payloadSha256"),
                "sourceLeaseReceiptId": source_receipt.get("eventId"),
                "sourceLeaseReceiptSha256": source_receipt.get("payloadSha256"),
                "integratedSnapshotSha256": target_payload.get(
                    "targetAfterSnapshotSha256"
                ),
            }.items()
        ):
            return (
                "integration cleanup receipt chain is incomplete or mismatched; "
                "child was retained"
            )
        try:
            self._read_patch_artifact(source_payload)
            source_snapshot = self._workspace_content_digest(source)
        except (OSError, RoomWorkspaceError) as exc:
            return f"integration cleanup evidence could not be verified: {exc}"
        if source_snapshot != str(
            source_payload.get("workspaceContentSha256") or ""
        ):
            return (
                "source changed after its durable write-lease revocation; child was "
                "retained"
            )
        if str(binding.get("integratedSnapshotSha256") or "") != str(
            target_payload.get("targetAfterSnapshotSha256") or ""
        ):
            return (
                "binding projection does not match the exact target-after receipt; "
                "child was retained"
            )
        return ""

    def _retain_binding(
        self,
        binding: Mapping[str, object],
        *,
        state: str,
        reason: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        source = self._receipted_workspace_path(binding, require_exists=False)
        snapshot = ""
        if source.is_dir():
            try:
                snapshot = self.snapshot_digest([source])
            except RoomWorkspaceError:
                pass
        try:
            return self.ledger.retain(
                str(binding.get("workspaceBindingId") or ""),
                reason=reason,
                state=state,
                workspace_snapshot_sha256=snapshot,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            raise RoomWorkspaceError(str(exc)) from exc

    def _receipted_workspace_path(
        self,
        binding: Mapping[str, object],
        *,
        require_exists: bool,
    ) -> Path:
        raw = str(binding.get("workspaceRoot") or "").strip()
        if not raw:
            raise RoomWorkspaceError("workspace binding has no physical path")
        source = Path(raw).expanduser().resolve(strict=require_exists)
        try:
            source.relative_to(self.root_dir)
        except ValueError as exc:
            raise RoomWorkspaceError(
                "receipted workspace path is outside the managed workspace root"
            ) from exc
        return source

    def _workspace_patch(self, source: Path) -> bytes:
        self._git_bytes(source, "add", "-N", "--", ".")
        return self._git_bytes(
            source,
            "diff",
            "--binary",
            "--full-index",
            "HEAD",
            "--",
        )

    def _changed_files(self, source: Path) -> list[str]:
        return [
            value.decode("utf-8", errors="strict")
            for value in self._git_bytes(
                source,
                "diff",
                "--name-only",
                "-z",
                "HEAD",
                "--",
            ).split(b"\0")
            if value
        ]

    def _seal_patch_artifact(
        self,
        *,
        binding_id: str,
        delivery_revision: str,
        patch: bytes,
    ) -> Path:
        artifact_root = self.root_dir / ".artifacts"
        artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(artifact_root, 0o700)
        patch_sha256 = hashlib.sha256(patch).hexdigest()
        artifact = self._sealed_patch_artifact_path(
            binding_id=binding_id,
            delivery_revision=delivery_revision,
            patch_sha256=patch_sha256,
        )
        identity = artifact.name.split("-", 1)[0]
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{identity}-",
            suffix=".tmp",
            dir=artifact_root,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(patch)
                stream.flush()
                os.fchmod(stream.fileno(), 0o400)
                os.fsync(stream.fileno())
            try:
                os.link(temporary, artifact)
            except FileExistsError:
                pass
            directory_fd = os.open(artifact_root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        self._read_patch_artifact(
            {
                "patchArtifactPath": str(artifact),
                "patchArtifactSize": len(patch),
                "patchSha256": patch_sha256,
            }
        )
        return artifact

    def _sealed_patch_artifact_path(
        self,
        *,
        binding_id: str,
        delivery_revision: str,
        patch_sha256: str,
    ) -> Path:
        identity = hashlib.sha256(
            f"{binding_id}\0{delivery_revision}".encode("utf-8")
        ).hexdigest()[:32]
        return self.root_dir / ".artifacts" / f"{identity}-{patch_sha256}.patch"

    def _read_patch_artifact(self, evidence: Mapping[str, object]) -> bytes:
        raw_path = str(evidence.get("patchArtifactPath") or "").strip()
        if not raw_path:
            raise RoomWorkspaceError("sealed patch artifact path is missing")
        artifact = Path(raw_path).expanduser()
        try:
            metadata = artifact.lstat()
        except OSError as exc:
            raise RoomWorkspaceError(
                f"sealed patch artifact is unavailable: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RoomWorkspaceError("sealed patch artifact is not a regular file")
        if metadata.st_mode & 0o222:
            raise RoomWorkspaceError("sealed patch artifact became writable")
        artifact = artifact.resolve(strict=True)
        artifact_root = (self.root_dir / ".artifacts").resolve(strict=True)
        try:
            artifact.relative_to(artifact_root)
        except ValueError as exc:
            raise RoomWorkspaceError(
                "sealed patch artifact is outside the coordinator artifact root"
            ) from exc
        expected_size = evidence.get("patchArtifactSize")
        if isinstance(expected_size, bool) or not isinstance(expected_size, int):
            raise RoomWorkspaceError("sealed patch artifact size is invalid")
        payload = artifact.read_bytes()
        if len(payload) != expected_size:
            raise RoomWorkspaceError("sealed patch artifact size changed")
        expected_sha256 = str(evidence.get("patchSha256") or "")
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise RoomWorkspaceError("sealed patch artifact digest changed")
        return payload

    def _revoke_source_write_lease(
        self,
        *,
        owner_session_id: str,
        source: Path,
        base: Path,
    ) -> str:
        if not owner_session_id:
            raise RoomWorkspaceError(
                "workspace delivery has no current owner Session to revoke"
            )
        self._set_session_roots(
            owner_session_id,
            [base],
            policy="read_only",
            grant_workspace_scope=True,
        )
        session = self.sessions.get(owner_session_id)
        roots = [
            str(Path(str(value)).expanduser().resolve(strict=False))
            for value in session.get("workspaceRoots") or []
            if str(value).strip()
        ]
        if (
            str(session.get("executionMode") or "") != "read_only"
            or str(source) in roots
            or roots != [str(base)]
        ):
            raise RoomWorkspaceError(
                "worker Session write lease was not durably revoked"
            )
        material = {
            "sessionId": owner_session_id,
            "executionMode": session.get("executionMode"),
            "toolProfileVersion": session.get("toolProfileVersion"),
            "workspaceRoots": roots,
            "workspaceScopeGranted": bool(session.get("workspaceScopeGranted")),
            "workspaceScopeSha256": session.get("workspaceScopeSha256"),
        }
        return hashlib.sha256(
            json.dumps(
                material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @contextmanager
    def _repository_integration_lock(
        self,
        base: Path,
        *,
        expected_repository_id: str,
    ) -> Iterator[None]:
        if self._repository_identity(base) != expected_repository_id:
            raise RoomWorkspaceError(
                "integration repository no longer matches its durable identity"
            )
        common_raw = self._git_text(base, "rev-parse", "--git-common-dir")
        common = Path(common_raw)
        if not common.is_absolute():
            common = (base / common).resolve(strict=True)
        else:
            common = common.resolve(strict=True)
        lock_path = common / "personal-agent-workbench-room-integration.lock"
        lock_key = str(lock_path)
        with _REPOSITORY_LOCKS_GUARD:
            process_lock = _REPOSITORY_LOCKS.setdefault(
                lock_key,
                threading.RLock(),
            )
        if not process_lock.acquire(timeout=30.0):
            raise RoomWorkspaceError(
                "timed out waiting for the process repository integration lock"
            )
        descriptor = -1
        acquired = False
        deadline = time.monotonic() + 30.0
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            while not acquired:
                try:
                    fcntl.flock(
                        descriptor,
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                    acquired = True
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise RoomWorkspaceError(
                            "timed out waiting for the repository integration lock"
                        ) from exc
                    time.sleep(0.05)
            yield
        finally:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            if descriptor >= 0:
                os.close(descriptor)
            process_lock.release()

    def _delivery_manifest(
        self,
        source: Path,
        *,
        baseline_commit: str,
    ) -> dict[str, object]:
        raw = self._git_bytes(
            source,
            "diff",
            "--numstat",
            "-z",
            "--no-renames",
            baseline_commit,
            "--",
        )
        records = [value for value in raw.split(b"\0") if value]
        if len(records) > _DELIVERY_MAX_FILES:
            raise RoomWorkspaceError(
                "workspace delivery exceeds the bounded changed-file limit"
            )
        files: list[dict[str, object]] = []
        additions = 0
        deletions = 0
        binary_files = 0
        generated_files = 0
        redacted_files = 0
        for ordinal, record in enumerate(records, start=1):
            try:
                added_raw, deleted_raw, path_raw = record.split(b"\t", 2)
            except ValueError as exc:
                raise RoomWorkspaceError(
                    "workspace delivery numstat is malformed"
                ) from exc
            if not path_raw or len(path_raw) > _DELIVERY_MAX_PATH_BYTES:
                raise RoomWorkspaceError(
                    "workspace delivery contains an invalid or oversized path"
                )
            try:
                relative_path = path_raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                relative_path = ""
            path_parts = tuple(
                part.lower()
                for part in Path(relative_path).parts
            )
            unsafe = (
                not relative_path
                or relative_path.startswith("/")
                or ".." in path_parts
            )
            if unsafe:
                sensitive = True
            else:
                name = path_parts[-1] if path_parts else ""
                credential_stem = any(
                    name == stem
                    or any(
                        name.startswith(f"{stem}{separator}")
                        for separator in (".", "-", "_")
                    )
                    for stem in (
                        "secret",
                        "secrets",
                        "token",
                        "tokens",
                        "credential",
                        "credentials",
                    )
                )
                sensitive = (
                    name in _DELIVERY_SENSITIVE_NAMES
                    or name.startswith(".env.")
                    or any(
                        part in _DELIVERY_SENSITIVE_PARTS
                        for part in path_parts
                    )
                    or name.endswith(_DELIVERY_SENSITIVE_SUFFIXES)
                    or credential_stem
                    or "keychain" in name
                    or any(
                        ord(character) < 32 or ord(character) == 127
                        for character in relative_path
                    )
                )
            generated = any(
                part in _DELIVERY_GENERATED_PARTS
                for part in path_parts[:-1]
            ) or (
                bool(path_parts)
                and (
                    path_parts[-1].endswith(".min.js")
                    or path_parts[-1].endswith(".min.css")
                    or path_parts[-1].endswith(".map")
                )
            )
            binary = added_raw == b"-" and deleted_raw == b"-"
            if binary:
                added = None
                deleted = None
                binary_files += 1
            else:
                try:
                    added = int(added_raw)
                    deleted = int(deleted_raw)
                except ValueError as exc:
                    raise RoomWorkspaceError(
                        "workspace delivery numstat counts are invalid"
                    ) from exc
                if not 0 <= added <= 1_000_000_000 or not 0 <= deleted <= 1_000_000_000:
                    raise RoomWorkspaceError(
                        "workspace delivery numstat counts exceed bounds"
                    )
                additions += added
                deletions += deleted
            if sensitive:
                redacted_files += 1
            if generated:
                generated_files += 1
            files.append(
                {
                    "path": (
                        f"[redacted-file-{ordinal}]"
                        if sensitive
                        else relative_path
                    ),
                    "additions": added,
                    "deletions": deleted,
                    "binary": binary,
                    "generated": generated,
                    "redacted": sensitive,
                }
            )
        totals = {
            "fileCount": len(files),
            "additions": additions,
            "deletions": deletions,
            "binaryFiles": binary_files,
            "generatedFiles": generated_files,
            "redactedFiles": redacted_files,
        }
        material = {
            "baselineCommit": baseline_commit,
            "files": files,
            "totals": totals,
        }
        encoded = json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _DELIVERY_MAX_MANIFEST_BYTES:
            raise RoomWorkspaceError(
                "workspace delivery manifest exceeds its bounded size"
            )
        return {
            "manifestSha256": hashlib.sha256(encoded).hexdigest(),
            "files": files,
            "totals": totals,
        }

    @staticmethod
    def _delivery_revision(
        *,
        base_commit: str,
        workspace_snapshot_sha256: str,
        patch_sha256: str,
        manifest_sha256: str,
        metadata: Mapping[str, object],
    ) -> str:
        metadata_sha256 = hashlib.sha256(
            json.dumps(
                dict(metadata),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return "sha256:" + hashlib.sha256(
            b"\0".join(
                (
                    base_commit.encode("utf-8"),
                    workspace_snapshot_sha256.encode("utf-8"),
                    patch_sha256.encode("utf-8"),
                    manifest_sha256.encode("utf-8"),
                    metadata_sha256.encode("utf-8"),
                )
            )
        ).hexdigest()

    def _capture_delivered_workspace(
        self,
        source: Path,
        *,
        expected_commit: str,
        delivery_payload: Mapping[str, object],
    ) -> dict[str, object]:
        workspace_delivery = delivery_payload.get("workspaceDelivery")
        if not isinstance(workspace_delivery, Mapping):
            raise RoomWorkspaceError(
                "workspace delivery receipt lacks immutable workspace evidence"
            )
        patch = self._workspace_patch(source)
        patch_sha256 = hashlib.sha256(patch).hexdigest()
        snapshot = self.snapshot_digest([source])
        manifest = self._delivery_manifest(
            source,
            baseline_commit=expected_commit,
        )
        manifest_sha256 = str(manifest["manifestSha256"])
        metadata = {
            "artifactRefs": workspace_delivery.get("artifactRefs"),
            "verificationRefs": workspace_delivery.get("verificationRefs"),
            "verifications": workspace_delivery.get("verifications"),
            "residualRisks": workspace_delivery.get("residualRisks"),
            "resultSummary": workspace_delivery.get("resultSummary"),
        }
        revision = self._delivery_revision(
            base_commit=expected_commit,
            workspace_snapshot_sha256=snapshot,
            patch_sha256=patch_sha256,
            manifest_sha256=manifest_sha256,
            metadata=metadata,
        )
        current = {
            "deliveryRevision": revision,
            "deliveryHead": expected_commit,
            "workspaceSnapshotSha256": snapshot,
            "patchSha256": patch_sha256,
            "manifestSha256": manifest_sha256,
        }
        receipted = {
            "deliveryRevision": delivery_payload.get("deliveryRevision"),
            "deliveryHead": delivery_payload.get("deliveryHead"),
            "workspaceSnapshotSha256": delivery_payload.get(
                "workspaceSnapshotSha256"
            ),
            "patchSha256": delivery_payload.get("patchSha256"),
            "manifestSha256": delivery_payload.get("manifestSha256"),
        }
        nested = {
            "deliveryRevision": workspace_delivery.get("deliveryRevision"),
            "deliveryHead": workspace_delivery.get("baseCommit"),
            "workspaceSnapshotSha256": workspace_delivery.get(
                "workspaceSnapshotSha256"
            ),
            "patchSha256": workspace_delivery.get("patchSha256"),
            "manifestSha256": workspace_delivery.get("manifestSha256"),
        }
        if receipted != current or nested != current:
            raise RoomWorkspaceError(
                "isolated workspace changed after its delivery receipt"
            )
        return {
            **current,
            "patch": patch,
            "manifest": manifest,
        }

    @staticmethod
    def _sealed_delivery_matches_settlement_replay(
        prior: Mapping[str, object],
        candidate: Mapping[str, object],
        *,
        invocation_created_at_ms: int | None,
    ) -> bool:
        """Recognize only the crash replay of the invocation that sealed it.

        A delivery is written before the enclosing Room settle transaction.
        If the latter fails, retrying the same tool invocation must reuse that
        sealed generation instead of asking for a new writer lease.  A later
        invocation cannot match because its creation time is after the sealed
        delivery; changed bytes or evidence are rejected independently.
        """

        if invocation_created_at_ms is None or invocation_created_at_ms < 0:
            return False
        try:
            delivered_at_ms = int(prior.get("deliveredAtMs") or -1)
        except (TypeError, ValueError):
            return False
        if not (
            invocation_created_at_ms
            <= delivered_at_ms
            <= invocation_created_at_ms + 60_000
        ):
            return False
        stable_fields = (
            "schemaVersion",
            "workItemId",
            "taskId",
            "baseCommit",
            "workspaceSnapshotSha256",
            "patchSha256",
            "manifestSha256",
            "files",
            "totals",
            "artifactRefs",
            "verificationCount",
            "verifications",
            "verificationRefs",
            "residualRisks",
        )
        if any(prior.get(key) != candidate.get(key) for key in stable_fields):
            return False
        prior_summary = " ".join(str(prior.get("resultSummary") or "").split())
        candidate_summary = " ".join(
            str(candidate.get("resultSummary") or "").split()
        )
        if prior_summary and (
            prior_summary != candidate_summary
            or prior.get("deliveryRevision") != candidate.get("deliveryRevision")
        ):
            return False
        return True

    @staticmethod
    def _delivery_refs(values: Sequence[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = " ".join(str(value or "").split())[:1_000]
            if normalized and normalized not in result:
                result.append(normalized)
            if len(result) >= 128:
                break
        return result

    @staticmethod
    def _delivery_verification_results(
        values: Sequence[Mapping[str, object]],
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for value in values:
            status = str(value.get("result") or "").strip()
            if status not in {"pass", "fail", "not_verified", "recorded"}:
                raise RoomWorkspaceError(
                    "workspace delivery verification result is invalid"
                )
            result.append(
                {
                    "label": f"验收项 {len(result) + 1}",
                    "result": status,
                    "source": "quality_gate",
                }
            )
            if len(result) >= 64:
                break
        return result

    @staticmethod
    def _prepared_payload(
        binding: Mapping[str, object],
        restore_policy: Mapping[str, object],
        *,
        created_by_attempt: bool,
    ) -> dict[str, object]:
        return _PreparedWorkspace(
            {
            "workspaceBindingId": binding["workspaceBindingId"],
            "workspaceRepositoryId": binding["repositoryId"],
            "workspacePolicy": binding["workspacePolicy"],
            "workspaceRoot": binding["workspaceRoot"],
            "workspaceBaseRoot": binding["workspaceBaseRoot"],
            "workspaceBaseCommit": binding["workspaceBaseCommit"],
            "workspaceIntegrationState": "pending",
            "workspaceIntegrationRef": binding.get("workspaceIntegrationRef"),
            "workspaceLifecycleState": binding["workspaceLifecycleState"],
            "workspaceCleanupState": binding["cleanupState"],
            "workspaceAttentionRequired": bool(binding["attentionRequired"]),
            "workspaceRestorePolicy": dict(restore_policy),
            },
            created_by_attempt=created_by_attempt,
        )

    def task_snapshot_digest(self, task: Mapping[str, object]) -> str:
        raw_root = str(
            task.get("workspaceBaseRoot")
            or task.get("workspaceRoot")
            or ""
        ).strip()
        if not raw_root:
            return ""
        try:
            resolved = Path(raw_root).expanduser().resolve(strict=True)
        except OSError:
            return ""
        return self.snapshot_digest([resolved])

    def snapshot_digest(self, roots: Sequence[Path]) -> str:
        """Hash the complete supported Git identity and workspace bytes."""

        return self._snapshot_digest(roots, include_root_identity=True)

    def _workspace_content_digest(self, root: Path) -> str:
        """Hash workspace content without its relocatable absolute path."""

        return self._snapshot_digest([root], include_root_identity=False)

    @staticmethod
    def _vault_content_digest(root: Path) -> str:
        """Hash every recoverable vault byte without relying on live Git metadata."""

        normalized = Path(root).expanduser().resolve(strict=True)
        if normalized.is_symlink() or not normalized.is_dir():
            raise RoomWorkspaceError("recoverable vault root is not an exact directory")
        digest = hashlib.sha256()

        def visit(directory: Path, relative_root: Path) -> None:
            try:
                entries = sorted(
                    directory.iterdir(),
                    key=lambda item: os.fsencode(item.name),
                )
            except OSError as exc:
                raise RoomWorkspaceError(
                    "recoverable vault directory could not be enumerated"
                ) from exc
            for entry in entries:
                relative = relative_root / entry.name
                relative_bytes = os.fsencode(str(relative))
                try:
                    metadata = entry.lstat()
                except OSError as exc:
                    raise RoomWorkspaceError(
                        "recoverable vault entry changed during hashing"
                    ) from exc
                RoomWorkspaceCoordinator._digest_component(
                    digest,
                    b"vault-path",
                    relative_bytes,
                )
                RoomWorkspaceCoordinator._digest_component(
                    digest,
                    b"vault-mode",
                    int(metadata.st_mode).to_bytes(8, "big"),
                )
                if stat.S_ISLNK(metadata.st_mode):
                    RoomWorkspaceCoordinator._digest_component(
                        digest,
                        b"vault-symlink",
                        os.fsencode(os.readlink(entry)),
                    )
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    visit(entry, relative)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    raise RoomWorkspaceError(
                        "recoverable vault contains an unsupported special file"
                    )
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                try:
                    descriptor = os.open(entry, flags)
                except OSError as exc:
                    raise RoomWorkspaceError(
                        "recoverable vault file could not be opened exactly"
                    ) from exc
                try:
                    opened = os.fstat(descriptor)
                    if (
                        opened.st_dev != metadata.st_dev
                        or opened.st_ino != metadata.st_ino
                        or not stat.S_ISREG(opened.st_mode)
                    ):
                        raise RoomWorkspaceError(
                            "recoverable vault file identity changed during hashing"
                        )
                    with os.fdopen(descriptor, "rb", closefd=False) as handle:
                        while chunk := handle.read(1024 * 1024):
                            RoomWorkspaceCoordinator._digest_component(
                                digest,
                                b"vault-bytes",
                                chunk,
                            )
                    after = os.fstat(descriptor)
                    if any(
                        before != current
                        for before, current in (
                            (opened.st_size, after.st_size),
                            (opened.st_mtime_ns, after.st_mtime_ns),
                            (opened.st_ctime_ns, after.st_ctime_ns),
                        )
                    ):
                        raise RoomWorkspaceError(
                            "recoverable vault file changed during hashing"
                        )
                finally:
                    os.close(descriptor)

        visit(normalized, Path())
        return digest.hexdigest()

    def _snapshot_digest(
        self,
        roots: Sequence[Path],
        *,
        include_root_identity: bool,
    ) -> str:

        digest = hashlib.sha256()
        normalized_roots = [
            Path(root).expanduser().resolve(strict=True)
            for root in roots
        ]
        if not normalized_roots:
            raise RoomWorkspaceError(
                "read_only review requires a supported Git workspace root"
            )
        for root in normalized_roots:
            try:
                top = Path(
                    self._git_text(root, "rev-parse", "--show-toplevel")
                ).resolve(strict=True)
                head = self._git_bytes(root, "rev-parse", "HEAD")
                tree = self._git_bytes(root, "rev-parse", "HEAD^{tree}")
                tree_entries = self._git_bytes(
                    root,
                    "ls-tree",
                    "-r",
                    "-z",
                    "HEAD",
                )
                index = self._git_bytes(root, "ls-files", "--stage", "-z")
                staged = self._git_bytes(
                    root,
                    "diff",
                    "--cached",
                    "--binary",
                    "--full-index",
                    "HEAD",
                    "--",
                )
                worktree = self._git_bytes(
                    root,
                    "diff",
                    "--binary",
                    "--full-index",
                    "--",
                )
                combined = self._git_bytes(
                    root,
                    "diff",
                    "--binary",
                    "--full-index",
                    "HEAD",
                    "--",
                )
                status = self._git_bytes(
                    root,
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=all",
                )
            except (RoomWorkspaceError, UnicodeError) as exc:
                raise RoomWorkspaceError(
                    "read_only review requires a supported Git worktree"
                ) from exc
            if top != root:
                raise RoomWorkspaceError(
                    "read_only review root must be the Git worktree root"
                )
            if include_root_identity:
                self._digest_component(digest, b"root", str(root).encode("utf-8"))
            self._digest_component(digest, b"head", head)
            self._digest_component(digest, b"head-tree", tree)
            self._digest_component(digest, b"head-tree-entries", tree_entries)
            self._digest_component(digest, b"index", index)
            self._digest_component(digest, b"staged", staged)
            self._digest_component(digest, b"worktree", worktree)
            self._digest_component(digest, b"combined", combined)
            self._digest_component(digest, b"status", status)
            for entry in status.split(b"\0"):
                if not entry:
                    continue
                if not entry.startswith(b"?? "):
                    continue
                relative_bytes = entry[3:]
                relative = os.fsdecode(relative_bytes)
                candidate = (root / relative).resolve(strict=False)
                try:
                    candidate.relative_to(root)
                except ValueError as exc:
                    raise RoomWorkspaceError(
                        "Git status escaped the workspace root"
                    ) from exc
                if candidate.is_symlink() or not candidate.is_file():
                    raise RoomWorkspaceError(
                        "read_only review cannot hash an unsupported untracked path"
                    )
                self._digest_component(
                    digest,
                    b"untracked-path",
                    relative_bytes,
                )
                with candidate.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        self._digest_component(digest, b"untracked-bytes", chunk)
        return digest.hexdigest()

    @staticmethod
    def _digest_component(
        digest: "hashlib._Hash",
        label: bytes,
        value: bytes,
    ) -> None:
        digest.update(label)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)

    def _isolated_task_roots(
        self,
        task: Mapping[str, object],
    ) -> tuple[Path, Path, str]:
        source = Path(str(task.get("workspaceRoot") or "")).resolve(
            strict=True
        )
        base = Path(str(task.get("workspaceBaseRoot") or "")).resolve(
            strict=True
        )
        expected_commit = str(task.get("workspaceBaseCommit") or "").strip()
        if not expected_commit:
            raise RoomWorkspaceError("isolated worktree has no base commit")
        try:
            top = Path(
                self._git_text(source, "rev-parse", "--show-toplevel")
            ).resolve(strict=True)
        except (RoomWorkspaceError, OSError, UnicodeError) as exc:
            raise RoomWorkspaceError(
                "isolated Task workspace is not a supported Git worktree"
            ) from exc
        if top != source or self._git_text(source, "rev-parse", "HEAD") != expected_commit:
            raise RoomWorkspaceError(
                "isolated Task workspace identity no longer matches its lease"
            )
        try:
            source.relative_to(self.root_dir)
        except ValueError as exc:
            raise RoomWorkspaceError(
                "isolated Task workspace is outside the managed workspace root"
            ) from exc
        return source, base, expected_commit

    def _assert_task_binding_identity(
        self,
        task: Mapping[str, object],
        binding: Mapping[str, object],
    ) -> None:
        """Reject a Task payload that tries to retarget durable workspace evidence."""

        task_id = str(task.get("taskId") or "").strip()
        root_id = str(task.get("rootId") or "").strip()
        task_source = Path(str(task.get("workspaceRoot") or "")).expanduser().resolve(
            strict=False
        )
        task_base = Path(
            str(task.get("workspaceBaseRoot") or "")
        ).expanduser().resolve(strict=False)
        binding_source = Path(
            str(binding.get("workspaceRoot") or "")
        ).expanduser().resolve(strict=False)
        binding_base = Path(
            str(binding.get("workspaceBaseRoot") or "")
        ).expanduser().resolve(strict=False)
        if (
            (task_id and task_id != str(binding.get("taskId") or ""))
            or (root_id and root_id != str(binding.get("rootId") or ""))
            or task_source != binding_source
            or task_base != binding_base
            or str(task.get("workspaceBaseCommit") or "").strip()
            != str(binding.get("workspaceBaseCommit") or "")
            or str(task.get("workspacePolicy") or "")
            != str(binding.get("workspacePolicy") or "")
        ):
            raise RoomWorkspaceError(
                "Task workspace identity does not match its durable binding"
            )
        task_repository_id = str(task.get("workspaceRepositoryId") or "").strip()
        if task_repository_id and task_repository_id != str(
            binding.get("repositoryId") or ""
        ):
            raise RoomWorkspaceError(
                "Task repository identity does not match its durable binding"
            )
        if task_base.is_dir() and self._repository_identity(task_base) != str(
            binding.get("repositoryId") or ""
        ):
            raise RoomWorkspaceError(
                "integration base repository no longer matches the durable binding"
            )

    @staticmethod
    def _restore_policy(session: Mapping[str, object]) -> dict[str, object]:
        allowlist_mode = (
            "explicit"
            if session.get("toolAllowlistMode") == "explicit"
            else "profile"
        )
        allowed_tools = (
            [
                str(value)[:160]
                for value in session.get("allowedTools") or []
                if str(value).strip()
            ]
            if allowlist_mode == "explicit"
            else []
        )
        return {
            "mode": str(session.get("mode") or "coordinator"),
            "toolProfileVersion": str(
                session.get("toolProfileVersion") or "control-center-v1"
            ),
            "executionMode": str(
                session.get("executionMode") or "per_action"
            ),
            "workspaceScopeGranted": bool(session.get("workspaceScopeGranted")),
            "workspaceScopeSha256": str(
                session.get("workspaceScopeSha256") or ""
            ),
            "workspaceScopeGrantedAtMs": int(
                session.get("workspaceScopeGrantedAtMs") or 0
            ),
            "toolAllowlistMode": allowlist_mode,
            "allowedTools": allowed_tools,
            "projectContextEnabled": bool(
                session.get("projectContextEnabled")
            ),
            "piSkillsEnabled": bool(session.get("piSkillsEnabled")),
            "codexSkillsEnabled": bool(session.get("codexSkillsEnabled")),
        }

    def _set_session_roots(
        self,
        session_id: str,
        roots: Sequence[Path],
        *,
        policy: str = "restore",
        grant_workspace_scope: bool | None = None,
        restore_policy: Mapping[str, object] | None = None,
    ) -> None:
        session = self.sessions.get(session_id)
        session_mode = str(session.get("mode") or "coordinator")
        allowed_tools = (
            list(session.get("allowedTools") or [])
            if session.get("toolAllowlistMode") == "explicit"
            else None
        )
        current_execution_mode = str(
            session.get("executionMode") or "workspace_managed"
        )
        current_profile = str(
            session.get("toolProfileVersion") or "control-center-v1"
        )
        if restore_policy is not None:
            session_mode = str(restore_policy.get("mode") or "").strip()
            current_profile = str(
                restore_policy.get("toolProfileVersion") or ""
            ).strip()
            current_execution_mode = str(
                restore_policy.get("executionMode") or ""
            ).strip()
            if session_mode not in {"assistant", "coordinator"}:
                raise RoomWorkspaceError("workspace restore policy has invalid mode")
            if not current_profile or not current_execution_mode:
                raise RoomWorkspaceError(
                    "workspace restore policy is missing the prior runtime policy"
                )
            if restore_policy.get("toolAllowlistMode") == "explicit":
                allowed_tools = [
                    str(value)
                    for value in restore_policy.get("allowedTools") or []
                    if str(value).strip()
                ]
            else:
                allowed_tools = None
            granted = bool(restore_policy.get("workspaceScopeGranted"))
        elif policy == "read_only":
            current_execution_mode = "read_only"
            current_profile = "subagent-readonly-v1"
            granted = (
                bool(session.get("workspaceScopeGranted"))
                if grant_workspace_scope is None
                else bool(grant_workspace_scope)
            )
        elif (
            policy == "isolated_writable"
            and current_execution_mode == "read_only"
        ):
            # A prior delivery may have revoked this Session to the bounded
            # read-only profile.  ``prepare`` is the sole coordinator-owned
            # operation allowed to grant a fresh isolated write lease.
            current_execution_mode = "workspace_managed"
            current_profile = "control-center-v1"
            granted = True
        elif (
            current_execution_mode == "read_only"
            and policy != "isolated_writable"
        ):
            raise RoomWorkspaceError(
                "workspace restore policy is missing for a read_only Session"
            )
        else:
            granted = (
                bool(session.get("workspaceScopeGranted"))
                if grant_workspace_scope is None
                else bool(grant_workspace_scope)
            )
        self.sessions.set_runtime_policy(
            session_id,
            mode=session_mode,
            tool_profile_version=current_profile,
            execution_mode=current_execution_mode,
            grant_workspace_scope=granted,
            allowed_tools=allowed_tools,
            project_context_enabled=(
                bool(restore_policy.get("projectContextEnabled"))
                if restore_policy is not None
                else bool(session.get("projectContextEnabled"))
            ),
            pi_skills_enabled=(
                bool(restore_policy.get("piSkillsEnabled"))
                if restore_policy is not None
                else bool(session.get("piSkillsEnabled"))
            ),
            codex_skills_enabled=(
                bool(restore_policy.get("codexSkillsEnabled"))
                if restore_policy is not None
                else bool(session.get("codexSkillsEnabled"))
            ),
            workspace_roots=[str(root) for root in roots],
        )

    @staticmethod
    def _bounded_error(value: bytes) -> str:
        return value.decode("utf-8", errors="replace").strip()[:1000]

    def _git_text(self, root: Path, *args: str) -> str:
        return self._git_bytes(root, *args).decode("utf-8", errors="strict").strip()

    def _git_bytes(self, root: Path, *args: str) -> bytes:
        return self._run(["git", "-C", str(root), *args]).stdout

    def _repository_identity(self, root: Path) -> str:
        common_raw = self._git_text(root, "rev-parse", "--git-common-dir")
        common = Path(common_raw)
        if not common.is_absolute():
            common = (root / common).resolve(strict=True)
        else:
            common = common.resolve(strict=True)
        origin_result = self._run(
            ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
            check=False,
        )
        origin = origin_result.stdout.decode("utf-8", errors="replace").strip()
        return hashlib.sha256(
            f"git\0{common}\0{origin}".encode("utf-8")
        ).hexdigest()

    def _remove_worktree(
        self,
        base: Path,
        workspace: Path,
    ) -> subprocess.CompletedProcess[bytes]:
        guard = self._removal_guards.get(str(workspace.resolve(strict=False)))
        if guard is None:
            return subprocess.CompletedProcess(
                args=[str(base), str(workspace)],
                returncode=1,
                stdout=b"",
                stderr=b"physical cleanup lacks exact removal authorization",
            )
        return self._run(
            [
                sys.executable,
                "-I",
                str(_GUARDED_CLEANUP_SCRIPT),
                str(self.ledger.db_path),
                str(guard.get("workspaceBindingId") or ""),
                str(base),
                str(workspace),
                str(guard.get("vaultWorkspaceRoot") or ""),
                str(guard.get("workspaceContentSha256") or ""),
                str(guard.get("targetSnapshotSha256") or ""),
                str(guard.get("observedCleanupTargetSnapshotSha256") or ""),
                str(guard.get("removalAuthorizationReceiptId") or ""),
                str(guard.get("removalAuthorizationReceiptSha256") or ""),
            ],
            check=False,
        )

    def _move_worktree(
        self,
        base: Path,
        source: Path,
        quarantine: Path,
    ) -> subprocess.CompletedProcess[bytes]:
        return self._run(
            [
                _SYSTEM_GIT,
                "-C",
                str(base),
                "worktree",
                "move",
                str(source),
                str(quarantine),
            ],
            check=False,
        )

    @staticmethod
    def _run(
        command: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                list(command),
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RoomWorkspaceError(f"workspace command failed: {exc}") from exc
        if check and result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()[:1000]
            raise RoomWorkspaceError(message or "workspace command failed")
        return result
