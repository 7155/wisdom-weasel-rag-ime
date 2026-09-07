"""Bounded local/text intake for Lab projects; never executes a source project."""
from __future__ import annotations

import hashlib
import itertools
import os
import time
import uuid
from pathlib import Path
from typing import Any

MAX_FILES = 100
MAX_FILE_BYTES = 500_000
MAX_TOTAL_BYTES = 2_000_000
MAX_SCAN_ENTRIES = 2_000
MAX_DEPTH = 8
_IGNORED_DIRS = {"node_modules", "vendor", "__pycache__", "venv", "build", "dist", "target", "coverage", "logs", "cache"}
_TEXT_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".sql", ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".sh", ".go", ".rs", ".java", ".kt", ".swift", ".rb", ".php", ".c", ".h", ".cpp"}
_CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".sh", ".go", ".rs", ".java", ".kt", ".swift", ".rb", ".php", ".c", ".h", ".cpp", ".sql", ".html", ".css"}
_PRIVATE_NAMES = {"auth.json", "credentials.json", "credentials", "secrets.json", "secrets.yaml", "secrets.yml", "id_rsa", "id_ed25519"}


def empty_intake() -> dict[str, Any]:
    return {"reader": "utf8-text.v1", "state": "needs_materials", "requestedPath": "", "resolvedPath": "",
            "pathKind": "", "readCount": 0, "readBytes": 0, "scannedCount": 0, "skippedCount": 0,
            "partial": False, "issues": [], "checkedAtMs": None}


def _text(value: Any, label: str, limit: int, *, optional: bool = False) -> str:
    if not isinstance(value, str) or (not optional and not value.strip()) or len(value) > limit:
        raise ValueError(f"{label}无效。")
    return value


def material(title: str, content: str, *, source_id: str, uri: str, kind: str, origin: str) -> dict[str, Any]:
    if not content.strip() or "\x00" in content:
        raise ValueError("材料需要包含可读取的文本。")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("单份材料超过 500 KB，请按内容拆分后添加。")
    return {"sourceId": source_id, "title": title, "kind": kind, "origin": origin, "uri": uri,
            "text": content, "byteSize": len(encoded), "contentHash": hashlib.sha256(encoded).hexdigest(),
            "importedAtMs": int(time.time() * 1000)}


def validate_material_set(materials: list[dict[str, Any]]) -> None:
    if len(materials) > MAX_FILES or sum(item["byteSize"] for item in materials) > MAX_TOTAL_BYTES:
        raise ValueError("当前材料最多 100 份、合计 2 MB；请收窄材料范围。")


