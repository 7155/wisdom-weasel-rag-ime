from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from .knowledge_library import AssetBlob, HttpKnowledgeClient, KnowledgeLibraryError


class KnowledgeWorkerSupervisor:
    """Lazily starts the isolated document worker and exposes its HTTP client."""

    def __init__(
        self,
        *,
        settings_provider: Callable[[], Mapping[str, object]],
        root_dir: Path | None = None,
        base_url: str = "http://127.0.0.1:8769",
        idle_seconds: int = 900,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings_provider = settings_provider
        self.root_dir = Path(root_dir or default_knowledge_root()).expanduser()
        self.base_url = base_url.rstrip("/")
        parsed_url = urllib.parse.urlparse(self.base_url)
        self._worker_host = str(parsed_url.hostname or "127.0.0.1")
        self._worker_port = int(parsed_url.port or 80)
        self.idle_seconds = max(60, min(86_400, int(idle_seconds)))
        self._popen = popen
        self._clock = clock
        self._client = HttpKnowledgeClient(self.base_url)
        self._process: subprocess.Popen[bytes] | None = None
        self._started_fingerprint = ""
        self._lock = RLock()

    def list_bases(self, payload: Mapping[str, object]) -> dict[str, Any]:
        return self._call("list_bases", payload)

    def search(self, payload: Mapping[str, object]) -> dict[str, Any]:
        return self._call("search", payload)

    def find(self, payload: Mapping[str, object]) -> dict[str, Any]:
        return self._call("find", payload)

    def open(self, payload: Mapping[str, object]) -> dict[str, Any]:
        return self._call("open", payload)

    def status(self, payload: Mapping[str, object]) -> dict[str, Any]:
        _ = payload
        try:
            return self._call("status", {})
        except KnowledgeLibraryError as exc:
            return {
                "schemaVersion": "rag-ime.knowledge-library.v1",
                "available": False,
                "state": "unavailable",
                "reason": exc.code,
            }

    def management_call(self, operation: str, *args: object, **kwargs: object) -> dict[str, Any] | AssetBlob:
        return self._call(operation, *args, **kwargs)

    def ensure_running(self) -> None:
        with self._lock:
            fingerprint, mineru_enabled, mineru_port = self._worker_settings()
            if self._healthy():
                if self._process is None or fingerprint == self._started_fingerprint:
                    return
                self._stop_owned_worker()
            elif self._process is not None and self._process.poll() is not None:
                self._process = None

            self.root_dir.mkdir(parents=True, exist_ok=True)
            command = [
                sys.executable,
                "-m",
                "rag_ime.knowledge_library.worker",
                "--host",
                self._worker_host,
                "--port",
                str(self._worker_port),
                "--root",
                str(self.root_dir),
                "--idle-seconds",
                str(self.idle_seconds),
                "--mineru-port",
                str(mineru_port),
            ]
            if mineru_enabled:
                command.append("--mineru-enabled")
            self._process = self._popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(Path(__file__).resolve().parents[1]),
                start_new_session=True,
            )
            self._started_fingerprint = fingerprint
            deadline = self._clock() + 5.0
            while self._clock() < deadline:
                if self._process.poll() is not None:
                    break
                if self._healthy():
                    return
                time.sleep(0.05)
            code = self._process.poll()
            raise KnowledgeLibraryError(
                f"knowledge worker failed to start{f' (exit {code})' if code is not None else ''}",
                code="worker_start_failed",
            )

    def close(self) -> None:
        with self._lock:
            self._stop_owned_worker()

    def _call(self, operation: str, *args: object, **kwargs: object) -> Any:
        self.ensure_running()
        handler = getattr(self._client, operation, None)
        if not callable(handler):
            raise KnowledgeLibraryError(
                f"knowledge worker operation is unavailable: {operation}",
                code="unsupported_operation",
            )
        try:
            result = handler(*args, **kwargs)
        except KnowledgeLibraryError as exc:
            if exc.code != "worker_unavailable":
                raise
            with self._lock:
                if self._process is not None and self._process.poll() is not None:
                    self._process = None
            self.ensure_running()
            result = handler(*args, **kwargs)
        if not isinstance(result, (dict, AssetBlob)):
            raise KnowledgeLibraryError(
                "knowledge worker returned an invalid response",
                code="worker_bad_response",
            )
        return result

    def _healthy(self) -> bool:
        request = urllib.request.Request(
            f"{self.base_url}/v1/health",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=0.35) as response:
                return int(getattr(response, "status", 0)) == 200
        except (OSError, urllib.error.URLError):
            return False

    def _worker_settings(self) -> tuple[str, bool, int]:
        settings = self.settings_provider()
        knowledge = settings.get("knowledgeLibrary") if isinstance(settings, Mapping) else None
        parser = knowledge.get("parser") if isinstance(knowledge, Mapping) else None
        mineru = parser.get("mineru") if isinstance(parser, Mapping) else None
        enabled = bool(mineru.get("enabled", False)) if isinstance(mineru, Mapping) else False
        raw_port = mineru.get("port", 30_001) if isinstance(mineru, Mapping) else 30_001
        port = int(raw_port) if isinstance(raw_port, (int, float)) and not isinstance(raw_port, bool) else 30_001
        port = max(1_024, min(65_535, port))
        return f"mineru:{int(enabled)}:{port}", enabled, port

    def _stop_owned_worker(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)


def default_knowledge_root() -> Path:
    explicit = os.environ.get("RAG_IME_KNOWLEDGE_ROOT", "").strip()
    if explicit:
        return Path(explicit)
    support = os.environ.get("RAG_IME_APP_SUPPORT_DIR", "").strip()
    if support:
        return Path(support) / "Knowledge"
    return Path.home() / "Library" / "Application Support" / "RagIme" / "Knowledge"
