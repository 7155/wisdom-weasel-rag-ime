from __future__ import annotations

import json
import os
import socket
import stat
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path


DESKTOP_BRIDGE_MAX_MESSAGE_BYTES = 1_048_576


class DesktopBridgeError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = str(code or "desktop_bridge_error")
        self.message = str(message or self.code)
        super().__init__(f"{self.code}: {self.message}")


class DesktopBridgeClient:
    """Bounded JSON client for the native macOS Accessibility bridge."""

    def __init__(
        self,
        *,
        socket_path: str | Path | None = None,
        timeout_seconds: float = 2.0,
        verify_socket_owner: bool = True,
    ) -> None:
        configured = socket_path or os.environ.get("RAG_IME_DESKTOP_BRIDGE_SOCKET")
        if configured:
            self.socket_path = Path(configured).expanduser()
        else:
            app_support = Path(
                os.environ.get("RAG_IME_APP_SUPPORT_DIR")
                or Path.home() / "Library" / "Application Support" / "RagIme"
            ).expanduser()
            self.socket_path = app_support / "desktop-bridge.sock"
        self.timeout_seconds = max(0.1, min(float(timeout_seconds), 10.0))
        self.verify_socket_owner = bool(verify_socket_owner)

    def status(self) -> dict[str, object]:
        return self.request("status")

    def list_applications(self, *, include_background: bool = False) -> dict[str, object]:
        return self.request("list", includeBackground=bool(include_background))

    def inspect(
        self,
        *,
        bundle_id: str = "",
        pid: int = 0,
        query: str = "",
        max_nodes: int = 160,
        max_depth: int = 8,
        since_snapshot_id: str = "",
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "maxNodes": max(1, min(int(max_nodes), 500)),
            "maxDepth": max(1, min(int(max_depth), 12)),
        }
        if bundle_id:
            payload["bundleId"] = str(bundle_id)[:300]
        if pid > 0:
            payload["pid"] = int(pid)
        if query:
            payload["query"] = str(query)[:300]
        if since_snapshot_id:
            payload["sinceSnapshotId"] = str(since_snapshot_id)[:200]
        return self.request("inspect", **payload)

    def prepare_action(
        self,
        *,
        snapshot_id: str,
        revision: int,
        node_ref: str,
        action: str,
        text: str | None = None,
        key: str = "",
        modifiers: Sequence[str] = (),
        duration_ms: int | None = None,
        scroll_delta: int | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "snapshotId": str(snapshot_id)[:200],
            "revision": int(revision),
            "nodeRef": str(node_ref)[:200],
            "action": str(action)[:80],
        }
        if text is not None:
            payload["text"] = str(text)[:8_000]
        if key:
            payload["key"] = str(key)[:40]
        if modifiers:
            payload["modifiers"] = [str(value)[:20] for value in list(modifiers)[:5]]
        if duration_ms is not None:
            payload["durationMs"] = int(duration_ms)
        if scroll_delta is not None:
            payload["scrollDelta"] = int(scroll_delta)
        return self.request("prepare_action", **payload)

    def act(
        self,
        *,
        action_payload: Mapping[str, object],
        base_state: Mapping[str, object],
    ) -> dict[str, object]:
        return self.request(
            "act",
            actionPayload=dict(action_payload),
            baseState=dict(base_state),
        )

    def request(self, operation: str, **payload: object) -> dict[str, object]:
        request_id = f"desktop:{uuid.uuid4()}"
        request = {
            "schemaVersion": "rag-ime.desktop-bridge-request.v1",
            "requestId": request_id,
            "op": str(operation),
            **payload,
        }
        encoded = (
            json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
        if len(encoded) > DESKTOP_BRIDGE_MAX_MESSAGE_BYTES:
            raise DesktopBridgeError("invalid_request", "request_too_large")
        self._validate_socket()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(str(self.socket_path))
                connection.sendall(encoded)
                response_bytes = self._read_response(connection)
        except FileNotFoundError as exc:
            raise DesktopBridgeError("unavailable", "desktop_bridge_socket_missing") from exc
        except (ConnectionError, OSError, TimeoutError) as exc:
            raise DesktopBridgeError("unavailable", "desktop_bridge_connection_failed") from exc

        try:
            response = json.loads(response_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DesktopBridgeError("invalid_response", "desktop_bridge_response_invalid") from exc
        if not isinstance(response, Mapping):
            raise DesktopBridgeError("invalid_response", "desktop_bridge_response_must_be_object")
        if str(response.get("schemaVersion") or "") != "rag-ime.desktop-bridge-response.v1":
            raise DesktopBridgeError("invalid_response", "desktop_bridge_response_schema_mismatch")
        if str(response.get("requestId") or "") != request_id:
            raise DesktopBridgeError("invalid_response", "desktop_bridge_request_id_mismatch")
        if response.get("ok") is not True:
            error = response.get("error") if isinstance(response.get("error"), Mapping) else {}
            raise DesktopBridgeError(
                str(error.get("code") or "desktop_bridge_error"),
                str(error.get("message") or "desktop_bridge_request_failed"),
            )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise DesktopBridgeError("invalid_response", "desktop_bridge_result_must_be_object")
        return dict(result)

    def _validate_socket(self) -> None:
        if not self.verify_socket_owner:
            return
        try:
            metadata = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(metadata.st_mode):
            raise DesktopBridgeError("permission_denied", "desktop_bridge_path_is_not_socket")
        if metadata.st_uid != os.getuid():
            raise DesktopBridgeError("permission_denied", "desktop_bridge_socket_owner_mismatch")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise DesktopBridgeError("permission_denied", "desktop_bridge_socket_permissions_too_broad")

    @staticmethod
    def _read_response(connection: socket.socket) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while size <= DESKTOP_BRIDGE_MAX_MESSAGE_BYTES:
            chunk = connection.recv(16_384)
            if not chunk:
                break
            if b"\n" in chunk:
                before, _, _ = chunk.partition(b"\n")
                chunks.append(before)
                size += len(before)
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > DESKTOP_BRIDGE_MAX_MESSAGE_BYTES:
            raise DesktopBridgeError("invalid_response", "desktop_bridge_response_too_large")
        payload = b"".join(chunks)
        if not payload:
            raise DesktopBridgeError("invalid_response", "desktop_bridge_response_empty")
        return payload
