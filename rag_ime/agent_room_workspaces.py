from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
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


class RoomWorkspaceCoordinator:
    """Own linked worktrees and Session root rebinding for Room child work."""

    def __init__(
        self,
        *,
        root_dir: str | Path,
        sessions: AgentSessionStore,
        ledger: RoomWorkspaceLedgerStore | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve(strict=False)
        self.sessions = sessions
        self.ledger = ledger or RoomWorkspaceLedgerStore(sessions.db_path)
        self.ledger.initialize()
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
            if (
                lifecycle_state in {
                    "materialized",
                    "work_started",
                    "delivered",
                    "retry_bound",
                }
                and workspace_root.is_dir()
            ):
                self._set_session_roots(
                    target_session_id,
                    [workspace_root],
                    policy=policy,
                    grant_workspace_scope=True,
                )
                return self._prepared_payload(binding, restore_policy)
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
        return self._prepared_payload(binding, restore_policy)

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
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            raise RoomWorkspaceError(str(exc)) from exc
        source_session = self.sessions.get(source_session_id)
        target_session = self.sessions.get(target_session_id)
        source_restore_policy = task.get("workspaceRestorePolicy")
        target_restore_policy = self._restore_policy(target_session)
        source_roots = [
            str(value)
            for value in source_session.get("workspaceRoots") or []
            if str(value).strip()
        ]
        target_roots = [
            str(value)
            for value in target_session.get("workspaceRoots") or []
            if str(value).strip()
        ]
        if str(source) not in source_roots:
            if str(source) in target_roots:
                return {
                    "workspaceRoot": str(source),
                    "workspaceBaseRoot": str(base),
                    "workspaceBaseCommit": expected_commit,
                    "sourceSessionId": source_session_id,
                    "targetSessionId": target_session_id,
                    "idempotent": True,
                }
            raise RoomWorkspaceError(
                "ownership transfer source Session does not own the Task workspace"
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
        now_ms: int | None = None,
    ) -> dict[str, object]:
        source, _base, expected_commit = self._isolated_task_roots(task)
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
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            raise RoomWorkspaceError(str(exc)) from exc
        return {
            "workspaceBindingId": binding_id,
            "deliveryRevision": delivery_revision,
            "deliveryHead": expected_commit,
            "deliverySnapshotSha256": snapshot,
            "workspaceLifecycleState": binding["workspaceLifecycleState"],
            "workspaceDelivery": workspace_delivery,
        }

    def integrate(
        self,
        task: Mapping[str, object],
        *,
        integration_ref: str = "",
        actor_ref: str = "",
        now_ms: int | None = None,
    ) -> dict[str, object]:
        # Keep all coordinator-owned delivery capture, lease binding, target
        # mutation, receipt, and cleanup in one process-local critical section.
        # External writers are still fenced by repeated content evidence below.
        with self._lock:
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
        if str(binding.get("workspaceLifecycleState") or "") in {
            "integrated",
            "cleaned",
        }:
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
        try:
            delivered = self._capture_delivered_workspace(
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
        patch = bytes(delivered["patch"])
        patch_sha256 = str(delivered["patchSha256"])
        changed_files = [
            value
            for value in self._git_text(
                source,
                "diff",
                "--name-only",
                "HEAD",
                "--",
            ).splitlines()
            if value.strip()
        ]
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

        recovered_after_apply = False
        prior_start = self.ledger.integration_start_payload(binding_id) or {}
        recorded_target_before = str(
            prior_start.get("targetBeforeSnapshotSha256") or ""
        )
        if target_before != recorded_target_before:
            reverse_check = (
                self._run(
                    [
                        "git",
                        "-C",
                        str(base),
                        "apply",
                        "--reverse",
                        "--check",
                        "--whitespace=nowarn",
                        "-",
                    ],
                    input_bytes=patch,
                    check=False,
                )
                if patch
                else None
            )
            if patch and reverse_check is not None and reverse_check.returncode == 0:
                recovered_after_apply = True
            else:
                reason = (
                    "integration target changed after its receipted start; "
                    "the child workspace was retained"
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
        integrated_snapshot = self.snapshot_digest([base])
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
                actor_ref=actor_ref or "system:room-facilitator",
                now_ms=timestamp,
            )
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
            # The physical child remains intact. A retry can prove an already
            # applied patch from the integration-start receipt.
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
        }

    def discard(self, prepared: Mapping[str, object]) -> None:
        """Retain an allocated child when enqueue fails; never erase evidence."""

        if prepared.get("workspacePolicy") != "isolated_writable":
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
        session_id: str,
        reason: str,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        binding = self.ledger.binding(binding_id)
        source = self._receipted_workspace_path(binding, require_exists=True)
        snapshot = self.snapshot_digest([source])
        if (
            binding.get("workspaceLifecycleState") == "retry_bound"
            and binding.get("attentionRequired") is False
        ):
            retry_event = next(
                (
                    event
                    for event in reversed(self.ledger.events(binding_id))
                    if event.get("eventKind") == "retry_bound"
                ),
                None,
            )
            payload = (
                retry_event.get("payload")
                if isinstance(retry_event, Mapping)
                else None
            )
            if (
                isinstance(payload, Mapping)
                and payload.get("participantId") == participant_id
                and payload.get("sessionId") == session_id
                and payload.get("workspaceSnapshotSha256") == snapshot
                and payload.get("reason") == reason[:2_000]
            ):
                self._set_session_roots(
                    session_id,
                    [source],
                    policy="isolated_writable",
                    grant_workspace_scope=True,
                )
                return binding
            raise RoomWorkspaceError(
                "workspace retry binding was replayed with different evidence"
            )
        try:
            rebound = self.ledger.retry_binding(
                binding_id,
                participant_id=participant_id,
                session_id=session_id,
                workspace_snapshot_sha256=snapshot,
                reason=reason,
                actor_ref=participant_id or session_id,
                now_ms=timestamp,
            )
            self._set_session_roots(
                session_id,
                [source],
                policy="isolated_writable",
                grant_workspace_scope=True,
            )
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
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
            cleanup_state = str(binding.get("cleanupState") or "")
            cleanup_completed = cleanup_state in {"cleaned", "missing"}
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
                "abandonmentSnapshotSha256": prior_payload.get(
                    "workspaceSnapshotSha256"
                ),
                "abandonmentReceiptId": prior_event.get("eventId"),
                "abandonmentReceiptSha256": prior_event.get(
                    "payloadSha256"
                ),
            }
        source = self._receipted_workspace_path(binding, require_exists=False)
        snapshot = self.snapshot_digest([source]) if source.is_dir() else (
            str(binding.get("deliverySnapshotSha256") or "")
            or hashlib.sha256(str(source).encode("utf-8")).hexdigest()
        )
        try:
            abandoned = self.ledger.abandon(
                binding_id,
                reason=reason,
                workspace_snapshot_sha256=snapshot,
                acceptance_aliases=normalized_aliases,
                actor_ref=actor_ref,
                now_ms=timestamp,
            )
        except (RoomWorkspaceLedgerError, RoomWorkspaceLedgerConflict) as exc:
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
        claimed_paths: set[Path] = set()
        for binding in self.ledger.recovery_candidates():
            source = self._receipted_workspace_path(binding, require_exists=False)
            claimed_paths.add(source)
            state = str(binding.get("workspaceLifecycleState") or "")
            path_exists = source.is_dir()
            if state == "reserved" or (
                not path_exists
                and state not in {
                    "integrated",
                    "abandoned",
                    "cleanup_failed",
                    "cleaned",
                }
            ):
                discovered.append(
                    self._retain_binding(
                        binding,
                        state="orphaned",
                        reason=(
                            "workspace materialization was interrupted"
                            if state == "reserved"
                            else "receipted workspace path is missing before terminal cleanup"
                        ),
                        actor_ref="system:workspace-recovery",
                        now_ms=timestamp,
                    )
                )
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

    def _cleanup_receipted_worktree(
        self,
        binding: Mapping[str, object],
        *,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object]:
        binding_id = str(binding.get("workspaceBindingId") or "")
        source = self._receipted_workspace_path(binding, require_exists=False)
        base = Path(str(binding.get("workspaceBaseRoot") or "")).resolve(
            strict=False
        )
        if not source.exists():
            return self.ledger.record_cleanup(
                binding_id,
                result="missing",
                reason="receipted child path was already absent",
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        if not base.is_dir():
            return self.ledger.record_cleanup(
                binding_id,
                result="failed",
                reason="integration base path is unavailable; child was retained",
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        removed = self._remove_worktree(base, source)
        if removed.returncode != 0 or source.exists():
            return self.ledger.record_cleanup(
                binding_id,
                result="failed",
                reason=(
                    self._bounded_error(removed.stderr)
                    or "git worktree remove did not remove the exact receipted path"
                ),
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
        try:
            source.parent.rmdir()
        except OSError:
            pass
        return self.ledger.record_cleanup(
            binding_id,
            result="cleaned",
            reason="exact receipted child worktree removed after integration receipt",
            actor_ref=actor_ref,
            now_ms=now_ms,
        )

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
    ) -> dict[str, object]:
        return {
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
        }

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
        elif current_execution_mode == "read_only":
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
        return self._run(
            ["git", "-C", str(base), "worktree", "remove", "--force", str(workspace)],
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
