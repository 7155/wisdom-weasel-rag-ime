from __future__ import annotations

import http.client
import json
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping
from urllib.parse import urlsplit

from rag_ime.debug_server import DebugImeService, DebugRequestHandler


_BRIDGE_HOST = "rag-ime-file-bridge.invalid"
_MAX_BRIDGE_BYTES = 2_000_000
_DEFAULT_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class InProcessHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class InProcessControlApi:
    """Exercise the canonical HTTP handler over an unbound socket pair."""

    def __init__(
        self,
        service: DebugImeService,
        *,
        static_dir: Path,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
    ):
        if not 1 <= int(max_response_bytes) <= 256 * 1024 * 1024:
            raise ValueError("in-process HTTP response limit is out of bounds")
        self.service = service
        self.static_dir = static_dir
        self.max_response_bytes = int(max_response_bytes)

        class Handler(DebugRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

        Handler.service = service
        Handler.static_dir = static_dir
        self._handler = Handler
        self._server = SimpleNamespace()

    def request_json(
        self,
        _base_url: str,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        timeout: float = 130,
    ) -> dict[str, object]:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        response = self.request_http(
            method,
            path,
            body=body,
            headers=headers,
            timeout=timeout,
        )
        try:
            result = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"{method} {path} returned invalid JSON ({response.status})"
            ) from error
        if not isinstance(result, dict):
            raise RuntimeError(f"{method} {path} returned a non-object response")
        if not 200 <= response.status < 300:
            raise RuntimeError(
                f"{method} {path} failed ({response.status}): "
                f"{json.dumps(result, ensure_ascii=False)[:1200]}"
            )
        return result

    def request_http(
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        headers: Mapping[str, str] | None = None,
        timeout: float = 130,
    ) -> InProcessHttpResponse:
        normalized_method = str(method or "GET").upper()
        if not path.startswith("/") or "\r" in path or "\n" in path:
            raise ValueError("in-process HTTP path must be an absolute request target")
        if len(body) > _MAX_BRIDGE_BYTES:
            raise ValueError("in-process HTTP body exceeds the bridge limit")
        normalized_headers = {
            str(key): str(value)
            for key, value in dict(headers or {}).items()
            if "\r" not in str(key)
            and "\n" not in str(key)
            and "\r" not in str(value)
            and "\n" not in str(value)
        }
        normalized_headers["Host"] = "127.0.0.1"
        normalized_headers["Connection"] = "close"
        normalized_headers["Content-Length"] = str(len(body))
        request = [f"{normalized_method} {path} HTTP/1.1\r\n"]
        request.extend(f"{key}: {value}\r\n" for key, value in normalized_headers.items())
        encoded = "".join(request).encode("iso-8859-1") + b"\r\n" + body

        client, server = socket.socketpair()
        client.settimeout(max(0.1, float(timeout)))
        handler_errors: list[BaseException] = []

        def serve() -> None:
            try:
                self._handler(server, ("127.0.0.1", 0), self._server)
            except BaseException as error:  # surfaced to the caller below
                handler_errors.append(error)
            finally:
                server.close()

        thread = threading.Thread(
            target=serve,
            name=f"rag-ime-in-process-http-{uuid.uuid4().hex[:8]}",
            daemon=True,
        )
        thread.start()
        try:
            client.sendall(encoded)
            client.shutdown(socket.SHUT_WR)
            response = http.client.HTTPResponse(client)
            response.begin()
            response_body = response.read(self.max_response_bytes + 1)
            if len(response_body) > self.max_response_bytes:
                raise RuntimeError("in-process HTTP response exceeds the bridge limit")
            result = InProcessHttpResponse(
                status=int(response.status),
                headers={key: value for key, value in response.getheaders()},
                body=response_body,
            )
        finally:
            client.close()
            thread.join(timeout=max(1.0, min(float(timeout), 5.0)))
        if thread.is_alive():
            raise TimeoutError(f"in-process HTTP handler did not finish: {method} {path}")
        if handler_errors:
            raise RuntimeError(f"in-process HTTP handler failed: {handler_errors[0]}")
        return result


class FileFetchBridge:
    """Adapt Pi's fetch calls to the real local HTTP handler without binding a port."""

    def __init__(self, root: Path, api: InProcessControlApi):
        self.root = root.resolve(strict=False)
        self.api = api
        self.requests = self.root / "requests"
        self.responses = self.root / "responses"
        self.requests.mkdir(parents=True, mode=0o700)
        self.responses.mkdir(parents=True, mode=0o700)
        os.chmod(self.root, 0o700)
        os.chmod(self.requests, 0o700)
        os.chmod(self.responses, 0o700)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="rag-ime-file-fetch-bridge",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)
        if self._thread.is_alive():
            raise RuntimeError("file fetch bridge did not stop")

    def _run(self) -> None:
        while not self._stop.is_set():
            handled = False
            for path in sorted(self.requests.glob("*.json")):
                handled = True
                self._handle(path)
            if not handled:
                self._stop.wait(0.01)

    def _handle(self, path: Path) -> None:
        request_id = path.stem
        try:
            if not request_id or any(character not in "0123456789abcdef-" for character in request_id):
                raise ValueError("invalid bridge request id")
            if path.stat().st_size > _MAX_BRIDGE_BYTES:
                raise ValueError("file fetch request exceeds the bridge limit")
            request = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(request, dict) or request.get("bridgeId") != request_id:
                raise ValueError("file fetch request identity mismatch")
            parsed = urlsplit(str(request.get("url") or ""))
            if parsed.scheme != "http" or parsed.hostname != _BRIDGE_HOST:
                raise ValueError("file fetch bridge host is not allowed")
            target = parsed.path or "/"
            if parsed.query:
                target += f"?{parsed.query}"
            raw_headers = request.get("headers")
            headers = (
                {
                    str(key): str(value)
                    for key, value in raw_headers.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
                if isinstance(raw_headers, dict)
                else {}
            )
            raw_body = str(request.get("body") or "").encode("utf-8")
            response = self.api.request_http(
                str(request.get("method") or "POST"),
                target,
                body=raw_body,
                headers=headers,
                timeout=130,
            )
            payload = json.loads(response.body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("file fetch response must be a JSON object")
            result = {
                "bridgeId": request_id,
                "status": response.status,
                "headers": dict(response.headers),
                "payload": payload,
            }
        except BaseException as error:
            result = {
                "bridgeId": request_id,
                "status": 599,
                "headers": {"Content-Type": "application/json"},
                "payload": {"ok": False, "error": str(error)[:800]},
            }
        finally:
            path.unlink(missing_ok=True)
        self._atomic_write(self.responses / f"{request_id}.json", result)

    @staticmethod
    def _atomic_write(path: Path, value: Mapping[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        temporary.write_text(encoded, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
