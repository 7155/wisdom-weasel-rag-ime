from __future__ import annotations

from collections.abc import Mapping
from typing import Any

class AgentTaskContextResolver:
    """Resolve the one authoritative task bound to a Session."""

    def __init__(
        self,
        *,
        delegation: Any,
        rooms: Any,
    ) -> None:
        self.delegation = delegation
        self.rooms = rooms

    def trigger(self, session_id: str) -> str:
        if self.delegation.owns_session(session_id):
            return "subagent_task"
        if self.rooms.participant_for_session(
            session_id,
            active_only=False,
        ) is not None:
            return "room_task"
        return "first_user_prompt"

    def room_ids(self, session_id: str) -> tuple[str, ...]:
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=False,
        )
        if not isinstance(participant, Mapping):
            return ()
        room_id = str(participant.get("roomId") or "").strip()
        return (room_id,) if room_id else ()

    def resolve(self, session_id: str) -> dict[str, object]:
        subagent = self._subagent_task(session_id)
        if subagent:
            return subagent
        return self._room_work(session_id)

    def _subagent_task(
        self,
        session_id: str,
    ) -> dict[str, object]:
        run = self.delegation.store.run_for_child_session(
            session_id
        )
        if not isinstance(run, Mapping):
            return {}
        return {
            "kind": "subagent",
            "objective": str(run.get("task") or ""),
            "expectedOutput": (
                "按受管子任务预算返回可验证结果"
            ),
            "state": str(run.get("state") or ""),
        }

    def _room_work(
        self,
        session_id: str,
    ) -> dict[str, object]:
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=False,
        )
        if not isinstance(participant, Mapping):
            return {}
        room_id = str(participant.get("roomId") or "")
        participant_id = str(participant.get("id") or "")
        try:
            room = self.rooms.get(room_id)
        except (KeyError, ValueError):
            return {}
        candidates = [
            item
            for item in room.get("workItems", [])
            if isinstance(item, Mapping)
            and str(item.get("state") or "")
            in {"queued", "active", "review", "blocked"}
            and participant_id
            in {
                str(
                    item.get(
                        "accountableParticipantId"
                    )
                    or ""
                ),
                str(
                    item.get(
                        "currentOwnerParticipantId"
                    )
                    or ""
                ),
                str(
                    item.get(
                        "offeredToParticipantId"
                    )
                    or ""
                ),
            }
        ]
        if not candidates:
            return {}
        work = max(
            candidates,
            key=lambda item: int(
                item.get("updatedAtMs") or 0
            ),
        )
        return {
            "kind": "room_work_item",
            "objective": str(work.get("objective") or ""),
            "expectedOutput": str(
                work.get("expectedOutput") or ""
            ),
            "acceptanceCriteria": list(
                work.get("acceptanceCriteria") or []
            ),
            "state": str(work.get("state") or ""),
        }
