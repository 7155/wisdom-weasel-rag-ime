from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class ManagementEvent:
    event_id: int
    event_type: str
    created_at_ms: int
    payload: dict[str, object]

    def sse(self) -> bytes:
        body = json.dumps(
            {
                "schemaVersion": "rag-ime.management-event.v1",
                "id": self.event_id,
                "type": self.event_type,
                "createdAtMs": self.created_at_ms,
                "payload": self.payload,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {body}\n\n".encode("utf-8")


class ManagementEventHub:
    """Bounded fan-out for the optional control center SSE connection."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._next_id = 1
        self._subscribers: set[queue.Queue[ManagementEvent]] = set()

    def publish(self, event_type: str, payload: dict[str, object] | None = None) -> ManagementEvent:
        with self._lock:
            event = ManagementEvent(
                event_id=self._next_id,
                event_type=event_type,
                created_at_ms=int(time.time() * 1000),
                payload=dict(payload or {}),
            )
            self._next_id += 1
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass
        return event

    def subscribe(self, *, heartbeat_seconds: float = 10.0) -> Iterator[bytes]:
        subscriber: queue.Queue[ManagementEvent] = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            yield b": connected\n\n"
            while True:
                try:
                    yield subscriber.get(timeout=heartbeat_seconds).sse()
                except queue.Empty:
                    yield b": heartbeat\n\n"
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