def read_inline_materials(value: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_FILES:
        raise ValueError("请添加 1–100 份文本材料。")
    result = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {"sourceId", "title", "text", "kind", "uri"}:
            raise ValueError("材料字段无效。")
        source_id = _text(item.get("sourceId", f"source-{uuid.uuid4().hex}"), "材料标识", 240)
        if source_id in seen:
            raise ValueError("一次导入不能包含重复的材料标识。")
        seen.add(source_id)
        kind = item.get("kind", "document")
        if not isinstance(kind, str) or kind not in {"document", "code", "skill", "history", "failure"}:
            raise ValueError("材料类型无效。")
        result.append(material(_text(item.get("title"), "材料名称", 500),
                               _text(item.get("text"), "材料文本", MAX_FILE_BYTES), source_id=source_id,
                               uri=_text(item.get("uri", f"upload:{source_id}"), "材料来源", 4096), kind=kind, origin="text"))
    validate_material_set(result)
    intake = {**empty_intake(), "state": "read", "readCount": len(result), "scannedCount": len(result),
              "readBytes": sum(item["byteSize"] for item in result), "checkedAtMs": int(time.time() * 1000)}
    return result, intake


def read_local_materials(path_value: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requested = _text(path_value, "本地路径", 4096).strip()
    if "\x00" in requested or not Path(requested).expanduser().is_absolute():
        raise ValueError("请提供本机的绝对文件或目录路径。")
    intake = {**empty_intake(), "requestedPath": requested, "checkedAtMs": int(time.time() * 1000)}
    result: list[dict[str, Any]] = []

    def issue(code: str, title: str, message: str) -> None:
        intake["skippedCount"] += 1
        intake["partial"] = True
        if len(intake["issues"]) < MAX_FILES:
            intake["issues"].append({"code": code, "title": title, "message": message})

    try:
        root = Path(requested).expanduser().resolve(strict=True)
        if not root.is_file() and not root.is_dir():
            raise OSError("not a regular file or directory")
    except (OSError, RuntimeError):
        issue("path_unavailable", Path(requested).name, "路径不存在或暂时无法读取；已有材料仍保留。")
        intake["state"] = "unavailable"
        return result, intake
    intake.update(resolvedPath=str(root), pathKind="directory" if root.is_dir() else "file")

    def read_file(path: Path, title: str) -> None:
        if path.name.startswith(".") or path.name.lower() in _PRIVATE_NAMES:
            issue("excluded", title, "已略过配置或凭据文件。")
            return
        if path.suffix.lower() not in _TEXT_SUFFIXES and path.name not in {"Dockerfile", "Makefile", "LICENSE", "README"}:
            issue("unsupported_format", title, "当前读取器支持 UTF-8 文档与源码；此格式尚未接入。")
            return
        if len(result) >= MAX_FILES:
            issue("file_limit", title, "达到 100 份材料的读取上限。")
            return
        try:
            # O_NOFOLLOW also closes the symlink replacement race after directory
            # enumeration. Only a bounded amount is read from a regular file.
            descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as source:
                import stat
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    issue("not_regular_file", title, "只读取普通文件。")
                    return
                data = source.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                issue("file_too_large", title, "文件超过 500 KB，未截断导入。")
                return
            if intake["readBytes"] + len(data) > MAX_TOTAL_BYTES:
                issue("total_size_limit", title, "达到 2 MB 的材料读取上限。")
                return
            content = data.decode("utf-8-sig")
            if "\x00" in content:
                raise UnicodeError()
            if not content.strip():
                issue("empty_file", title, "文件没有可用文本。")
                return
        except UnicodeError:
            issue("binary_or_encoding", title, "文件包含二进制内容或不是 UTF-8 文本。")
            return
        except OSError:
            issue("file_unavailable", title, "文件暂时无法读取。")
            return
        kind = "skill" if path.name == "SKILL.md" else "code" if path.suffix.lower() in _CODE_SUFFIXES else "document"
        uri = path.as_uri()
        result.append(material(title, content, source_id=f"source-{hashlib.sha256(uri.encode()).hexdigest()[:24]}",
                               uri=uri, kind=kind, origin="path"))
        intake["readBytes"] += len(data)

    if root.is_file():
        intake["scannedCount"] = 1
        read_file(root, root.name)
    else:
        pending = [(root, 0)]
        while pending:
            directory, depth = pending.pop()
            remaining = MAX_SCAN_ENTRIES - intake["scannedCount"]
            if remaining <= 0:
                issue("scan_limit", root.name, "达到目录扫描上限，请选择更具体的子目录。")
                break
            try:
                with os.scandir(directory) as iterator:
                    entries = sorted(itertools.islice(iterator, remaining + 1), key=lambda entry: entry.name)
            except OSError:
                issue("directory_unavailable", directory.name, "子目录暂时无法读取。")
                continue
            if len(entries) > remaining:
                issue("scan_limit", directory.name, "达到目录扫描上限，未遍历全部文件。")
                entries = entries[:remaining]
            for entry in entries:
                intake["scannedCount"] += 1
                path = Path(entry.path)
                title = str(path.relative_to(root))
                try:
                    if entry.is_symlink():
                        issue("symlink", title, "未跟随子目录中的符号链接。")
                    elif entry.name.startswith(".") or entry.name.lower() in _PRIVATE_NAMES:
                        issue("excluded", title, "已略过隐藏文件、配置或凭据。")
                    elif entry.is_dir(follow_symlinks=False):
                        if entry.name in _IGNORED_DIRS:
                            issue("excluded", title, "已略过依赖、构建或缓存目录。")
                        elif depth >= MAX_DEPTH:
                            issue("depth_limit", title, "达到目录深度上限。")
                        else:
                            pending.append((path, depth + 1))
                    elif entry.is_file(follow_symlinks=False):
                        read_file(path, title)
                    else:
                        issue("not_regular_file", title, "只读取普通文件。")
                except OSError:
                    issue("file_unavailable", title, "文件暂时无法读取。")
    intake.update(readCount=len(result), state="read" if result else "needs_materials")
    return result, intake
