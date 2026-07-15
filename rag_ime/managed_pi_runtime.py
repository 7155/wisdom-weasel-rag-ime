from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .agent_tool_ids import CONTROL_TOOL_IDS
from .contracts.json_schema import ContractValidationError, validate_contract


MANIFEST_SCHEMA_VERSION = "rag-ime.pi-runtime-manifest.v1"
POINTER_SCHEMA_VERSION = "rag-ime.pi-runtime-pointer.v1"
MANIFEST_NAME = "manifest.json"
POINTER_NAME = "current.json"
_MANIFEST_CONTRACT = "pi-runtime-manifest.v1.json"
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_TOOL_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_RUNTIME_FILES = 100_000


class ManagedPiRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManagedPiRuntimeInstallation:
    runtime_root: Path
    runtime_dir: Path
    runtime_version: str
    pi_version: str
    executable: Path
    node_executable: str
    extension_path: Path
    tools: tuple[str, ...]
    manifest_sha256: str


def discover_managed_pi_runtime(
    app_support: str | Path,
    *,
    expected_pi_version: str = "",
) -> ManagedPiRuntimeInstallation:
    runtime_root = _runtime_root(app_support)
    pointer_path = runtime_root / POINTER_NAME
    if not pointer_path.is_file() or pointer_path.is_symlink():
        raise ManagedPiRuntimeError("managed Pi runtime pointer is missing")
    pointer = _read_json_object(pointer_path)
    if pointer.get("schemaVersion") != POINTER_SCHEMA_VERSION:
        raise ManagedPiRuntimeError("managed Pi runtime pointer schema is unsupported")
    version = _safe_version(pointer.get("version"), label="runtime pointer version")
    manifest_sha256 = _sha256_text(pointer.get("manifestSha256"), label="runtime manifest digest")
    runtime_dir = runtime_root / version
    return _load_installation(
        runtime_root=runtime_root,
        runtime_dir=runtime_dir,
        expected_manifest_sha256=manifest_sha256,
        expected_pi_version=expected_pi_version,
        verify_all_files=True,
    )


