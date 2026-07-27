from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote
from urllib.request import Request, urlopen

from tests.runtime_capabilities import requires_loopback_bind

from rag_ime.agent_room_work import AgentRoomWorkAssignmentChanged
from rag_ime.agent_service import AgentService
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.pi_runtime import PiRuntimeConfig


class AgentRoomWorkServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-work-service-")
        self.root = Path(self.tmp.name)
        self.service = AgentService(
            db_path=self.root / "rag-ime.sqlite",
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=self.root / "agent-config",
                session_dir=self.root / "sessions",
                logs_dir=self.root / "logs",
            ),
        )
        self.room = self.service.create_room(
            {
                "title": "生产 WorkItem",
                "routingPolicy": "natural",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        self.participants = list(self.room["participants"])

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def test_room_scoped_create_list_get_and_reassign_have_stable_payloads(
        self,
    ) -> None:
        owner, accountable, other = self.participants
        created = self.service.create_room_work_item(
            str(self.room["id"]),
            {
                "objective": "检查个人记忆召回",
                "expectedOutput": "一份带证据的诊断",
                "acceptanceCriteria": ["包含复现步骤", "包含修复建议"],
                "currentOwnerParticipantId": owner["id"],
                "accountableParticipantId": accountable["id"],
                "createdByParticipantId": owner["id"],
                "clientMessageId": "work-create-1",
            },
        )

        self.assertEqual(
            created["schemaVersion"],
            "rag-ime.agent-room-work-item-create.v1",
        )
        self.assertTrue(created["ok"])
        self.assertEqual(created["roomId"], self.room["id"])
        item = created["workItem"]
        self.assertEqual(item["currentOwnerParticipantId"], owner["id"])
        self.assertEqual(
            item["accountableParticipantId"],
            accountable["id"],
        )

        listed = self.service.room_work_items(
            str(self.room["id"]),
            {"states": ["active"], "ownerParticipantId": owner["id"]},
        )
        self.assertEqual(
            listed["schemaVersion"],
            "rag-ime.agent-room-work-item-list.v1",
        )
        self.assertEqual([value["id"] for value in listed["items"]], [item["id"]])

        fetched = self.service.room_work_item(
            str(self.room["id"]),
            str(item["id"]),
        )
        self.assertEqual(
            fetched["schemaVersion"],
            "rag-ime.agent-room-work-item-get.v1",
        )
        self.assertEqual(fetched["workItem"]["id"], item["id"])
        self.assertEqual(
            [event["eventType"] for event in fetched["events"]],
            ["assigned"],
        )

        with self.assertRaisesRegex(
            ValueError,
            "only the current owner or accountable",
        ):
            self.service.reassign_room_work_item(
                str(self.room["id"]),
                str(item["id"]),
                {
                    "actorParticipantId": other["id"],
                    "targetParticipantId": accountable["id"],
                },
            )

        reassigned = self.service.reassign_room_work_item(
            str(self.room["id"]),
            str(item["id"]),
            {
                "actorParticipantId": accountable["id"],
                "targetParticipantId": other["id"],
                "reason": "由负责人正式转交",
            },
        )
        self.assertEqual(
            reassigned["schemaVersion"],
            "rag-ime.agent-room-work-item-reassign.v1",
        )
        self.assertEqual(
            reassigned["workItem"]["currentOwnerParticipantId"],
            other["id"],
        )

    @requires_loopback_bind
    def test_http_routes_create_list_get_and_reassign_work_items(self) -> None:
        owner, next_owner, _ = self.participants
        wrapper = SimpleNamespace(
            agent=self.service,
            management_security_settings=lambda: {
                "postRequiresJson": True,
                "sameOriginOnly": True,
                "requireToken": False,
            },
        )

        class Handler(DebugRequestHandler):
            pass

        Handler.service = wrapper
        Handler.static_dir = self.root
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        room_path = quote(str(self.room["id"]), safe="")
        base = (
            f"http://127.0.0.1:{server.server_port}"
            f"/api/agent/rooms/{room_path}/work-items"
        )
        try:
            create = Request(
                base,
                data=json.dumps(
                    {
                        "objective": "通过 Control API 创建任务",
                        "expectedOutput": "可追踪结果",
                        "acceptanceCriteria": ["任务可通过 HTTP 创建、查询并重新分派"],
                        "currentOwnerParticipantId": owner["id"],
                        "clientMessageId": "http-work-create",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(create, timeout=5) as response:
                created = json.load(response)
            work_item_id = str(created["workItem"]["id"])

            with urlopen(f"{base}?state=active", timeout=5) as response:
                listed = json.load(response)
            self.assertEqual(
                [item["id"] for item in listed["items"]],
                [work_item_id],
            )

            item_path = quote(work_item_id, safe="")
            with urlopen(f"{base}/{item_path}", timeout=5) as response:
                fetched = json.load(response)
            self.assertEqual(fetched["workItem"]["id"], work_item_id)

            reassign = Request(
                f"{base}/{item_path}/reassign",
                data=json.dumps(
                    {
                        "actorParticipantId": owner["id"],
                        "targetParticipantId": next_owner["id"],
                        "reason": "HTTP 接线验证",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(reassign, timeout=5) as response:
                reassigned = json.load(response)
            self.assertEqual(
                reassigned["workItem"]["currentOwnerParticipantId"],
                next_owner["id"],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @requires_loopback_bind
    def test_http_routes_add_remove_and_permanently_delete_room_membership(self) -> None:
        room = self.service.create_room(
            {
                "title": "HTTP 成员生命周期",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        wrapper = SimpleNamespace(
            agent=self.service,
            management_security_settings=lambda: {
                "postRequiresJson": True,
                "sameOriginOnly": True,
                "requireToken": False,
            },
        )

        class Handler(DebugRequestHandler):
            pass

        Handler.service = wrapper
        Handler.static_dir = self.root
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        room_path = quote(str(room["id"]), safe="")
        base = f"http://127.0.0.1:{server.server_port}/api/agent/rooms/{room_path}"
        try:
            add = Request(
                f"{base}/participants",
                data=json.dumps({"roleId": "companion-future-v1", "roleVersion": "1"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(add, timeout=5) as response:
                added = json.load(response)
            participant_id = str(added["participant"]["id"])
            self.assertEqual(added["participant"]["displayName"], "澄·远")

            remove = Request(
                f"{base}/participants",
                data=json.dumps({"participantId": participant_id}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="PATCH",
            )
            with urlopen(remove, timeout=5) as response:
                removed = json.load(response)
            self.assertEqual(removed["participant"]["status"], "removed")

            self.service.update_room(str(room["id"]), {"archived": True})
            delete = Request(
                base,
                data=json.dumps({"confirmTitle": room["title"]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="DELETE",
            )
            with urlopen(delete, timeout=5) as response:
                deleted = json.load(response)
            self.assertEqual(deleted["roomId"], room["id"])
            self.assertNotIn(
                room["id"],
                [value["id"] for value in self.service.list_rooms({"includeArchived": True})["items"]],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_create_and_reassign_reject_participants_outside_the_room(self) -> None:
        owner = self.participants[0]
        second_room = self.service.create_room(
            {
                "title": "另一个 Room",
                "routingPolicy": "natural",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        outsider = second_room["participants"][0]

        with self.assertRaisesRegex(ValueError, "active members of the room"):
            self.service.create_room_work_item(
                str(self.room["id"]),
                {
                    "objective": "错误归属",
                    "expectedOutput": "不应创建",
                    "acceptanceCriteria": ["不应越过 Room 成员边界"],
                    "currentOwnerParticipantId": outsider["id"],
                    "clientMessageId": "outside-owner",
                },
            )
        item = self.service.create_room_work_item(
            str(self.room["id"]),
            {
                "objective": "合法任务",
                "expectedOutput": "结果",
                "acceptanceCriteria": ["结果已产生"],
                "currentOwnerParticipantId": owner["id"],
                "clientMessageId": "inside-owner",
            },
        )["workItem"]
        with self.assertRaisesRegex(ValueError, "active room participants"):
            self.service.reassign_room_work_item(
                str(self.room["id"]),
                str(item["id"]),
                {
                    "actorParticipantId": owner["id"],
                    "targetParticipantId": outsider["id"],
                },
            )

    def test_active_room_snapshot_repairs_legacy_archived_participant_sessions(
        self,
    ) -> None:
        session_id = str(self.participants[0]["sessionId"])
        self.service.sessions.archive(session_id, archived=True)

        self.assertEqual(self.service.sessions.get(session_id)["status"], "archived")
        snapshot = self.service.room_snapshot(str(self.room["id"]))

        self.assertTrue(snapshot["ok"])
        self.assertEqual(self.service.sessions.get(session_id)["status"], "idle")

    def test_restoring_room_repairs_participant_sessions_archived_while_room_was_closed(
        self,
    ) -> None:
        room_id = str(self.room["id"])
        session_ids = [str(value["sessionId"]) for value in self.participants]

        archived = self.service.update_room(room_id, {"archived": True})
        self.assertEqual(archived["room"]["status"], "archived")
        self.assertEqual(
            [self.service.sessions.get(value)["status"] for value in session_ids],
            ["idle"] * len(session_ids),
        )
        self.service.update_session(session_ids[0], {"archived": True})
        self.assertEqual(self.service.sessions.get(session_ids[0])["status"], "archived")

        restored = self.service.update_room(room_id, {"archived": False})
        self.assertEqual(restored["room"]["status"], "active")
        self.assertEqual(
            [self.service.sessions.get(value)["status"] for value in session_ids],
            ["idle"] * len(session_ids),
        )

    def test_room_participant_session_cannot_be_archived_directly(self) -> None:
        session_id = str(self.participants[0]["sessionId"])

        with self.assertRaisesRegex(ValueError, "cannot be archived directly"):
            self.service.update_session(session_id, {"archived": True})

        self.assertEqual(self.service.sessions.get(session_id)["status"], "idle")

    def test_create_idempotency_rejects_changed_task_constraints(self) -> None:
        owner, accountable, _ = self.participants
        payload = {
            "objective": "验证完整创建幂等",
            "expectedOutput": "稳定任务",
            "acceptanceCriteria": ["必须有测试"],
            "currentOwnerParticipantId": owner["id"],
            "accountableParticipantId": accountable["id"],
            "createdByParticipantId": owner["id"],
            "clientMessageId": "full-idempotency",
            "state": "active",
            "depth": 1,
        }
        first = self.service.create_room_work_item(
            str(self.room["id"]),
            payload,
        )
        replay = self.service.create_room_work_item(
            str(self.room["id"]),
            payload,
        )
        self.assertEqual(
            replay["workItem"]["id"],
            first["workItem"]["id"],
        )

        with self.assertRaisesRegex(
            ValueError,
            "different room work item",
        ):
            self.service.create_room_work_item(
                str(self.room["id"]),
                {
                    **payload,
                    "acceptanceCriteria": ["必须有测试", "必须有审计"],
                },
            )

    def test_create_requires_at_least_one_acceptance_criterion(self) -> None:
        owner = self.participants[0]

        with self.assertRaisesRegex(
            ValueError,
            "acceptance_criteria must not be empty",
        ):
            self.service.create_room_work_item(
                str(self.room["id"]),
                {
                    "objective": "不能在没有验收条件时开工",
                    "expectedOutput": "拒绝创建",
                    "currentOwnerParticipantId": owner["id"],
                    "clientMessageId": "missing-acceptance",
                },
            )

    def test_dispatch_claim_fails_closed_after_reassignment(self) -> None:
        owner, next_owner, _ = self.participants
        item = self.service.create_room_work_item(
            str(self.room["id"]),
            {
                "objective": "验证派发一致性",
                "expectedOutput": "只交给正式 owner",
                "acceptanceCriteria": ["只有正式 owner 收到派发"],
                "currentOwnerParticipantId": owner["id"],
                "clientMessageId": "claim-race",
            },
        )["workItem"]
        stale_assignment_key = str(item["assignmentKey"])
        stale_accepted_turn_id = str(item["acceptedTurnId"])

        self.service.reassign_room_work_item(
            str(self.room["id"]),
            str(item["id"]),
            {
                "actorParticipantId": owner["id"],
                "targetParticipantId": next_owner["id"],
            },
        )

        with self.assertRaisesRegex(
            AgentRoomWorkAssignmentChanged,
            "changed before dispatch",
        ):
            self.service.room_work.claim_dispatch(
                str(item["id"]),
                room_id=str(self.room["id"]),
                owner_participant_id=str(owner["id"]),
                assignment_key=stale_assignment_key,
                previous_accepted_turn_id=stale_accepted_turn_id,
                room_turn_id="room-turn:stale",
            )

        current = self.service.room_work.get(
            str(item["id"]),
            room_id=str(self.room["id"]),
        )
        self.assertEqual(
            current["currentOwnerParticipantId"],
            next_owner["id"],
        )
        self.assertEqual(current["acceptedTurnId"], "")

    def test_service_does_not_prompt_stale_owner_when_assignment_races(
        self,
    ) -> None:
        owner, next_owner, _ = self.participants
        item = self.service.create_room_work_item(
            str(self.room["id"]),
            {
                "objective": "路由前发生移交",
                "expectedOutput": "旧 owner 不应收到任务",
                "acceptanceCriteria": ["旧 owner 未收到任务"],
                "currentOwnerParticipantId": owner["id"],
                "clientMessageId": "dispatch-race",
            },
        )["workItem"]
        original_claim = self.service.room_work.claim_dispatch

        def race_reassignment(work_item_id: str, **kwargs: object) -> object:
            self.service.room_work.reassign(
                work_item_id,
                actor_participant_id=str(owner["id"]),
                current_owner_participant_id=str(next_owner["id"]),
                reason="模拟 route read 后的并发移交",
            )
            return original_claim(work_item_id, **kwargs)

        with (
            patch.object(
                self.service.room_work,
                "claim_dispatch",
                side_effect=race_reassignment,
            ),
            patch.object(self.service, "prompt") as prompt,
            self.assertRaisesRegex(
                AgentRoomWorkAssignmentChanged,
                "changed before dispatch",
            ),
        ):
            self.service.post_room_message(
                str(self.room["id"]),
                {
                    "message": "开始处理",
                    "workItemId": item["id"],
                },
            )

        prompt.assert_not_called()
        current = self.service.room_work.get(
            str(item["id"]),
            room_id=str(self.room["id"]),
        )
        self.assertEqual(
            current["currentOwnerParticipantId"],
            next_owner["id"],
        )

    def test_failed_runtime_dispatch_restores_previous_claim_cursor(self) -> None:
        owner = self.participants[0]
        item = self.service.create_room_work_item(
            str(self.room["id"]),
            {
                "objective": "派发失败可恢复",
                "expectedOutput": "保留明确审计",
                "acceptanceCriteria": ["派发游标恢复且留下审计"],
                "currentOwnerParticipantId": owner["id"],
                "clientMessageId": "dispatch-failure",
            },
        )["workItem"]

        with (
            patch.object(
                self.service,
                "prompt",
                side_effect=RuntimeError("runtime unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "runtime unavailable"),
        ):
            self.service.post_room_message(
                str(self.room["id"]),
                {
                    "message": "开始处理",
                    "workItemId": item["id"],
                },
            )

        current = self.service.room_work.get(
            str(item["id"]),
            room_id=str(self.room["id"]),
        )
        self.assertEqual(current["acceptedTurnId"], "")
        events = self.service.room_work.list_events(str(item["id"]))
        self.assertEqual(
            [event["eventType"] for event in events],
            ["assigned", "accepted", "assignment_failed"],
        )

    def test_work_item_is_ephemeral_task_context_not_role_book_content(
        self,
    ) -> None:
        owner = self.participants[0]
        objective = "只在本轮检查向量召回漂移"
        item = self.service.create_room_work_item(
            str(self.room["id"]),
            {
                "objective": objective,
                "expectedOutput": "输出一份对照表",
                "acceptanceCriteria": ["不得改写角色身份"],
                "currentOwnerParticipantId": owner["id"],
                "clientMessageId": "ephemeral-work-context",
            },
        )["workItem"]

        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": "turn:ephemeral-work-context"},
        ) as prompt:
            self.service.post_room_message(
                str(self.room["id"]),
                {
                    "message": "开始",
                    "workItemId": item["id"],
                },
            )

        prompt_payload = prompt.call_args.args[1]
        self.assertEqual(prompt_payload["message"], "开始")
        transient_context = str(prompt_payload["_transientContext"])
        self.assertIn(objective, transient_context)
        self.assertIn("当前受管任务", transient_context)
        self.assertNotIn(str(item["id"]), transient_context)
        self.assertNotIn("revision=", transient_context)
        session = self.service.sessions.get(str(owner["sessionId"]))
        role_book = self.service.role_books.routing_profile(
            str(owner["roleId"]),
            str(owner["roleVersion"]),
            str(session["roleBookRevisionId"]),
        )
        self.assertNotIn(objective, str(role_book))


if __name__ == "__main__":
    unittest.main()
