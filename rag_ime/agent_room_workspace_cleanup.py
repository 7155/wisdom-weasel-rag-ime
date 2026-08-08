from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .agent_room_workspace_ledger import (
    RoomWorkspaceLedgerError,
    RoomWorkspaceLedgerStore,
)
from .agent_room_workspaces import RoomWorkspaceCoordinator, RoomWorkspaceError


_SYSTEM_GIT = Path("/usr/bin/git")
_ARCHIVED_GIT_ADMIN_NAME = ".room-git-admin"


def _trusted_git() -> Path:
    try:
        metadata = _SYSTEM_GIT.stat()
    except OSError as exc:
        raise RoomWorkspaceError("trusted system Git is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not os.access(_SYSTEM_GIT, os.X_OK)
    ):
        raise RoomWorkspaceError("trusted system Git has unsafe ownership or mode")
    return _SYSTEM_GIT


def _trusted_coordinator(git: Path) -> RoomWorkspaceCoordinator:
    coordinator = object.__new__(RoomWorkspaceCoordinator)

    def run_trusted(
        command: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        normalized = list(command)
        if not normalized or normalized[0] != "git":
            raise RoomWorkspaceError("guarded cleanup refused a non-Git child command")
        normalized[0] = str(git)
        return RoomWorkspaceCoordinator._run(
            normalized,
            input_bytes=input_bytes,
            check=check,
        )

    coordinator._run = run_trusted  # type: ignore[method-assign]
    return coordinator


def _common_git_dir(coordinator: RoomWorkspaceCoordinator, base: Path) -> Path:
    common_raw = coordinator._git_text(base, "rev-parse", "--git-common-dir")
    common = Path(common_raw)
    if not common.is_absolute():
        common = base / common
    return common.resolve(strict=True)


def _worktree_admin_root(
    *,
    common_git_dir: Path,
    workspace: Path,
    vault: Path,
) -> tuple[Path, Path]:
    archived = vault / _ARCHIVED_GIT_ADMIN_NAME
    if archived.exists():
        if archived.is_symlink() or not archived.is_dir():
            raise RoomWorkspaceError("vaulted Git admin evidence is not a directory")
        return archived, archived
    git_pointer = (workspace if workspace.is_dir() else vault) / ".git"
    if git_pointer.is_symlink() or not git_pointer.is_file():
        raise RoomWorkspaceError("guarded cleanup cannot resolve exact worktree admin metadata")
    pointer = git_pointer.read_text(encoding="utf-8").strip()
    prefix = "gitdir: "
    if not pointer.startswith(prefix):
        raise RoomWorkspaceError("worktree Git pointer is malformed")
    raw_admin = Path(pointer[len(prefix) :])
    if not raw_admin.is_absolute():
        raw_admin = git_pointer.parent / raw_admin
    admin = raw_admin.resolve(strict=True)
    worktrees_root = (common_git_dir / "worktrees").resolve(strict=True)
    if admin.parent != worktrees_root or admin.is_symlink() or not admin.is_dir():
        raise RoomWorkspaceError("worktree Git admin metadata escaped the exact repository")
    reciprocal = admin / "gitdir"
    if reciprocal.is_symlink() or not reciprocal.is_file():
        raise RoomWorkspaceError("worktree Git admin metadata lacks its reciprocal pointer")
    reciprocal_raw = Path(reciprocal.read_text(encoding="utf-8").strip())
    if not reciprocal_raw.is_absolute():
        reciprocal_raw = reciprocal.parent / reciprocal_raw
    if reciprocal_raw.resolve(strict=False) != (workspace / ".git").resolve(
        strict=False
    ):
        raise RoomWorkspaceError("worktree Git admin metadata belongs to another path")
    return admin, archived


def _registered_worktree_paths(
    coordinator: RoomWorkspaceCoordinator,
    base: Path,
) -> set[Path]:
    output = coordinator._git_bytes(base, "worktree", "list", "--porcelain")
    paths: set[Path] = set()
    for line in output.splitlines():
        if not line.startswith(b"worktree "):
            continue
        paths.add(Path(os.fsdecode(line[len(b"worktree ") :])).resolve(strict=False))
    return paths


def _guarded_remove(arguments: list[str]) -> int:
    if len(arguments) != 9:
        raise RoomWorkspaceError("guarded cleanup received an invalid argument set")
    (
        db_path,
        binding_id,
        base_raw,
        workspace_raw,
        vault_raw,
        expected_source,
        expected_target,
        receipt_id,
        receipt_sha256,
    ) = arguments
    base = Path(base_raw).expanduser().resolve(strict=True)
    workspace = Path(os.path.abspath(os.path.expanduser(workspace_raw)))
    vault = Path(os.path.abspath(os.path.expanduser(vault_raw)))
    if workspace.parent.name != ".quarantine" or vault != (
        workspace.parent.parent / ".vault" / workspace.name
    ):
        raise RoomWorkspaceError("guarded cleanup vault identity is invalid")
    if workspace.exists() and vault.exists():
        raise RoomWorkspaceError("guarded cleanup found both quarantine and vault paths")
    if not workspace.is_dir() and not vault.is_dir():
        raise RoomWorkspaceError("guarded cleanup source and vault paths are missing")
    ledger = RoomWorkspaceLedgerStore(db_path)
    binding = ledger.binding(binding_id)
    if base != Path(str(binding["workspaceBaseRoot"])).resolve(strict=True):
        raise RoomWorkspaceError("guarded cleanup base identity changed")
    git = _trusted_git()
    coordinator = _trusted_coordinator(git)
    if coordinator._repository_identity(base) != str(binding["repositoryId"]):
        raise RoomWorkspaceError("guarded cleanup repository identity changed")
    if coordinator.snapshot_digest([base]) != expected_target:
        raise RoomWorkspaceError("integration target changed before physical cleanup")
    ledger.assert_cleanup_removal_authority(
        binding_id,
        receipt_id=receipt_id,
        receipt_sha256=receipt_sha256,
        quarantined_workspace_root=str(workspace),
        vault_workspace_root=str(vault),
        workspace_content_sha256=expected_source,
        target_snapshot_sha256=expected_target,
    )
    common_git_dir = _common_git_dir(coordinator, base)
    admin, archived_admin = _worktree_admin_root(
        common_git_dir=common_git_dir,
        workspace=workspace,
        vault=vault,
    )
    if workspace.is_dir():
        handle_evidence = RoomWorkspaceCoordinator._inspect_open_handles(workspace)
        if (
            handle_evidence.get("known") is not True
            or handle_evidence.get("activeCount") != 0
        ):
            raise RoomWorkspaceError(
                "quarantined child has unknown or active handles before atomic vaulting"
            )
        if coordinator._workspace_content_digest(workspace) != expected_source:
            raise RoomWorkspaceError("quarantined source changed before atomic vaulting")
        vault.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        vault_parent = vault.parent.resolve(strict=True)
        if vault_parent != vault.parent or vault.parent.is_symlink():
            raise RoomWorkspaceError("guarded cleanup vault parent is not exact")
        if vault.exists():
            raise RoomWorkspaceError("guarded cleanup vault destination already exists")
        os.rename(workspace, vault)
    if not vault.is_dir() or workspace.exists():
        raise RoomWorkspaceError("atomic vault rename did not remove the active path")
    if admin != archived_admin:
        if archived_admin.exists():
            raise RoomWorkspaceError("vaulted Git admin destination already exists")
        os.rename(admin, archived_admin)
    if admin != archived_admin and admin.exists():
        raise RoomWorkspaceError("exact Git admin metadata remained active")
    handle_evidence = RoomWorkspaceCoordinator._inspect_open_handles(vault)
    if (
        handle_evidence.get("known") is not True
        or handle_evidence.get("activeCount") != 0
    ):
        raise RoomWorkspaceError(
            "vaulted child has unknown or active handles; evidence was retained"
        )
    vault_content = RoomWorkspaceCoordinator._vault_content_digest(vault)
    ledger.record_vaulted(
        binding_id,
        removal_authorization_receipt_id=receipt_id,
        removal_authorization_receipt_sha256=receipt_sha256,
        quarantined_workspace_root=str(workspace),
        vault_workspace_root=str(vault),
        authorized_workspace_content_sha256=expected_source,
        vault_content_sha256=vault_content,
        target_snapshot_sha256=expected_target,
        actor_ref="system:guarded-workspace-cleanup",
        now_ms=int(time.time() * 1000),
    )
    registered = _registered_worktree_paths(coordinator, base)
    if workspace.resolve(strict=False) in registered or vault.resolve(strict=False) in registered:
        raise RoomWorkspaceError("vaulted child remained registered as an active worktree")
    sys.stdout.write(
        json.dumps(
            {
                "vaultWorkspaceRoot": str(vault),
                "vaultContentSha256": vault_content,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def main() -> int:
    try:
        return _guarded_remove(sys.argv[1:])
    except (OSError, UnicodeError, RoomWorkspaceError, RoomWorkspaceLedgerError) as exc:
        sys.stderr.write(f"guarded workspace cleanup refused: {exc}\n")
        return 73


if __name__ == "__main__":
    raise SystemExit(main())
