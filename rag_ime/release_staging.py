from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import plistlib
import stat
import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping


SCHEMA_VERSION = "rag-ime.release-candidate-staging.v1"
SOURCE_EXCLUDED_PARTS = {".git", "__pycache__", "build", "download", "Frameworks", "lib", "node_modules"}
PROJECT_EXCLUDED_PREFIXES = (
    "docs/agent/",
    "docs/archive/",
    ".github/",
    "macos/RagImeMac/",
    "scripts/build_macos_frontend.sh",
    "scripts/doctor_macos_frontend.sh",
    "scripts/install_macos_frontend.sh",
    "scripts/install_system_macos_frontend.sh",
    "scripts/refresh_macos_input_sources.sh",
    "scripts/reset_macos_ragime_registration.sh",
)


def prepare_release_candidate(
    root: str | Path,
    *,
    release_id: str,
    output_root: str | Path,
    squirrel_source: str | Path,
    apps: Mapping[str, str | Path],
    project_files: Iterable[str] | None = None,
) -> dict[str, object]:
    """Create deterministic unsigned staging archives without release claims."""

    repo_root = Path(root).resolve()
    output = Path(output_root).resolve()
    if not release_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in release_id):
        raise ValueError("release_id must contain only letters, digits, dot, underscore, or hyphen")
    source_root = Path(squirrel_source).resolve()
    if not source_root.is_dir() or not (source_root / "LICENSE.txt").is_file():
        raise ValueError("squirrel_source must be a prepared Squirrel checkout with LICENSE.txt")
    upstream_commit = _git_value(source_root, "rev-parse", "HEAD")
    if len(upstream_commit) != 40:
        raise ValueError("squirrel_source must have a readable Git HEAD")

    normalized_apps = _validate_apps(apps)
    files = sorted(set(project_files if project_files is not None else _candidate_files(repo_root)))
    source_files = [
        relative
        for relative in files
        if not relative.startswith(PROJECT_EXCLUDED_PREFIXES)
        and (repo_root / relative).is_file()
    ]
    if not source_files:
        raise ValueError("project source file set is empty")

    stage = output / release_id
    stage.mkdir(parents=True, exist_ok=True)
    source_archive = stage / f"RAG-IME-{release_id}-corresponding-source.tar.gz"
    app_archive = stage / f"RAG-IME-{release_id}-macos-unsigned.tar.gz"
    manifest_path = stage / "staging-manifest.json"

    project_snapshot = _snapshot_files(repo_root, source_files)
    squirrel_snapshot = _tree_snapshot(source_root, excluded_parts=SOURCE_EXCLUDED_PARTS)
    source_metadata = {
        "schemaVersion": SCHEMA_VERSION,
        "releaseId": release_id,
        "projectCommit": _git_value(repo_root, "rev-parse", "HEAD"),
        "projectDirty": bool(_git_value(repo_root, "status", "--porcelain")),
        "projectSnapshotSha256": _snapshot_digest(project_snapshot),
        "projectFileCount": len(project_snapshot),
        "squirrelUpstreamCommit": upstream_commit,
        "squirrelDirty": bool(_git_value(source_root, "status", "--porcelain")),
        "squirrelTreeSha256": _snapshot_digest(squirrel_snapshot),
        "excludedSquirrelParts": sorted(SOURCE_EXCLUDED_PARTS),
    }
    with _deterministic_tar_gz(source_archive) as archive:
        for relative in source_files:
            _add_path(archive, repo_root / relative, PurePosixPath("rag-ime-project") / relative)
        _add_tree(archive, source_root, PurePosixPath("patched-squirrel-source"))
        _add_bytes(
            archive,
            "SOURCE-SNAPSHOT.json",
            json.dumps(source_metadata, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        )
    if _snapshot_files(repo_root, source_files) != project_snapshot:
        source_archive.unlink(missing_ok=True)
        raise RuntimeError("project source changed during release staging")
    if _tree_snapshot(source_root, excluded_parts=SOURCE_EXCLUDED_PARTS) != squirrel_snapshot:
        source_archive.unlink(missing_ok=True)
        raise RuntimeError("Squirrel source changed during release staging")

    app_records: list[dict[str, object]] = []
    app_snapshots = {label: _tree_snapshot(path) for label, path in normalized_apps.items()}
    with _deterministic_tar_gz(app_archive) as archive:
        _add_bytes(
            archive,
            "INSTALL-NOT-READY.txt",
            (
                "This is an unsigned engineering staging archive.\n"
                "Do not distribute or install it as a public release.\n"
                "Developer ID signing, notarization, stapling, foreground acceptance, and the final release manifest are pending.\n"
            ).encode("utf-8"),
        )
        for label, app_path in normalized_apps.items():
            _add_path(archive, app_path, PurePosixPath("apps") / app_path.name)
            app_records.append(
                {
                    "label": label,
                    "bundle": app_path.name,
                    "bundleIdentifier": _bundle_identifier(app_path),
                    "treeSha256": _snapshot_digest(app_snapshots[label]),
                }
            )
    for label, app_path in normalized_apps.items():
        if _tree_snapshot(app_path) != app_snapshots[label]:
            app_archive.unlink(missing_ok=True)
            raise RuntimeError(f"app bundle changed during release staging: {label}")

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "releaseId": release_id,
        "status": "unsigned_staging_only",
        "releaseEligible": False,
        "trainingOrRuntimeStateModified": False,
        "source": source_metadata,
        "artifacts": [
            _artifact_record(source_archive, kind="corresponding_source_staging"),
            _artifact_record(app_archive, kind="macos_unsigned_staging"),
        ],
        "apps": app_records,
        "pendingGates": [
            "top_level_project_license",
            "clean_source_commit",
            "foreground_acceptance",
            "developer_id_codesign",
            "notarization",
            "stapling",
            "gatekeeper_clean_machine",
            "final_release_manifest",
        ],
        "notes": [
            "This is not rag-ime.release-manifest.v1 and cannot satisfy the public release gate.",
            "Archives use normalized ordering, ownership, permissions, and timestamps for reproducibility.",
            "Squirrel build/download products are excluded; full edited source and initialized source subtrees are included.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "manifest": str(manifest_path), **manifest}


def _candidate_files(root: Path) -> list[str]:
    tracked = _git_lines(root, "ls-files")
    untracked = _git_lines(root, "ls-files", "--others", "--exclude-standard")
    return sorted(set(tracked + untracked))


def _validate_apps(apps: Mapping[str, str | Path]) -> dict[str, Path]:
    if not apps:
        raise ValueError("at least one app bundle is required")
    result: dict[str, Path] = {}
    seen_names: set[str] = set()
    for label, raw_path in sorted(apps.items()):
        path = Path(raw_path).resolve()
        if not label or not path.is_dir() or path.suffix != ".app" or not (path / "Contents" / "Info.plist").is_file():
            raise ValueError(f"invalid app bundle for {label!r}: {raw_path}")
        if path.name in seen_names:
            raise ValueError(f"duplicate app bundle name: {path.name}")
        seen_names.add(path.name)
        result[label] = path
    return result


def _deterministic_tar_gz(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.open("wb")
    compressed = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
    archive = tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT)

    class _Context:
        def __enter__(self):
            return archive

        def __exit__(self, exc_type, exc, traceback):
            archive.close()
            compressed.close()
            raw.close()

    return _Context()


def _add_tree(archive: tarfile.TarFile, root: Path, destination: PurePosixPath) -> None:
    _add_path(archive, root, destination, excluded_parts=SOURCE_EXCLUDED_PARTS)


def _add_path(
    archive: tarfile.TarFile,
    source: Path,
    destination: PurePosixPath,
    *,
    excluded_parts: set[str] | None = None,
) -> None:
    excluded = excluded_parts or set()
    if source.name in excluded:
        return
    info = source.lstat()
    if stat.S_ISDIR(info.st_mode):
        _add_directory(archive, str(destination))
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _add_path(archive, child, destination / child.name, excluded_parts=excluded)
        return
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(source)
        _validate_symlink_target(target)
        tar_info = _tar_info(str(destination), mode=0o777, size=0)
        tar_info.type = tarfile.SYMTYPE
        tar_info.linkname = target
        archive.addfile(tar_info)
        return
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"unsupported staging file type: {source}")
    mode = 0o755 if info.st_mode & stat.S_IXUSR else 0o644
    tar_info = _tar_info(str(destination), mode=mode, size=info.st_size)
    with source.open("rb") as handle:
        archive.addfile(tar_info, handle)


def _add_directory(archive: tarfile.TarFile, name: str) -> None:
    info = _tar_info(name.rstrip("/") + "/", mode=0o755, size=0)
    info.type = tarfile.DIRTYPE
    archive.addfile(info)


def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    archive.addfile(_tar_info(name, mode=0o644, size=len(payload)), io.BytesIO(payload))


def _tar_info(name: str, *, mode: int, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.mode = mode
    info.size = size
    return info


def _validate_symlink_target(target: str) -> None:
    path = PurePosixPath(target)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe symlink target in release staging: {target}")


def _bundle_identifier(app: Path) -> str:
    with (app / "Contents" / "Info.plist").open("rb") as handle:
        payload = plistlib.load(handle)
    return str(payload.get("CFBundleIdentifier") or "")


def _snapshot_files(root: Path, files: Iterable[str]) -> list[dict[str, object]]:
    return [
        {"path": relative, "sha256": _sha256_file(root / relative), "sizeBytes": (root / relative).stat().st_size}
        for relative in files
    ]


def _snapshot_digest(records: list[dict[str, object]]) -> str:
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _tree_snapshot(root: Path, *, excluded_parts: set[str] | None = None) -> list[dict[str, object]]:
    excluded = excluded_parts or set()
    records = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if set(relative.parts) & excluded:
            continue
        if path.is_file() and not path.is_symlink():
            records.append({"path": relative.as_posix(), "sha256": _sha256_file(path)})
        elif path.is_symlink():
            records.append({"path": relative.as_posix(), "symlink": os.readlink(path)})
    return records


def _artifact_record(path: Path, *, kind: str) -> dict[str, object]:
    return {"kind": kind, "path": str(path), "sha256": _sha256_file(path), "sizeBytes": path.stat().st_size}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_lines(root: Path, *args: str) -> list[str]:
    completed = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return [line for line in completed.stdout.splitlines() if line]


def _git_value(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, check=False, capture_output=True, text=True)
    return completed.stdout.strip() if completed.returncode == 0 else ""
