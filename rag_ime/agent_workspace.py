from __future__ import annotations

import difflib
import hashlib
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class WorkspaceHarnessError(RuntimeError):
    pass


_SENSITIVE_NAMES = frozenset(
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
_SENSITIVE_PARTS = frozenset({".git", ".ssh", ".gnupg", ".aws", ".azure", ".keychain"})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db")
_MAX_SEARCH_FILES = 5_000
_FORBIDDEN_COMMAND = re.compile(
    r"(?ix)(?:^|[;&|()\s])"
    r"(?:sudo|su|security|tccutil|csrutil|spctl|kmutil|kextload|nvram|diskutil|"
    r"mount|umount|launchctl|osascript|open|pbcopy|pbpaste|shutdown|reboot|halt|"
    r"pkill|killall|nohup)"
    r"(?:\s|$)"
)
_DESTRUCTIVE_COMMANDS = (
    re.compile(r"(?i)(?:^|[;&|\s])rm\s+(?:-[^\s]*[rf][^\s]*\s+|--recursive\b|--force\b)"),
    re.compile(r"(?i)\bgit\s+(?:reset\s+--hard|clean\s+-[^\s]*[fdx])\b"),
    re.compile(r"(?i)(?:^|[;&|\s])(?:dd|mkfs|shred)\s"),
    re.compile(r"(?i)(?:^|[;&|\s])(?:chmod|chown)\s+-R\b"),
    re.compile(r"(?i)(?:^|[;&|\s])truncate\s+-s\s*0\b"),
)
_SECRET_COMMAND = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|token|authorization|password|passwd|secret)\s*[:=]"
)
_NETWORK_COMMAND = re.compile(
    r"(?i)(?:^|[;&|()\s])(?:curl|wget|ssh|scp|sftp|nc|ncat|telnet|ftp|rsync)"
    r"(?:\s|$)"
)
_SENSITIVE_COMMAND_PATH = re.compile(
    r"(?i)(?:^|[/\s])(?:\.env(?:\.[^/\s]*)?|\.git-credentials|\.netrc|auth\.json|"
    r"credentials\.json|id_rsa|id_ed25519|[^/\s]+\.(?:pem|key|p12|pfx|sqlite|sqlite3|db))"
    r"(?:$|\s)"
)
_OUTPUT_REDACTIONS = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED]"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|authorization|password|secret)"
            r"(\s*[:=]\s*)\S+"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*"), "Bearer [REDACTED]"),
)


@dataclass(frozen=True)
class PreparedWorkspaceCommand:
    command: str
    cwd: Path
    roots: tuple[Path, ...]
    timeout_seconds: int
    allow_network: bool

    @property
    def roots_digest(self) -> str:
        value = "\n".join(str(root) for root in self.roots).encode("utf-8")
        return hashlib.sha256(value).hexdigest()


WorkspaceExecutor = Callable[[PreparedWorkspaceCommand], dict[str, object]]


@dataclass(frozen=True)
class PreparedWorkspacePatch:
    path: Path
    root: Path
    old_text: str
    new_text: str
    expected_occurrences: int
    preimage_sha256: str
    preimage_size: int
    postimage_sha256: str
    diff: str

    @property
    def roots_digest(self) -> str:
        return hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()


