from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRequestToken:
    request_id: str
    session_id: str
    panel_session_id: str
    input_generation: int
    apply_anchor: str
    query_anchor: str
    profile_id: str
    created_at_ms: int


class LatestWinsModelScheduler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[tuple[str, str, str], ModelRequestToken] = {}
        self._cancelled: dict[str, str] = {}

    def begin(self, token: ModelRequestToken) -> None:
        with self._lock:
            for request_id in self.cancel_older(token):
                self._cancelled[request_id] = "superseded_by_newer_generation"
            self._latest[self._key(token)] = token

    def cancel_older(self, token: ModelRequestToken) -> list[str]:
        key = self._key(token)
        current = self._latest.get(key)
        if current is None:
            return []
        if current.input_generation <= token.input_generation and current.request_id != token.request_id:
            return [current.request_id]
        return []

    def is_latest(self, token: ModelRequestToken) -> bool:
        with self._lock:
            current = self._latest.get(self._key(token))
            return current is None or current.request_id == token.request_id

    def is_cancelled(self, request_id: str) -> bool:
        with self._lock:
            return request_id in self._cancelled

    def cancel_reason(self, request_id: str) -> str:
        with self._lock:
            return self._cancelled.get(request_id, "")

    def finish(self, token: ModelRequestToken) -> None:
        with self._lock:
            current = self._latest.get(self._key(token))
            if current and current.request_id == token.request_id:
                self._latest.pop(self._key(token), None)
            self._cancelled.pop(token.request_id, None)

    @staticmethod
    def _key(token: ModelRequestToken) -> tuple[str, str, str]:
        return (token.session_id, token.panel_session_id, token.profile_id)


def model_request_token_from_metadata(metadata: dict[str, object], *, profile_id: str) -> ModelRequestToken:
    request_id = str(metadata.get("requestId") or metadata.get("request_id") or "")
    if not request_id:
        request_id = f"model-{int(time.time() * 1000)}-{id(metadata)}"
    return ModelRequestToken(
        request_id=request_id,
        session_id=str(metadata.get("sessionId") or metadata.get("session_id") or "default"),
        panel_session_id=str(metadata.get("panelSessionId") or metadata.get("panel_session_id") or "default"),
        input_generation=_int(metadata.get("inputGeneration") or metadata.get("requestSeq")),
        apply_anchor=str(metadata.get("applyAnchor") or metadata.get("contextFingerprint") or ""),
        query_anchor=str(metadata.get("queryAnchor") or metadata.get("currentInputFingerprint") or ""),
        profile_id=profile_id,
        created_at_ms=_int(metadata.get("createdAtMs")) or int(time.time() * 1000),
    )


def _int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
