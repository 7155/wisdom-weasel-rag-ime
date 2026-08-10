from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

if __package__:
    from .agent_room_workspace_ledger import (
        RoomWorkspaceLedgerError,
        RoomWorkspaceLedgerStore,
    )
    from .agent_room_workspaces import RoomWorkspaceCoordinator, RoomWorkspaceError
else:
    # The installed gateway is started by a wrapper that adds the app code to
    # its own sys.path; its Python environment does not install ``rag_ime``.
    # Guarded cleanup runs under ``-I``, so bind imports to this exact helper's
    # verified source tree instead of inheriting either launcher's import path.
    sys.path.insert(0, str(Path(__file__).resolve(strict=True).parents[1]))
    from rag_ime.agent_room_workspace_ledger import (
        RoomWorkspaceLedgerError,
        RoomWorkspaceLedgerStore,
    )
    from rag_ime.agent_room_workspaces import (
        RoomWorkspaceCoordinator,
        RoomWorkspaceError,
    )


_SYSTEM_GIT = Path("/usr/bin/git")
_ARCHIVED_GIT_ADMIN_NAME = ".room-git-admin"
_ARCHIVED_GIT_ADMIN_PARTIAL_PREFIX = f"{_ARCHIVED_GIT_ADMIN_NAME}.partial-"


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
    worktrees_root = (common_git_dir / "worktrees").resolve(strict=True)
    if raw_admin.parent.resolve(strict=True) != worktrees_root:
        raise RoomWorkspaceError("worktree Git admin metadata escaped the exact repository")
    admin = worktrees_root / raw_admin.name
    if os.path.lexists(admin):
        if admin.is_symlink() or not admin.is_dir():
            raise RoomWorkspaceError("worktree Git admin metadata is not an exact directory")
        reciprocal = admin / "gitdir"
        if reciprocal.is_file() and not reciprocal.is_symlink():
            reciprocal_raw = Path(reciprocal.read_text(encoding="utf-8").strip())
            if not reciprocal_raw.is_absolute():
                reciprocal_raw = reciprocal.parent / reciprocal_raw
            if reciprocal_raw.resolve(strict=False) != (workspace / ".git").resolve(
                strict=False
            ):
                raise RoomWorkspaceError(
                    "worktree Git admin metadata belongs to another path"
                )
        elif not archived.is_dir():
            raise RoomWorkspaceError(
                "worktree Git admin metadata lacks its reciprocal pointer"
            )
        return admin, archived
    if archived.is_symlink() or not archived.is_dir():
        raise RoomWorkspaceError("guarded cleanup cannot find vaulted Git admin evidence")
    admin = archived
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


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_git_admin_tree(root: Path) -> None:
    normalized = root.resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise RoomWorkspaceError("Git admin evidence is not an exact directory")

    def visit(directory: Path) -> None:
        for entry in sorted(directory.iterdir(), key=lambda item: os.fsencode(item.name)):
            metadata = entry.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                target = Path(os.readlink(entry))
                if target.is_absolute():
                    raise RoomWorkspaceError("Git admin evidence contains an escaping symlink")
                try:
                    resolved_target = (entry.parent / target).resolve(strict=False)
                    resolved_target.relative_to(normalized)
                except (OSError, RuntimeError, ValueError) as exc:
                    raise RoomWorkspaceError(
                        "Git admin evidence contains an escaping symlink"
                    ) from exc
                continue
            if stat.S_ISDIR(metadata.st_mode):
                visit(entry)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise RoomWorkspaceError(
                    "Git admin evidence contains an unsupported special file"
                )

    visit(normalized)


def _git_admin_digest(root: Path) -> str:
    _validate_git_admin_tree(root)
    metadata = root.lstat()
    digest = hashlib.sha256()
    digest.update(b"room-git-admin-v1\0")
    digest.update(int(metadata.st_mode).to_bytes(8, "big"))
    digest.update(
        RoomWorkspaceCoordinator._vault_content_digest(root).encode("ascii")
    )
    return digest.hexdigest()


