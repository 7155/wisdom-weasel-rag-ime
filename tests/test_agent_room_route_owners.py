from __future__ import annotations

import inspect
import unittest

from rag_ime.agent_room_route_owners import (
    ROOM_ROUTE_OWNER_CENSUS,
    room_message_owner,
    room_route_owner,
    validate_room_route_owner_census,
)
from rag_ime.agent_room_capabilities import ROOM_PUBLIC_TOOLS
from rag_ime.agent_room_intercom_application import (
    RoomIntercomApplicationService,
)
from rag_ime.agent_room_legacy_dispatch import RoomLegacyDispatchService
from rag_ime.agent_service import AgentService
from rag_ime.agent_room_work_application import RoomWorkApplicationService
from rag_ime.agent_wake_application import AgentWakeApplicationService


class AgentRoomRouteOwnerTests(unittest.TestCase):
    def test_every_audited_room_binding_route_has_exactly_one_kernel_owner(self) -> None:
        validate_room_route_owner_census(AgentService)
        self.assertEqual(len(ROOM_ROUTE_OWNER_CENSUS), 17)
        self.assertTrue(
            all(
                room_route_owner(route.route_id, has_room_binding=True) == "kernel"
                for route in ROOM_ROUTE_OWNER_CENSUS
                if route.route_id != "room.message.conversation"
            )
        )
        self.assertEqual(
            room_route_owner(
                "room.message.conversation",
                has_room_binding=True,
            ),
            "reject",
        )

    def test_room_message_semantics_have_one_owner_each(self) -> None:
        self.assertEqual(room_message_owner(work_item_id=""), "session")
        self.assertEqual(
            room_message_owner(work_item_id="work-item:confirmed"),
            "kernel",
        )
        self.assertEqual(
            {
                route.route_id
                for route in ROOM_ROUTE_OWNER_CENSUS
                if route.route_id.startswith("room.message.")
            },
            {"room.message.conversation", "room.message.execute"},
        )

    def test_each_legacy_owner_enforces_its_kernel_fence(self) -> None:
        guarded = (
            (RoomLegacyDispatchService, "post_message", "room.message.execute"),
            (RoomWorkApplicationService, "assign_room_work", "work_item.assign"),
            (RoomWorkApplicationService, "submit_room_work", "work_item.submit"),
            (RoomWorkApplicationService, "accept_room_work", "work_item.accept"),
            (RoomWorkApplicationService, "return_room_work", "work_item.return"),
            (RoomWorkApplicationService, "block_room_work", "work_item.block"),
            (RoomWorkApplicationService, "escalate_room_work", "work_item.escalate"),
            (AgentWakeApplicationService, "dispatch", "wake.dispatch"),
            (RoomIntercomApplicationService, "deliver", "intercom.delivery"),
        )
        for owner, method_name, route_id in guarded:
            with self.subTest(owner=owner.__name__, entrypoint=method_name):
                source = inspect.getsource(getattr(owner, method_name))
                if owner is RoomLegacyDispatchService:
                    source += inspect.getsource(
                        RoomLegacyDispatchService._post_session_messages
                    )
                self.assertIn(route_id, source)
                self.assertIn("guard_legacy_room_route", source)

        enqueue_source = inspect.getsource(
            RoomWorkApplicationService._enqueue_room_intercom
        )
        self.assertIn('route_id = f"intercom.{kind}"', enqueue_source)
        self.assertEqual(
            {route.route_id for route in ROOM_ROUTE_OWNER_CENSUS if route.route_id.startswith("intercom.")},
            {"intercom.send", "intercom.ask", "intercom.reply", "intercom.delivery"},
        )

    def test_kernel_gateway_has_only_the_three_canonical_room_tools(self) -> None:
        self.assertEqual(
            {
                route.route_id.removeprefix("tool.")
                for route in ROOM_ROUTE_OWNER_CENSUS
                if route.route_id.startswith("tool.")
            },
            set(ROOM_PUBLIC_TOOLS),
        )
        source = inspect.getsource(
            AgentService.execute_room_capability_tool
        )
        self.assertNotIn("authorized_tool", source)


if __name__ == "__main__":
    unittest.main()
