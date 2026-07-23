from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from threading import RLock


class AgentSessionModeConflict(ValueError):
    """One logical Session cannot enter Agent and Room execution at once."""


class AgentSessionModeGate:
    """Own short-lived Agent/Room entry claims before durable busy state exists."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._claims: dict[str, tuple[str, object]] = {}

    @contextmanager
    def claim_agent(self, session_id: str) -> Iterator[None]:
        with self._claim((session_id,), mode="agent"):
            yield

    @contextmanager
    def claim_room(self, session_ids: Sequence[str]) -> Iterator[None]:
        with self._claim(session_ids, mode="room"):
            yield

    @contextmanager
    def _claim(
        self,
        session_ids: Sequence[str],
        *,
        mode: str,
    ) -> Iterator[None]:
        normalized = tuple(
            dict.fromkeys(
                value
                for value in (
                    str(session_id or "").strip()
                    for session_id in session_ids
                )
                if value
            )
        )
        token = object()
        with self._lock:
            conflict = next(
                (
                    (session_id, self._claims[session_id][0])
                    for session_id in normalized
                    if session_id in self._claims
                ),
                None,
            )
            if conflict is not None:
                raise AgentSessionModeConflict(
                    _conflict_message(
                        requested_mode=mode,
                        current_mode=conflict[1],
                    )
                )
            for session_id in normalized:
                self._claims[session_id] = (mode, token)
        try:
            yield
        finally:
            with self._lock:
                for session_id in normalized:
                    claim = self._claims.get(session_id)
                    if claim is not None and claim[1] is token:
                        self._claims.pop(session_id, None)


def _conflict_message(
    *,
    requested_mode: str,
    current_mode: str,
) -> str:
    if requested_mode == "agent" and current_mode == "room":
        return (
            "Session 正在进入 Room 任务，不能同时从 Agent 发送；"
            "请等待 Room 结束或先停止该 Room 任务"
        )
    if requested_mode == "room" and current_mode == "agent":
        return "Room 成员 Session 正在接收 Agent 消息，请稍后重试"
    if requested_mode == "agent":
        return "Session 正在接收另一条 Agent 消息，请稍后重试"
    return "Room 成员 Session 正在被另一条调度占用，请稍后重试"
