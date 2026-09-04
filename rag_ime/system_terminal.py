"""Process-owned local PTY sessions for the PAWOS Terminal app.

The Terminal surface is a system app, not an Agent prompt adapter.  This
service therefore owns the operating-system PTY and exposes a small cursor
based stream contract.  Pi may use its own governed process tools separately;
the two concerns deliberately do not share lifecycle state.
"""

from __future__ import annotations

import fcntl
import os
import signal
import struct
import subprocess
import termios
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock, Thread
from typing import Mapping


SCHEMA_VERSION = "rag-ime.system-terminal.v1"
DEFAULT_MAX_BUFFER_BYTES = 2 * 1024 * 1024


def _acquire_controlling_terminal() -> None:
    """Make stdin the child session's controlling terminal before exec."""

    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class SystemTerminalError(RuntimeError):
    """A stable, user-readable terminal contract failure."""


@dataclass
class _TerminalSession:
    terminal_id: str
    title: str
    cwd: str
    shell: str
    cols: int
    rows: int
    master_fd: int
    process: subprocess.Popen[bytes]
    created_at_ms: int
    buffer: bytearray = field(default_factory=bytearray)
    base_cursor: int = 0
    next_cursor: int = 0
    exit_code: int | None = None
    closed: bool = False
    lock: RLock = field(default_factory=RLock)


