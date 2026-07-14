from __future__ import annotations

import hashlib
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
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
_SENSITIVE_PARTS = frozenset({".ssh", ".gnupg", ".aws", ".azure", ".keychain"})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3", ".db")
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
        return {
            "schemaVersion": "rag-ime.workspace-command-receipt.v1",
            "mutationApplied": True,
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
