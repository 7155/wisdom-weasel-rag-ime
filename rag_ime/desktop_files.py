"""User-driven local Files browsing; independent of Agent execution scopes."""
from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Mapping
from http import HTTPStatus
from pathlib import Path


def file_error_response(error: Exception) -> tuple[HTTPStatus, dict[str, object]]:
    if isinstance(error, PermissionError):
        status, message = HTTPStatus.FORBIDDEN, "系统未允许读取此位置，请检查文件权限或 macOS 的文件访问设置。"
    elif isinstance(error, FileNotFoundError):
        status, message = HTTPStatus.NOT_FOUND, "路径不存在或已被移动，请检查路径后重试。"
    elif isinstance(error, (ValueError, OSError, RuntimeError)):
        status, message = HTTPStatus.BAD_REQUEST, str(error)
    else:
        raise error
    return status, {"ok": False, "error": message}


def _integer(value: object, default: int, maximum: int, minimum: int = 0) -> int:
    try:
        result = default if value in (None, "") else int(str(value))
    except ValueError as error:
        raise ValueError("分页参数必须是整数。") from error
    if not minimum <= result <= maximum:
        raise ValueError(f"分页参数须在 {minimum}–{maximum} 之间。")
    return result


def _path(value: object, *, default_home: bool = False) -> Path:
    raw = str(value or "").strip()
    if not raw and default_home:
        return Path.home().resolve(strict=True)
    if not raw or "\0" in raw:
        raise ValueError("请输入文件或文件夹路径。")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("请输入绝对路径，也可以使用 ~/ 开头的主目录路径。")
    return candidate.resolve(strict=True)


def _revision(info: os.stat_result) -> str:
    return "stat:" + ":".join(str(value) for value in (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))


class DesktopFiles:
    def __init__(self, *, editability: Callable[[str, str], Mapping[str, object]] | None = None) -> None:
        self._editability = editability

    def list(self, args: Mapping[str, object]) -> dict[str, object]:
        target = _path(args.get("path"), default_home=True)
        selected = str(target) if target.is_file() else ""
        directory = target.parent if selected else target
        if not directory.is_dir():
            raise ValueError("这个位置不是文件夹或普通文件。")
        offset = _integer(args.get("offset"), 0, 10_000_000)
        limit = _integer(args.get("limit"), 240, 300, 1)
        entries: list[dict[str, object]] = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                try:
                    kind = "directory" if entry.is_dir() else "symlink" if entry.is_symlink() else "file"
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    kind, size = "symlink" if entry.is_symlink() else "file", None
                entries.append({"path": str(directory / entry.name), "name": entry.name, "kind": kind,
                                **({"byteSize": size} if size is not None and kind != "directory" else {})})
        entries.sort(key=lambda entry: (entry["kind"] != "directory", str(entry["name"]).casefold()))
        end = min(offset + limit, len(entries))
        return {"ok": True, "scope": "local", "path": str(directory), "parentPath": str(directory.parent),
                "homePath": str(Path.home()), "selectedPath": selected, "items": entries[offset:end],
                "truncated": end < len(entries), "nextOffset": end if end < len(entries) else None}

    def read(self, args: Mapping[str, object]) -> dict[str, object]:
        target = _path(args.get("path"))
        offset = _integer(args.get("offset"), 0, 2**53 - 1)
        limit = _integer(args.get("limit"), 65_536, 65_536, 1)
        permission: dict[str, object] = {"editable": False, "reason": "独立浏览仅预览；选择有写入权限的 Session 工作区后可以编辑。"}
        session_id = str(args.get("sessionId") or "")
        # This optional lookup controls the existing editor only, never reading.
        if session_id and self._editability:
            try:
                permission = dict(self._editability(session_id, str(target)))
            except (LookupError, ValueError, RuntimeError, TypeError, OSError):
                pass
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("仅支持预览普通文件，不能读取设备或管道。")
            if offset > before.st_size:
                raise ValueError("文件长度已变化，请刷新后重新读取。")
            handle.seek(offset)
            raw = handle.read(limit)
            if b"\0" in raw:
                raise ValueError("二进制文件不能作为文本预览，可复制路径后使用对应应用打开。")
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                if error.reason != "unexpected end of data" or offset + len(raw) >= before.st_size:
                    raise ValueError("此文件不是 UTF-8 文本，无法在文本预览中显示。") from error
                content = raw[:error.start].decode("utf-8")
            loaded = len(content.encode("utf-8"))
            if not loaded and offset < before.st_size:
                raise ValueError("读取长度不足以容纳一个完整字符，请增加读取长度。")
            revision = _revision(before)
            if permission.get("editable") and before.st_size <= 2 * 1024 * 1024:
                handle.seek(0)
                digest = hashlib.sha256()
                while chunk := handle.read(65_536):
                    digest.update(chunk)
                revision = "sha256:" + digest.hexdigest()
            else:
                permission["editable"] = False
            if _revision(os.fstat(handle.fileno())) != _revision(before):
                raise ValueError("读取期间文件已变化，请刷新后重新读取。")
        return {"ok": True, "scope": "local", "requestedPath": str(args.get("path")), "path": str(target),
                "content": content, "byteSize": before.st_size, "offset": offset,
                "nextOffset": offset + loaded, "truncated": offset + loaded < before.st_size,
                "resourceRevision": revision, "editability": permission}
