from __future__ import annotations

import inspect
import unittest

from rag_ime.agent_room_route_owners import (
    ROOM_ROUTE_OWNER_CENSUS,
    room_route_owner,
    validate_room_route_owner_census,
)
from rag_ime.agent_service import AgentService


class AgentRoomRouteOwnerTests(unittest.TestCase):
    def test_every_audited_room_binding_route_has_exactly_one_kernel_owner(self) -> None:
        validate_room_route_owner_census(AgentService)
        self.assertEqual(len(ROOM_ROUTE_OWNER_CENSUS), 22)
        self.assertTrue(
            all(
                room_route_owner(route.route_id, has_room_binding=True) == "kernel"
                for route in ROOM_ROUTE_OWNER_CENSUS
            )
        )

    def test_each_legacy_execution_entry_has_an_executable_kernel_fence(self) -> None:
        guarded = {
            "_post_room_message_once": "room.message.mention",
            "assign_room_work": "work_item.assign",
            "submit_room_work": "work_item.submit",
            "accept_room_work": "work_item.accept",
            "return_room_work": "work_item.return",
            "block_room_work": "work_item.block",
            "escalate_room_work": "work_item.escalate",
            "_dispatch_scheduled_wake": "wake.dispatch",
            "_deliver_room_intercom": "intercom.delivery",
        }
        for method_name, route_id in guarded.items():
            with self.subTest(entrypoint=method_name):
                source = inspect.getsource(getattr(AgentService, method_name))
                self.assertIn(f'_guard_legacy_room_route("{route_id}"', source)

        enqueue_source = inspect.getsource(AgentService._enqueue_room_intercom)
        self.assertIn('route_id = f"intercom.{kind}"', enqueue_source)
        self.assertEqual(
            {route.route_id for route in ROOM_ROUTE_OWNER_CENSUS if route.route_id.startswith("intercom.")},
            {"intercom.send", "intercom.ask", "intercom.reply", "intercom.delivery"},
        )

    def test_all_tool_aliases_are_canonicalized_by_the_kernel_gateway(self) -> None:
        source = inspect.getsource(AgentService.execute_room_capability_tool)
        for alias in (
            "send", "ask", "reply", "room_send", "room_ask", "room_reply",
            "assign", "submit", "room_assign", "room_submit",
        ):
            self.assertIn(f'"{alias}"', source)
        self.assertIn('authorized_tool = "room_post"', source)
        self.assertIn('authorized_tool = "room_commit"', source)


if __name__ == "__main__":
    unittest.main()
