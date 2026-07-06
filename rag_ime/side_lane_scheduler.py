from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock


@dataclass(frozen=True)
class LaneRequestToken:
    session_id: str
    panel_session_id: str
    frontend_revision: int
    input_generation: int
    apply_anchor: str
    query_anchor: str
    created_at_ms: int
    serial: int = 0
    cancelled: bool = False


class LatestWinsLaneScheduler:
    """Tracks the latest side-lane request for an IME panel transaction."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._serial = 0
        self._latest: dict[tuple[str, str], LaneRequestToken] = {}

    def begin(self, token: LaneRequestToken) -> LaneRequestToken:
        with self._lock:
            latest = self._latest.get(self._key(token))
            if latest is not None and _same_request_context(latest, token):
                return latest
            self._serial += 1
            active = replace(token, serial=self._serial, cancelled=False)
            self._latest[self._key(active)] = active
            return active

    def is_latest(self, token: LaneRequestToken) -> bool:
        with self._lock:
            latest = self._latest.get(self._key(token))
            return latest == token and not token.cancelled

    def cancel_older(self, session_id: str, panel_session_id: str) -> int:
        key = (session_id, panel_session_id)
        with self._lock:
            if key not in self._latest:
                return 0
            del self._latest[key]
            return 1

    @staticmethod
    def _key(token: LaneRequestToken) -> tuple[str, str]:
        return (token.session_id, token.panel_session_id)


def _same_request_context(left: LaneRequestToken, right: LaneRequestToken) -> bool:
    return (
        left.frontend_revision == right.frontend_revision
        and left.apply_anchor == right.apply_anchor
        and left.query_anchor == right.query_anchor
        and not left.cancelled
    )
