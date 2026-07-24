from __future__ import annotations

from threading import RLock

from .agent_protocol import AgentEventEnvelope


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