class WorkspaceHarness:
    """Fail-closed workspace reader and macOS sandboxed command harness."""

    def __init__(
        self,
        *,
        sandbox_executable: str | Path = "/usr/bin/sandbox-exec",
        executor: WorkspaceExecutor | None = None,
        max_output_bytes: int = 1_048_576,
    ) -> None:
        self.sandbox_executable = Path(sandbox_executable)
        self._executor = executor or self._run_sandboxed
        self.max_output_bytes = max(16_384, min(int(max_output_bytes), 4 * 1024 * 1024))

    def list(self, session: Mapping[str, object], args: Mapping[str, object]) -> dict[str, object]:
        roots = self._session_roots(session)
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            return {
                "summary": f"当前会话已授权 {len(roots)} 个工作区",
                "roots": [str(root) for root in roots],
                "items": [
                    {
                        "path": str(root),
                        "name": root.name or str(root),
                        "kind": "workspace",
                    }
                    for root in roots
                ],
            }
        target, root = self._resolve_existing_path(roots, raw_path, allow_directory=True)
        if not target.is_dir():
            raise WorkspaceHarnessError("workspace_list path must be a directory")
        depth = _bounded_integer(args.get("depth"), default=1, minimum=1, maximum=3)
        limit = _bounded_integer(args.get("limit"), default=100, minimum=1, maximum=300)
        items: list[dict[str, object]] = []
        self._walk(target=target, root=root, depth=depth, limit=limit, output=items)
        return {
            "summary": f"列出 {len(items)} 个工作区条目",
            "root": str(root),
            "path": str(target),
            "items": items,
            "truncated": len(items) >= limit,
        }

    def read(self, session: Mapping[str, object], args: Mapping[str, object]) -> dict[str, object]:
        roots = self._session_roots(session)
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise WorkspaceHarnessError("path is required for workspace_read")
        target, root = self._resolve_existing_path(roots, raw_path, allow_directory=False)
        if self._is_sensitive(target, root):
            raise WorkspaceHarnessError("sensitive files are not available to coordinator sessions")
        if not target.is_file() or target.is_symlink():
            raise WorkspaceHarnessError("workspace_read requires a regular non-symlink file")
        offset = _bounded_integer(args.get("offset"), default=0, minimum=0, maximum=50_000_000)
        limit = _bounded_integer(args.get("limit"), default=32_768, minimum=1, maximum=65_536)
        size = target.stat().st_size
        with target.open("rb") as handle:
            handle.seek(offset)
            raw = handle.read(limit + 1)
        if b"\x00" in raw:
            raise WorkspaceHarnessError("binary files are not available through workspace_read")
        try:
            text = raw[:limit].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceHarnessError("workspace_read only accepts UTF-8 text") from exc
        return {
            "summary": f"已读取 {target.name}",
            "path": str(target),
            "root": str(root),
            "offset": offset,
            "byteSize": size,
            "content": text,
            "truncated": len(raw) > limit or offset + len(raw) < size,
            "nextOffset": offset + len(raw[:limit]),
        }

    def search(self, session: Mapping[str, object], args: Mapping[str, object]) -> dict[str, object]:
        roots = self._session_roots(session)
        query = str(args.get("query") or "")
        if not query or len(query) > 200 or "\x00" in query or "\n" in query or "\r" in query:
            raise WorkspaceHarnessError("workspace_search query must be 1-200 single-line characters")
        mode = str(args.get("mode") or "content").strip().lower()
        if mode not in {"content", "name", "both"}:
            raise WorkspaceHarnessError("workspace_search mode must be content, name, or both")
        case_sensitive = _strict_bool(args.get("caseSensitive"))
        limit = _bounded_integer(args.get("limit"), default=50, minimum=1, maximum=100)
        raw_path = str(args.get("path") or "").strip()
        targets: list[tuple[Path, Path]] = []
        if raw_path:
            target, root = self._resolve_existing_path(roots, raw_path, allow_directory=True)
            targets.append((target, root))
        else:
            targets.extend((root, root) for root in roots)

        needle = query if case_sensitive else query.casefold()
        matches: list[dict[str, object]] = []
        files_scanned = 0
        truncated = False
        for target, root in targets:
            for path in self._search_files(target, root):
                if files_scanned >= _MAX_SEARCH_FILES or len(matches) >= limit:
                    truncated = True
                    break
                files_scanned += 1
                relative = str(path.relative_to(root))
                comparable_name = relative if case_sensitive else relative.casefold()
                if mode in {"name", "both"} and needle in comparable_name:
                    matches.append({"path": str(path), "relativePath": relative, "kind": "name"})
                    if len(matches) >= limit:
                        truncated = True
                        break
                if mode not in {"content", "both"}:
                    continue
                try:
                    if path.stat().st_size > 1_048_576:
                        continue
                    raw = path.read_bytes()
                    if b"\x00" in raw:
                        continue
                    text = raw.decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    comparable_line = line if case_sensitive else line.casefold()
                    if needle not in comparable_line:
                        continue
                    matches.append(
                        {
                            "path": str(path),
                            "relativePath": relative,
                            "kind": "content",
                            "lineNumber": line_number,
                            "preview": line[:500],
                        }
                    )
                    if len(matches) >= limit:
                        truncated = True
                        break
                if len(matches) >= limit:
                    break
            if truncated:
                break
        return {
            "summary": f"在 {files_scanned} 个文件中找到 {len(matches)} 条匹配",
            "query": query,
            "mode": mode,
            "matches": matches,
            "filesScanned": files_scanned,
            "truncated": truncated,
        }

    def prepare_patch(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> PreparedWorkspacePatch:
        roots = self._session_roots(session)
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise WorkspaceHarnessError("path is required for workspace_patch")
        target, root = self._resolve_existing_path(roots, raw_path, allow_directory=False)
        if self._is_sensitive(target, root) or target.is_symlink() or not target.is_file():
            raise WorkspaceHarnessError("workspace_patch requires a non-sensitive regular file")
        old_text = args.get("oldText")
        new_text = args.get("newText")
        if not isinstance(old_text, str) or not old_text or len(old_text) > 65_536 or "\x00" in old_text:
            raise WorkspaceHarnessError("oldText must be 1-65536 UTF-8 characters")
        if not isinstance(new_text, str) or len(new_text) > 131_072 or "\x00" in new_text:
            raise WorkspaceHarnessError("newText must be at most 131072 UTF-8 characters")
        expected = _bounded_integer(args.get("expectedOccurrences"), default=1, minimum=1, maximum=100)
        raw = target.read_bytes()
        if len(raw) > 2 * 1024 * 1024 or b"\x00" in raw:
            raise WorkspaceHarnessError("workspace_patch only accepts UTF-8 files up to 2 MiB")
        try:
            before = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceHarnessError("workspace_patch only accepts UTF-8 text") from exc
        actual = before.count(old_text)
        if actual != expected:
            raise WorkspaceHarnessError(
                f"oldText occurrence count changed: expected {expected}, found {actual}"
            )
        after = before.replace(old_text, new_text)
        after_raw = after.encode("utf-8")
        if len(after_raw) > 2 * 1024 * 1024:
            raise WorkspaceHarnessError("patched file would exceed 2 MiB")
        relative = str(target.relative_to(root))
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
                n=3,
            )
        )
        if len(diff.encode("utf-8")) > 131_072:
            raise WorkspaceHarnessError("workspace_patch diff is too large to review safely")
        return PreparedWorkspacePatch(
            path=target,
            root=root,
            old_text=old_text,
            new_text=new_text,
            expected_occurrences=expected,
            preimage_sha256=hashlib.sha256(raw).hexdigest(),
            preimage_size=len(raw),
            postimage_sha256=hashlib.sha256(after_raw).hexdigest(),
            diff=diff,
        )

    def patch_preview(self, prepared: PreparedWorkspacePatch) -> dict[str, object]:
        return {
            "title": "确认修改工作区文件",
            "summary": f"将对 {prepared.path.name} 执行精确文本替换",
            "operationLabel": "应用精确文本替换",
            "changes": [
                {"label": "文件", "before": str(prepared.path), "after": str(prepared.path)},
                {"label": "匹配次数", "before": str(prepared.expected_occurrences), "after": "已替换"},
                {"label": "差异", "before": "", "after": prepared.diff},
            ],
            "actionPayload": {
                "path": str(prepared.path),
                "oldText": prepared.old_text,
                "newText": prepared.new_text,
                "expectedOccurrences": prepared.expected_occurrences,
            },
            "baseState": {
                "preimageSha256": prepared.preimage_sha256,
                "preimageSize": prepared.preimage_size,
                "postimageSha256": prepared.postimage_sha256,
                "workspaceRootSha256": prepared.roots_digest,
            },
        }

    def apply_patch(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
        base_state: Mapping[str, object],
    ) -> dict[str, object]:
        prepared = self.prepare_patch(session, args)
        if prepared.roots_digest != str(base_state.get("workspaceRootSha256") or ""):
            raise WorkspaceHarnessError("authorized workspace changed after approval preview")
        if prepared.preimage_sha256 != str(base_state.get("preimageSha256") or ""):
            raise WorkspaceHarnessError("workspace file changed after approval preview")
        if prepared.postimage_sha256 != str(base_state.get("postimageSha256") or ""):
            raise WorkspaceHarnessError("workspace patch no longer matches approval preview")
        current_raw = prepared.path.read_bytes()
        if hashlib.sha256(current_raw).hexdigest() != prepared.preimage_sha256:
            raise WorkspaceHarnessError("workspace file changed immediately before atomic write")
        try:
            current_text = current_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceHarnessError("workspace file is no longer valid UTF-8") from exc
        if current_text.count(prepared.old_text) != prepared.expected_occurrences:
            raise WorkspaceHarnessError("workspace file match count changed before atomic write")
        after_raw = current_text.replace(prepared.old_text, prepared.new_text).encode("utf-8")
        if hashlib.sha256(after_raw).hexdigest() != prepared.postimage_sha256:
            raise WorkspaceHarnessError("workspace patch changed immediately before atomic write")
        mode = prepared.path.stat().st_mode & 0o777
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{prepared.path.name}.", dir=prepared.path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(after_raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, mode)
            os.replace(temporary, prepared.path)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "schemaVersion": "rag-ime.workspace-patch-receipt.v1",
            "mutationApplied": True,
            "summary": f"已修改 {prepared.path.name}",
            "path": str(prepared.path),
            "preimageSha256": prepared.preimage_sha256,
            "postimageSha256": prepared.postimage_sha256,
            "replacementCount": prepared.expected_occurrences,
            "undoAvailable": False,
        }

    def prepare_command(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> PreparedWorkspaceCommand:
        if str(session.get("mode") or "") != "coordinator":
            raise WorkspaceHarnessError("workspace commands require a coordinator session")
        roots = self._session_roots(session)
        command = str(args.get("command") or "").strip()
        if not command:
            raise WorkspaceHarnessError("command is required for workspace_shell")
        if len(command) > 2_000 or "\x00" in command or "\r" in command:
            raise WorkspaceHarnessError("workspace command is malformed or too long")
        if any(ord(character) < 32 and character not in "\n\t" for character in command):
            raise WorkspaceHarnessError("workspace command contains unsupported control characters")
        if _FORBIDDEN_COMMAND.search(command):
            raise WorkspaceHarnessError("this system or privilege command is not available")
        if any(pattern.search(command) for pattern in _DESTRUCTIVE_COMMANDS):
            raise WorkspaceHarnessError("destructive commands are not enabled in coordinator v1")
        if _SECRET_COMMAND.search(command):
            raise WorkspaceHarnessError("commands containing secret-like values are not accepted")
        if _SENSITIVE_COMMAND_PATH.search(command):
            raise WorkspaceHarnessError("commands may not name sensitive files")
        if re.search(r"(?<!&)&(?!&)", command):
            raise WorkspaceHarnessError("background commands are not accepted")

        allow_network = _strict_bool(args.get("allowNetwork"))
        if _NETWORK_COMMAND.search(command) and not allow_network:
            raise WorkspaceHarnessError("network command requires an explicit allowNetwork approval")
        raw_cwd = str(args.get("cwd") or "").strip()
        if raw_cwd:
            cwd, _ = self._resolve_existing_path(roots, raw_cwd, allow_directory=True)
        elif len(roots) == 1:
            cwd = roots[0]
        else:
            raise WorkspaceHarnessError("cwd is required when a session has multiple workspaces")
        if not cwd.is_dir():
            raise WorkspaceHarnessError("workspace command cwd must be a directory")
        timeout = _bounded_integer(args.get("timeoutSeconds"), default=30, minimum=1, maximum=120)
        return PreparedWorkspaceCommand(
            command=command,
            cwd=cwd,
            roots=roots,
            timeout_seconds=timeout,
            allow_network=allow_network,
        )

    def execute(self, prepared: PreparedWorkspaceCommand) -> dict[str, object]:
        return self._executor(prepared)

    def preview(self, prepared: PreparedWorkspaceCommand) -> dict[str, object]:
        return {
            "title": "确认运行工作区命令",
            "summary": f"在 {prepared.cwd.name or prepared.cwd} 中运行一条受沙箱保护的命令",
            "operationLabel": "运行受控命令",
            "changes": [
                {"label": "命令", "before": "", "after": prepared.command},
                {"label": "工作目录", "before": "", "after": str(prepared.cwd)},
                {
                    "label": "网络",
                    "before": "默认拒绝",
                    "after": "本次允许" if prepared.allow_network else "保持拒绝",
                },
                {
                    "label": "超时",
                    "before": "",
                    "after": f"{prepared.timeout_seconds} 秒",
                },
            ],
            "actionPayload": {
                "command": prepared.command,
                "cwd": str(prepared.cwd),
                "timeoutSeconds": prepared.timeout_seconds,
                "allowNetwork": prepared.allow_network,
            },
            "baseState": {"workspaceRootsSha256": prepared.roots_digest},
        }

    def _session_roots(self, session: Mapping[str, object]) -> tuple[Path, ...]:
        if str(session.get("mode") or "") != "coordinator":
            raise WorkspaceHarnessError("workspace tools require a coordinator session")
        values = session.get("workspaceRoots")
        if not isinstance(values, list) or not values:
            raise WorkspaceHarnessError("coordinator session has no authorized workspace")
        roots: list[Path] = []
        for value in values:
            root = Path(str(value)).expanduser().resolve(strict=True)
            if not root.is_dir() or root.is_symlink():
                raise WorkspaceHarnessError("authorized workspace must be a real directory")
            if root in {
                Path("/"),
                Path("/Users"),
                Path("/Volumes"),
                Path("/private"),
                Path.home().resolve(strict=False),
            }:
                raise WorkspaceHarnessError("authorized workspace root is too broad")
            if root not in roots:
                roots.append(root)
        return tuple(roots)

    def _resolve_existing_path(
        self,
        roots: Sequence[Path],
        raw_path: str,
        *,
        allow_directory: bool,
    ) -> tuple[Path, Path]:
        requested = Path(raw_path).expanduser()
        candidates = [requested] if requested.is_absolute() else [root / requested for root in roots]
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            for root in roots:
                if _is_within(resolved, root):
                    if resolved.is_dir() and not allow_directory:
                        raise WorkspaceHarnessError("workspace_read path must be a file")
                    return resolved, root
        raise WorkspaceHarnessError("path is outside the authorized workspace or does not exist")

    def _walk(
        self,
        *,
        target: Path,
        root: Path,
        depth: int,
        limit: int,
        output: list[dict[str, object]],
    ) -> None:
        if depth <= 0 or len(output) >= limit:
            return
        try:
            children = sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))
        except OSError as exc:
            raise WorkspaceHarnessError(f"cannot list workspace directory: {exc}") from exc
        for child in children:
            if len(output) >= limit:
                return
            if self._is_sensitive(child, root):
                continue
            is_link = child.is_symlink()
            kind = "symlink" if is_link else "directory" if child.is_dir() else "file"
            item: dict[str, object] = {"path": str(child), "name": child.name, "kind": kind}
            if kind == "file":
                try:
                    item["byteSize"] = child.stat().st_size
                except OSError:
                    item["byteSize"] = 0
            output.append(item)
            if kind == "directory":
                self._walk(
                    target=child,
                    root=root,
                    depth=depth - 1,
                    limit=limit,
                    output=output,
                )

    def _search_files(self, target: Path, root: Path):
        # Search shallow paths first so a large nested tree cannot consume the
        # whole scan budget before nearby project files are considered.
        pending = deque([target])
        while pending:
            current = pending.popleft()
            if current.is_symlink() or self._is_sensitive(current, root):
                continue
            if current.is_file():
                yield current
                continue
            if not current.is_dir():
                continue
            try:
                children = sorted(current.iterdir(), key=lambda path: path.name.lower())
            except OSError:
                continue
            pending.extend(children)

    def _is_sensitive(self, path: Path, root: Path) -> bool:
        try:
            relative = path.relative_to(root)
        except ValueError:
            return True
        parts = tuple(part.lower() for part in relative.parts)
        name = path.name.lower()
        return (
            name in _SENSITIVE_NAMES
            or any(part in _SENSITIVE_PARTS for part in parts)
            or name.endswith(_SENSITIVE_SUFFIXES)
            or "credential" in name
            or "keychain" in name
        )

    def _run_sandboxed(self, prepared: PreparedWorkspaceCommand) -> dict[str, object]:
        sandbox = self.sandbox_executable
        if not sandbox.is_file() or not os.access(sandbox, os.X_OK):
            raise WorkspaceHarnessError("macOS command harness is unavailable; refusing unsandboxed execution")
        started_at_ms = int(time.time() * 1_000)
        with tempfile.TemporaryDirectory(prefix="rag-ime-agent-command-") as temp_directory:
            temporary = Path(temp_directory).resolve(strict=True)
            profile = _sandbox_profile(
                roots=prepared.roots,
                temporary=temporary,
                allow_network=prepared.allow_network,
            )
            environment = {
                "HOME": str(temporary),
                "TMPDIR": str(temporary),
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "en_US.UTF-8",
                "LC_ALL": "en_US.UTF-8",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
            }
            process = subprocess.Popen(
                [str(sandbox), "-p", profile, "/bin/zsh", "-f", "-c", prepared.command],
                cwd=prepared.cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            output, timed_out, output_limited = self._bounded_output(process, prepared.timeout_seconds)
            exit_code = process.poll()
            if exit_code is None:
                self._terminate_group(process)
                exit_code = process.wait(timeout=2)
            else:
                # A shell may otherwise leave an approved background descendant.
                self._terminate_group(process)
            if process.stdout is not None:
                process.stdout.close()
            duration_ms = max(0, int(time.time() * 1_000) - started_at_ms)
        decoded = output.decode("utf-8", errors="replace")
        for pattern, replacement in _OUTPUT_REDACTIONS:
            decoded = pattern.sub(replacement, decoded)
        succeeded = int(exit_code) == 0 and not timed_out and not output_limited
        return {
            "schemaVersion": "rag-ime.workspace-command-receipt.v1",
            "mutationApplied": succeeded,
            "summary": (
                "命令执行超时"
                if timed_out
                else "命令输出超过上限，已停止"
                if output_limited
                else f"命令执行完成，退出码 {exit_code}"
            ),
            "commandSha256": hashlib.sha256(prepared.command.encode("utf-8")).hexdigest(),
            "cwd": str(prepared.cwd),
            "exitCode": int(exit_code),
            "durationMs": duration_ms,
            "timedOut": timed_out,
            "outputLimited": output_limited,
            "networkAllowed": prepared.allow_network,
            "output": decoded,
            "outputBytes": len(output),
            "undoAvailable": False,
        }

    def _bounded_output(
        self,
        process: subprocess.Popen[bytes],
        timeout_seconds: int,
    ) -> tuple[bytes, bool, bool]:
        if process.stdout is None:
            return b"", False, False
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout_seconds
        chunks: list[bytes] = []
        size = 0
        timed_out = False
        output_limited = False
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    self._terminate_group(process)
                    break
                events = selector.select(timeout=min(0.1, remaining))
                if not events and process.poll() is not None:
                    events = selector.select(timeout=0)
                    if not events:
                        break
                for key, _ in events:
                    chunk = os.read(key.fd, min(65_536, self.max_output_bytes - size + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    remaining_capacity = self.max_output_bytes - size
                    chunks.append(chunk[:remaining_capacity])
                    size += min(len(chunk), remaining_capacity)
                    if len(chunk) > remaining_capacity or size >= self.max_output_bytes:
                        output_limited = True
                        self._terminate_group(process)
                        return b"".join(chunks), timed_out, output_limited
        finally:
            selector.close()
        return b"".join(chunks), timed_out, output_limited

    @staticmethod
    def _terminate_group(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def _sandbox_profile(
    *,
    roots: Sequence[Path],
    temporary: Path,
    allow_network: bool,
) -> str:
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow sysctl-read)",
        "(allow file-read-metadata)",
        '(allow file-read* file-write-data (literal "/dev/null"))',
        "(allow file-read*",
        "  (require-all",
        '    (require-not (subpath "/Users"))',
        '    (require-not (subpath "/Volumes"))',
        '    (require-not (subpath "/private/var/folders"))',
        '    (require-not (subpath "/private/tmp"))))',
    ]
    for root in roots:
        escaped = _profile_escape(str(root))
        lines.append(f'(allow file-read* (subpath "{escaped}"))')
        lines.append(f'(allow file-write* (subpath "{escaped}"))')
    temp = _profile_escape(str(temporary))
    lines.append(f'(allow file-read* (subpath "{temp}"))')
    lines.append(f'(allow file-write* (subpath "{temp}"))')
    sensitive_patterns = (
        r"/\.env$",
        r"/\.env\.[^/]*$",
        r"/\.git-credentials$",
        r"/\.netrc$",
        r"/auth\.json$",
        r"/credentials\.json$",
        r"/cookies\.sqlite$",
        r"/id_rsa$",
        r"/id_ed25519$",
        r"/[^/]*\.(pem|key|p12|pfx|sqlite|sqlite3|db)$",
        r"/\.(ssh|gnupg|aws|azure|keychain)(/|$)",
    )
    for pattern in sensitive_patterns:
        lines.append(f'(deny file-read* (regex #"{pattern}"))')
        lines.append(f'(deny file-write* (regex #"{pattern}"))')
    if allow_network:
        lines.append("(allow network-outbound)")
        lines.append('(allow file-read* (literal "/private/etc/hosts"))')
        lines.append('(allow file-read* (literal "/private/etc/resolv.conf"))')
    return "\n".join(lines)


def _profile_escape(value: str) -> str:
    if "\n" in value or "\r" in value or "\x00" in value:
        raise WorkspaceHarnessError("workspace path cannot be represented in a sandbox profile")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _bounded_integer(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise WorkspaceHarnessError("numeric workspace parameter cannot be boolean")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkspaceHarnessError("workspace parameter must be an integer") from exc
    if result < minimum or result > maximum:
        raise WorkspaceHarnessError(f"workspace parameter must be between {minimum} and {maximum}")
    return result


def _strict_bool(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise WorkspaceHarnessError("allowNetwork must be boolean")
