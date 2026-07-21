from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .agent_prompt_support import bounded_text


class AgentTaskContextResolver:
    """Resolve the one authoritative task bound to a Session."""

    def __init__(
        self,
        *,
        delegation: Any,
        rooms: Any,
        room_capabilities: Any,
        room_kernel: Any,
        room_requirements: Any,
    ) -> None:
        self.delegation = delegation
        self.rooms = rooms
        self.room_capabilities = room_capabilities
        self.room_kernel = room_kernel
        self.room_requirements = room_requirements

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
        kernel_task = self._kernel_task(session_id)
        if kernel_task:
            return kernel_task
        return self._legacy_room_work(session_id)

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

    def _kernel_task(
        self,
        session_id: str,
    ) -> dict[str, object]:
        identity = self.room_capabilities.runtime_identity(
            session_id
        )
        if not isinstance(identity, Mapping):
            return {}
        task_id = str(identity.get("taskId") or "")
        dispatch_id = str(identity.get("dispatchId") or "")
        try:
            task = self.room_kernel.task(task_id)
        except (KeyError, ValueError):
            return {}
        requirement_context = (
            self.room_requirements.dispatch_context(
                dispatch_id
            )
            if dispatch_id
            else None
        )
        criterion_ids = [
            str(value)
            for value in task.get(
                "acceptanceCriterionIds"
            )
            or []
            if str(value).strip()
        ]
        catalog = (
            requirement_context.get("catalog")
            if isinstance(requirement_context, Mapping)
            and isinstance(
                requirement_context.get("catalog"), Mapping
            )
            else {}
        )
        criteria_by_id = {
            str(value.get("criterionId") or ""): value
            for value in catalog.get("acceptanceCriteria") or []
            if isinstance(value, Mapping)
        }
        criteria = [
            str(
                criteria_by_id.get(criterion_id, {}).get(
                    "statement"
                )
                or criterion_id
            )
            for criterion_id in criterion_ids
        ]
        originals = [
            bounded_text(value.get("text"), maximum=2_000)
            for value in (
                requirement_context.get("originalRequirements")
                if isinstance(requirement_context, Mapping)
                else []
            )
            if isinstance(value, Mapping)
            and bounded_text(value.get("text"), maximum=2_000)
        ]
        return {
            "kind": "room_kernel_task",
            "objective": str(task.get("objective") or ""),
            "expectedOutput": str(
                task.get("expectedOutput") or ""
            ),
            "acceptanceCriteria": criteria,
            "originalRequirements": originals,
            "requirementCatalogRevisionId": str(
                catalog.get("catalogRevisionId") or ""
            ),
            "blockers": [
                str(value.get("statement") or "")
                for value in catalog.get("openObstacles") or []
                if isinstance(value, Mapping)
                and str(value.get("statement") or "").strip()
            ],
            "state": str(task.get("state") or ""),
        }

    def _legacy_room_work(
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
