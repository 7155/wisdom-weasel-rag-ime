from __future__ import annotations

from collections.abc import Callable, Iterable
from threading import RLock

from .agent_protocol import AgentEventEnvelope


# Cancelled-turn receipts kept for late event stamping. The bound lives next to
# the dict it bounds; it is a memory cap, not a cancellation policy.
_CANCELLED_TURN_RECEIPT_LIMIT = 2048


class RoomSessionBusyError(RuntimeError):
    """One target Session already has priority, a pending turn or a live turn.

    Raised inside the registry lock so the reservation that failed leaves no
    partial state. Carries the Session id; the caller owns the user-facing
    message, which names a Room participant rather than a Session.
    """

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session busy: {session_id}")
        self.session_id = session_id


class RoomTurnRegistry:
    """Own the mapping from private Session turns to public Room roots."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.pending_turn_by_session: dict[str, str] = {}
        self.pending_dispatch_by_session: dict[str, str] = {}
        self.turn_by_session_turn: dict[
            tuple[str, str],
            str,
        ] = {}
        self.dispatch_by_session_turn: dict[
            tuple[str, str],
            str,
        ] = {}
        self.topic_by_room_turn: dict[str, str] = {}
        self.user_priority_sessions: set[str] = set()
        self.cancelled_turns: dict[str, str] = {}
        self.cancelled_root_by_session: dict[str, str] = {}
        self.cancelled_turn_by_session_turn: dict[
            tuple[str, str],
            str,
        ] = {}

    def begin(
        self,
        session_id: str,
        room_turn_id: str,
        topic_id: str = "",
        *,
        dispatch_id: str = "",
    ) -> None:
        with self.lock:
            self.cancelled_root_by_session.pop(
                session_id,
                None,
            )
            for key in tuple(
                self.cancelled_turn_by_session_turn
            ):
                if key[0] == session_id:
                    self.cancelled_turn_by_session_turn.pop(
                        key,
                        None,
                    )
            self.pending_turn_by_session[session_id] = (
                room_turn_id
            )
            if dispatch_id:
                self.pending_dispatch_by_session[
                    session_id
                ] = dispatch_id
            self.topic_by_room_turn[room_turn_id] = topic_id

    def accept(
        self,
        session_id: str,
        session_turn_id: str,
        room_turn_id: str,
    ) -> None:
        if not session_turn_id:
            return
        with self.lock:
            if (
                self.pending_turn_by_session.get(session_id)
                != room_turn_id
            ):
                return
            self.pending_turn_by_session.pop(session_id, None)
            key = (session_id, session_turn_id)
            self.turn_by_session_turn[key] = room_turn_id
            dispatch_id = (
                self.pending_dispatch_by_session.pop(
                    session_id,
                    "",
                )
            )
            if dispatch_id:
                self.dispatch_by_session_turn[
                    key
                ] = dispatch_id

    def cancel(
        self,
        session_id: str,
        room_turn_id: str,
    ) -> None:
        with self.lock:
            if room_turn_id in self.cancelled_turns:
                self.cancelled_root_by_session[
                    session_id
                ] = room_turn_id
            if (
                self.pending_turn_by_session.get(session_id)
                == room_turn_id
            ):
                self.pending_turn_by_session.pop(
                    session_id,
                    None,
                )
                self.pending_dispatch_by_session.pop(
                    session_id,
                    None,
                )
            for key, value in tuple(
                self.turn_by_session_turn.items()
            ):
                if (
                    key[0] == session_id
                    and value == room_turn_id
                ):
                    if room_turn_id in self.cancelled_turns:
                        self.cancelled_turn_by_session_turn[
                            key
                        ] = room_turn_id
                    self.turn_by_session_turn.pop(key, None)
                    self.dispatch_by_session_turn.pop(
                        key,
                        None,
                    )
            while (
                len(self.cancelled_turn_by_session_turn)
                > 4_096
            ):
                self.cancelled_turn_by_session_turn.pop(
                    next(
                        iter(
                            self.cancelled_turn_by_session_turn
                        )
                    )
                )
            self._drop_topic_if_idle(room_turn_id)

    def hold_priority(
        self,
        session_ids: Iterable[str],
    ) -> None:
        """Mark Sessions user-priority unconditionally.

        The direct-Agent entry path proves availability separately before
        claiming, so this hold does not re-check; use
        `hold_priority_if_idle` when the check and the hold must be one
        critical section.
        """

        with self.lock:
            self.user_priority_sessions.update(session_ids)

    def hold_priority_if_idle(
        self,
        session_ids: Iterable[str],
        *,
        ensure_available: Callable[[str], None] | None = None,
    ) -> None:
        """Atomically reserve Sessions that are not already engaged.

        For each Session, in order: run `ensure_available` (inside the lock,
        so caller pre-checks stay atomic with the reservation), then reject
        with `RoomSessionBusyError` if the Session holds priority, a pending
        turn or a registered turn. Only after every Session passes is the
        whole set marked priority -- a failure reserves nothing.
        """

        ordered = list(session_ids)
        with self.lock:
            for session_id in ordered:
                if ensure_available is not None:
                    ensure_available(session_id)
                if (
                    session_id in self.user_priority_sessions
                    or session_id in self.pending_turn_by_session
                    or any(
                        key[0] == session_id
                        for key in self.turn_by_session_turn
                    )
                ):
                    raise RoomSessionBusyError(session_id)
            self.user_priority_sessions.update(ordered)

    def release_priority(
        self,
        session_ids: Iterable[str],
    ) -> None:
        with self.lock:
            self.user_priority_sessions.difference_update(
                session_ids
            )

    def release_priority_session(
        self,
        session_id: str,
    ) -> None:
        with self.lock:
            self.user_priority_sessions.discard(session_id)

    def session_turn_active(self, session_id: str) -> bool:
        """Whether a Session has a pending or registered Room turn.

        This is the direct-Agent guard's decision. It deliberately excludes
        the priority set: a Session held for an imminent dispatch has no turn
        yet, and the guard treated it as available.
        """

        with self.lock:
            return (
                session_id in self.pending_turn_by_session
                or any(
                    key[0] == session_id
                    for key in self.turn_by_session_turn
                )
            )

    def turn_targets(
        self,
        room_turn_id: str,
        *,
        resolve: Callable[[str], str | None],
    ) -> tuple[tuple[str, str, str], ...]:
        """(resolved id, session id, dispatch id) for Sessions bound to a turn.

        Pending Sessions come first, each with its pending dispatch id;
        registered session-turns follow with an empty dispatch id, matching
        the traversal this replaces. `resolve` runs inside the registry lock
        so participant resolution and map traversal remain one critical
        section, exactly as the caller's inline loops were; returning None
        drops the entry.
        """

        results: list[tuple[str, str, str]] = []
        with self.lock:
            for session_id, pending_turn_id in (
                self.pending_turn_by_session.items()
            ):
                if pending_turn_id != room_turn_id:
                    continue
                resolved = resolve(session_id)
                if resolved is None:
                    continue
                results.append(
                    (
                        resolved,
                        session_id,
                        self.pending_dispatch_by_session.get(
                            session_id,
                            "",
                        ),
                    )
                )
            for (session_id, _session_turn_id), bound_turn_id in (
                self.turn_by_session_turn.items()
            ):
                if bound_turn_id != room_turn_id:
                    continue
                resolved = resolve(session_id)
                if resolved is None:
                    continue
                results.append((resolved, session_id, ""))
        return tuple(results)

    def record_cancellation(
        self,
        room_turn_id: str,
        cancellation_receipt_id: str,
    ) -> None:
        """Remember a turn's cancellation receipt, evicting oldest past 2048.

        Same dict semantics as the inline code this replaces: re-cancelling a
        turn overwrites the receipt in place without refreshing its insertion
        position, and eviction starts only once the size exceeds the limit.
        """

        with self.lock:
            self.cancelled_turns[room_turn_id] = (
                cancellation_receipt_id
            )
            while (
                len(self.cancelled_turns)
                > _CANCELLED_TURN_RECEIPT_LIMIT
            ):
                self.cancelled_turns.pop(
                    next(iter(self.cancelled_turns))
                )

    def turn_for_event(
        self,
        event: AgentEventEnvelope,
    ) -> str:
        registered = self.registered_turn_for_event(event)
        return registered or event.turn_id

    def registered_turn_for_event(
        self,
        event: AgentEventEnvelope,
    ) -> str:
        """Return only an explicitly registered public Room conversation."""

        if not event.turn_id:
            return ""
        key = (event.session_id, event.turn_id)
        with self.lock:
            room_turn_id = self.turn_by_session_turn.get(key)
            if room_turn_id:
                return room_turn_id
            cancelled = (
                self.cancelled_turn_by_session_turn.get(key)
            )
            if cancelled:
                return cancelled
            pending = self.pending_turn_by_session.get(
                event.session_id
            )
            if pending:
                self.turn_by_session_turn[key] = pending
                dispatch_id = (
                    self.pending_dispatch_by_session.get(
                        event.session_id,
                        "",
                    )
                )
                if dispatch_id:
                    self.dispatch_by_session_turn[
                        key
                    ] = dispatch_id
                return pending
            cancelled_pending = (
                self.cancelled_root_by_session.get(
                    event.session_id
                )
            )
            if cancelled_pending:
                self.cancelled_turn_by_session_turn[
                    key
                ] = cancelled_pending
                return cancelled_pending
        return ""

    def dispatch_for_event(
        self,
        event: AgentEventEnvelope,
    ) -> str:
        if not event.turn_id:
            return ""
        key = (event.session_id, event.turn_id)
        with self.lock:
            dispatch_id = self.dispatch_by_session_turn.get(
                key
            )
            if dispatch_id:
                return dispatch_id
            return self.pending_dispatch_by_session.get(
                event.session_id,
                "",
            )

    def finish(
        self,
        session_id: str,
        session_turn_id: str,
        room_turn_id: str,
    ) -> None:
        with self.lock:
            key = (session_id, session_turn_id)
            self.turn_by_session_turn.pop(key, None)
            self.dispatch_by_session_turn.pop(key, None)
            if (
                self.pending_turn_by_session.get(session_id)
                == room_turn_id
            ):
                self.pending_turn_by_session.pop(
                    session_id,
                    None,
                )
                self.pending_dispatch_by_session.pop(
                    session_id,
                    None,
                )
            self._drop_topic_if_idle(room_turn_id)

    def is_cancelled(
        self,
        session_id: str,
        room_turn_id: str,
    ) -> bool:
        with self.lock:
            return (
                room_turn_id in self.cancelled_turns
                or self.cancelled_root_by_session.get(
                    session_id
                )
                == room_turn_id
            )

    def topic_for_turn(self, room_turn_id: str) -> str:
        with self.lock:
            return self.topic_by_room_turn.get(
                room_turn_id,
                "",
            )

    def drop_topic_if_idle(self, room_turn_id: str) -> None:
        with self.lock:
            self._drop_topic_if_idle(room_turn_id)

    def _drop_topic_if_idle(
        self,
        room_turn_id: str,
    ) -> None:
        if (
            room_turn_id
            in self.pending_turn_by_session.values()
        ):
            return
        if (
            room_turn_id
            in self.turn_by_session_turn.values()
        ):
            return
        self.topic_by_room_turn.pop(room_turn_id, None)