def _directory_identity(directory: Path) -> tuple[int, int, int]:
    metadata = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise RoomWorkspaceError("Git admin source is not an exact directory")
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def _assert_git_admin_source(
    source: Path,
    *,
    expected_identity: tuple[int, int, int],
    expected_digest: str,
) -> None:
    if _directory_identity(source) != expected_identity:
        raise RoomWorkspaceError("Git admin source identity changed during archival")
    if _git_admin_digest(source) != expected_digest:
        raise RoomWorkspaceError("Git admin source changed during archival")


def _copy_git_admin_file(source: Path, destination: Path, metadata: os.stat_result) -> None:
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    destination_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
    )
    source_descriptor = os.open(source, source_flags)
    destination_descriptor = -1
    try:
        opened = os.fstat(source_descriptor)
        if (
            opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_mode != metadata.st_mode
            or not stat.S_ISREG(opened.st_mode)
        ):
            raise RoomWorkspaceError("Git admin file identity changed during copy")
        destination_descriptor = os.open(
            destination,
            destination_flags,
            stat.S_IMODE(metadata.st_mode),
        )
        while chunk := os.read(source_descriptor, 1024 * 1024):
            view = memoryview(chunk)
            while view:
                written = os.write(destination_descriptor, view)
                if written <= 0:
                    raise OSError("Git admin copy made no forward progress")
                view = view[written:]
        os.fchmod(destination_descriptor, stat.S_IMODE(metadata.st_mode))
        os.fsync(destination_descriptor)
        after = os.fstat(source_descriptor)
        if any(
            before != current
            for before, current in (
                (opened.st_dev, after.st_dev),
                (opened.st_ino, after.st_ino),
                (opened.st_mode, after.st_mode),
                (opened.st_size, after.st_size),
                (opened.st_mtime_ns, after.st_mtime_ns),
                (opened.st_ctime_ns, after.st_ctime_ns),
            )
        ):
            raise RoomWorkspaceError("Git admin source changed during copy")
    finally:
        if destination_descriptor >= 0:
            os.close(destination_descriptor)
        os.close(source_descriptor)


def _copy_git_admin_tree(source: Path, destination: Path) -> None:
    before = source.lstat()
    if source.is_symlink() or not stat.S_ISDIR(before.st_mode):
        raise RoomWorkspaceError("Git admin copy source is not an exact directory")
    destination.mkdir(mode=0o700)
    for entry in sorted(source.iterdir(), key=lambda item: os.fsencode(item.name)):
        metadata = entry.lstat()
        copied = destination / entry.name
        if stat.S_ISLNK(metadata.st_mode):
            os.symlink(os.readlink(entry), copied)
        elif stat.S_ISDIR(metadata.st_mode):
            _copy_git_admin_tree(entry, copied)
        elif stat.S_ISREG(metadata.st_mode):
            _copy_git_admin_file(entry, copied, metadata)
        else:
            raise RoomWorkspaceError(
                "Git admin evidence contains an unsupported special file"
            )
    os.chmod(destination, stat.S_IMODE(before.st_mode), follow_symlinks=False)
    _fsync_directory(destination)
    after = source.lstat()
    if any(
        original != current
        for original, current in (
            (before.st_dev, after.st_dev),
            (before.st_ino, after.st_ino),
            (before.st_mode, after.st_mode),
            (before.st_mtime_ns, after.st_mtime_ns),
            (before.st_ctime_ns, after.st_ctime_ns),
        )
    ):
        raise RoomWorkspaceError("Git admin source changed during copy")


def _git_admin_partial_path(
    vault: Path,
    *,
    binding_id: str,
    receipt_id: str,
    receipt_sha256: str,
) -> Path:
    authority = hashlib.sha256(
        "\0".join((binding_id, receipt_id, receipt_sha256)).encode("utf-8")
    ).hexdigest()[:24]
    return vault / f"{_ARCHIVED_GIT_ADMIN_PARTIAL_PREFIX}{authority}"


