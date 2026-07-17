from __future__ import annotations

import queue
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator, Mapping

from .agent_protocol import AgentEventEnvelope


class AgentEventHub:
    """Per-session ordered event fan-out with bounded replay."""

    def __init__(
        self,
        *,
        replay_limit: int = 512,
        sequence_loader: Callable[[str], int] | None = None,
        event_recorder: Callable[[AgentEventEnvelope], None] | None = None,
        event_observer: Callable[[AgentEventEnvelope], None] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._replay_limit = max(32, int(replay_limit))
        self._sequence_loader = sequence_loader or (lambda _session_id: 0)
        self._event_recorder = event_recorder
        self._observers: set[Callable[[AgentEventEnvelope], None]] = set()
        if event_observer is not None:
            self._observers.add(event_observer)
        self._sequences: dict[str, int] = {}
        self._events: dict[str, deque[AgentEventEnvelope]] = defaultdict(
            lambda: deque(maxlen=self._replay_limit)
        )
        self._subscribers: dict[str, set[queue.Queue[AgentEventEnvelope]]] = defaultdict(set)

    def publish(
        self,
        session_id: str,
        event_type: str,
        payload: Mapping[str, object] | None = None,
        *,
        turn_id: str = "",
        created_at_ms: int | None = None,
    ) -> AgentEventEnvelope:
        with self._lock:
            envelope = self._build_event_locked(
                session_id,
                event_type,
                payload,
                turn_id=turn_id,
                created_at_ms=created_at_ms,
            )
            subscribers = tuple(self._subscribers.get(session_id, ()))
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(envelope)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(envelope)
                except (queue.Empty, queue.Full):
                    pass
        with self._lock:
            observers = tuple(self._observers)
        for observer in observers:
            try:
                observer(envelope)
            except Exception:
                # Room/event projections are secondary indexes. A projection
                # failure must never break the participant's primary Pi turn.
                pass
        return envelope

    def add_observer(
        self,
        observer: Callable[[AgentEventEnvelope], None],
    ) -> Callable[[], None]:
        """Register a secondary projection and return an idempotent remover."""

        with self._lock:
            self._observers.add(observer)

        def remove() -> None:
            with self._lock:
                self._observers.discard(observer)

        return remove

    def invalidate_projection(
        self,
        session_id: str,
        *,
        reason: str = "session_rewritten",
    ) -> AgentEventEnvelope:
        """Drop stale replay state and make live clients reload the runtime snapshot."""

        with self._lock:
            envelope = self._build_event_locked(
                session_id,
                "snapshot_required",
                {"reason": str(reason or "session_rewritten")},
                turn_id="",
                created_at_ms=None,
            )
            # The invalidation itself is a live control event. Keeping it in
            # replay would let a reconnect apply the old projection before the
            # authoritative snapshot has replaced it.
            self._events[session_id].clear()
            subscribers = tuple(self._subscribers.get(session_id, ()))
            for subscriber in subscribers:
                while True:
                    try:
                        subscriber.get_nowait()
                    except queue.Empty:
                        break
                try:
                    subscriber.put_nowait(envelope)
                except queue.Full:
                    pass
            observers = tuple(self._observers)
        for observer in observers:
            try:
                observer(envelope)
            except Exception:
                pass
        return envelope

    def subscribe(
        self,
        session_id: str,
        *,
        after_event_id: str = "",
        heartbeat_seconds: float = 10.0,
    ) -> Iterator[bytes]:
        subscriber: queue.Queue[AgentEventEnvelope] = queue.Queue(maxsize=128)
        with self._lock:
            replay, gap = self._replay_locked(session_id, after_event_id)
            if gap:
                replay = [
                    self._build_event_locked(
                        session_id,
                        "snapshot_required",
                        {"reason": "event_replay_gap", "afterEventId": after_event_id},
                        turn_id="",
                        created_at_ms=None,
                    )
                ]
            self._subscribers[session_id].add(subscriber)
        try:
            yield b": connected\n\n"
            for event in replay:
                yield event.sse()
            while True:
                try:
                    yield subscriber.get(timeout=heartbeat_seconds).sse()
                except queue.Empty:
                    yield b": heartbeat\n\n"
        finally:
            with self._lock:
                self._subscribers[session_id].discard(subscriber)
                if not self._subscribers[session_id]:
                    self._subscribers.pop(session_id, None)

    def replay(self, session_id: str, *, after_event_id: str = "") -> tuple[list[AgentEventEnvelope], bool]:
        with self._lock:
            return self._replay_locked(session_id, after_event_id)

    def subscriber_count(self, session_id: str | None = None) -> int:
        with self._lock:
            if session_id is not None:
                return len(self._subscribers.get(session_id, ()))
            return sum(len(items) for items in self._subscribers.values())

    def _build_event_locked(
        self,
        session_id: str,
        event_type: str,
        payload: Mapping[str, object] | None,
        *,
        turn_id: str,
        created_at_ms: int | None,
    ) -> AgentEventEnvelope:
        if not session_id:
            raise ValueError("agent event sessionId must not be empty")
        if session_id not in self._sequences:
            self._sequences[session_id] = max(0, int(self._sequence_loader(session_id)))
        sequence = self._sequences[session_id] + 1
        self._sequences[session_id] = sequence
        event_id = f"{session_id}:{sequence}"
        envelope = AgentEventEnvelope(
            event_id=event_id,
            session_id=session_id,
            turn_id=turn_id,
            sequence=sequence,
            created_at_ms=int(created_at_ms if created_at_ms is not None else time.time() * 1000),
            event_type=event_type,
            payload=dict(payload or {}),
            resume_token=event_id,
        )
        envelope.to_payload()
        self._events[session_id].append(envelope)
        if self._event_recorder is not None:
            self._event_recorder(envelope)
        return envelope

    def _replay_locked(
        self,
        session_id: str,
        after_event_id: str,
    ) -> tuple[list[AgentEventEnvelope], bool]:
        events = list(self._events.get(session_id, ()))
        if not after_event_id:
            return events, False
        after_sequence = _event_sequence(session_id, after_event_id)
        if after_sequence is None:
            return [], True
        current_sequence = self._sequences.get(session_id)
        if current_sequence is None:
            current_sequence = max(0, int(self._sequence_loader(session_id)))
            self._sequences[session_id] = current_sequence
        if after_sequence > current_sequence:
            return [], True
        if not events:
            return ([], after_sequence < current_sequence)
        first_sequence = events[0].sequence
        if after_sequence < first_sequence - 1:
            return [], True
        return [event for event in events if event.sequence > after_sequence], False


def _event_sequence(session_id: str, event_id: str) -> int | None:
    prefix = f"{session_id}:"
    if not event_id.startswith(prefix):
        return None
    try:
        return int(event_id[len(prefix) :])
    except ValueError:
        return None