def install_managed_pi_runtime(
    payload_dir: str | Path,
    app_support: str | Path,
    *,
    activate: bool = True,
) -> ManagedPiRuntimeInstallation:
    source = Path(payload_dir).expanduser().resolve(strict=True)
    if not source.is_dir() or source.is_symlink():
        raise ManagedPiRuntimeError("managed Pi payload must be a real directory")
    source_manifest = source / MANIFEST_NAME
    if not source_manifest.is_file() or source_manifest.is_symlink():
        raise ManagedPiRuntimeError("managed Pi payload manifest is missing")
    manifest_bytes = _read_limited_bytes(source_manifest)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = _parse_json_object(manifest_bytes, source_manifest)
    version = _safe_version(manifest.get("runtimeVersion"), label="runtime version")

    # Verify the complete payload before the application support tree changes.
    _load_installation(
        runtime_root=source.parent,
        runtime_dir=source,
        expected_manifest_sha256=manifest_sha256,
        expected_pi_version="",
        verify_all_files=True,
        expected_runtime_version=version,
    )

    runtime_root = _runtime_root(app_support)
    runtime_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if runtime_root.is_symlink():
        raise ManagedPiRuntimeError("managed Pi runtime root must not be a symlink")
    destination = runtime_root / version
    staging = runtime_root / f".{version}.staging-{uuid.uuid4().hex}"
    try:
        if destination.exists():
            installed_manifest = destination / MANIFEST_NAME
            if not installed_manifest.is_file() or _sha256_file(installed_manifest) != manifest_sha256:
                raise ManagedPiRuntimeError("managed Pi runtime version already exists with different contents")
        else:
            staging.mkdir(mode=0o700)
            for item in _manifest_file_items(manifest):
                relative = _safe_relative_path(item.get("path"))
                source_file = _resolve_payload_file(source, relative)
                target_file = staging.joinpath(*relative.parts)
                target_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(source_file, target_file)
                os.chmod(target_file, 0o755 if bool(item.get("executable")) else 0o644)
            _atomic_write_bytes(staging / MANIFEST_NAME, manifest_bytes, mode=0o644)
            _load_installation(
                runtime_root=runtime_root,
                runtime_dir=staging,
                expected_manifest_sha256=manifest_sha256,
                expected_pi_version="",
                verify_all_files=True,
                expected_runtime_version=version,
            )
            os.replace(staging, destination)
            _fsync_directory(runtime_root)
        if activate:
            pointer = {
                "schemaVersion": POINTER_SCHEMA_VERSION,
                "version": version,
                "manifestSha256": manifest_sha256,
                "activatedAtMs": int(time.time() * 1000),
            }
            _atomic_write_bytes(
                runtime_root / POINTER_NAME,
                (json.dumps(pointer, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                mode=0o600,
            )
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    if activate:
        return discover_managed_pi_runtime(app_support)
    return _load_installation(
        runtime_root=runtime_root,
        runtime_dir=destination,
        expected_manifest_sha256=manifest_sha256,
        expected_pi_version="",
        verify_all_files=True,
    )


def build_managed_pi_runtime_manifest(
    payload_dir: str | Path,
    *,
    runtime_version: str,
    pi_version: str,
    launch_kind: str,
    pi_entrypoint: str,
    extension_entrypoint: str,
    node_entrypoint: str = "",
    tools: tuple[str, ...] = CONTROL_TOOL_IDS,
    source_repository: str,
    source_commit: str,
    source_package: str,
) -> dict[str, object]:
    root = Path(payload_dir).expanduser().resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ManagedPiRuntimeError("managed Pi payload must be a real directory")
    version = _safe_version(runtime_version, label="runtime version")
    normalized_tools = _validate_tools(tools)
    if launch_kind not in {"node", "standalone"}:
        raise ManagedPiRuntimeError("managed Pi launch kind must be node or standalone")
    critical = [
        _safe_relative_path(pi_entrypoint),
        _safe_relative_path(extension_entrypoint),
    ]
    if launch_kind == "node":
        if not node_entrypoint:
            raise ManagedPiRuntimeError("node launch requires nodeEntrypoint")
        critical.append(_safe_relative_path(node_entrypoint))
    elif node_entrypoint:
        raise ManagedPiRuntimeError("standalone launch must not define nodeEntrypoint")

    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.name == MANIFEST_NAME and path.parent == root:
            continue
        if path.is_symlink():
            raise ManagedPiRuntimeError(f"managed Pi payload contains a symlink: {path.relative_to(root)}")
        if not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        files.append(
            {
                "path": relative.as_posix(),
                "sha256": _sha256_file(path),
                "byteSize": path.stat().st_size,
                "executable": bool(path.stat().st_mode & stat.S_IXUSR),
            }
        )
    file_paths = {str(item["path"]) for item in files}
    missing = [path.as_posix() for path in critical if path.as_posix() not in file_paths]
    if missing:
        raise ManagedPiRuntimeError(f"managed Pi payload is missing critical files: {', '.join(missing)}")
    manifest: dict[str, object] = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "runtimeVersion": version,
        "piVersion": str(pi_version).strip(),
        "platform": _current_platform(),
        "architecture": _current_architecture(),
        "launchKind": launch_kind,
        "piEntrypoint": critical[0].as_posix(),
        "nodeEntrypoint": _safe_relative_path(node_entrypoint).as_posix() if node_entrypoint else "",
        "extensionEntrypoint": critical[1].as_posix(),
        "tools": list(normalized_tools),
        "createdAtMs": int(time.time() * 1000),
        "source": {
            "repository": str(source_repository).strip(),
            "commit": str(source_commit).strip(),
            "package": str(source_package).strip(),
        },
        "files": files,
    }
    _validate_manifest(manifest)
    return manifest


def write_managed_pi_runtime_manifest(path: str | Path, manifest: Mapping[str, object]) -> None:
    payload = dict(manifest)
    _validate_manifest(payload)
    _atomic_write_bytes(
        Path(path),
        (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        mode=0o644,
    )


def _load_installation(
    *,
    runtime_root: Path,
    runtime_dir: Path,
    expected_manifest_sha256: str,
    expected_pi_version: str,
    verify_all_files: bool,
    expected_runtime_version: str = "",
) -> ManagedPiRuntimeInstallation:
    root_resolved = runtime_root.expanduser().resolve(strict=False)
    if runtime_dir.is_symlink():
        raise ManagedPiRuntimeError("managed Pi runtime version directory must not be a symlink")
    try:
        runtime_resolved = runtime_dir.expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise ManagedPiRuntimeError("managed Pi runtime version is missing") from exc
    if not runtime_resolved.is_dir() or not _is_within(runtime_resolved, root_resolved):
        raise ManagedPiRuntimeError("managed Pi runtime version escapes the runtime root")
    manifest_path = runtime_resolved / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ManagedPiRuntimeError("managed Pi runtime manifest is missing")
    manifest_bytes = _read_limited_bytes(manifest_path)
    actual_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise ManagedPiRuntimeError("managed Pi runtime manifest digest does not match the active pointer")
    manifest = _parse_json_object(manifest_bytes, manifest_path)
    _validate_manifest(manifest)
    runtime_version = _safe_version(manifest.get("runtimeVersion"), label="runtime version")
    directory_version = expected_runtime_version or runtime_resolved.name
    if runtime_version != directory_version:
        raise ManagedPiRuntimeError("managed Pi runtime version does not match its directory")
    pi_version = str(manifest.get("piVersion") or "").strip()
    if expected_pi_version and pi_version != expected_pi_version:
        raise ManagedPiRuntimeError(
            f"managed Pi version {pi_version or '<empty>'} does not match required {expected_pi_version}"
        )
    if _normalize_platform(manifest.get("platform")) != _current_platform():
        raise ManagedPiRuntimeError("managed Pi runtime platform does not match this machine")
    if _normalize_architecture(manifest.get("architecture")) != _current_architecture():
        raise ManagedPiRuntimeError("managed Pi runtime architecture does not match this machine")

    launch_kind = str(manifest.get("launchKind") or "")
    pi_relative = _safe_relative_path(manifest.get("piEntrypoint"))
    extension_relative = _safe_relative_path(manifest.get("extensionEntrypoint"))
    node_value = str(manifest.get("nodeEntrypoint") or "").strip()
    node_relative = _safe_relative_path(node_value) if node_value else None
    if launch_kind == "node" and node_relative is None:
        raise ManagedPiRuntimeError("managed Pi node runtime is missing nodeEntrypoint")
    if launch_kind == "standalone" and node_relative is not None:
        raise ManagedPiRuntimeError("managed Pi standalone runtime must not define nodeEntrypoint")

    items = _manifest_file_items(manifest)
    by_path: dict[str, Mapping[str, object]] = {}
    for item in items:
        relative = _safe_relative_path(item.get("path"))
        key = relative.as_posix()
        if key in by_path:
            raise ManagedPiRuntimeError(f"managed Pi manifest contains duplicate file: {key}")
        by_path[key] = item
    critical = [pi_relative, extension_relative, *([node_relative] if node_relative is not None else [])]
    for relative in critical:
        if relative.as_posix() not in by_path:
            raise ManagedPiRuntimeError(f"managed Pi manifest omits critical file: {relative.as_posix()}")

    verified_paths = set(by_path) if verify_all_files else {path.as_posix() for path in critical}
    for relative_text in sorted(verified_paths):
        _verify_manifest_file(runtime_resolved, _safe_relative_path(relative_text), by_path[relative_text])
    if verify_all_files:
        actual_paths = _runtime_file_paths(runtime_resolved)
        expected_paths = set(by_path) | {MANIFEST_NAME}
        unexpected = sorted(actual_paths - expected_paths)
        missing = sorted(expected_paths - actual_paths)
        if unexpected or missing:
            detail = unexpected[0] if unexpected else missing[0]
            kind = "unexpected" if unexpected else "missing"
            raise ManagedPiRuntimeError(f"managed Pi runtime has {kind} file: {detail}")

    executable = _resolve_runtime_file(runtime_resolved, pi_relative)
    extension = _resolve_runtime_file(runtime_resolved, extension_relative)
    node_executable = ""
    if node_relative is not None:
        node_path = _resolve_runtime_file(runtime_resolved, node_relative)
        if not _is_executable(node_path):
            raise ManagedPiRuntimeError("managed Pi Node runtime is not executable")
        node_executable = str(node_path)
    elif not _is_executable(executable):
        raise ManagedPiRuntimeError("managed Pi standalone entrypoint is not executable")
    return ManagedPiRuntimeInstallation(
        runtime_root=root_resolved,
        runtime_dir=runtime_resolved,
        runtime_version=runtime_version,
        pi_version=pi_version,
        executable=executable,
        node_executable=node_executable,
        extension_path=extension,
        tools=_validate_tools(manifest.get("tools")),
        manifest_sha256=actual_manifest_sha256,
    )


def _validate_manifest(manifest: Mapping[str, object]) -> None:
    try:
        validate_contract(dict(manifest), _MANIFEST_CONTRACT)
    except ContractValidationError as exc:
        raise ManagedPiRuntimeError(f"managed Pi runtime manifest is invalid: {exc}") from exc
    _safe_version(manifest.get("runtimeVersion"), label="runtime version")
    if not str(manifest.get("piVersion") or "").strip():
        raise ManagedPiRuntimeError("managed Pi manifest piVersion is empty")
    _validate_tools(manifest.get("tools"))
    source = manifest.get("source")
    if not isinstance(source, Mapping) or any(
        not str(source.get(key) or "").strip() for key in ("repository", "commit", "package")
    ):
        raise ManagedPiRuntimeError("managed Pi manifest source provenance is incomplete")
    items = _manifest_file_items(manifest)
    if not items:
        raise ManagedPiRuntimeError("managed Pi manifest does not list files")
    for item in items:
        _safe_relative_path(item.get("path"))
        _sha256_text(item.get("sha256"), label="runtime file digest")
        size = item.get("byteSize")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ManagedPiRuntimeError("managed Pi manifest file size is invalid")
        if not isinstance(item.get("executable"), bool):
            raise ManagedPiRuntimeError("managed Pi manifest executable flag is invalid")


def _manifest_file_items(manifest: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = manifest.get("files")
    if not isinstance(raw, list) or len(raw) > _MAX_RUNTIME_FILES:
        raise ManagedPiRuntimeError("managed Pi manifest file list is invalid")
    if any(not isinstance(item, Mapping) for item in raw):
        raise ManagedPiRuntimeError("managed Pi manifest file entry is invalid")
    return [item for item in raw if isinstance(item, Mapping)]


def _verify_manifest_file(runtime_dir: Path, relative: PurePosixPath, item: Mapping[str, object]) -> None:
    path = _resolve_runtime_file(runtime_dir, relative)
    expected_size = int(item.get("byteSize") or 0)
    if path.stat().st_size != expected_size:
        raise ManagedPiRuntimeError(f"managed Pi runtime file size mismatch: {relative.as_posix()}")
    if _sha256_file(path) != str(item.get("sha256") or ""):
        raise ManagedPiRuntimeError(f"managed Pi runtime file digest mismatch: {relative.as_posix()}")
    if bool(item.get("executable")) and not _is_executable(path):
        raise ManagedPiRuntimeError(f"managed Pi runtime file is not executable: {relative.as_posix()}")


def _resolve_payload_file(root: Path, relative: PurePosixPath) -> Path:
    return _resolve_runtime_file(root, relative)


def _resolve_runtime_file(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or _has_symlink_component(candidate, root):
        raise ManagedPiRuntimeError(f"managed Pi runtime contains a symlink: {relative.as_posix()}")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ManagedPiRuntimeError(f"managed Pi runtime file is missing: {relative.as_posix()}") from exc
    root_resolved = root.resolve(strict=True)
    if not resolved.is_file() or not _is_within(resolved, root_resolved):
        raise ManagedPiRuntimeError(f"managed Pi runtime file escapes its package: {relative.as_posix()}")
    return resolved


def _safe_relative_path(value: object) -> PurePosixPath:
    text = str(value or "").strip()
    path = PurePosixPath(text)
    if (
        not text
        or "\\" in text
        or path.is_absolute()
        or path.as_posix() != text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ManagedPiRuntimeError(f"unsafe managed Pi runtime path: {text or '<empty>'}")
    return path


def _safe_version(value: object, *, label: str) -> str:
    version = str(value or "").strip()
    if not _VERSION_PATTERN.fullmatch(version):
        raise ManagedPiRuntimeError(f"{label} is invalid")
    return version


def _sha256_text(value: object, *, label: str) -> str:
    digest = str(value or "").strip().lower()
    if not _SHA256_PATTERN.fullmatch(digest):
        raise ManagedPiRuntimeError(f"{label} is invalid")
    return digest


def _validate_tools(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 32:
        raise ManagedPiRuntimeError("managed Pi tool list is invalid")
    tools = tuple(str(item or "").strip() for item in value)
    if len(set(tools)) != len(tools) or any(not _TOOL_PATTERN.fullmatch(tool) for tool in tools):
        raise ManagedPiRuntimeError("managed Pi tool list is invalid")
    return tools


def _runtime_root(app_support: str | Path) -> Path:
    root = Path(app_support).expanduser() / "PiRuntime"
    if root.exists() and root.is_symlink():
        raise ManagedPiRuntimeError("managed Pi runtime root must not be a symlink")
    return root.resolve(strict=False)


def _runtime_file_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ManagedPiRuntimeError(f"managed Pi runtime contains a symlink: {path.relative_to(root)}")
        if path.is_file():
            paths.add(path.relative_to(root).as_posix())
    return paths


def _has_symlink_component(path: Path, root: Path) -> bool:
    current = path
    root_resolved = root.resolve(strict=True)
    while current != root_resolved:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return True
        current = parent
    return False


def _read_json_object(path: Path) -> dict[str, object]:
    return _parse_json_object(_read_limited_bytes(path), path)


def _read_limited_bytes(path: Path) -> bytes:
    try:
        size = path.stat().st_size
        if size > _MAX_JSON_BYTES:
            raise ManagedPiRuntimeError(f"managed Pi JSON file is too large: {path.name}")
        return path.read_bytes()
    except OSError as exc:
        raise ManagedPiRuntimeError(f"cannot read managed Pi JSON file: {path.name}") from exc


def _parse_json_object(data: bytes, path: Path) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManagedPiRuntimeError(f"managed Pi JSON file is invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise ManagedPiRuntimeError(f"managed Pi JSON file must contain an object: {path.name}")
    return value


def _atomic_write_bytes(path: Path, data: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXUSR)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _current_platform() -> str:
    return _normalize_platform(platform.system())


def _normalize_platform(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return {"macos": "darwin", "osx": "darwin"}.get(normalized, normalized)


def _current_architecture() -> str:
    return _normalize_architecture(platform.machine())


def _normalize_architecture(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return {"aarch64": "arm64", "amd64": "x86_64"}.get(normalized, normalized)
