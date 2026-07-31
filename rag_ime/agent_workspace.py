from __future__ import annotations

import atexit
import difflib
import fnmatch
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from .agent_execution_policy import (
    FULL_TRUST_EXECUTION_MODE,
    normalize_execution_mode,
    workspace_scope_is_granted,
)
from .contracts.json_schema import validate_contract


class WorkspaceHarnessError(RuntimeError):
    pass

class WorkspaceSnapshotError(WorkspaceHarnessError):
    """A machine-classifiable stale or missing file snapshot."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


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
_PI_TOOL_RESULT_MAX_BYTES = 50 * 1024
_PI_READ_MAX_LINES = 2_000
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
_CATASTROPHIC_COMMANDS = (
    re.compile(
        r"(?i)(?:^|[;&|\s])rm\s+(?:-[^\s]*[rf][^\s]*\s+|--recursive\b[^\n]*|"
        r"--force\b[^\n]*)(?:[\"']?(?:/|~|\$HOME|\$\{?PWD\}?|\.)[\"']?(?:\s|$)|[^\n]*"
        r"(?:\.sqlite3?|\.db)(?:\s|$))"
    ),
    re.compile(r"(?i)\bgit\s+clean\s+-[^\s]*f[^\s]*[dx][^\s]*\b"),
    re.compile(r"(?i)(?:^|[;&|\s])(?:dd|mkfs(?:\.\w+)?|shred)\s"),
    re.compile(
        r"(?i)(?:^|[;&|\s])(?:rm|unlink)\s+[^\n]*(?:\.sqlite3?|\.db)(?:\s|$)"
    ),
    re.compile(r"(?i)\b(?:drop|truncate)\s+(?:database|schema|table)\b"),
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
_SENSITIVE_EGRESS_PATH = re.compile(
    r"(?i)(?:\.env(?:\.[^/\\\s\"']*)?|\.git-credentials|\.netrc|auth\.json|"
    r"credentials\.json|cookies\.sqlite|id_rsa|id_ed25519|"
    r"[^/\\\s\"']+\.(?:pem|key|p12|pfx|sqlite|sqlite3|db))"
)
_NETWORK_DESTINATION = re.compile(
    r"(?i)(?:https?://|(?:^|[;&|()\s])(?:curl|wget|ssh|scp|sftp|nc|ncat|telnet|ftp|rsync)"
    r"(?:\s|$))"
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

def _workspace_command_path(
    *,
    opt_roots: Sequence[Path] = (
        Path("/opt/homebrew/opt"),
        Path("/usr/local/opt"),
    ),
    base_directories: Sequence[Path] = (
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/bin"),
        Path("/usr/sbin"),
        Path("/sbin"),
    ),
) -> str:
    """Return a fixed, credential-free PATH including keg-only Node installs."""

    candidates: list[Path] = []
    for opt_root in opt_roots:
        unversioned = opt_root / "node" / "bin"
        if unversioned.is_dir():
            candidates.append(unversioned)
        versioned = [
            path
            for path in opt_root.glob("node@*/bin")
            if path.is_dir()
        ]
        versioned.sort(
            key=lambda path: int(
                match.group(1)
                if (
                    match := re.fullmatch(
                        r"node@(\d+)",
                        path.parent.name,
                    )
                )
                else 0
            ),
            reverse=True,
        )
        candidates.extend(versioned)
    candidates.extend(base_directories)
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate)
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return os.pathsep.join(unique)


def _linked_worktree_metadata_roots(roots: Sequence[Path]) -> tuple[Path, ...]:
    """Return validated shared Git metadata required by linked worktrees."""

    metadata_roots: list[Path] = []
    for root in roots:
        pointer = root / ".git"
        if not pointer.is_file() or pointer.is_symlink():
            continue
        try:
            pointer_text = pointer.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        lines = pointer_text.splitlines()
        if (
            len(pointer_text) > 4_096
            or len(lines) != 1
            or not lines[0].startswith("gitdir:")
        ):
            continue
        raw_git_dir = lines[0].removeprefix("gitdir:").strip()
        if not raw_git_dir or "\x00" in raw_git_dir:
            continue
        try:
            git_dir_path = Path(raw_git_dir).expanduser()
            if not git_dir_path.is_absolute():
                git_dir_path = pointer.parent / git_dir_path
            git_dir = git_dir_path.resolve(strict=True)
            backlink_text = (git_dir / "gitdir").read_text(encoding="utf-8").strip()
            common_text = (git_dir / "commondir").read_text(encoding="utf-8").strip()
            if not backlink_text or not common_text:
                continue
            backlink_path = Path(backlink_text).expanduser()
            if not backlink_path.is_absolute():
                backlink_path = git_dir / backlink_path
            common_path = Path(common_text).expanduser()
            if not common_path.is_absolute():
                common_path = git_dir / common_path
            backlink = backlink_path.resolve(strict=True)
            common = common_path.resolve(strict=True)
            worktrees = (common / "worktrees").resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if (
            not git_dir.is_dir()
            or git_dir.parent != worktrees
            or backlink != pointer.resolve(strict=True)
            or not (git_dir / "HEAD").is_file()
            or not (common / "objects").is_dir()
            or any(common == root or common.is_relative_to(root) for root in roots)
        ):
            continue
        if common not in metadata_roots:
            metadata_roots.append(common)
    return tuple(metadata_roots)


@dataclass(frozen=True)
class PreparedWorkspaceCommand:
    command: str
    cwd: Path
    roots: tuple[Path, ...]
    timeout_seconds: int
    allow_network: bool
    repository_metadata_roots: tuple[Path, ...] = ()

    @property
    def roots_digest(self) -> str:
        values = [str(root) for root in self.roots]
        values.extend(
            f"repository-metadata:{root}" for root in self.repository_metadata_roots
        )
        return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()

    @property
    def sandbox_roots(self) -> tuple[Path, ...]:
        return (*self.roots, *self.repository_metadata_roots)


WorkspaceExecutor = Callable[[PreparedWorkspaceCommand], dict[str, object]]


@dataclass
class SpawnedWorkspaceCommand:
    process: subprocess.Popen[bytes]
    temporary_directory: tempfile.TemporaryDirectory

    def cleanup(self) -> None:
        self.temporary_directory.cleanup()


@dataclass(frozen=True)
class WorkspaceReadOriginProof:
    sha256: str
    displayed_ranges: tuple[tuple[int, int], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "displayedRanges": [
                {"startLine": start, "endLine": end}
                for start, end in self.displayed_ranges
            ],
        }


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
    read_origin: WorkspaceReadOriginProof | None = None

    @property
    def roots_digest(self) -> str:
        return hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreparedWorkspaceEdit:
    path: Path
    root: Path
    edits: tuple[tuple[str, str], ...]
    preimage_sha256: str
    preimage_size: int
    postimage_sha256: str
    postimage: bytes
    diff: str
    read_origin: WorkspaceReadOriginProof | None = None

    @property
    def resource_revision(self) -> str:
        return _workspace_resource_revision_from_sha256(self.preimage_sha256)

    @property
    def roots_digest(self) -> str:
        return hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreparedWorkspaceWrite:
    path: Path
    root: Path
    content: str
    existed_before: bool
    preimage_sha256: str
    preimage_size: int
    postimage_sha256: str
    postimage: bytes
    diff: str
    work_document: dict[str, object] | None = None

    @property
    def resource_revision(self) -> str:
        return (
            _workspace_resource_revision_from_sha256(self.preimage_sha256)
            if self.existed_before
            else "missing"
        )

    @property
    def roots_digest(self) -> str:
        return hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()


class WorkspaceLspError(WorkspaceHarnessError):
    """A stable, machine-classifiable workspace LSP failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WorkspaceLspServerConfig:
    name: str
    command: tuple[str, ...]
    language_ids: tuple[str, ...]
    file_extensions: tuple[str, ...]
    root_markers: tuple[str, ...]


@dataclass(frozen=True)
class PreparedWorkspaceLspFile:
    path: Path
    preimage_sha256: str
    preimage_size: int
    postimage_sha256: str
    postimage: bytes
    mode: int
    diff: str


@dataclass(frozen=True)
class PreparedWorkspaceLspMutation:
    operation: str
    root: Path
    server: str
    request: Mapping[str, object]
    files: tuple[PreparedWorkspaceLspFile, ...]

    @property
    def root_digest(self) -> str:
        return hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()


_DEFAULT_LSP_SERVERS = (
    WorkspaceLspServerConfig(
        name="pyright",
        command=("pyright-langserver", "--stdio"),
        language_ids=("python",),
        file_extensions=(".py", ".pyi"),
        root_markers=("pyproject.toml", "pyrightconfig.json", "requirements.txt", "setup.py", "setup.cfg"),
    ),
    WorkspaceLspServerConfig(
        name="typescript",
        command=("typescript-language-server", "--stdio"),
        language_ids=("typescript", "typescriptreact", "javascript", "javascriptreact"),
        file_extensions=(".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"),
        root_markers=("package.json", "tsconfig.json", "jsconfig.json"),
    ),
    WorkspaceLspServerConfig(
        name="rust-analyzer",
        command=("rust-analyzer",),
        language_ids=("rust",),
        file_extensions=(".rs",),
        root_markers=("Cargo.toml",),
    ),
    WorkspaceLspServerConfig(
        name="gopls",
        command=("gopls",),
        language_ids=("go",),
        file_extensions=(".go",),
        root_markers=("go.mod", "go.work"),
    ),
    WorkspaceLspServerConfig(
        name="clangd",
        command=("clangd",),
        language_ids=("c", "cpp", "objective-c", "objective-cpp"),
        file_extensions=(".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".m", ".mm"),
        root_markers=("compile_commands.json", "compile_flags.txt", "CMakeLists.txt"),
    ),
    WorkspaceLspServerConfig(
        name="sourcekit-lsp",
        command=("sourcekit-lsp",),
        language_ids=("swift",),
        file_extensions=(".swift",),
        root_markers=("Package.swift",),
    ),
)
_LSP_MAX_RESULT_ITEMS = 200
_LSP_MAX_FILES = 16
_LSP_MAX_TOTAL_WRITE_BYTES = 4 * 1024 * 1024
_LSP_MAX_DIFF_BYTES = 128 * 1024
_LSP_SYMBOL_KINDS = {
    1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class",
    6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum",
    11: "interface", 12: "function", 13: "variable", 14: "constant",
    15: "string", 16: "number", 17: "boolean", 18: "array", 19: "object",
    20: "key", 21: "null", 22: "enum_member", 23: "struct", 24: "event",
    25: "operator", 26: "type_parameter",
}
_LSP_DIAGNOSTIC_SEVERITIES = {1: "error", 2: "warning", 3: "information", 4: "hint"}


@dataclass
class _WorkspaceLspClient:
    config: WorkspaceLspServerConfig
    root: Path
    process: subprocess.Popen[bytes]
    temporary_directory: tempfile.TemporaryDirectory | None
    capabilities: Mapping[str, object] = field(default_factory=dict)
    diagnostics: dict[str, list[Mapping[str, object]]] = field(default_factory=dict)
    open_documents: dict[Path, tuple[str, int]] = field(default_factory=dict)
    last_activity: float = field(default_factory=time.monotonic)
    _request_id: int = 0
    _buffer: bytes = b""
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _cancelled: bool = False

    def request(self, method: str, params: Mapping[str, object], timeout_seconds: float) -> object:
        with self._lock:
            if self.process.poll() is not None:
                raise WorkspaceLspError(
                    "server_degraded",
                    f"workspace_lsp server {self.config.name} exited unexpectedly",
                )
            self._request_id += 1
            request_id = self._request_id
            self._write_message(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)}
            )
            deadline = time.monotonic() + timeout_seconds
            while True:
                message = self._next_message(deadline)
                if message.get("id") == request_id and "method" not in message:
                    error = message.get("error")
                    if isinstance(error, Mapping):
                        raise WorkspaceLspError(
                            "request_failed",
                            f"{self.config.name} rejected {method}: "
                            f"{str(error.get('message') or 'unknown LSP error')[:240]}",
                        )
                    self.last_activity = time.monotonic()
                    return message.get("result")
                self._handle_unsolicited(message)

    def notify(self, method: str, params: Mapping[str, object]) -> None:
        with self._lock:
            self._write_message({"jsonrpc": "2.0", "method": method, "params": dict(params)})
            self.last_activity = time.monotonic()

    def open_document(self, path: Path, language_id: str) -> None:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        previous = self.open_documents.get(path)
        if previous is not None and previous[0] == digest:
            return
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceLspError(
                "invalid_document",
                "workspace_lsp only accepts UTF-8 source files",
            ) from exc
        if previous is None:
            version = 1
            self.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": path.as_uri(),
                        "languageId": language_id,
                        "version": version,
                        "text": text,
                    }
                },
            )
        else:
            version = previous[1] + 1
            self.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": path.as_uri(), "version": version},
                    "contentChanges": [{"text": text}],
                },
            )
        self.open_documents[path] = (digest, version)

    def cancel(self) -> None:
        self._cancelled = True
        WorkspaceHarness._terminate_group(self.process)


    def close(self) -> None:
        try:
            if self.process.poll() is None:
                try:
                    self.request("shutdown", {}, 0.2)
                    self.notify("exit", {})
                except Exception:
                    pass
                WorkspaceHarness._terminate_group(self.process)
        finally:
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            if self.temporary_directory is not None:
                self.temporary_directory.cleanup()

    def _write_message(self, message: Mapping[str, object]) -> None:
        if self.process.stdin is None:
            raise WorkspaceLspError("server_degraded", "workspace_lsp server stdin is unavailable")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.process.stdin.write(
                f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
            )
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise WorkspaceLspError(
                "server_degraded",
                f"workspace_lsp server {self.config.name} stopped accepting requests",
            ) from exc

    def _next_message(self, deadline: float) -> Mapping[str, object]:
        if self.process.stdout is None:
            raise WorkspaceLspError("server_degraded", "workspace_lsp server stdout is unavailable")
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            while True:
                parsed = self._parse_buffered_message()
                if parsed is not None:
                    return parsed
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkspaceLspError(
                        "request_timeout",
                        f"workspace_lsp request to {self.config.name} timed out",
                    )
                events = selector.select(timeout=min(0.1, remaining))
                if not events:
                    if self.process.poll() is not None:
                        raise WorkspaceLspError(
                            "server_degraded",
                            f"workspace_lsp server {self.config.name} exited unexpectedly",
                        )
                    continue
                chunk = os.read(self.process.stdout.fileno(), 65_536)
                if not chunk:
                    raise WorkspaceLspError(
                        "server_degraded",
                        f"workspace_lsp server {self.config.name} closed its protocol stream",
                    )
                self._buffer += chunk
                if len(self._buffer) > 4 * 1024 * 1024:
                    raise WorkspaceLspError(
                        "server_degraded",
                        "workspace_lsp server response exceeded the protocol buffer limit",
                    )
        finally:
            selector.close()

    def _parse_buffered_message(self) -> Mapping[str, object] | None:
        separator = self._buffer.find(b"\r\n\r\n")
        if separator < 0:
            return None
        headers = self._buffer[:separator].decode("ascii", errors="replace").split("\r\n")
        length = None
        for header in headers:
            name, _, value = header.partition(":")
            if name.lower().strip() == "content-length":
                try:
                    length = int(value.strip())
                except ValueError:
                    length = None
                break
        if length is None or length < 0 or length > 4 * 1024 * 1024:
            raise WorkspaceLspError("server_degraded", "workspace_lsp server sent invalid framing")
        body_start = separator + 4
        if len(self._buffer) < body_start + length:
            return None
        body = self._buffer[body_start : body_start + length]
        self._buffer = self._buffer[body_start + length :]
        try:
            message = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkspaceLspError(
                "server_degraded",
                "workspace_lsp server sent invalid JSON",
            ) from exc
        if not isinstance(message, Mapping):
            raise WorkspaceLspError("server_degraded", "workspace_lsp server sent a non-object message")
        return message

    def _handle_unsolicited(self, message: Mapping[str, object]) -> None:
        method = str(message.get("method") or "")
        params = message.get("params")
        if method == "textDocument/publishDiagnostics" and isinstance(params, Mapping):
            uri = str(params.get("uri") or "")
            values = params.get("diagnostics")
            if isinstance(values, list):
                self.diagnostics[uri] = [
                    item for item in values[:_LSP_MAX_RESULT_ITEMS] if isinstance(item, Mapping)
                ]
            return
        if "id" in message and method:
            result: object = None
            if method == "workspace/workspaceFolders":
                result = [{"uri": self.root.as_uri(), "name": self.root.name}]
            elif method == "workspace/configuration":
                items = params.get("items") if isinstance(params, Mapping) else []
                result = [{} for _ in items] if isinstance(items, list) else []
            self._write_message({"jsonrpc": "2.0", "id": message["id"], "result": result})