class SystemTerminalService:
    """Own real local shells and retain a bounded scrollback per terminal."""

    def __init__(
        self,
        *,
        default_cwd: str | Path | None = None,
        max_buffer_bytes: int = DEFAULT_MAX_BUFFER_BYTES,
    ) -> None:
        self.default_cwd = Path(default_cwd or Path.cwd()).expanduser().resolve(strict=False)
        self.max_buffer_bytes = max(64 * 1024, int(max_buffer_bytes))
        self._sessions: dict[str, _TerminalSession] = {}
        self._lock = RLock()
        self._closed = False

    def list(self) -> dict[str, object]:
        with self._lock:
            sessions = list(self._sessions.values())
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "items": [self._public(item) for item in sorted(sessions, key=lambda item: item.created_at_ms)],
        }

    def create(self, payload: Mapping[str, object]) -> dict[str, object]:
        with self._lock:
            if self._closed:
                raise SystemTerminalError("system terminal service is closed")
        cwd = self._cwd(payload.get("cwd"))
        shell = self._shell(payload.get("shell"))
        cols = self._dimension(payload.get("cols"), default=104, maximum=400)
        rows = self._dimension(payload.get("rows"), default=30, maximum=200)
        title = str(payload.get("title") or cwd.name or "Terminal").strip()[:120] or "Terminal"
        master_fd, slave_fd = os.openpty()
        try:
            self._set_size(master_fd, cols=cols, rows=rows)
            environment = {
                **os.environ,
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
            }
            process = subprocess.Popen(
                [shell, "-l"],
                cwd=str(cwd),
                env=environment,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=_acquire_controlling_terminal,
                close_fds=True,
            )
        except BaseException:
            try:
                os.close(master_fd)
            except OSError:
                pass
            raise
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        terminal = _TerminalSession(
            terminal_id=f"term_{uuid.uuid4().hex}",
            title=title,
            cwd=str(cwd),
            shell=shell,
            cols=cols,
            rows=rows,
            master_fd=master_fd,
            process=process,
            created_at_ms=int(time.time() * 1000),
        )
        with self._lock:
            if self._closed:
                self._terminate(terminal)
                raise SystemTerminalError("system terminal service is closed")
            self._sessions[terminal.terminal_id] = terminal
        Thread(
            target=self._read_loop,
            args=(terminal,),
            name=f"paw-terminal-{terminal.terminal_id[-8:]}",
            daemon=True,
        ).start()
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "terminal": self._public(terminal)}

    def read(self, payload: Mapping[str, object]) -> dict[str, object]:
        terminal = self._get(payload.get("terminalId"))
        requested = self._cursor(payload.get("cursor"))
        maximum = self._dimension(payload.get("maxBytes"), default=131_072, maximum=524_288)
        with terminal.lock:
            cursor = max(requested, terminal.base_cursor)
            offset = cursor - terminal.base_cursor
            available = bytes(terminal.buffer[offset : offset + maximum])
            next_cursor = cursor + len(available)
            return {
                "schemaVersion": SCHEMA_VERSION,
                "ok": True,
                "terminal": self._public_locked(terminal),
                "cursor": cursor,
                "nextCursor": next_cursor,
                "truncated": requested < terminal.base_cursor,
                "text": available.decode("utf-8", errors="replace"),
            }

    def write(self, payload: Mapping[str, object]) -> dict[str, object]:
        terminal = self._get(payload.get("terminalId"))
        text = str(payload.get("text") or "")
        if not text:
            raise SystemTerminalError("terminal text must not be empty")
        with terminal.lock:
            if terminal.closed or terminal.process.poll() is not None:
                raise SystemTerminalError("terminal is not running")
            try:
                written = os.write(terminal.master_fd, text.encode("utf-8"))
            except OSError as exc:
                raise SystemTerminalError("terminal input could not be written") from exc
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "writtenBytes": written}

    def resize(self, payload: Mapping[str, object]) -> dict[str, object]:
        terminal = self._get(payload.get("terminalId"))
        cols = self._dimension(payload.get("cols"), default=terminal.cols, maximum=400)
        rows = self._dimension(payload.get("rows"), default=terminal.rows, maximum=200)
        with terminal.lock:
            if terminal.closed:
                raise SystemTerminalError("terminal is closed")
            self._set_size(terminal.master_fd, cols=cols, rows=rows)
            terminal.cols = cols
            terminal.rows = rows
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "terminal": self._public(terminal)}

    def close_terminal(self, payload: Mapping[str, object]) -> dict[str, object]:
        terminal = self._get(payload.get("terminalId"))
        self._terminate(terminal)
        receipt = self._public(terminal)
        with self._lock:
            if self._sessions.get(terminal.terminal_id) is terminal:
                del self._sessions[terminal.terminal_id]
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "terminal": receipt}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            sessions = list(self._sessions.values())
        for terminal in sessions:
            self._terminate(terminal)

    def _read_loop(self, terminal: _TerminalSession) -> None:
        while True:
            try:
                chunk = os.read(terminal.master_fd, 65_536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            with terminal.lock:
                terminal.buffer.extend(chunk)
                terminal.next_cursor += len(chunk)
                overflow = len(terminal.buffer) - self.max_buffer_bytes
                if overflow > 0:
                    del terminal.buffer[:overflow]
                    terminal.base_cursor += overflow
        with terminal.lock:
            terminal.exit_code = terminal.process.poll()
            if terminal.exit_code is None:
                try:
                    terminal.exit_code = terminal.process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass

    def _terminate(self, terminal: _TerminalSession) -> None:
        with terminal.lock:
            if terminal.closed:
                return
            terminal.closed = True
            pid = terminal.process.pid
        if terminal.process.poll() is None:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    terminal.process.terminate()
                except ProcessLookupError:
                    pass
            try:
                terminal.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    terminal.process.kill()
                terminal.process.wait(timeout=0.5)
        with terminal.lock:
            terminal.exit_code = terminal.process.poll()
            try:
                os.close(terminal.master_fd)
            except OSError:
                pass

    def _get(self, raw_terminal_id: object) -> _TerminalSession:
        terminal_id = str(raw_terminal_id or "").strip()
        if not terminal_id:
            raise SystemTerminalError("terminalId is required")
        with self._lock:
            terminal = self._sessions.get(terminal_id)
        if terminal is None:
            raise SystemTerminalError("terminal session was not found")
        return terminal

    def _public(self, terminal: _TerminalSession) -> dict[str, object]:
        with terminal.lock:
            return self._public_locked(terminal)

    @staticmethod
    def _public_locked(terminal: _TerminalSession) -> dict[str, object]:
        exit_code = terminal.process.poll()
        if exit_code is not None:
            terminal.exit_code = exit_code
        status = "closed" if terminal.closed else "exited" if terminal.exit_code is not None else "running"
        return {
            "terminalId": terminal.terminal_id,
            "title": terminal.title,
            "cwd": terminal.cwd,
            "shell": terminal.shell,
            "pid": terminal.process.pid,
            "cols": terminal.cols,
            "rows": terminal.rows,
            "status": status,
            "exitCode": terminal.exit_code,
            "baseCursor": terminal.base_cursor,
            "nextCursor": terminal.next_cursor,
            "createdAtMs": terminal.created_at_ms,
        }

    def _cwd(self, raw: object) -> Path:
        value = str(raw or "").strip()
        path = Path(value).expanduser().resolve(strict=False) if value else self.default_cwd
        if not path.is_dir():
            raise SystemTerminalError("terminal working directory does not exist")
        return path

    @staticmethod
    def _shell(raw: object) -> str:
        shell = str(raw or os.environ.get("SHELL") or "/bin/zsh").strip()
        path = Path(shell).expanduser().resolve(strict=False)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise SystemTerminalError("terminal shell is not executable")
        return str(path)

    @staticmethod
    def _dimension(raw: object, *, default: int, maximum: int) -> int:
        if raw in (None, ""):
            return default
        try:
            value = int(str(raw))
        except (TypeError, ValueError) as exc:
            raise SystemTerminalError("terminal dimension must be an integer") from exc
        if value < 1 or value > maximum:
            raise SystemTerminalError(f"terminal dimension must be between 1 and {maximum}")
        return value

    @staticmethod
    def _cursor(raw: object) -> int:
        if raw in (None, ""):
            return 0
        try:
            value = int(str(raw))
        except (TypeError, ValueError) as exc:
            raise SystemTerminalError("terminal cursor must be an integer") from exc
        if value < 0:
            raise SystemTerminalError("terminal cursor must not be negative")
        return value

    @staticmethod
    def _set_size(fd: int, *, cols: int, rows: int) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
