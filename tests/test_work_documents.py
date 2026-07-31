from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_context_runtime import AgentContextRuntime
from rag_ime.agent_room_work import AgentRoomWorkStore
from rag_ime.agent_rooms import AgentRoomStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.control_api.route_policy import ControlPathId, default_route_policy
from rag_ime.control_api.route_table import find_route
from rag_ime.work_documents import WorkDocumentError, WorkDocumentService


class WorkDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-work-documents-")
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.session = self.sessions.create(title="work-document owner")
        self.session_id = str(self.session["id"])
        self.context_runtime = AgentContextRuntime(self.db_path)
        self.context_runtime.initialize()
        self.service = WorkDocumentService(
            self.db_path,
            sessions=self.sessions,
            context_runtime=self.context_runtime,
        )
        self.service.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _plan_document(self, name: str = "plan") -> tuple[dict[str, object], dict[str, object], str]:
        plan = self.sessions.mutate_agent_plan(
            self.session_id,
            {
                "action": "save",
                "title": f"{name} authority",
                "items": [{"title": "deliver", "status": "pending"}],
            },
        )["plan"]
        relative = f"docs/drafts/{name}.md"
        source = self.root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        content = f"# {name}\n\ncanonical work\n"
        source.write_text(content, encoding="utf-8")
        command = self.service.register(
            {
                "authorityKind": "session_plan",
                "authorityId": self.session_id,
                "authorityRevision": plan["revision"],
                "workspaceRoot": str(self.root),
                "sourcePath": relative,
                "title": name,
            }
        )
        return plan, command["document"], content

    def _cancel_plan(self, plan: dict[str, object]) -> tuple[dict[str, object], str]:
        cancelled = self.sessions.mutate_agent_plan(
            self.session_id,
            {"action": "cancel", "expectedRevision": plan["revision"]},
        )["plan"]
        return cancelled, self._latest_event_id("agent_plan_state_events", "session_id", self.session_id)

    def _latest_event_id(self, table: str, column: str, value: str) -> str:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT event_id FROM {table} WHERE {column}=? ORDER BY sequence DESC LIMIT 1",
                (value,),
            ).fetchone()
        assert row is not None
        return str(row[0])

    def _durable_operation_state(self, receipt_id: str) -> tuple[str, str, str, str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT receipt.status,outbox.state,receipt.operation_key,outbox.operation_key
                FROM work_document_operation_receipts receipt
                JOIN work_document_outbox outbox
                  ON outbox.operation_key=receipt.operation_key
                WHERE receipt.receipt_id=?
                """,
                (receipt_id,),
            ).fetchone()
        assert row is not None
        return str(row[0]), str(row[1]), str(row[2]), str(row[3])

    def test_routes_are_canonical_contract_bound_and_local_only(self) -> None:
        list_route = find_route("GET", "/api/agent/work-documents")
        history_route = find_route(
            "GET", "/api/agent/work-documents/history/search"
        )
        register_route = find_route("POST", "/api/agent/work-documents")
        self.assertIsNotNone(list_route)
        self.assertIsNotNone(history_route)
        self.assertIsNotNone(register_route)
        self.assertEqual(list_route.response_contract, "work-document-list.v1.json")
        self.assertEqual(history_route.response_contract, "work-document-list.v1.json")
        self.assertEqual(register_route.response_contract, "work-document-command.v1.json")
        self.assertEqual(register_route.status, 201)

        manifest = {
            item["pathId"]: item
            for item in default_route_policy().manifest(include_targets=True)
        }
        for path_id in (
            ControlPathId.WORK_DOCUMENTS_LIST,
            ControlPathId.WORK_DOCUMENTS_HISTORY_SEARCH,
            ControlPathId.WORK_DOCUMENT_GET,
            ControlPathId.WORK_DOCUMENT_REGISTER,
            ControlPathId.WORK_DOCUMENT_ARCHIVE,
            ControlPathId.WORK_DOCUMENT_REPAIR,
            ControlPathId.WORK_DOCUMENT_REOPEN,
            ControlPathId.WORK_DOCUMENT_ERASE_PREVIEW,
            ControlPathId.WORK_DOCUMENT_ERASE,
        ):
            entry = manifest[path_id.value]
            self.assertFalse(entry["remoteSafe"])
            self.assertIsNone(entry["target"]["8768"])


    def test_deterministic_active_archive_history_context_and_duplicate_receipt(self) -> None:
        plan, document, _content = self._plan_document("deterministic")
        document_id = str(document["documentId"])
        expected_active = f"docs/agent/work/active/session_plan/{document_id}.md"
        expected_archive = f"docs/agent/work/archive/session_plan/{document_id}.md"
        self.assertEqual(document["path"], expected_active)
        self.assertTrue((self.root / expected_active).is_file())
        self.assertEqual(self.service.list()["total"], 1)
        self.assertEqual(len(self.service.context_discovery()["items"]), 1)

        _cancelled, receipt_id = self._cancel_plan(plan)
        first = self.service.request_archive(
            document_id, {"terminalReceiptId": receipt_id}
        )
        duplicate = self.service.request_archive(
            document_id, {"terminalReceiptId": receipt_id}
        )

        self.assertEqual(first["document"]["path"], expected_archive)
        self.assertEqual(first["document"]["state"], "archived")
        self.assertTrue(duplicate["receipt"]["idempotent"])
        self.assertEqual(first["receipt"]["status"], "applied")
        self.assertEqual(duplicate["receipt"]["status"], "applied")
        self.assertEqual(self.service.list()["total"], 0)
        self.assertEqual(self.service.context_discovery()["items"], [])
        history = self.service.history_search(query="deterministic")
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["items"][0]["documentId"], document_id)
        self.assertEqual(self.service.detail(document_id)["document"]["state"], "archived")
        with sqlite3.connect(self.db_path) as conn:
            terminal_count = conn.execute(
                "SELECT COUNT(*) FROM work_document_terminal_receipts WHERE authority_id=?",
                (self.session_id,),
            ).fetchone()[0]
            archive_count = conn.execute(
                "SELECT COUNT(*) FROM work_document_outbox WHERE document_id=? AND operation='archive'",
                (document_id,),
            ).fetchone()[0]
        self.assertEqual((terminal_count, archive_count), (1, 1))

    def test_register_idempotency_is_bound_to_authority_content_and_title(self) -> None:
        plan, document, _content = self._plan_document("idempotency")
        payload = {
            "authorityKind": "session_plan",
            "authorityId": self.session_id,
            "authorityRevision": plan["revision"],
            "workspaceRoot": str(self.root),
            "sourcePath": document["path"],
            "title": "idempotency",
        }

        exact_replay = self.service.register(payload)
        title_change = self.service.register({**payload, "title": "renamed"})
        title_replay = self.service.register({**payload, "title": "renamed"})

        self.assertTrue(exact_replay["receipt"]["idempotent"])
        self.assertFalse(title_change["receipt"]["idempotent"])
        self.assertTrue(title_replay["receipt"]["idempotent"])
        self.assertEqual(exact_replay["receipt"]["status"], "applied")
        self.assertEqual(title_change["receipt"]["status"], "applied")
        self.assertEqual(title_replay["receipt"]["status"], "applied")
        self.assertNotEqual(
            exact_replay["receipt"]["receiptId"],
            title_change["receipt"]["receiptId"],
        )
        self.assertEqual(
            title_change["receipt"]["receiptId"],
            title_replay["receipt"]["receiptId"],
        )
        self.assertEqual(
            exact_replay["document"]["documentRevision"],
            title_change["document"]["documentRevision"],
        )
        self.assertEqual(title_change["document"]["title"], "renamed")
        with sqlite3.connect(self.db_path) as conn:
            receipts = conn.execute(
                "SELECT status FROM work_document_operation_receipts "
                "WHERE document_id=? AND operation='register' ORDER BY receipt_id",
                (document["documentId"],),
            ).fetchall()
        self.assertEqual(receipts, [("applied",), ("applied",)])

    def test_terminal_revision_fence_rejects_stale_receipt_then_advances(self) -> None:
        plan, document, _content = self._plan_document("revision-fence")
        initial_receipt = self._latest_event_id(
            "agent_plan_state_events", "session_id", self.session_id
        )
        cancelled, terminal_receipt = self._cancel_plan(plan)
        with self.assertRaisesRegex(WorkDocumentError, "canonical"):
            self.service.request_archive(
                str(document["documentId"]),
                {"terminalReceiptId": initial_receipt},
            )
        archived = self.service.request_archive(
            str(document["documentId"]),
            {"terminalReceiptId": terminal_receipt},
        )["document"]
        self.assertEqual(archived["authorityRevision"], cancelled["revision"])
        self.assertGreater(archived["authorityRevision"], plan["revision"])

    def test_restart_recovers_move_completed_before_outbox_commit(self) -> None:
        plan, document, _content = self._plan_document("restart")
        _cancelled, receipt_id = self._cancel_plan(plan)
        pending = self.service.request_archive(
            str(document["documentId"]),
            {"terminalReceiptId": receipt_id},
            _reconcile=False,
        )["document"]
        source = self.root / str(pending["path"])
        target = self.root / str(pending["archivePath"])
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE work_document_outbox SET state='processing' WHERE document_id=? AND operation='archive'",
                (document["documentId"],),
            )

        restarted = WorkDocumentService(
            self.db_path,
            sessions=self.sessions,
            context_runtime=self.context_runtime,
        )
        restarted.initialize()
        recovered = restarted.detail(str(document["documentId"]))["document"]
        self.assertEqual(recovered["state"], "archived")
        self.assertEqual(recovered["path"], recovered["archivePath"])
        self.assertTrue(target.is_file())

    def test_activate_failure_receipt_is_durable_and_replays_failed(self) -> None:
        plan = self.sessions.mutate_agent_plan(
            self.session_id,
            {
                "action": "save",
                "title": "activate failure authority",
                "items": [{"title": "deliver", "status": "pending"}],
            },
        )["plan"]
        source = self.root / "docs/drafts/activate-failure.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# activate failure\n", encoding="utf-8")
        payload = {
            "authorityKind": "session_plan",
            "authorityId": self.session_id,
            "authorityRevision": plan["revision"],
            "workspaceRoot": str(self.root),
            "sourcePath": "docs/drafts/activate-failure.md",
            "title": "activate failure",
        }

        with patch(
            "rag_ime.work_documents._move",
            side_effect=OSError("injected activate reconciliation failure"),
        ):
            first = self.service.register(payload)

        self.assertEqual(first["document"]["state"], "error")
        self.assertEqual(first["receipt"]["status"], "failed")
        durable = self._durable_operation_state(
            str(first["receipt"]["receiptId"])
        )
        self.assertEqual(durable[:2], ("failed", "failed"))
        self.assertEqual(durable[2], durable[3])

        replay = self.service.register(payload)
        self.assertEqual(replay["document"]["state"], "error")
        self.assertEqual(replay["document"], first["document"])
        self.assertEqual(replay["receipt"]["status"], "failed")
        self.assertTrue(replay["receipt"]["idempotent"])
        self.assertEqual(replay["receipt"]["receiptId"], first["receipt"]["receiptId"])

    def test_archive_failure_receipt_is_durable_and_replays_failed(self) -> None:
        plan, document, _content = self._plan_document("archive-failure")
        _cancelled, terminal_receipt_id = self._cancel_plan(plan)
        payload = {"terminalReceiptId": terminal_receipt_id}

        with patch(
            "rag_ime.work_documents._move",
            side_effect=OSError("injected archive reconciliation failure"),
        ):
            first = self.service.request_archive(
                str(document["documentId"]),
                payload,
            )

        self.assertEqual(first["document"]["state"], "error")
        self.assertEqual(first["receipt"]["status"], "failed")
        durable = self._durable_operation_state(
            str(first["receipt"]["receiptId"])
        )
        self.assertEqual(durable[:2], ("failed", "failed"))
        self.assertEqual(durable[2], durable[3])

        replay = self.service.request_archive(
            str(document["documentId"]),
            payload,
        )
        self.assertEqual(replay["document"]["state"], "error")
        self.assertEqual(replay["document"], first["document"])
        self.assertEqual(replay["receipt"]["status"], "failed")
        self.assertTrue(replay["receipt"]["idempotent"])
        self.assertEqual(replay["receipt"]["receiptId"], first["receipt"]["receiptId"])

    def test_reopen_failure_receipt_is_durable_and_replays_failed(self) -> None:
        plan, document, _content = self._plan_document("reopen-failure")
        cancelled, terminal_receipt_id = self._cancel_plan(plan)
        archived = self.service.request_archive(
            str(document["documentId"]),
            {"terminalReceiptId": terminal_receipt_id},
        )
        self.assertEqual(archived["receipt"]["status"], "applied")
        reset = self.sessions.mutate_agent_plan(
            self.session_id,
            {"action": "reset", "expectedRevision": cancelled["revision"]},
        )["plan"]
        transition_receipt_id = self._latest_event_id(
            "agent_plan_state_events",
            "session_id",
            self.session_id,
        )
        payload = {
            "authorityRevision": reset["revision"],
            "transitionReceiptId": transition_receipt_id,
        }

        with patch(
            "rag_ime.work_documents._move",
            side_effect=OSError("injected reopen reconciliation failure"),
        ):
            first = self.service.reopen(str(document["documentId"]), payload)

        self.assertEqual(first["document"]["state"], "error")
        self.assertEqual(first["receipt"]["status"], "failed")
        durable = self._durable_operation_state(
            str(first["receipt"]["receiptId"])
        )
        self.assertEqual(durable[:2], ("failed", "failed"))
        self.assertEqual(durable[2], durable[3])

        replay = self.service.reopen(str(document["documentId"]), payload)
        self.assertEqual(replay["document"]["state"], "error")
        self.assertEqual(replay["document"], first["document"])
        self.assertEqual(replay["receipt"]["status"], "failed")
        self.assertTrue(replay["receipt"]["idempotent"])
        self.assertEqual(replay["receipt"]["receiptId"], first["receipt"]["receiptId"])

    def test_observer_failure_is_durable_without_outbox_and_restart_retries(self) -> None:
        plan, document, content = self._plan_document("observer-failure")
        _cancelled, _receipt_id = self._cancel_plan(plan)
        active_path = self.root / str(document["path"])
        active_path.unlink()

        with self.assertRaises(FileNotFoundError):
            self.service.observe_authority("session_plan", self.session_id)
        with sqlite3.connect(self.db_path) as conn:
            failure = conn.execute(
                "SELECT state,attempt_count,error FROM work_document_observer_failures WHERE authority_key=?",
                (f"session_plan:{self.session_id}",),
            ).fetchone()
            archive_count = conn.execute(
                "SELECT COUNT(*) FROM work_document_outbox WHERE document_id=? AND operation='archive'",
                (document["documentId"],),
            ).fetchone()[0]
        self.assertEqual(failure[0], "failed")
        self.assertEqual(failure[1], 1)
        self.assertTrue(failure[2])
        self.assertEqual(archive_count, 0)
        self.assertEqual(self.service.detail(str(document["documentId"]))["document"]["state"], "error")

        active_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.write_text(content, encoding="utf-8")
        restarted = WorkDocumentService(
            self.db_path,
            sessions=self.sessions,
            context_runtime=self.context_runtime,
        )
        restarted.initialize()
        self.assertEqual(
            restarted.detail(str(document["documentId"]))["document"]["state"],
            "archived",
        )
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT state FROM work_document_observer_failures WHERE authority_key=?",
                    (f"session_plan:{self.session_id}",),
                ).fetchone()[0],
                "applied",
            )

    def test_failed_outbox_repairs_then_history_reopens_idempotently(self) -> None:
        plan, document, content = self._plan_document("repair-reopen")
        cancelled, receipt_id = self._cancel_plan(plan)
        pending = self.service.request_archive(
            str(document["documentId"]),
            {"terminalReceiptId": receipt_id},
            _reconcile=False,
        )["document"]
        active_path = self.root / str(pending["path"])
        active_path.write_text("changed after staging", encoding="utf-8")
        self.service.reconcile(str(document["documentId"]), observe_authorities=False)
        self.assertEqual(
            self.service.detail(str(document["documentId"]))["document"]["state"],
            "error",
        )
        active_path.write_text(content, encoding="utf-8")
        repaired = self.service.repair(str(document["documentId"]))
        self.assertEqual(repaired["document"]["state"], "archived")

        reset = self.sessions.mutate_agent_plan(
            self.session_id,
            {"action": "reset", "expectedRevision": cancelled["revision"]},
        )["plan"]
        transition_id = self._latest_event_id(
            "agent_plan_state_events", "session_id", self.session_id
        )
        reopened = self.service.reopen(
            str(document["documentId"]),
            {
                "authorityRevision": reset["revision"],
                "transitionReceiptId": transition_id,
            },
        )
        duplicate = self.service.reopen(
            str(document["documentId"]),
            {
                "authorityRevision": reset["revision"],
                "transitionReceiptId": transition_id,
            },
        )
        self.assertEqual(reopened["document"]["state"], "active")
        self.assertTrue(duplicate["receipt"]["idempotent"])
        self.assertEqual(reopened["receipt"]["status"], "applied")
        self.assertEqual(duplicate["receipt"]["status"], "applied")
        self.assertEqual(self.service.history_search()["total"], 0)
        self.assertEqual(self.service.list()["total"], 1)

    def test_goal_and_room_terminal_observation_archive_exactly_once(self) -> None:
        goal = self.sessions.mutate_agent_goal(
            self.session_id,
            {
                "action": "confirm_setup",
                "confirmed": True,
                "expectedRevision": 0,
                "objective": "finish governed work",
                "successCriteria": "receipt exists",
                "evidenceExpectations": ["receipt"],
                "tokenBudget": 1000,
                "timeBudgetMs": 60000,
            },
        )["workflow"]["goal"]
        goal_source = self.root / "docs/drafts/goal.md"
        goal_source.parent.mkdir(parents=True, exist_ok=True)
        goal_source.write_text("# Goal\n", encoding="utf-8")
        goal_document = self.service.register(
            {
                "authorityKind": "session_goal",
                "authorityId": goal["goalId"],
                "authorityRevision": goal["revision"],
                "workspaceRoot": str(self.root),
                "sourcePath": "docs/drafts/goal.md",
            }
        )["document"]
        self.sessions.mutate_agent_goal(
            self.session_id,
            {
                "action": "cancel",
                "expectedRevision": goal["revision"],
                "reason": "scope closed",
            },
        )
        self.service.observe_authority("session_goal", str(goal["goalId"]))
        self.service.observe_authority("session_goal", str(goal["goalId"]))
        self.assertEqual(
            self.service.detail(str(goal_document["documentId"]))["document"]["state"],
            "archived",
        )

        worker_session = self.sessions.create(title="room worker")
        rooms = AgentRoomStore(self.db_path, room_dir=self.root / "rooms")
        rooms.initialize()
        room = rooms.create(
            title="work document room",
            routing_policy="moderator",
            participants=[
                {
                    "sessionId": self.session_id,
                    "roleId": "coordinator",
                    "roleVersion": "1",
                    "displayName": "Coordinator",
                    "collaborationRole": "coordinator",
                },
                {
                    "sessionId": worker_session["id"],
                    "roleId": "worker",
                    "roleVersion": "1",
                    "displayName": "Worker",
                    "collaborationRole": "implementer",
                },
            ],
        )
        room_work = AgentRoomWorkStore(
            self.db_path, terminal_observer=self.service.observe_authority
        )
        room_work.initialize()
        item = room_work.create(
            room_id=str(room["id"]),
            objective="deliver artifact",
            expected_output="verified artifact",
            current_owner_participant_id=str(room["participants"][1]["id"]),
            created_by_participant_id=str(room["participants"][0]["id"]),
            accountable_participant_id=str(room["participants"][0]["id"]),
            client_message_id="work-document-room-item",
            acceptance_criteria=["artifact exists"],
        )
        room_source = self.root / "docs/drafts/room.md"
        room_source.write_text("# Room work\n", encoding="utf-8")
        room_document = self.service.register(
            {
                "authorityKind": "room_work_item",
                "authorityId": item["id"],
                "authorityRevision": 1,
                "workspaceRoot": str(self.root),
                "sourcePath": "docs/drafts/room.md",
            }
        )["document"]
        room_work.submit(
            str(worker_session["id"]),
            {
                "workId": item["id"],
                "resultSummary": "delivered",
                "artifactRefs": ["docs/drafts/room.md"],
            },
        )
        room_work.accept(self.session_id, {"workId": item["id"]})
        self.assertEqual(
            self.service.detail(str(room_document["documentId"]))["document"]["state"],
            "archived",
        )
        with sqlite3.connect(self.db_path) as conn:
            room_archives = conn.execute(
                "SELECT COUNT(*) FROM work_document_outbox WHERE document_id=? AND operation='archive'",
                (room_document["documentId"],),
            ).fetchone()[0]
        self.assertEqual(room_archives, 1)

        failed_item = room_work.create(
            room_id=str(room["id"]),
            objective="surface failed work",
            expected_output="failure evidence",
            current_owner_participant_id=str(room["participants"][1]["id"]),
            created_by_participant_id=str(room["participants"][0]["id"]),
            accountable_participant_id=str(room["participants"][0]["id"]),
            client_message_id="work-document-room-failure",
            acceptance_criteria=["failure is retained"],
        )
        failed_source = self.root / "docs/drafts/room-failed.md"
        failed_source.write_text("# Failed Room work\n", encoding="utf-8")
        failed_document = self.service.register(
            {
                "authorityKind": "room_work_item",
                "authorityId": failed_item["id"],
                "authorityRevision": 1,
                "workspaceRoot": str(self.root),
                "sourcePath": "docs/drafts/room-failed.md",
            }
        )["document"]
        room_work.escalate(
            str(worker_session["id"]),
            {
                "workId": failed_item["id"],
                "reason": "provider failed permanently",
                "nextStep": "retain evidence",
            },
        )
        self.assertEqual(
            self.service.detail(str(failed_document["documentId"]))["document"]["state"],
            "archived",
        )

    def test_erase_requires_current_hash_bound_approval(self) -> None:
        _plan, document, content = self._plan_document("erase")
        document_id = str(document["documentId"])
        preview = self.service.erase_preview(
            document_id, {"sessionId": self.session_id}
        )
        with self.assertRaisesRegex(WorkDocumentError, "approval"):
            self.service.erase(
                document_id,
                {
                    "sessionId": self.session_id,
                    "approvalId": preview["approval"]["approvalId"],
                    "payloadSha256": preview["payloadSha256"],
                },
            )
        self.sessions.decide_approval(
            str(preview["approval"]["approvalId"]),
            approved=True,
            payload_sha256=str(preview["payloadSha256"]),
        )
        path = self.root / str(document["path"])
        path.write_text("changed after approval", encoding="utf-8")
        with self.assertRaisesRegex(WorkDocumentError, "changed"):
            self.service.erase(
                document_id,
                {
                    "sessionId": self.session_id,
                    "approvalId": preview["approval"]["approvalId"],
                    "payloadSha256": preview["payloadSha256"],
                },
            )
        path.write_text(content, encoding="utf-8")
        erased = self.service.erase(
            document_id,
            {
                "sessionId": self.session_id,
                "approvalId": preview["approval"]["approvalId"],
                "payloadSha256": preview["payloadSha256"],
            },
        )
        self.assertIsNone(erased["document"])
        self.assertFalse(path.exists())
        with self.assertRaises(KeyError):
            self.service.detail(document_id)


if __name__ == "__main__":
    unittest.main()