class WorkspaceHarness:
    """Fail-closed workspace reader and macOS sandboxed command harness."""

    def __init__(
        self,
        *,
        sandbox_executable: str | Path = "/usr/bin/sandbox-exec",
        executor: WorkspaceExecutor | None = None,
        max_output_bytes: int = 1_048_576,
        lsp_servers: Sequence[WorkspaceLspServerConfig] | None = None,
        lsp_process_sandbox: bool = True,
        lsp_max_clients: int = 4,
        lsp_idle_timeout_seconds: float = 300.0,
    ) -> None:
        self.sandbox_executable = Path(sandbox_executable)
        self._executor = executor or self._run_sandboxed
        self.max_output_bytes = max(16_384, min(int(max_output_bytes), 4 * 1024 * 1024))
        self.lsp_servers = tuple(lsp_servers) if lsp_servers is not None else _DEFAULT_LSP_SERVERS
        self.lsp_process_sandbox = bool(lsp_process_sandbox)
        self.lsp_max_clients = max(1, min(int(lsp_max_clients), 8))
        self.lsp_idle_timeout_seconds = max(1.0, min(float(lsp_idle_timeout_seconds), 3_600.0))
        self._lsp_clients: OrderedDict[tuple[Path, str], _WorkspaceLspClient] = OrderedDict()
        self._lsp_errors: dict[tuple[Path, str], str] = {}
        self._lsp_pending: dict[
            tuple[Path, str],
            subprocess.Popen[bytes],
        ] = {}
        self._lsp_generation = 0
        self._lsp_runtime_instance_id = f"workspace-lsp-{uuid.uuid4().hex}"
        self._lsp_heartbeat_ttl_ms = 30_000
        self._lsp_root_generations: dict[Path, int] = {}
        self._lsp_lock = threading.RLock()
        self._lsp_closed = False
        atexit.register(self.close_lsp)

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
        selector = str(args.get("selector") or "").strip()
        if selector:
            return self._read_selector(
                target=target,
                root=root,
                args=args,
                selector=selector,
            )
        if "lineOffset" in args or "lineLimit" in args:
            return self._read_lines(target=target, root=root, args=args)
        offset = _bounded_integer(args.get("offset"), default=0, minimum=0, maximum=50_000_000)
        requested_limit = _bounded_integer(
            args.get("limit"),
            default=32_768,
            minimum=1,
            maximum=65_536,
        )
        content_limit = min(requested_limit, _PI_TOOL_RESULT_MAX_BYTES)
        with target.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if offset > size:
                raise WorkspaceHarnessError(
                    f"workspace_read offset {offset} is beyond end of file ({size} UTF-8 bytes)"
                )
            digest = hashlib.sha256()
            bytes_before = offset
            lines_before = 0
            while bytes_before:
                chunk = handle.read(min(65_536, bytes_before))
                if not chunk:
                    raise WorkspaceHarnessError("workspace file changed during read")
                digest.update(chunk)
                lines_before += chunk.count(b"\n")
                bytes_before -= len(chunk)
            raw = handle.read(content_limit + 4)
            digest.update(raw)
            while chunk := handle.read(65_536):
                digest.update(chunk)
        if b"\x00" in raw:
            raise WorkspaceHarnessError("binary files are not available through workspace_read")
        text = _decode_workspace_read_prefix(
            raw[:content_limit],
            allow_trailing_partial=offset + content_limit < size,
            offset=offset,
        )
        if not text and offset < size:
            required = _utf8_codepoint_width(raw[0]) if raw else 1
            raise WorkspaceHarnessError(
                "workspace_read limit is too small for the next UTF-8 character; "
                f"use at least {required} bytes"
            )
        text, line_limited = _limit_workspace_read_lines(text)
        return _bounded_workspace_read_result(
            target=target,
            root=root,
            offset=offset,
            size=size,
            requested_limit=requested_limit,
            candidate=text,
            line_limited=line_limited,
            read_origin_sha256=digest.hexdigest(),
            start_line=lines_before + 1,
        )

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
        pattern_kind = str(args.get("patternKind") or "literal").strip().lower()
        if pattern_kind not in {"literal", "regex", "glob"}:
            raise WorkspaceHarnessError(
                "workspace_search patternKind must be literal, regex, or glob"
            )
        context = _bounded_integer(args.get("context"), default=0, minimum=0, maximum=20)
        path_glob = str(args.get("glob") or "").strip()
        if "\x00" in path_glob or "\n" in path_glob or "\r" in path_glob:
            raise WorkspaceHarnessError("workspace_search glob must be a single-line pattern")
        raw_path = str(args.get("path") or "").strip()
        targets: list[tuple[Path, Path]] = []
        if raw_path:
            target, root = self._resolve_existing_path(roots, raw_path, allow_directory=True)
            targets.append((target, root))
        else:
            targets.extend((root, root) for root in roots)

        needle = query if case_sensitive else query.casefold()
        regex: re.Pattern[str] | None = None
        if pattern_kind == "regex":
            try:
                regex = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
            except re.error as error:
                raise WorkspaceHarnessError(
                    f"workspace_search regex is invalid: {error}"
                ) from error

        def matches_pattern(value: str) -> bool:
            comparable = value if case_sensitive else value.casefold()
            if pattern_kind == "regex":
                assert regex is not None
                return regex.search(value) is not None
            if pattern_kind == "glob":
                return fnmatch.fnmatchcase(comparable, needle)
            return needle in comparable

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
                if path_glob and not (
                    fnmatch.fnmatch(relative, path_glob)
                    or fnmatch.fnmatch(path.name, path_glob)
                ):
                    continue
                if mode in {"name", "both"} and matches_pattern(relative):
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
                lines = text.splitlines()
                for line_number, line in enumerate(lines, start=1):
                    if not matches_pattern(line):
                        continue
                    before_start = max(0, line_number - context - 1)
                    after_end = min(len(lines), line_number + context)
                    matches.append(
                        {
                            "path": str(path),
                            "relativePath": relative,
                            "kind": "content",
                            "lineNumber": line_number,
                            "preview": line[:500],
                            **(
                                {
                                    "contextBefore": lines[before_start : line_number - 1],
                                    "contextAfter": lines[line_number:after_end],
                                }
                                if context
                                else {}
                            ),
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
            "patternKind": pattern_kind,
            "matches": matches,
            "filesScanned": files_scanned,
            "truncated": truncated,
        }

    def _read_lines(
        self,
        *,
        target: Path,
        root: Path,
        args: Mapping[str, object],
    ) -> dict[str, object]:
        start_line = _bounded_integer(
            args.get("lineOffset"),
            default=1,
            minimum=1,
            maximum=50_000_000,
        )
        line_limit = _bounded_integer(
            args.get("lineLimit"),
            default=_PI_READ_MAX_LINES,
            minimum=1,
            maximum=_PI_READ_MAX_LINES,
        )
        chunks: list[str] = []
        bytes_used = 0
        end_line = start_line - 1
        next_line_offset: int | None = None
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            for line_number, raw_line in enumerate(handle, start=1):
                digest.update(raw_line)
                if line_number < start_line or next_line_offset is not None:
                    continue
                if len(chunks) >= line_limit:
                    next_line_offset = line_number
                    continue
                if b"\x00" in raw_line:
                    raise WorkspaceHarnessError(
                        "binary files are not available through workspace_read"
                    )
                remaining = _PI_TOOL_RESULT_MAX_BYTES - bytes_used
                if len(raw_line) > remaining:
                    if not chunks and remaining > 0:
                        prefix = _decode_workspace_read_prefix(
                            raw_line[:remaining],
                            allow_trailing_partial=True,
                            offset=0,
                        )
                        chunks.append(prefix)
                        end_line = line_number
                        next_line_offset = line_number + 1
                    else:
                        next_line_offset = line_number
                    continue
                try:
                    decoded = raw_line.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise WorkspaceHarnessError(
                        "workspace_read requires valid UTF-8 text"
                    ) from error
                chunks.append(decoded)
                bytes_used += len(raw_line)
                end_line = line_number
        if end_line < start_line:
            raise WorkspaceHarnessError(
                f"workspace_read lineOffset {start_line} is beyond end of file"
            )
        content = "".join(chunks)
        return {
            "summary": f"已读取 {target.name} 第 {start_line}-{end_line} 行",
            "path": str(target),
            "relativePath": str(target.relative_to(root)),
            "content": content,
            "startLine": start_line,
            "endLine": end_line,
            "nextLineOffset": next_line_offset,
            "truncated": next_line_offset is not None,
            "size": size,
            "resourceRevision": _workspace_resource_revision_from_sha256(digest.hexdigest()),
            "readOrigin": WorkspaceReadOriginProof(
                sha256=digest.hexdigest(),
                displayed_ranges=((start_line, end_line),),
            ).as_dict(),
        }

    def _read_selector(
        self,
        *,
        target: Path,
        root: Path,
        args: Mapping[str, object],
        selector: str,
    ) -> dict[str, object]:
        selector_mode, requested_ranges, raw_mode = _parse_workspace_read_selector(selector)
        cursor = _bounded_integer(
            args.get("selectorCursor"),
            default=0,
            minimum=0,
            maximum=50_000_000,
        )
        line_limit = _bounded_integer(
            args.get("lineLimit"),
            default=_PI_READ_MAX_LINES,
            minimum=1,
            maximum=_PI_READ_MAX_LINES,
        )
        requested_limit = _bounded_integer(
            args.get("limit"),
            default=32_768,
            minimum=1,
            maximum=65_536,
        )
        content_limit = min(requested_limit, 40 * 1024)
        digest = hashlib.sha256()
        selected_total = 0
        emitted: list[tuple[int, str]] = []
        bytes_used = 0
        truncated_by = ""
        page_full = False
        conflict_active = False
        range_index = 0
        with target.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            for line_number, raw_line in enumerate(handle, start=1):
                digest.update(raw_line)
                if b"\x00" in raw_line:
                    raise WorkspaceHarnessError(
                        "binary files are not available through workspace_read"
                    )
                try:
                    decoded = raw_line.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise WorkspaceHarnessError(
                        "workspace_read requires valid UTF-8 text"
                    ) from error
                if selector_mode == "conflicts":
                    if decoded.startswith("<<<<<<<"):
                        conflict_active = True
                    selected = conflict_active
                    if conflict_active and decoded.startswith(">>>>>>>"):
                        conflict_active = False
                else:
                    while (
                        range_index < len(requested_ranges)
                        and line_number > requested_ranges[range_index][1]
                    ):
                        range_index += 1
                    selected = bool(
                        range_index < len(requested_ranges)
                        and requested_ranges[range_index][0]
                        <= line_number
                        <= requested_ranges[range_index][1]
                    )
                if not selected:
                    continue
                selected_total += 1
                if selected_total <= cursor:
                    continue
                if page_full:
                    continue
                if len(emitted) >= line_limit:
                    truncated_by = truncated_by or "lines"
                    continue
                remaining = content_limit - bytes_used
                if remaining <= 0:
                    truncated_by = truncated_by or "bytes"
                    page_full = True
                    continue
                if len(raw_line) > remaining:
                    if emitted:
                        truncated_by = truncated_by or "bytes"
                        page_full = True
                        continue
                    raise WorkspaceHarnessError(
                        "workspace_read selected line exceeds the bounded selector page; "
                        "use byte offset/limit reading for this file"
                    )
                emitted.append((line_number, decoded))
                bytes_used += len(decoded.encode("utf-8"))

        if selector_mode != "conflicts" and selected_total == 0:
            raise WorkspaceHarnessError(
                f"workspace_read selector {selector!r} does not select an existing line"
            )
        if cursor > selected_total:
            raise WorkspaceHarnessError(
                f"workspace_read selectorCursor {cursor} is beyond the selected result"
            )
        def build_result(
            selected: Sequence[tuple[int, str]],
            *,
            result_truncated_by: str,
        ) -> dict[str, object]:
            content_parts: list[str] = []
            segments: list[dict[str, object]] = []
            displayed_ranges: list[tuple[int, int]] = []
            content_chars = 0
            for line_number, text in selected:
                start_char = content_chars
                content_parts.append(text)
                content_chars += len(text)
                if segments and line_number == int(segments[-1]["endLine"]) + 1:
                    segments[-1]["endLine"] = line_number
                    segments[-1]["contentEnd"] = content_chars
                    displayed_ranges[-1] = (displayed_ranges[-1][0], line_number)
                else:
                    segments.append(
                        {
                            "startLine": line_number,
                            "endLine": line_number,
                            "contentStart": start_char,
                            "contentEnd": content_chars,
                        }
                    )
                    displayed_ranges.append((line_number, line_number))
            content = "".join(content_parts)
            consumed = len(selected)
            next_cursor = (
                cursor + consumed
                if selected_total > cursor + consumed
                else None
            )
            bounded_by = result_truncated_by
            if next_cursor is not None and not bounded_by:
                bounded_by = "lines"
            return {
                "summary": (
                    f"已读取 {target.name} 的 {consumed} 行选择结果"
                    if consumed
                    else f"{target.name} 没有未解决的冲突块"
                ),
                "path": str(target),
                "relativePath": str(target.relative_to(root)),
                "selector": selector,
                "selectorMode": selector_mode,
                "raw": raw_mode,
                "content": content,
                "segments": segments,
                "selectedLineCount": selected_total,
                "selectorCursor": cursor,
                "nextSelectorCursor": next_cursor,
                "truncated": next_cursor is not None,
                "truncatedBy": bounded_by or None,
                "contentLines": consumed,
                "contentChars": len(content),
                "contentBytes": len(content.encode("utf-8")),
                "size": size,
                "resourceRevision": _workspace_resource_revision_from_sha256(digest.hexdigest()),
                "readOrigin": WorkspaceReadOriginProof(
                    sha256=digest.hexdigest(),
                    displayed_ranges=tuple(displayed_ranges),
                ).as_dict(),
            }

        result = build_result(emitted, result_truncated_by=truncated_by)
        if _compact_json_size(result) <= _PI_TOOL_RESULT_MAX_BYTES:
            return result
        low = 1
        high = len(emitted)
        best: dict[str, object] | None = None
        while low <= high:
            middle = (low + high) // 2
            trial = build_result(
                emitted[:middle],
                result_truncated_by="bytes",
            )
            if _compact_json_size(trial) <= _PI_TOOL_RESULT_MAX_BYTES:
                best = trial
                low = middle + 1
            else:
                high = middle - 1
        if best is None:
            raise WorkspaceHarnessError(
                "workspace_read selected line exceeds the bounded selector result; "
                "use byte offset/limit reading for this file"
            )
        return best

    def lsp_status(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> dict[str, object]:
        roots = self._lsp_requested_roots(session, args)
        self._cleanup_idle_lsp_clients()
        observed_at_ms = int(time.time() * 1000)
        with self._lsp_lock:
            current = not self._lsp_closed
            runtime_instance_id = self._lsp_runtime_instance_id
            runtime_epoch = self._lsp_generation
            clients = dict(self._lsp_clients)
            errors = dict(self._lsp_errors)
        snapshots: list[dict[str, object]] = []
        for root in roots:
            servers: list[dict[str, object]] = []
            for config in self.lsp_servers:
                if not self._lsp_detected(root, config):
                    continue
                key = (root, config.name)
                executable = self._resolve_lsp_executable(config.command[0])
                client = clients.get(key)
                error = errors.get(key, "")
                if not current:
                    state = "unavailable"
                    error = "workspace_lsp runtime lifecycle is closed"
                elif client is not None and client.process.poll() is None:
                    state = "ready"
                elif error:
                    state = "degraded"
                elif executable is None:
                    state = "unavailable"
                    error = f"{config.command[0]} is not available on the configured PATH"
                elif self.lsp_process_sandbox and not self._lsp_sandbox_available():
                    state = "degraded"
                    error = "macOS LSP sandbox is unavailable; refusing an unsandboxed server"
                else:
                    state = "available"
                item: dict[str, object] = {
                    "name": config.name,
                    "state": state,
                    "languageIds": list(config.language_ids),
                    "fileExtensions": list(config.file_extensions),
                }
                if error:
                    item["errorCode"] = (
                        "server_unavailable" if state == "unavailable" else "server_degraded"
                    )
                    item["error"] = error[:500]
                servers.append(item)
            if not servers:
                root_state = "unavailable"
            elif any(item["state"] == "ready" for item in servers):
                root_state = "ready"
            elif any(item["state"] == "available" for item in servers):
                root_state = "available"
            elif any(item["state"] == "degraded" for item in servers):
                root_state = "degraded"
            else:
                root_state = "unavailable"
            snapshots.append(
                {
                    "root": str(root),
                    "state": root_state,
                    "servers": servers,
                    **(
                        {
                            "errorCode": "no_server_configured",
                            "error": "No configured language server matches this workspace root",
                        }
                        if not servers
                        else {}
                    ),
                }
            )
        states = {str(item["state"]) for item in snapshots}
        state = (
            "ready"
            if "ready" in states
            else "available"
            if "available" in states
            else "degraded"
            if "degraded" in states
            else "unavailable"
        )
        ready = sum(1 for item in snapshots if item["state"] == "ready")
        return _validated_lsp(
            {
                "schemaVersion": "rag-ime.workspace-lsp-status.v1",
                "runtimeInstanceId": runtime_instance_id,
                "runtimeEpoch": runtime_epoch,
                "observedAtMs": observed_at_ms,
                "heartbeatExpiresAtMs": (
                    observed_at_ms + self._lsp_heartbeat_ttl_ms
                    if current
                    else observed_at_ms
                ),
                "current": current,
                "summary": f"{len(snapshots)} 个授权工作区中 {ready} 个语言服务已就绪",
                "state": state,
                "roots": snapshots,
            },
            "workspace-lsp-status.v1.json",
        )

    def lsp_read(
        self,
        session: Mapping[str, object],
        operation: str,
        args: Mapping[str, object],
    ) -> dict[str, object]:
        if operation not in {
            "symbols",
            "hover",
            "definition",
            "references",
            "diagnostics",
        }:
            raise WorkspaceLspError(
                "unsupported_operation",
                f"unsupported workspace_lsp read operation: {operation}",
            )
        timeout_seconds = _bounded_integer(
            args.get("timeoutMs"),
            default=5_000,
            minimum=100,
            maximum=20_000,
        ) / 1_000
        if operation == "symbols":
            root = self._lsp_single_root(session, args)
            query = str(args.get("query") or "").strip()
            if len(query) > 240 or "\x00" in query:
                raise WorkspaceLspError("invalid_request", "workspace_lsp query is invalid")
            items: list[dict[str, object]] = []
            server_names: list[str] = []
            for config in self._lsp_configs_for_root(root, requested=args.get("server")):
                client = self._lsp_client(root, config, timeout_seconds)
                raw = self._lsp_request(
                    client,
                    "workspace/symbol",
                    {"query": query},
                    timeout_seconds,
                )
                server_names.append(config.name)
                for value in raw if isinstance(raw, list) else []:
                    normalized = self._normalize_lsp_symbol(value, root, config.name)
                    if normalized is not None:
                        items.append(normalized)
                        if len(items) >= _LSP_MAX_RESULT_ITEMS:
                            break
                if len(items) >= _LSP_MAX_RESULT_ITEMS:
                    break
            return _validated_lsp(
                {
                    "schemaVersion": "rag-ime.workspace-lsp-result.v1",
                    "summary": f"找到 {len(items)} 个工作区符号",
                    "operation": operation,
                    "root": str(root),
                    "server": ",".join(server_names),
                    "items": items,
                    "truncated": len(items) >= _LSP_MAX_RESULT_ITEMS,
                },
                "workspace-lsp-result.v1.json",
            )

        target, root = self._lsp_source_path(session, args)
        config = self._lsp_config_for_file(root, target, requested=args.get("server"))
        client = self._lsp_client(root, config, timeout_seconds)
        client.open_document(target, self._lsp_language_id(config, target))
        position = self._lsp_position(args)
        document = {"uri": target.as_uri()}
        if operation == "hover":
            raw = self._lsp_request(
                client,
                "textDocument/hover",
                {"textDocument": document, "position": position},
                timeout_seconds,
            )
            hover = self._normalize_lsp_hover(raw)
            return _validated_lsp(
                {
                    "schemaVersion": "rag-ime.workspace-lsp-result.v1",
                    "summary": "已读取悬停信息" if hover["content"] else "当前位置没有悬停信息",
                    "operation": operation,
                    "root": str(root),
                    "server": config.name,
                    **hover,
                },
                "workspace-lsp-result.v1.json",
            )
        if operation == "diagnostics":
            items: list[Mapping[str, object]] = []
            try:
                raw = self._lsp_request(
                    client,
                    "textDocument/diagnostic",
                    {"textDocument": document},
                    timeout_seconds,
                    discard_on_failure=False,
                )
                if isinstance(raw, Mapping) and isinstance(raw.get("items"), list):
                    items = [item for item in raw["items"] if isinstance(item, Mapping)]
            except WorkspaceLspError as exc:
                if exc.code != "request_failed":
                    raise
            if not items:
                items = client.diagnostics.get(target.as_uri(), [])
            normalized_diagnostics = [
                self._normalize_lsp_diagnostic(value, target, root)
                for value in items[:_LSP_MAX_RESULT_ITEMS]
            ]
            return _validated_lsp(
                {
                    "schemaVersion": "rag-ime.workspace-lsp-result.v1",
                    "summary": f"找到 {len(normalized_diagnostics)} 条诊断",
                    "operation": operation,
                    "root": str(root),
                    "server": config.name,
                    "items": normalized_diagnostics,
                    "truncated": len(items) > _LSP_MAX_RESULT_ITEMS,
                },
                "workspace-lsp-result.v1.json",
            )
        method = (
            "textDocument/definition"
            if operation == "definition"
            else "textDocument/references"
        )
        params: dict[str, object] = {"textDocument": document, "position": position}
        if operation == "references":
            params["context"] = {"includeDeclaration": args.get("includeDeclaration") is not False}
        raw = self._lsp_request(client, method, params, timeout_seconds)
        values = raw if isinstance(raw, list) else ([] if raw is None else [raw])
        locations = []
        for value in values[:_LSP_MAX_RESULT_ITEMS]:
            normalized = self._normalize_lsp_location(value, root)
            if normalized is not None:
                locations.append(normalized)
        return _validated_lsp(
            {
                "schemaVersion": "rag-ime.workspace-lsp-result.v1",
                "summary": f"找到 {len(locations)} 个位置",
                "operation": operation,
                "root": str(root),
                "server": config.name,
                "items": locations,
                "truncated": len(values) > _LSP_MAX_RESULT_ITEMS,
            },
            "workspace-lsp-result.v1.json",
        )

    def close_lsp(self) -> None:
        with self._lsp_lock:
            clients = list(self._lsp_clients.values())
            pending = list(self._lsp_pending.values())
            self._lsp_clients.clear()
            self._lsp_pending.clear()
            self._lsp_generation += 1
            self._lsp_closed = True
        for process in pending:
            self._terminate_group(process)
        for client in clients:
            client.cancel()
            client.close()

    def cancel_lsp(self, root: str | Path | None = None) -> int:
        """Cancel active requests by terminating their root-scoped process groups."""

        requested = Path(root).resolve(strict=False) if root is not None else None
        with self._lsp_lock:
            keys = [
                key
                for key in self._lsp_clients
                if requested is None or key[0] == requested
            ]
            pending_keys = [
                key
                for key in self._lsp_pending
                if requested is None or key[0] == requested
            ]
            clients = [self._lsp_clients.pop(key) for key in keys]
            pending = [self._lsp_pending.pop(key) for key in pending_keys]
            self._lsp_generation += 1
            if requested is not None:
                self._lsp_root_generations[requested] = (
                    self._lsp_root_generations.get(requested, 0) + 1
                )
        for process in pending:
            self._terminate_group(process)
        for client in clients:
            client.cancel()
            client.close()
        return len(clients) + len(pending)

    def _lsp_requested_roots(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> tuple[Path, ...]:
        roots = self._session_roots(session)
        raw_root = str(args.get("root") or "").strip()
        if not raw_root:
            return roots
        try:
            target, root = self._resolve_existing_path(
                roots,
                raw_root,
                allow_directory=True,
            )
        except WorkspaceHarnessError as exc:
            raise WorkspaceLspError(
                "root_not_authorized",
                "workspace_lsp root must be an authorized workspace root",
            ) from exc
        if not target.is_dir() or target != root:
            raise WorkspaceLspError(
                "root_not_authorized",
                "workspace_lsp root must be an authorized workspace root",
            )
        return (root,)

    def _lsp_single_root(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> Path:
        roots = self._lsp_requested_roots(session, args)
        if len(roots) != 1:
            raise WorkspaceLspError(
                "root_required",
                "workspace_lsp root is required when a session has multiple workspaces",
            )
        return roots[0]

    def _lsp_source_path(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> tuple[Path, Path]:
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise WorkspaceLspError("invalid_request", "path is required for workspace_lsp")
        try:
            target, root = self._resolve_existing_path(
                self._session_roots(session),
                raw_path,
                allow_directory=False,
            )
        except WorkspaceHarnessError as exc:
            raise WorkspaceLspError(
                "path_not_allowed",
                "workspace_lsp path is outside the authorized workspace or does not exist",
            ) from exc
        if (
            self._is_sensitive(target, root)
            or target.is_symlink()
            or not target.is_file()
            or target.stat().st_size > 2 * 1024 * 1024
        ):
            raise WorkspaceLspError(
                "path_not_allowed",
                "workspace_lsp requires a non-sensitive regular source file up to 2 MiB",
            )
        return target, root

    def _lsp_detected(self, root: Path, config: WorkspaceLspServerConfig) -> bool:
        if "." in config.root_markers:
            return True
        for marker in config.root_markers:
            matched = any(root.glob(marker)) if "*" in marker else (root / marker).exists()
            if matched:
                return True
        scanned = 0
        pending = deque([root])
        while pending and scanned < 1_000:
            directory = pending.popleft()
            try:
                children = tuple(directory.iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_symlink() or self._is_sensitive(child, root):
                    continue
                if child.is_dir():
                    if child.name not in {
                        "node_modules",
                        ".venv",
                        "venv",
                        "target",
                        "build",
                        "dist",
                        "__pycache__",
                    }:
                        pending.append(child)
                    continue
                scanned += 1
                if child.suffix.lower() in config.file_extensions:
                    return True
                if scanned >= 1_000:
                    break
        return False

    def _lsp_configs_for_root(
        self,
        root: Path,
        *,
        requested: object = None,
    ) -> tuple[WorkspaceLspServerConfig, ...]:
        requested_name = str(requested or "").strip()
        configs = tuple(
            config
            for config in self.lsp_servers
            if self._lsp_detected(root, config)
            and (not requested_name or config.name == requested_name)
        )
        if not configs:
            raise WorkspaceLspError(
                "no_server_configured",
                "no configured language server matches this authorized workspace",
            )
        return configs

    def _lsp_config_for_file(
        self,
        root: Path,
        path: Path,
        *,
        requested: object = None,
    ) -> WorkspaceLspServerConfig:
        suffix = path.suffix.lower()
        configs = tuple(
            config
            for config in self._lsp_configs_for_root(root, requested=requested)
            if suffix in config.file_extensions
        )
        if not configs:
            raise WorkspaceLspError(
                "no_server_configured",
                f"no configured language server supports {path.name}",
            )
        if len(configs) > 1 and not str(requested or "").strip():
            raise WorkspaceLspError(
                "server_required",
                "multiple language servers support this file; select server explicitly",
            )
        return configs[0]

    @staticmethod
    def _resolve_lsp_executable(command: str) -> str | None:
        candidate = Path(command).expanduser()
        if candidate.is_absolute():
            return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
        return shutil.which(command)

    def _lsp_sandbox_available(self) -> bool:
        return self.sandbox_executable.is_file() and os.access(self.sandbox_executable, os.X_OK)

    def _lsp_client(
        self,
        root: Path,
        config: WorkspaceLspServerConfig,
        timeout_seconds: float,
    ) -> _WorkspaceLspClient:
        self._cleanup_idle_lsp_clients()
        key = (root, config.name)
        with self._lsp_lock:
            if self._lsp_closed:
                raise WorkspaceLspError(
                    "request_cancelled",
                    "workspace_lsp lifecycle is closed",
                )
            generation = self._lsp_generation
            root_generation = self._lsp_root_generations.get(root, 0)
            existing = self._lsp_clients.get(key)
            if existing is not None and existing.process.poll() is None:
                self._lsp_clients.move_to_end(key)
                return existing
            if existing is not None:
                self._lsp_clients.pop(key, None)
                existing.close()
        executable = self._resolve_lsp_executable(config.command[0])
        if executable is None:
            raise WorkspaceLspError(
                "server_unavailable",
                f"workspace_lsp server {config.command[0]} is unavailable",
            )
        temporary_directory: tempfile.TemporaryDirectory | None = None
        command = [executable, *config.command[1:]]
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if self.lsp_process_sandbox:
            if not self._lsp_sandbox_available():
                raise WorkspaceLspError(
                    "server_degraded",
                    "macOS LSP sandbox is unavailable; refusing unsandboxed execution",
                )
            try:
                temporary_directory = tempfile.TemporaryDirectory(
                    prefix="rag-ime-workspace-lsp-"
                )
                temporary = Path(temporary_directory.name).resolve(strict=True)
                environment.update({"HOME": str(temporary), "TMPDIR": str(temporary)})
                command = [
                    str(self.sandbox_executable),
                    "-p",
                    _lsp_sandbox_profile(root=root, temporary=temporary),
                    *command,
                ]
            except Exception:
                if temporary_directory is not None:
                    temporary_directory.cleanup()
                raise
        try:
            process = subprocess.Popen(
                command,
                cwd=root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            with self._lsp_lock:
                cancelled = (
                    self._lsp_closed
                    or generation != self._lsp_generation
                    or root_generation != self._lsp_root_generations.get(root, 0)
                )
                if not cancelled:
                    self._lsp_pending[key] = process
            if cancelled:
                self._terminate_group(process)
                raise WorkspaceLspError(
                    "request_cancelled",
                    "workspace_lsp startup was cancelled",
                )
            client = _WorkspaceLspClient(
                config=config,
                root=root,
                process=process,
                temporary_directory=temporary_directory,
            )
            initialized = client.request(
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": root.as_uri(),
                    "rootPath": str(root),
                    "capabilities": {
                        "workspace": {"workspaceFolders": True},
                        "textDocument": {
                            "hover": {"contentFormat": ["markdown", "plaintext"]},
                            "definition": {"linkSupport": True},
                            "references": {},
                            "rename": {"prepareSupport": False},
                            "codeAction": {"resolveSupport": {"properties": ["edit"]}},
                            "diagnostic": {},
                            "synchronization": {"didSave": False},
                        },
                    },
                    "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
                },
                timeout_seconds,
            )
            if not isinstance(initialized, Mapping):
                raise WorkspaceLspError(
                    "server_degraded",
                    f"workspace_lsp server {config.name} returned no initialize result",
                )
            capabilities = initialized.get("capabilities")
            client.capabilities = capabilities if isinstance(capabilities, Mapping) else {}
            client.notify("initialized", {})
        except Exception as exc:
            with self._lsp_lock:
                if self._lsp_pending.get(key) is locals().get("process"):
                    self._lsp_pending.pop(key, None)
                cancelled = (
                    self._lsp_closed
                    or generation != self._lsp_generation
                    or root_generation != self._lsp_root_generations.get(root, 0)
                )
            if "client" in locals():
                self._terminate_group(client.process)
                client.close()
            elif "process" in locals():
                self._terminate_group(process)
                if temporary_directory is not None:
                    temporary_directory.cleanup()
            elif temporary_directory is not None:
                temporary_directory.cleanup()
            if cancelled:
                raise WorkspaceLspError(
                    "request_cancelled",
                    "workspace_lsp startup was cancelled",
                ) from exc
            message = str(exc)[:500]
            with self._lsp_lock:
                self._lsp_errors[key] = message
            if isinstance(exc, WorkspaceLspError):
                raise
            raise WorkspaceLspError(
                "server_degraded",
                f"workspace_lsp server {config.name} failed to initialize: {message}",
            ) from exc
        with self._lsp_lock:
            if self._lsp_pending.get(key) is process:
                self._lsp_pending.pop(key, None)
            cancelled = (
                self._lsp_closed
                or generation != self._lsp_generation
                or root_generation != self._lsp_root_generations.get(root, 0)
            )
            if not cancelled:
                while len(self._lsp_clients) >= self.lsp_max_clients:
                    _, evicted = self._lsp_clients.popitem(last=False)
                    evicted.close()
                self._lsp_clients[key] = client
                self._lsp_errors.pop(key, None)
        if cancelled:
            self._terminate_group(client.process)
            client.close()
            raise WorkspaceLspError(
                "request_cancelled",
                "workspace_lsp startup was cancelled",
            )
        return client

    def _lsp_request(
        self,
        client: _WorkspaceLspClient,
        method: str,
        params: Mapping[str, object],
        timeout_seconds: float,
        *,
        discard_on_failure: bool = True,
    ) -> object:
        try:
            return client.request(method, params, timeout_seconds)
        except WorkspaceLspError as exc:
            failure = (
                WorkspaceLspError(
                    "request_cancelled",
                    f"workspace_lsp request to {client.config.name} was cancelled",
                )
                if client._cancelled and exc.code != "request_cancelled"
                else exc
            )
            if discard_on_failure and failure.code in {
                "request_timeout",
                "request_cancelled",
                "server_degraded",
            }:
                key = (client.root, client.config.name)
                with self._lsp_lock:
                    if self._lsp_clients.get(key) is client:
                        self._lsp_clients.pop(key, None)
                    if failure.code == "request_cancelled":
                        self._lsp_errors.pop(key, None)
                    else:
                        self._lsp_errors[key] = str(failure)[:500]
                client.close()
            if failure is not exc:
                raise failure from exc
            raise

    def _cleanup_idle_lsp_clients(self) -> None:
        cutoff = time.monotonic() - self.lsp_idle_timeout_seconds
        with self._lsp_lock:
            stale_keys = [
                key
                for key, client in self._lsp_clients.items()
                if client.last_activity < cutoff or client.process.poll() is not None
            ]
            clients = [self._lsp_clients.pop(key) for key in stale_keys]
        for client in clients:
            client.close()

    @staticmethod
    def _lsp_position(args: Mapping[str, object]) -> dict[str, int]:
        line = _bounded_integer(args.get("line"), default=1, minimum=1, maximum=10_000_000)
        column = _bounded_integer(
            args.get("column"),
            default=1,
            minimum=1,
            maximum=10_000_000,
        )
        return {"line": line - 1, "character": column - 1}

    @staticmethod
    def _lsp_language_id(config: WorkspaceLspServerConfig, path: Path) -> str:
        try:
            index = config.file_extensions.index(path.suffix.lower())
        except ValueError:
            return config.language_ids[0]
        return config.language_ids[min(index, len(config.language_ids) - 1)]

    def _normalize_lsp_location(
        self,
        value: object,
        root: Path,
    ) -> dict[str, object] | None:
        if not isinstance(value, Mapping):
            return None
        uri = str(value.get("uri") or value.get("targetUri") or "")
        range_value = value.get("range") or value.get("targetSelectionRange")
        path = _lsp_uri_path(uri)
        if path is None or not _is_within(path, root) or self._is_sensitive(path, root):
            return None
        if not isinstance(range_value, Mapping):
            return None
        return {
            "path": str(path),
            "relativePath": str(path.relative_to(root)),
            **_normalize_lsp_range(range_value),
        }

    def _normalize_lsp_symbol(
        self,
        value: object,
        root: Path,
        server: str,
    ) -> dict[str, object] | None:
        if not isinstance(value, Mapping):
            return None
        location = self._normalize_lsp_location(value.get("location"), root)
        if location is None:
            return None
        kind = _safe_lsp_int(value.get("kind"))
        return {
            "name": str(value.get("name") or "")[:500],
            "kind": _LSP_SYMBOL_KINDS.get(kind, "unknown"),
            "containerName": str(value.get("containerName") or "")[:500],
            "server": server,
            **location,
        }

    @staticmethod
    def _normalize_lsp_hover(value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            return {"content": "", "range": None, "truncated": False}
        contents = value.get("contents")
        if isinstance(contents, str):
            content = contents
        elif isinstance(contents, Mapping):
            content = str(contents.get("value") or contents.get("language") or "")
        elif isinstance(contents, list):
            parts = []
            for item in contents[:20]:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, Mapping):
                    parts.append(str(item.get("value") or ""))
            content = "\n\n".join(parts)
        else:
            content = ""
        range_value = value.get("range")
        return {
            "content": content[:16_384],
            "range": (
                _normalize_lsp_range(range_value)
                if isinstance(range_value, Mapping)
                else None
            ),
            "truncated": len(content) > 16_384,
        }

    @staticmethod
    def _normalize_lsp_diagnostic(
        value: Mapping[str, object],
        path: Path,
        root: Path,
    ) -> dict[str, object]:
        range_value = value.get("range")
        severity = _safe_lsp_int(value.get("severity"))
        return {
            "path": str(path),
            "relativePath": str(path.relative_to(root)),
            **(
                _normalize_lsp_range(range_value)
                if isinstance(range_value, Mapping)
                else {"line": 1, "column": 1, "endLine": 1, "endColumn": 1}
            ),
            "severity": _LSP_DIAGNOSTIC_SEVERITIES.get(severity, "unknown"),
            "message": str(value.get("message") or "")[:2_000],
            "source": str(value.get("source") or "")[:160],
            "code": str(value.get("code") or "")[:160],
        }

    def prepare_lsp_mutation(
        self,
        session: Mapping[str, object],
        operation: str,
        args: Mapping[str, object],
    ) -> PreparedWorkspaceLspMutation:
        if operation not in {"rename", "code_action_apply"}:
            raise WorkspaceLspError(
                "unsupported_operation",
                f"unsupported workspace_lsp mutation: {operation}",
            )
        target, root = self._lsp_source_path(session, args)
        config = self._lsp_config_for_file(root, target, requested=args.get("server"))
        timeout_seconds = _bounded_integer(
            args.get("timeoutMs"),
            default=8_000,
            minimum=100,
            maximum=20_000,
        ) / 1_000
        client = self._lsp_client(root, config, timeout_seconds)
        client.open_document(target, self._lsp_language_id(config, target))
        position = self._lsp_position(args)
        request: dict[str, object] = {
            "path": str(target),
            "line": position["line"] + 1,
            "column": position["character"] + 1,
            "server": config.name,
        }
        if operation == "rename":
            new_name = str(args.get("newName") or "").strip()
            if (
                not new_name
                or len(new_name) > 240
                or "\x00" in new_name
                or "\n" in new_name
                or "\r" in new_name
            ):
                raise WorkspaceLspError(
                    "invalid_request",
                    "newName must be 1-240 single-line characters",
                )
            request["newName"] = new_name
            workspace_edit = self._lsp_request(
                client,
                "textDocument/rename",
                {
                    "textDocument": {"uri": target.as_uri()},
                    "position": position,
                    "newName": new_name,
                },
                timeout_seconds,
            )
        else:
            title = str(args.get("title") or "").strip()
            if not title or len(title) > 500 or "\x00" in title:
                raise WorkspaceLspError(
                    "invalid_request",
                    "title is required for workspace_lsp code_action_apply",
                )
            request["title"] = title
            raw_actions = self._lsp_request(
                client,
                "textDocument/codeAction",
                {
                    "textDocument": {"uri": target.as_uri()},
                    "range": {"start": position, "end": position},
                    "context": {"diagnostics": []},
                },
                timeout_seconds,
            )
            matches = (
                [
                    item
                    for item in raw_actions
                    if isinstance(item, Mapping)
                    and str(item.get("title") or "") == title
                ]
                if isinstance(raw_actions, list)
                else []
            )
            if len(matches) != 1:
                raise WorkspaceLspError(
                    "code_action_not_unique",
                    f"workspace_lsp code action title matched {len(matches)} actions",
                )
            action = matches[0]
            if action.get("command") is not None:
                raise WorkspaceLspError(
                    "unsupported_workspace_edit",
                    "workspace_lsp refuses code actions that execute server commands",
                )
            workspace_edit = action.get("edit")
            if not isinstance(workspace_edit, Mapping):
                resolved = self._lsp_request(
                    client,
                    "codeAction/resolve",
                    action,
                    timeout_seconds,
                )
                if not isinstance(resolved, Mapping) or resolved.get("command") is not None:
                    raise WorkspaceLspError(
                        "unsupported_workspace_edit",
                        "workspace_lsp code action did not resolve to an edit-only action",
                    )
                workspace_edit = resolved.get("edit")
        return self._prepare_lsp_workspace_edit(
            operation=operation,
            root=root,
            server=config.name,
            request=request,
            workspace_edit=workspace_edit,
        )

    def _prepare_lsp_workspace_edit(
        self,
        *,
        operation: str,
        root: Path,
        server: str,
        request: Mapping[str, object],
        workspace_edit: object,
    ) -> PreparedWorkspaceLspMutation:
        if not isinstance(workspace_edit, Mapping):
            raise WorkspaceLspError(
                "empty_workspace_edit",
                "workspace_lsp returned no workspace edit",
            )
        edits_by_uri: dict[str, list[Mapping[str, object]]] = {}
        changes = workspace_edit.get("changes")
        if changes is not None and not isinstance(changes, Mapping):
            raise WorkspaceLspError(
                "unsupported_workspace_edit",
                "workspace_lsp returned malformed changes",
            )
        if isinstance(changes, Mapping):
            for uri, values in changes.items():
                if (
                    not isinstance(uri, str)
                    or not isinstance(values, list)
                    or not values
                    or any(not isinstance(item, Mapping) for item in values)
                ):
                    raise WorkspaceLspError(
                        "unsupported_workspace_edit",
                        "workspace_lsp returned malformed changes",
                    )
                edits_by_uri.setdefault(uri, []).extend(values)
        document_changes = workspace_edit.get("documentChanges")
        if document_changes is not None:
            if not isinstance(document_changes, list):
                raise WorkspaceLspError(
                    "unsupported_workspace_edit",
                    "workspace_lsp returned malformed documentChanges",
                )
            for change in document_changes:
                if not isinstance(change, Mapping) or "kind" in change:
                    raise WorkspaceLspError(
                        "unsupported_workspace_edit",
                        "workspace_lsp refuses create, rename, and delete file operations",
                    )
                document = change.get("textDocument")
                values = change.get("edits")
                if (
                    not isinstance(document, Mapping)
                    or not isinstance(values, list)
                    or not values
                    or any(not isinstance(item, Mapping) for item in values)
                ):
                    raise WorkspaceLspError(
                        "unsupported_workspace_edit",
                        "workspace_lsp returned malformed text document edits",
                    )
                uri = str(document.get("uri") or "")
                edits_by_uri.setdefault(uri, []).extend(values)
        if not edits_by_uri or len(edits_by_uri) > _LSP_MAX_FILES:
            raise WorkspaceLspError(
                "workspace_edit_out_of_bounds",
                f"workspace_lsp edit must affect between 1 and {_LSP_MAX_FILES} files",
            )
        files: list[PreparedWorkspaceLspFile] = []
        total_bytes = 0
        total_diff_bytes = 0
        for uri, edits in edits_by_uri.items():
            path = _lsp_uri_path(uri)
            if (
                path is None
                or not _is_within(path, root)
                or not path.exists()
                or path.is_symlink()
                or not path.is_file()
                or self._is_sensitive(path, root)
            ):
                raise WorkspaceLspError(
                    "path_not_allowed",
                    "workspace_lsp edit targets an unauthorized, sensitive, or symlink path",
                )
            raw = path.read_bytes()
            if len(raw) > 2 * 1024 * 1024 or b"\x00" in raw:
                raise WorkspaceLspError(
                    "workspace_edit_out_of_bounds",
                    "workspace_lsp only edits UTF-8 files up to 2 MiB",
                )
            try:
                before = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkspaceLspError(
                    "invalid_document",
                    "workspace_lsp only edits UTF-8 files",
                ) from exc
            after = _apply_lsp_text_edits(before, edits)
            after_raw = after.encode("utf-8")
            total_bytes += len(after_raw)
            if len(after_raw) > 2 * 1024 * 1024 or total_bytes > _LSP_MAX_TOTAL_WRITE_BYTES:
                raise WorkspaceLspError(
                    "workspace_edit_out_of_bounds",
                    "workspace_lsp edit exceeds the bounded output size",
                )
            diff = _reviewable_diff(before, after, str(path.relative_to(root)))
            total_diff_bytes += len(diff.encode("utf-8"))
            if total_diff_bytes > _LSP_MAX_DIFF_BYTES:
                raise WorkspaceLspError(
                    "workspace_edit_out_of_bounds",
                    "workspace_lsp diff is too large to review safely",
                )
            files.append(
                PreparedWorkspaceLspFile(
                    path=path,
                    preimage_sha256=hashlib.sha256(raw).hexdigest(),
                    preimage_size=len(raw),
                    postimage_sha256=hashlib.sha256(after_raw).hexdigest(),
                    postimage=after_raw,
                    mode=path.stat().st_mode & 0o777,
                    diff=diff,
                )
            )
        return PreparedWorkspaceLspMutation(
            operation=operation,
            root=root,
            server=server,
            request=dict(request),
            files=tuple(sorted(files, key=lambda item: str(item.path))),
        )

    def lsp_mutation_preview(
        self,
        prepared: PreparedWorkspaceLspMutation,
    ) -> dict[str, object]:
        action_label = "重命名符号" if prepared.operation == "rename" else "应用代码操作"
        return {
            "title": f"确认{action_label}",
            "summary": f"{action_label}将修改 {len(prepared.files)} 个工作区文件",
            "operationLabel": action_label,
            "changes": [
                {
                    "label": str(item.path.relative_to(prepared.root)),
                    "before": "",
                    "after": item.diff,
                }
                for item in prepared.files
            ],
            "actionPayload": {
                **dict(prepared.request),
                "files": [
                    {
                        "path": str(item.path),
                        "content": item.postimage.decode("utf-8"),
                    }
                    for item in prepared.files
                ],
            },
            "baseState": {
                "operation": prepared.operation,
                "workspaceRoot": str(prepared.root),
                "workspaceRootSha256": prepared.root_digest,
                "server": prepared.server,
                "files": [
                    {
                        "path": str(item.path),
                        "preimageSha256": item.preimage_sha256,
                        "preimageSize": item.preimage_size,
                        "postimageSha256": item.postimage_sha256,
                    }
                    for item in prepared.files
                ],
            },
        }

    def apply_lsp_mutation(
        self,
        session: Mapping[str, object],
        operation: str,
        action_payload: Mapping[str, object],
        base_state: Mapping[str, object],
    ) -> dict[str, object]:
        if operation not in {"rename", "code_action_apply"}:
            raise WorkspaceLspError("unsupported_operation", "unsupported workspace_lsp mutation")
        if str(base_state.get("operation") or "") != operation:
            raise WorkspaceLspError(
                "invalid_approval",
                "workspace_lsp approval operation no longer matches its preview",
            )
        roots = self._session_roots(session)
        try:
            root = Path(str(base_state.get("workspaceRoot") or "")).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceLspError(
                "stale_snapshot",
                "workspace_lsp authorized root changed after approval preview",
            ) from exc
        expected_root_hash = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
        if (
            root not in roots
            or expected_root_hash != str(base_state.get("workspaceRootSha256") or "")
        ):
            raise WorkspaceLspError(
                "stale_snapshot",
                "workspace_lsp authorized root changed after approval preview",
            )
        payload_files = action_payload.get("files")
        state_files = base_state.get("files")
        if (
            not isinstance(payload_files, list)
            or not isinstance(state_files, list)
            or not 1 <= len(payload_files) <= _LSP_MAX_FILES
            or len(payload_files) != len(state_files)
        ):
            raise WorkspaceLspError(
                "invalid_approval",
                "workspace_lsp approval contains invalid file state",
            )
        prepared: list[tuple[Path, bytes, bytes, int, str, str]] = []
        total_bytes = 0
        for payload_item, state_item in zip(payload_files, state_files, strict=True):
            if not isinstance(payload_item, Mapping) or not isinstance(state_item, Mapping):
                raise WorkspaceLspError("invalid_approval", "workspace_lsp approval is malformed")
            if str(payload_item.get("path") or "") != str(state_item.get("path") or ""):
                raise WorkspaceLspError("invalid_approval", "workspace_lsp approval paths disagree")
            target, selected_root = self._resolve_existing_path(
                roots,
                str(payload_item.get("path") or ""),
                allow_directory=False,
            )
            if (
                selected_root != root
                or target.is_symlink()
                or not target.is_file()
                or self._is_sensitive(target, root)
            ):
                raise WorkspaceLspError(
                    "path_not_allowed",
                    "workspace_lsp approved path is no longer allowed",
                )
            content = payload_item.get("content")
            if not isinstance(content, str) or "\x00" in content:
                raise WorkspaceLspError("invalid_approval", "workspace_lsp content is invalid")
            postimage = content.encode("utf-8")
            total_bytes += len(postimage)
            if total_bytes > _LSP_MAX_TOTAL_WRITE_BYTES:
                raise WorkspaceLspError(
                    "workspace_edit_out_of_bounds",
                    "workspace_lsp approved output exceeds its size bound",
                )
            preimage = target.read_bytes()
            pre_hash = hashlib.sha256(preimage).hexdigest()
            post_hash = hashlib.sha256(postimage).hexdigest()
            expected_pre = str(state_item.get("preimageSha256") or "")
            expected_post = str(state_item.get("postimageSha256") or "")
            if pre_hash != expected_pre:
                raise WorkspaceLspError(
                    "stale_snapshot",
                    "workspace_lsp file changed after approval preview",
                )
            if post_hash != expected_post:
                raise WorkspaceLspError(
                    "invalid_approval",
                    "workspace_lsp approved output no longer matches its preview",
                )
            prepared.append(
                (
                    target,
                    preimage,
                    postimage,
                    target.stat().st_mode & 0o777,
                    pre_hash,
                    post_hash,
                )
            )
        staged: list[tuple[Path, Path]] = []
        applied: list[tuple[Path, bytes, int]] = []
        try:
            for target, _, postimage, mode, _, _ in prepared:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{target.name}.lsp.",
                    dir=target.parent,
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    handle.write(postimage)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, mode)
                staged.append((target, temporary))
            for index, (target, temporary) in enumerate(staged):
                current = target.read_bytes()
                if target.is_symlink() or hashlib.sha256(current).hexdigest() != prepared[index][4]:
                    raise WorkspaceLspError(
                        "stale_snapshot",
                        "workspace_lsp file changed immediately before atomic write",
                    )
                os.replace(temporary, target)
                applied.append((target, prepared[index][1], prepared[index][3]))
        except Exception:
            for target, preimage, mode in reversed(applied):
                self._atomic_write(target, preimage, mode)
            raise
        finally:
            for _, temporary in staged:
                temporary.unlink(missing_ok=True)
        return _validated_lsp(
            {
                "schemaVersion": "rag-ime.workspace-lsp-mutation-receipt.v1",
                "mutationApplied": True,
                "summary": f"workspace_lsp 已修改 {len(prepared)} 个文件",
                "operation": operation,
                "root": str(root),
                "server": str(base_state.get("server") or ""),
                "changedFiles": [
                    {
                        "path": str(target),
                        "preimageSha256": pre_hash,
                        "postimageSha256": post_hash,
                    }
                    for target, _, _, _, pre_hash, post_hash in prepared
                ],
                "undoAvailable": False,
            },
            "workspace-lsp-mutation-receipt.v1.json",
        )

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
        preimage_sha256 = hashlib.sha256(raw).hexdigest()
        occurrence_spans: list[tuple[int, int]] = []
        search_from = 0
        for _ in range(actual):
            start = before.find(old_text, search_from)
            occurrence_spans.append((start, start + len(old_text)))
            search_from = start + len(old_text)
        read_origin = _validated_workspace_read_origin(
            args.get("readOrigin"),
            preimage_sha256=preimage_sha256,
            text=before,
            anchor_spans=occurrence_spans,
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
            preimage_sha256=preimage_sha256,
            preimage_size=len(raw),
            postimage_sha256=hashlib.sha256(after_raw).hexdigest(),
            diff=diff,
            read_origin=read_origin,
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
                **(
                    {"readOrigin": prepared.read_origin.as_dict()}
                    if prepared.read_origin is not None
                    else {}
                ),
            },
        }

    def apply_patch(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
        base_state: Mapping[str, object],
    ) -> dict[str, object]:
        prepare_args = dict(args)
        if isinstance(base_state.get("readOrigin"), Mapping):
            prepare_args["readOrigin"] = base_state["readOrigin"]
        prepared = self.prepare_patch(session, prepare_args)
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
            "writeDiagnostics": self._write_diagnostics(session, prepared.path),
            "replacementCount": prepared.expected_occurrences,
            "undoAvailable": False,
        }

    def prepare_edit(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> PreparedWorkspaceEdit:
        roots = self._session_roots(session)
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise WorkspaceHarnessError("path is required for workspace_edit")
        target, root = self._resolve_existing_path(roots, raw_path, allow_directory=False)
        if self._is_sensitive(target, root) or target.is_symlink() or not target.is_file():
            raise WorkspaceHarnessError("workspace_edit requires a non-sensitive regular file")
        edits_value = args.get("edits")
        if not isinstance(edits_value, list) or not 1 <= len(edits_value) <= 64:
            raise WorkspaceHarnessError("edits must contain between 1 and 64 replacements")
        edits: list[tuple[str, str]] = []
        for index, value in enumerate(edits_value):
            if not isinstance(value, Mapping):
                raise WorkspaceHarnessError(f"edits[{index}] must be an object")
            old_text = value.get("oldText")
            new_text = value.get("newText")
            if (
                not isinstance(old_text, str)
                or not old_text
                or len(old_text) > 65_536
                or "\x00" in old_text
            ):
                raise WorkspaceHarnessError(
                    f"edits[{index}].oldText must be 1-65536 UTF-8 characters"
                )
            if (
                not isinstance(new_text, str)
                or len(new_text) > 131_072
                or "\x00" in new_text
            ):
                raise WorkspaceHarnessError(
                    f"edits[{index}].newText must be at most 131072 UTF-8 characters"
                )
            edits.append((old_text, new_text))
        raw = target.read_bytes()
        if len(raw) > 2 * 1024 * 1024 or b"\x00" in raw:
            raise WorkspaceHarnessError("workspace_edit only accepts UTF-8 files up to 2 MiB")
        try:
            before = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceHarnessError("workspace_edit only accepts UTF-8 text") from exc
        preimage_sha256 = hashlib.sha256(raw).hexdigest()
        expected_revision = _required_workspace_resource_revision(
            args.get("resourceRevision"),
            operation="workspace_edit",
        )
        actual_revision = _workspace_resource_revision_from_sha256(preimage_sha256)
        if expected_revision != actual_revision:
            raise WorkspaceSnapshotError(
                "stale_snapshot",
                "workspace_edit snapshot is stale; read the file again before editing",
                retryable=True,
            )
        replacements: list[tuple[int, int, str]] = []
        for index, (old_text, new_text) in enumerate(edits):
            occurrences = before.count(old_text)
            if occurrences != 1:
                raise WorkspaceHarnessError(
                    f"edits[{index}].oldText must match exactly once in the original file; "
                    f"found {occurrences}"
                )
            start = before.index(old_text)
            replacements.append((start, start + len(old_text), new_text))
        ordered = sorted(replacements)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current[0] < previous[1]:
                raise WorkspaceHarnessError("workspace_edit replacements may not overlap")
        read_origin = _validated_workspace_read_origin(
            args.get("readOrigin"),
            preimage_sha256=preimage_sha256,
            text=before,
            anchor_spans=[(start, end) for start, end, _ in ordered],
        )
        after = before
        for start, end, new_text in reversed(ordered):
            after = f"{after[:start]}{new_text}{after[end:]}"
        after_raw = after.encode("utf-8")
        if len(after_raw) > 2 * 1024 * 1024:
            raise WorkspaceHarnessError("edited file would exceed 2 MiB")
        relative = str(target.relative_to(root))
        diff = _reviewable_diff(before, after, relative)
        return PreparedWorkspaceEdit(
            path=target,
            root=root,
            edits=tuple(edits),
            preimage_sha256=preimage_sha256,
            preimage_size=len(raw),
            postimage_sha256=hashlib.sha256(after_raw).hexdigest(),
            postimage=after_raw,
            diff=diff,
            read_origin=read_origin,
        )

    def edit_preview(self, prepared: PreparedWorkspaceEdit) -> dict[str, object]:
        return {
            "title": "确认修改工作区文件",
            "summary": f"将对 {prepared.path.name} 应用 {len(prepared.edits)} 处精确修改",
            "operationLabel": "应用精确文件修改",
            "changes": [
                {"label": "文件", "before": str(prepared.path), "after": str(prepared.path)},
                {"label": "修改块", "before": str(len(prepared.edits)), "after": "已替换"},
                {"label": "差异", "before": "", "after": prepared.diff},
            ],
            "actionPayload": {
                "path": str(prepared.path),
                "resourceRevision": prepared.resource_revision,
                "edits": [
                    {"oldText": old_text, "newText": new_text}
                    for old_text, new_text in prepared.edits
                ],
            },
            "baseState": {
                "preimageSha256": prepared.preimage_sha256,
                "preimageSize": prepared.preimage_size,
                "postimageSha256": prepared.postimage_sha256,
                "workspaceRootSha256": prepared.roots_digest,
                **(
                    {"readOrigin": prepared.read_origin.as_dict()}
                    if prepared.read_origin is not None
                    else {}
                ),
            },
        }

    def apply_edit(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
        base_state: Mapping[str, object],
    ) -> dict[str, object]:
        prepare_args = dict(args)
        if isinstance(base_state.get("readOrigin"), Mapping):
            prepare_args["readOrigin"] = base_state["readOrigin"]
        prepared = self.prepare_edit(session, prepare_args)
        self._verify_text_mutation(prepared, base_state, operation="edit")
        current_raw = prepared.path.read_bytes()
        if hashlib.sha256(current_raw).hexdigest() != prepared.preimage_sha256:
            raise WorkspaceHarnessError("workspace file changed immediately before atomic edit")
        self._atomic_write(prepared.path, prepared.postimage, prepared.path.stat().st_mode & 0o777)
        return {
            "schemaVersion": "rag-ime.workspace-edit-receipt.v1",
            "mutationApplied": True,
            "summary": f"已修改 {prepared.path.name} 的 {len(prepared.edits)} 处内容",
            "path": str(prepared.path),
            "preimageSha256": prepared.preimage_sha256,
            "postimageSha256": prepared.postimage_sha256,
            "writeDiagnostics": self._write_diagnostics(session, prepared.path),
            "replacementCount": len(prepared.edits),
            "undoAvailable": False,
        }

    def prepare_write(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> PreparedWorkspaceWrite:
        roots = self._session_roots(session)
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            raise WorkspaceHarnessError("path is required for workspace_write")
        content = args.get("content")
        if not isinstance(content, str) or "\x00" in content:
            raise WorkspaceHarnessError("content must be UTF-8 text")
        postimage = content.encode("utf-8")
        if len(postimage) > 2 * 1024 * 1024:
            raise WorkspaceHarnessError("workspace_write content may not exceed 2 MiB")
        target, root = self._resolve_write_path(roots, raw_path)
        if self._is_sensitive(target, root) or target.is_symlink() or target.is_dir():
            raise WorkspaceHarnessError("workspace_write requires a non-sensitive file path")
        existed_before = target.exists()
        before_raw = target.read_bytes() if existed_before else b""
        preimage_sha256 = hashlib.sha256(before_raw).hexdigest()
        expected_revision = _required_workspace_resource_revision(
            args.get("resourceRevision"),
            operation="workspace_write",
            allow_missing=True,
        )
        actual_revision = (
            _workspace_resource_revision_from_sha256(preimage_sha256)
            if existed_before
            else "missing"
        )
        if expected_revision != actual_revision:
            raise WorkspaceSnapshotError(
                "stale_snapshot",
                "workspace_write snapshot is stale; read the existing file again "
                "or use resourceRevision='missing' only for a path that does not exist",
                retryable=True,
            )
        if len(before_raw) > 2 * 1024 * 1024 or b"\x00" in before_raw:
            raise WorkspaceHarnessError("workspace_write only overwrites UTF-8 files up to 2 MiB")
        try:
            before = before_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceHarnessError("workspace_write only overwrites UTF-8 text") from exc
        relative = str(target.relative_to(root))
        diff = _reviewable_diff(before, content, relative, new_file=not existed_before)
        return PreparedWorkspaceWrite(
            path=target,
            root=root,
            content=content,
            existed_before=existed_before,
            preimage_sha256=preimage_sha256,
            preimage_size=len(before_raw),
            postimage_sha256=hashlib.sha256(postimage).hexdigest(),
            postimage=postimage,
            diff=diff,
            work_document=(
                dict(args["workDocument"])
                if isinstance(args.get("workDocument"), Mapping)
                else None
            ),
        )

    def write_preview(self, prepared: PreparedWorkspaceWrite) -> dict[str, object]:
        action = "覆盖" if prepared.existed_before else "创建"
        return {
            "title": f"确认{action}工作区文件",
            "summary": f"将{action} {prepared.path.name}",
            "operationLabel": f"{action}文件",
            "changes": [
                {
                    "label": "文件",
                    "before": str(prepared.path) if prepared.existed_before else "不存在",
                    "after": str(prepared.path),
                },
                {"label": "差异", "before": "", "after": prepared.diff},
            ],
            "actionPayload": {
                "path": str(prepared.path),
                "resourceRevision": prepared.resource_revision,
                "content": prepared.content,
                **(
                    {"workDocument": dict(prepared.work_document)}
                    if prepared.work_document is not None
                    else {}
                ),
            },
            "baseState": {
                "existedBefore": prepared.existed_before,
                "preimageSha256": prepared.preimage_sha256,
                "preimageSize": prepared.preimage_size,
                "postimageSha256": prepared.postimage_sha256,
                "workspaceRootSha256": prepared.roots_digest,
            },
        }

    def apply_write(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
        base_state: Mapping[str, object],
    ) -> dict[str, object]:
        prepared = self.prepare_write(session, args)
        self._verify_text_mutation(prepared, base_state, operation="write")
        expected_existence = base_state.get("existedBefore") is True
        if prepared.existed_before != expected_existence:
            raise WorkspaceHarnessError("workspace file existence changed after approval preview")
        if prepared.path.exists():
            if prepared.path.is_symlink() or not prepared.path.is_file():
                raise WorkspaceHarnessError("workspace path changed before atomic write")
            current_raw = prepared.path.read_bytes()
            if hashlib.sha256(current_raw).hexdigest() != prepared.preimage_sha256:
                raise WorkspaceHarnessError("workspace file changed immediately before atomic write")
            mode = prepared.path.stat().st_mode & 0o777
        else:
            if prepared.existed_before:
                raise WorkspaceHarnessError("workspace file disappeared after approval preview")
            mode = 0o644
        prepared.path.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = prepared.path.parent.resolve(strict=True)
        if not _is_within(resolved_parent, prepared.root):
            raise WorkspaceHarnessError("workspace parent changed before atomic write")
        self._atomic_write(prepared.path, prepared.postimage, mode)
        return {
            "schemaVersion": "rag-ime.workspace-write-receipt.v1",
            "mutationApplied": True,
            "summary": (
                f"已覆盖 {prepared.path.name}"
                if prepared.existed_before
                else f"已创建 {prepared.path.name}"
            ),
            "path": str(prepared.path),
            "preimageSha256": prepared.preimage_sha256,
            "postimageSha256": prepared.postimage_sha256,
            "created": not prepared.existed_before,
            "writeDiagnostics": self._write_diagnostics(session, prepared.path),
            "undoAvailable": False,
        }

    def prepare_command(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> PreparedWorkspaceCommand:
        return self._prepare_command(
            session,
            args,
            tool_name="workspace_shell",
            default_timeout=30,
            maximum_timeout=120,
        )

    def prepare_background_command(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
    ) -> PreparedWorkspaceCommand:
        return self._prepare_command(
            session,
            args,
            tool_name="workspace_job",
            default_timeout=3_600,
            maximum_timeout=86_400,
        )

    def _prepare_command(
        self,
        session: Mapping[str, object],
        args: Mapping[str, object],
        *,
        tool_name: str,
        default_timeout: int,
        maximum_timeout: int,
    ) -> PreparedWorkspaceCommand:
        if str(session.get("mode") or "") != "coordinator":
            raise WorkspaceHarnessError("workspace commands require a coordinator session")
        roots = self._session_roots(session)
        repository_metadata_roots = _linked_worktree_metadata_roots(roots)
        model_arbitrated = (
            normalize_execution_mode(
                session.get("executionMode"),
                tool_profile_version=session.get("toolProfileVersion"),
            )
            == FULL_TRUST_EXECUTION_MODE
            and workspace_scope_is_granted(session)
        )
        command = str(args.get("command") or "").strip()
        if not command:
            raise WorkspaceHarnessError(f"command is required for {tool_name}")
        if len(command) > 2_000 or "\x00" in command or "\r" in command:
            raise WorkspaceHarnessError("workspace command is malformed or too long")
        if any(ord(character) < 32 and character not in "\n\t" for character in command):
            raise WorkspaceHarnessError("workspace command contains unsupported control characters")
        if _FORBIDDEN_COMMAND.search(command):
            raise WorkspaceHarnessError("this system or privilege command is not available")
        if any(pattern.search(command) for pattern in _CATASTROPHIC_COMMANDS):
            raise WorkspaceHarnessError(
                "catastrophic database or filesystem destruction is not available"
            )
        if (
            _NETWORK_DESTINATION.search(command)
            and _SENSITIVE_EGRESS_PATH.search(command)
        ):
            raise WorkspaceHarnessError(
                "sending sensitive workspace data to a network destination is not available"
            )
        if (
            any(pattern.search(command) for pattern in _DESTRUCTIVE_COMMANDS)
            and not model_arbitrated
        ):
            raise WorkspaceHarnessError("destructive commands require full-automation model arbitration")
        if _SECRET_COMMAND.search(command):
            raise WorkspaceHarnessError("commands containing secret-like values are not accepted")
        if _SENSITIVE_COMMAND_PATH.search(command):
            raise WorkspaceHarnessError(
                "commands naming sensitive files are not available"
            )
        if re.search(r"(?<!&)&(?!&)", command):
            raise WorkspaceHarnessError("background shell syntax is not accepted; use workspace_job")

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
        timeout = _bounded_integer(
            args.get("timeoutSeconds"),
            default=default_timeout,
            minimum=1,
            maximum=maximum_timeout,
        )
        return PreparedWorkspaceCommand(
            command=command,
            cwd=cwd,
            roots=roots,
            repository_metadata_roots=repository_metadata_roots,
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

    def _resolve_write_path(
        self,
        roots: Sequence[Path],
        raw_path: str,
    ) -> tuple[Path, Path]:
        requested = Path(raw_path).expanduser()
        candidates = [requested] if requested.is_absolute() else [root / requested for root in roots]
        for candidate in candidates:
            if candidate.name in {"", ".", ".."}:
                continue
            if candidate.exists() or candidate.is_symlink():
                if candidate.is_symlink():
                    raise WorkspaceHarnessError("workspace_write cannot target a symlink")
                try:
                    resolved = candidate.resolve(strict=True)
                except (OSError, RuntimeError):
                    continue
                for root in roots:
                    if _is_within(resolved, root):
                        return resolved, root
                continue
            ancestor = candidate.parent
            missing_parts = [candidate.name]
            while not ancestor.exists() and ancestor != ancestor.parent:
                missing_parts.append(ancestor.name)
                ancestor = ancestor.parent
            try:
                resolved_ancestor = ancestor.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            target = resolved_ancestor.joinpath(*reversed(missing_parts))
            for root in roots:
                if _is_within(target, root):
                    return target, root
        raise WorkspaceHarnessError("path is outside the authorized workspace")

    def _verify_text_mutation(
        self,
        prepared: PreparedWorkspaceEdit | PreparedWorkspaceWrite,
        base_state: Mapping[str, object],
        *,
        operation: str,
    ) -> None:
        if prepared.roots_digest != str(base_state.get("workspaceRootSha256") or ""):
            raise WorkspaceHarnessError("authorized workspace changed after approval preview")
        if prepared.preimage_sha256 != str(base_state.get("preimageSha256") or ""):
            raise WorkspaceHarnessError(f"workspace {operation} preimage changed after approval preview")
        if prepared.postimage_sha256 != str(base_state.get("postimageSha256") or ""):
            raise WorkspaceHarnessError(f"workspace {operation} no longer matches approval preview")

    def _write_diagnostics(
        self,
        session: Mapping[str, object],
        path: Path,
    ) -> dict[str, object]:
        try:
            result = self.lsp_read(
                session,
                "diagnostics",
                {"path": str(path), "timeoutMs": 2_000},
            )
        except WorkspaceLspError as exc:
            unavailable = exc.code in {"no_server_configured", "server_unavailable"}
            return {
                "schemaVersion": "rag-ime.workspace-write-diagnostics.v1",
                "state": "unavailable" if unavailable else "degraded",
                "summary": (
                    "该文件没有可用的语言服务诊断"
                    if unavailable
                    else "文件已写入，但语言服务诊断失败"
                ),
                "errorCode": exc.code,
                "error": str(exc)[:500],
                "items": [],
            }
        raw_items = result.get("items")
        items = list(raw_items[:50]) if isinstance(raw_items, list) else []
        return {
            "schemaVersion": "rag-ime.workspace-write-diagnostics.v1",
            "state": "issues" if items else "clean",
            "summary": f"写入后发现 {len(items)} 条语言服务诊断" if items else "写入后未发现语言服务诊断",
            "server": str(result.get("server") or ""),
            "items": items,
            "truncated": bool(result.get("truncated")) or (
                isinstance(raw_items, list) and len(raw_items) > len(items)
            ),
        }

    @staticmethod
    def _atomic_write(path: Path, content: bytes, mode: int) -> None:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

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

    def spawn_background(
        self,
        prepared: PreparedWorkspaceCommand,
    ) -> SpawnedWorkspaceCommand:
        return self._spawn_sandboxed(prepared)

    @staticmethod
    def terminate_background(launched: SpawnedWorkspaceCommand) -> None:
        WorkspaceHarness._terminate_group(launched.process)

    @staticmethod
    def redact_output(text: str) -> str:
        redacted = text
        for pattern, replacement in _OUTPUT_REDACTIONS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    def _run_sandboxed(self, prepared: PreparedWorkspaceCommand) -> dict[str, object]:
        started_at_ms = int(time.time() * 1_000)
        launched = self._spawn_sandboxed(prepared)
        process = launched.process
        try:
            output, timed_out, output_limited = self._bounded_output(
                process,
                prepared.timeout_seconds,
            )
            exit_code = process.poll()
            if exit_code is None:
                self._terminate_group(process)
                exit_code = process.wait(timeout=2)
            else:
                # A shell may otherwise leave an approved background descendant.
                self._terminate_group(process)
            if process.stdout is not None:
                process.stdout.close()
        finally:
            launched.cleanup()
        duration_ms = max(0, int(time.time() * 1_000) - started_at_ms)
        decoded = self.redact_output(output.decode("utf-8", errors="replace"))
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

    def _spawn_sandboxed(
        self,
        prepared: PreparedWorkspaceCommand,
    ) -> SpawnedWorkspaceCommand:
        sandbox = self.sandbox_executable
        if not sandbox.is_file() or not os.access(sandbox, os.X_OK):
            raise WorkspaceHarnessError("macOS command harness is unavailable; refusing unsandboxed execution")
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="rag-ime-agent-command-",
        )
        try:
            temporary = Path(temporary_directory.name).resolve(strict=True)
            profile = _sandbox_profile(
                roots=prepared.sandbox_roots,
                temporary=temporary,
                allow_network=prepared.allow_network,
            )
            environment = {
                "HOME": str(temporary),
                "TMPDIR": str(temporary),
                "PATH": _workspace_command_path(),
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
        except Exception:
            temporary_directory.cleanup()
            raise
        return SpawnedWorkspaceCommand(
            process=process,
            temporary_directory=temporary_directory,
        )

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


def _validated_lsp(
    payload: dict[str, object],
    contract: str,
) -> dict[str, object]:
    validate_contract(payload, contract)
    return payload


def _safe_lsp_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_lsp_range(value: Mapping[str, object]) -> dict[str, int]:
    start = value.get("start")
    end = value.get("end")
    start_value = start if isinstance(start, Mapping) else {}
    end_value = end if isinstance(end, Mapping) else start_value
    return {
        "line": max(0, _safe_lsp_int(start_value.get("line"))) + 1,
        "column": max(0, _safe_lsp_int(start_value.get("character"))) + 1,
        "endLine": max(0, _safe_lsp_int(end_value.get("line"))) + 1,
        "endColumn": max(0, _safe_lsp_int(end_value.get("character"))) + 1,
    }


def _lsp_uri_path(uri: str) -> Path | None:
    try:
        parsed = urlparse(uri)
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
            return None
        return Path(unquote(parsed.path)).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None


def _lsp_text_offset(text: str, position: Mapping[str, object]) -> int:
    line_number = _safe_lsp_int(position.get("line"))
    character = _safe_lsp_int(position.get("character"))
    if line_number < 0 or character < 0:
        raise WorkspaceLspError("invalid_workspace_edit", "workspace_lsp edit has a negative position")
    lines = text.splitlines(keepends=True) or [""]
    if line_number >= len(lines):
        if line_number == len(lines) and text.endswith(("\n", "\r")) and character == 0:
            return len(text)
        raise WorkspaceLspError("invalid_workspace_edit", "workspace_lsp edit line is out of bounds")
    content = lines[line_number].rstrip("\r\n")
    consumed_units = 0
    offset_in_line = 0
    for scalar in content:
        if consumed_units == character:
            break
        width = len(scalar.encode("utf-16-le")) // 2
        if consumed_units + width > character:
            raise WorkspaceLspError(
                "invalid_workspace_edit",
                "workspace_lsp edit splits a UTF-16 character",
            )
        consumed_units += width
        offset_in_line += 1
    if consumed_units != character:
        if character == len(content.encode("utf-16-le")) // 2:
            offset_in_line = len(content)
        else:
            raise WorkspaceLspError(
                "invalid_workspace_edit",
                "workspace_lsp edit column is out of bounds",
            )
    return sum(len(value) for value in lines[:line_number]) + offset_in_line


def _apply_lsp_text_edits(
    text: str,
    edits: Sequence[Mapping[str, object]],
) -> str:
    replacements: list[tuple[int, int, str]] = []
    for edit in edits:
        range_value = edit.get("range")
        new_text = edit.get("newText")
        if not isinstance(range_value, Mapping) or not isinstance(new_text, str):
            raise WorkspaceLspError(
                "invalid_workspace_edit",
                "workspace_lsp returned a malformed text edit",
            )
        start = range_value.get("start")
        end = range_value.get("end")
        if not isinstance(start, Mapping) or not isinstance(end, Mapping):
            raise WorkspaceLspError(
                "invalid_workspace_edit",
                "workspace_lsp returned a malformed edit range",
            )
        start_offset = _lsp_text_offset(text, start)
        end_offset = _lsp_text_offset(text, end)
        if end_offset < start_offset:
            raise WorkspaceLspError(
                "invalid_workspace_edit",
                "workspace_lsp returned a reversed edit range",
            )
        replacements.append((start_offset, end_offset, new_text))
    replacements.sort()
    for previous, current in zip(replacements, replacements[1:], strict=False):
        if current[0] < previous[1] or (
            current[0] == previous[0] and current[1] == previous[1]
        ):
            raise WorkspaceLspError(
                "invalid_workspace_edit",
                "workspace_lsp returned overlapping text edits",
            )
    result = text
    for start, end, new_text in reversed(replacements):
        result = f"{result[:start]}{new_text}{result[end:]}"
    return result


def _lsp_sandbox_profile(*, root: Path, temporary: Path) -> str:
    """Read-only workspace profile for a root-scoped language server."""

    escaped_root = _profile_escape(str(root))
    escaped_temporary = _profile_escape(str(temporary))
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
        f'(allow file-read* (subpath "{escaped_root}"))',
        f'(allow file-read* (subpath "{escaped_temporary}"))',
        f'(allow file-write* (subpath "{escaped_temporary}"))',
    ]
    for pattern in (
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
        r"/\.(git|ssh|gnupg|aws|azure|keychain)(/|$)",
    ):
        lines.append(f'(deny file-read* (regex #"{pattern}"))')
        lines.append(f'(deny file-write* (regex #"{pattern}"))')
    return "\n".join(lines)


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


def _parse_workspace_read_selector(
    raw_selector: str,
) -> tuple[str, tuple[tuple[int, int], ...], bool]:
    selector = raw_selector.strip()
    if not selector or len(selector) > 500 or any(
        character in selector for character in ("\x00", "\n", "\r")
    ):
        raise WorkspaceHarnessError(
            "workspace_read selector must be 1-500 single-line characters"
        )
    raw_mode = False
    if selector == "raw":
        selector = "1-"
        raw_mode = True
    elif selector.startswith("raw:"):
        selector = selector[4:]
        raw_mode = True
    elif selector.endswith(":raw"):
        selector = selector[:-4]
        raw_mode = True
    if selector == "conflicts":
        return "conflicts", (), raw_mode
    parsed: list[tuple[int, int]] = []
    for part in selector.split(","):
        match = re.fullmatch(r"([1-9]\d*)(?:(-)([1-9]\d*)?|(\+)([1-9]\d*))?", part.strip())
        if match is None:
            raise WorkspaceHarnessError(
                "workspace_read selector must use N, N-M, N-, N+COUNT, comma-separated "
                "ranges, raw, or conflicts"
            )
        start = int(match.group(1))
        if match.group(4):
            end = start + int(match.group(5)) - 1
        elif match.group(2):
            end = int(match.group(3)) if match.group(3) else 50_000_000
        else:
            end = start
        if end < start or end > 50_000_000:
            raise WorkspaceHarnessError("workspace_read selector range is invalid")
        parsed.append((start, end))
    if len(parsed) > 100:
        raise WorkspaceHarnessError("workspace_read selector accepts at most 100 ranges")
    merged: list[tuple[int, int]] = []
    for start, end in sorted(parsed):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return "ranges", tuple(merged), raw_mode


def _decode_workspace_read_prefix(
    raw: bytes,
    *,
    allow_trailing_partial: bool,
    offset: int,
) -> str:
    """Decode the largest valid UTF-8 prefix without splitting a code point."""

    if not raw:
        return ""
    for trim in range(4):
        candidate = raw[: len(raw) - trim] if trim else raw
        try:
            return candidate.decode("utf-8")
        except UnicodeDecodeError as exc:
            starts_mid_character = (
                exc.start == 0
                and candidate
                and 0x80 <= candidate[0] <= 0xBF
            )
            if starts_mid_character:
                raise WorkspaceHarnessError(
                    f"workspace_read offset {offset} is not on a UTF-8 character boundary"
                ) from exc
            trailing_partial = (
                allow_trailing_partial
                and exc.reason == "unexpected end of data"
                and exc.end == len(candidate)
            )
            if not trailing_partial:
                raise WorkspaceHarnessError(
                    "workspace_read only accepts UTF-8 text"
                ) from exc
    return ""


def _limit_workspace_read_lines(text: str) -> tuple[str, bool]:
    """Apply Pi's 2,000-line result bound while preserving byte continuity."""

    search_from = 0
    cut = -1
    for _ in range(_PI_READ_MAX_LINES):
        cut = text.find("\n", search_from)
        if cut < 0:
            return text, False
        search_from = cut + 1
    if search_from >= len(text):
        return text, False
    return text[:search_from], True


def _utf8_codepoint_width(first_byte: int) -> int:
    if first_byte < 0x80:
        return 1
    if 0xC2 <= first_byte <= 0xDF:
        return 2
    if 0xE0 <= first_byte <= 0xEF:
        return 3
    if 0xF0 <= first_byte <= 0xF4:
        return 4
    return 1


def _workspace_resource_revision_from_sha256(sha256: str) -> str:
    return f"sha256:{sha256}"


def _required_workspace_resource_revision(
    value: object,
    *,
    operation: str,
    allow_missing: bool = False,
) -> str:
    revision = str(value or "").strip().lower()
    if allow_missing and revision == "missing":
        return revision
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", revision):
        expected = "a read resourceRevision or 'missing'" if allow_missing else "a read resourceRevision"
        raise WorkspaceSnapshotError(
            "snapshot_required",
            f"{operation} requires {expected}; read the file immediately before writing",
            retryable=True,
        )
    return revision


def _validated_workspace_read_origin(
    value: object,
    *,
    preimage_sha256: str,
    text: str,
    anchor_spans: Sequence[tuple[int, int]],
) -> WorkspaceReadOriginProof | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise WorkspaceHarnessError("readOrigin must be an object")
    sha256 = str(value.get("sha256") or "")
    if sha256 != preimage_sha256:
        raise WorkspaceHarnessError("readOrigin does not match the current file")
    raw_ranges = value.get("displayedRanges")
    if not isinstance(raw_ranges, list) or not 1 <= len(raw_ranges) <= 64:
        raise WorkspaceHarnessError("readOrigin displayedRanges must contain 1-64 ranges")
    ranges: list[tuple[int, int]] = []
    for item in raw_ranges:
        if not isinstance(item, Mapping):
            raise WorkspaceHarnessError("readOrigin displayedRanges are malformed")
        start = item.get("startLine")
        end = item.get("endLine")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 1
            or end < start
        ):
            raise WorkspaceHarnessError("readOrigin line range is invalid")
        ranges.append((start, end))
    for start_offset, end_offset in anchor_spans:
        start_line = text.count("\n", 0, start_offset) + 1
        end_line = text.count("\n", 0, max(start_offset, end_offset - 1)) + 1
        if any(
            not any(first <= line <= last for first, last in ranges)
            for line in range(start_line, end_line + 1)
        ):
            raise WorkspaceHarnessError(
                "workspace mutation anchor was not present in the displayed read ranges"
            )
    return WorkspaceReadOriginProof(
        sha256=sha256,
        displayed_ranges=tuple(ranges),
    )


def _bounded_workspace_read_result(
    *,
    target: Path,
    root: Path,
    offset: int,
    size: int,
    requested_limit: int,
    candidate: str,
    line_limited: bool,
    read_origin_sha256: str,
    start_line: int,
) -> dict[str, object]:
    """Keep the complete JSON Tool result inside Pi's 50 KiB result budget."""

    candidate_bytes = len(candidate.encode("utf-8"))

    def build(content: str) -> dict[str, object]:
        content_bytes = len(content.encode("utf-8"))
        next_offset = offset + content_bytes
        truncated = next_offset < size
        result_trimmed = content_bytes < candidate_bytes
        displayed_ranges = []
        if content:
            end_line = start_line + content.count("\n")
            if content.endswith("\n"):
                end_line -= 1
            displayed_ranges.append(
                {"startLine": start_line, "endLine": max(start_line, end_line)}
            )
        return {
            "summary": f"已读取 {target.name}",
            "path": str(target),
            "root": str(root),
            "offset": offset,
            "offsetUnit": "utf8_bytes",
            "byteSize": size,
            "requestedLimitBytes": requested_limit,
            "contentLimitBytes": _PI_TOOL_RESULT_MAX_BYTES,
            "lineLimit": _PI_READ_MAX_LINES,
            "modelResultLimitBytes": _PI_TOOL_RESULT_MAX_BYTES,
            "content": content,
            "contentChars": len(content),
            "contentBytes": content_bytes,
            "contentLines": _workspace_text_line_count(content),
            "truncated": truncated,
            "truncatedBy": (
                None
                if not truncated
                else "lines"
                if line_limited and not result_trimmed
                else "bytes"
            ),
            "modelResultBounded": result_trimmed,
            "nextOffset": next_offset,
            "resourceRevision": _workspace_resource_revision_from_sha256(read_origin_sha256),
            "readOrigin": {
                "sha256": read_origin_sha256,
                "displayedRanges": displayed_ranges,
            },
        }

    result = build(candidate)
    if _compact_json_size(result) <= _PI_TOOL_RESULT_MAX_BYTES:
        return result

    low = 0
    high = len(candidate)
    best = build("")
    while low <= high:
        middle = (low + high) // 2
        trial = build(candidate[:middle])
        if _compact_json_size(trial) <= _PI_TOOL_RESULT_MAX_BYTES:
            best = trial
            low = middle + 1
        else:
            high = middle - 1
    return best


def _workspace_text_line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _compact_json_size(value: Mapping[str, object]) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _reviewable_diff(
    before: str,
    after: str,
    relative_path: str,
    *,
    new_file: bool = False,
) -> str:
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="/dev/null" if new_file else f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            n=3,
        )
    )
    if len(diff.encode("utf-8")) > 131_072:
        raise WorkspaceHarnessError("workspace mutation diff is too large to review safely")
    return diff


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