def _remove_exact_git_admin(
    source: Path,
    *,
    expected_identity: tuple[int, int, int],
    expected_digest: str,
) -> None:
    _assert_git_admin_source(
        source,
        expected_identity=expected_identity,
        expected_digest=expected_digest,
    )
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RoomWorkspaceError("exact Git admin removal is unavailable on this host")
    shutil.rmtree(source)
    if os.path.lexists(source):
        raise RoomWorkspaceError("exact Git admin metadata remained after removal")
    _fsync_directory(source.parent)


def _archive_git_admin(
    *,
    admin: Path,
    archived_admin: Path,
    vault: Path,
    binding_id: str,
    receipt_id: str,
    receipt_sha256: str,
) -> None:
    partial = _git_admin_partial_path(
        vault,
        binding_id=binding_id,
        receipt_id=receipt_id,
        receipt_sha256=receipt_sha256,
    )
    partials = [
        entry
        for entry in vault.iterdir()
        if entry.name.startswith(_ARCHIVED_GIT_ADMIN_PARTIAL_PREFIX)
    ]
    if any(entry != partial for entry in partials):
        raise RoomWorkspaceError("vault contains a foreign Git admin partial")
    if admin == archived_admin:
        if partials:
            raise RoomWorkspaceError("vault contains both final and partial Git admin evidence")
        _git_admin_digest(archived_admin)
        return

    source_identity = _directory_identity(admin)
    source_digest = _git_admin_digest(admin)
    if os.path.lexists(archived_admin):
        if partials:
            raise RoomWorkspaceError("vault contains both final and partial Git admin evidence")
        if _git_admin_digest(archived_admin) != source_digest:
            raise RoomWorkspaceError("vaulted Git admin evidence differs from the exact source")
        _remove_exact_git_admin(
            admin,
            expected_identity=source_identity,
            expected_digest=source_digest,
        )
        return

    if os.path.lexists(partial):
        if partial.is_symlink() or not partial.is_dir():
            raise RoomWorkspaceError("receipt-bound Git admin partial is not a directory")
        _validate_git_admin_tree(partial)
        if not shutil.rmtree.avoids_symlink_attacks:
            raise RoomWorkspaceError("safe Git admin partial recovery is unavailable")
        shutil.rmtree(partial)
        _fsync_directory(vault)

    try:
        os.rename(admin, archived_admin)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    else:
        _fsync_directory(admin.parent)
        _fsync_directory(vault)
        if os.path.lexists(admin) or not archived_admin.is_dir():
            raise RoomWorkspaceError("atomic Git admin rename did not settle exactly")
        if _git_admin_digest(archived_admin) != source_digest:
            raise RoomWorkspaceError("renamed Git admin evidence failed digest verification")
        return

    try:
        _copy_git_admin_tree(admin, partial)
    except (OSError, RoomWorkspaceError) as exc:
        raise RoomWorkspaceError(
            "cross-device Git admin copy failed; source and partial were retained"
        ) from exc
    _assert_git_admin_source(
        admin,
        expected_identity=source_identity,
        expected_digest=source_digest,
    )
    if _git_admin_digest(partial) != source_digest:
        raise RoomWorkspaceError("copied Git admin evidence failed digest verification")
    _fsync_directory(partial)
    _fsync_directory(vault)
    os.rename(partial, archived_admin)
    _fsync_directory(vault)
    if _git_admin_digest(archived_admin) != source_digest:
        raise RoomWorkspaceError("published Git admin evidence failed digest verification")
    _remove_exact_git_admin(
        admin,
        expected_identity=source_identity,
        expected_digest=source_digest,
    )


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
    if len(arguments) != 10:
        raise RoomWorkspaceError("guarded cleanup received an invalid argument set")
    (
        db_path,
        binding_id,
        base_raw,
        workspace_raw,
        vault_raw,
        expected_source,
        expected_target,
        observed_cleanup_target,
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
    if coordinator.snapshot_digest([base]) != observed_cleanup_target:
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
    _archive_git_admin(
        admin=admin,
        archived_admin=archived_admin,
        vault=vault,
        binding_id=binding_id,
        receipt_id=receipt_id,
        receipt_sha256=receipt_sha256,
    )
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
