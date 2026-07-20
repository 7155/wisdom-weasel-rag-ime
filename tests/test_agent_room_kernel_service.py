from __future__ import annotations

import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import Request, urlopen

from rag_ime.agent_room_kernel import RoomKernelFenceError
from rag_ime.agent_room_capabilities import ToolAuthorizationError
from rag_ime.agent_room_kernel_contracts import (
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    KERNEL_COMMAND_SCHEMA_VERSION,
    ROOM_COMMIT_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from rag_ime.agent_service import AgentService, _room_kernel_mode_from_environment
from rag_ime.debug_server import DebugRequestHandler


class KernelRuntime:
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"

    def __init__(self, root: Path) -> None:
        self.session_root = root / "sessions"
        self.default_model_profile = "pi/test"
        self.dispatched: list[str] = []
        self.cancelled: list[tuple[str, str, int]] = []
        self.stopped = False

    def runtime_status(self):
        return {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": True,
            "status": "ready",
            "capabilities": {"runtimePrimitives": {"roomTypes": True}},
        }

    def dispatch_room(self, payload, *, message: str, lease_token: str):
        del message, lease_token
        self.dispatched.append(str(payload["dispatchId"]))
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "dispatch_accepted",
            "status": "accepted",
            "rootId": payload["rootId"],
            "dispatchId": payload["dispatchId"],
            "generation": payload["generation"],
            "sessionId": payload["targetSessionId"],
            "turnId": "turn:kernel",
        }

    def cancel_room(self, *, session_id: str, root_id: str, generation: int):
        self.cancelled.append((session_id, root_id, generation))
        return {
            "schemaVersion": "wisdom-weasel.room-runtime-receipt.v1",
            "receiptKind": "cancel_applied",
            "status": "applied",
            "sessionId": session_id,
            "rootId": root_id,
            "generation": generation,
        }

    def stop(self):
        self.stopped = True


class KernelRuntimeFactory:
    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"
    default_model_profile = "pi/test"

    def __init__(self, root: Path) -> None:
        self.session_root = root / "sessions"
        self.runtime = KernelRuntime(root)

    def create(self, *_args, **_kwargs):
        return self.runtime

    def apply_policy(self, _policy):
        return None

    def reconfigure(self, _config):
        return None


class RoomKernelServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-kernel-service-")
        self.root = Path(self.tmp.name)
        self.factory = KernelRuntimeFactory(self.root)
        self.service = AgentService(
            db_path=self.root / "rag-ime.sqlite",
            runtime_factory=self.factory,
            room_kernel_mode="cohort",
            room_kernel_poll_seconds=60,
        )
        self.service.room_kernel_worker_loop.close()
        room = self.service.create_room(
            {
                "title": "Kernel cohort",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "zhiyou-v1", "roleVersion": "1"},
                    {"roleId": "hermes-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        self.room_id = str(room["id"])
        self.participant = room["participants"][1]
        self.session_id = str(self.participant["sessionId"])
        self._seed()

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def _seed(self) -> None:
        self.service.room_kernel.create_root(
            {
                "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
                "rootId": "root:service",
                "roomId": self.room_id,
                "generation": 0,
                "state": "running",
                "owner": str(self.participant["id"]),
                "requirementAnchorRef": "requirement-anchor:service@sha256:test",
                "createdByActorRef": "user:local",
                "terminalReceiptId": None,
                "activeProfileRef": None,
                "budgetPolicyRef": "room-budget:test-v1",
                "createdAtMs": 1,
            },
            budget=10,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=(),
            now_ms=1,
        )
        self.service.room_kernel.create_task(
            {
                "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
                "taskId": "task:service",
                "rootId": "root:service",
                "parentTaskId": None,
                "ownerParticipantId": str(self.participant["id"]),
                "assigneeParticipantId": str(self.participant["id"]),
                "objective": "Execute a bounded service test.",
                "expectedOutput": "A typed receipt.",
                "requirementItemIds": ["requirement:service"],
                "acceptanceCriterionIds": [],
                "revision": 0,
                "state": "active",
            },
            now_ms=2,
        )

    def _dispatch(self, dispatch_id: str = "dispatch:service") -> dict[str, object]:
        return {
            "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
            "dispatchId": dispatch_id,
            "rootId": "root:service",
            "taskId": "task:service",
            "parentDispatchId": None,
            "generation": 0,
            "hopCount": 0,
            "depth": 0,
            "budgetCost": 1,
            "targetSessionId": self.session_id,
            "targetParticipantId": str(self.participant["id"]),
            "triggerId": "trigger:service",
            "intentKind": "execute",
            "idempotencyKey": dispatch_id,
            "attempt": 0,
            "capabilityEpoch": 7,
            "runtimeProfileRevision": "runtime-profile:service-v1",
            "state": "pending",
        }

    def _cancel_command(self, *, generation: int = 0) -> dict[str, object]:
        return {
            "schemaVersion": KERNEL_COMMAND_SCHEMA_VERSION,
            "commandId": f"command:cancel:{generation}",
            "rootId": "root:service",
            "roomId": self.room_id,
            "commandKind": "cancel_root",
            "targetKind": "root",
            "targetId": "root:service",
            "sourceKind": "control_center",
            "sourceId": "control-center:test",
            "idempotencyKey": f"cancel:service:{generation}",
            "generation": generation,
            "payload": {},
            "createdAtMs": 20,
        }

    def _room_tool_invocation(self, call_id: str, content: str) -> str:
        loaded = self.service.room_capability_tool_load(
            {
                "sessionId": self.session_id,
                "receiptId": f"load:{call_id}",
                "toolName": "room_post",
                "createdAtMs": 29,
            }
        )["result"]
        result = self.service.execute_room_capability_tool(
            self.session_id,
            "room_post",
            {"content": content},
            tool_call_id=call_id,
            load_receipt_id=str(loaded["receiptId"]),
        )
        return str(result["invocationReceipt"]["receiptId"])

    def test_command_requires_server_authorization_and_current_room_generation(self) -> None:
        with self.assertRaises(PermissionError):
            self.service.apply_room_kernel_command(self.room_id, self._cancel_command())
        with self.assertRaisesRegex(RoomKernelFenceError, "generation is stale"):
            self.service.apply_room_kernel_command(
                self.room_id,
                self._cancel_command(generation=1),
                caller_authorized=True,
            )

        receipt = self.service.apply_room_kernel_command(
            self.room_id, self._cancel_command(), caller_authorized=True
        )

        self.assertEqual(receipt["receiptKind"], "root_cancelled")
        self.assertEqual(receipt["generation"], 1)
        snapshot = self.service.room_kernel_snapshot(self.room_id)
        self.assertEqual(snapshot["roots"][0]["state"], "cancelled")
        self.assertTrue(any(item["receiptId"] == receipt["receiptId"] for item in snapshot["receipts"]))

    def test_environment_cohort_requires_the_named_test_opt_in(self) -> None:
        with patch.dict("os.environ", {"RAG_IME_ROOM_KERNEL_MODE": "cohort"}, clear=True):
            self.assertEqual(_room_kernel_mode_from_environment(), "shadow")
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_ROOM_KERNEL_MODE": "cohort",
                "RAG_IME_ROOM_KERNEL_COHORT_ID": "room-v2-test",
            },
            clear=True,
        ):
            self.assertEqual(_room_kernel_mode_from_environment(), "cohort")

    def test_settle_bridge_requires_matching_settle_and_explicit_post(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:service",
            "dispatchId": "dispatch:service",
            "action": "post",
            "contentHash": "sha256:service",
            "postProposal": {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:service",
                "roomId": self.room_id,
                "rootId": "root:service",
                "generation": 0,
                "taskId": "task:service",
                "dispatchId": "dispatch:service",
                "authorActorRef": str(self.participant["id"]),
                "kind": "result",
                "visibility": "room",
                "content": "This text was explicitly committed.",
                "idempotencyKey": "post:service",
                "publicationSource": {"kind": "room_commit", "ref": "commit:service"},
                "createdAtMs": 30,
            },
            "evidenceRefs": ["test:service"],
            "requirementCoverage": [],
            "createdAtMs": 30,
        }
        bad_settle = {
            "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            "settleReceiptId": "settle:service",
            "eventKind": "message_completed",
            "status": "settled",
            "dispatchId": "dispatch:service",
            "sessionId": self.session_id,
            "generation": 0,
            "capabilityEpoch": 7,
            "createdAtMs": 30,
        }
        with self.assertRaisesRegex(RoomKernelFenceError, "agent_settled"):
            self.service.settle_room_kernel_dispatch(
                self.room_id,
                {"settleReceipt": bad_settle, "commit": commit},
                caller_authorized=True,
            )
        settle = {**bad_settle, "eventKind": "agent_settled"}
        invocation_receipt_id = self._room_tool_invocation(
            "call:settle-service", "This text was explicitly committed."
        )

        result = self.service.settle_room_kernel_dispatch(
            self.room_id,
            {"settleReceipt": settle, "commit": commit, "invocationReceiptId": invocation_receipt_id},
            caller_authorized=True,
        )

        self.assertEqual(result["receipt"]["status"], "applied")
        snapshot = self.service.room_kernel_snapshot(self.room_id)
        self.assertEqual([post["postId"] for post in snapshot["posts"]], ["post:service"])
        self.assertNotIn("This text", str(snapshot["sessions"]))

    def test_settle_rejects_invalid_post_before_persisting_commit(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:invalid-post",
            "dispatchId": "dispatch:service",
            "action": "post",
            "contentHash": "sha256:invalid-post",
            "postProposal": {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:wrong-room",
                "roomId": "room:wrong",
                "rootId": "root:service",
                "generation": 0,
                "dispatchId": "dispatch:service",
                "authorActorRef": str(self.participant["id"]),
                "kind": "result",
                "visibility": "room",
                "content": "Must not be committed.",
                "idempotencyKey": "post:wrong-room",
                "publicationSource": {"kind": "room_commit", "ref": "commit:invalid-post"},
                "createdAtMs": 31,
            },
            "evidenceRefs": [],
            "requirementCoverage": [],
            "createdAtMs": 31,
        }
        settle = {
            "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            "settleReceiptId": "settle:invalid-post",
            "eventKind": "agent_settled",
            "status": "settled",
            "dispatchId": "dispatch:service",
            "sessionId": self.session_id,
            "generation": 0,
            "capabilityEpoch": 7,
            "createdAtMs": 31,
        }
        invocation_receipt_id = self._room_tool_invocation(
            "call:invalid-post", "Must not be committed."
        )

        with self.assertRaisesRegex(RoomKernelFenceError, "RoomPost proposal"):
            self.service.settle_room_kernel_dispatch(
                self.room_id,
                {"settleReceipt": settle, "commit": commit, "invocationReceiptId": invocation_receipt_id},
                caller_authorized=True,
            )

        self.assertEqual(self.service.room_kernel.dispatch("dispatch:service")["state"], "running")
        self.assertEqual(self.service.room_kernel_snapshot(self.room_id)["posts"], [])

    def test_kernel_bound_message_completion_never_enters_legacy_room_timeline(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        before = len(self.service.rooms.list_events(self.room_id, limit=200))
        self.service.events.publish(
            self.session_id,
            "message_completed",
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "private reasoning"}]}},
            turn_id="turn:private",
        )
        after = self.service.rooms.list_events(self.room_id, limit=200)

        self.assertEqual(len(after), before)
        self.assertNotIn("private reasoning", str(self.service.room_kernel_snapshot(self.room_id)))

    def test_worker_lifecycle_is_stoppable(self) -> None:
        self.service.room_kernel_worker_loop.start()
        self.assertTrue(self.service.room_kernel_worker_loop.running)
        self.service.room_kernel_worker_loop.close()
        self.assertFalse(self.service.room_kernel_worker_loop.running)

    def test_capability_manifest_cuts_legacy_room_tool_to_one_kernel_path(self) -> None:
        self.service.room_kernel.enqueue_dispatch(self._dispatch(), now_ms=3)
        self.service.room_kernel_worker.run_once()
        tools = ("room_state", "room_post", "room_commit")
        bound = self.service.room_capabilities.manifest_for_runtime(self.session_id)
        self.assertIsNotNone(bound)
        self.assertEqual(bound[0]["dispatchId"], "dispatch:service")
        self.assertEqual(bound[1]["promptCompileReceiptId"], "prompt-compile:dispatch:service")
        self.assertEqual(
            [item["name"] for item in self.service._runtime_tool_manifest({"id": self.session_id})],
            list(tools),
        )
        loaded = self.service.room_capability_tool_load(
            {"sessionId": self.session_id, "receiptId": "load:service", "toolName": "room_post", "createdAtMs": 5}
        )["result"]
        legacy = self.service.execute_room_capability_tool(
            self.session_id, "room_send", {"content": "deliver", "targetParticipantId": "ignored"},
            tool_call_id="call:service", load_receipt_id=str(loaded["receiptId"]),
        )
        canonical = self.service.execute_room_capability_tool(
            self.session_id, "room_post", {"content": "deliver"},
            tool_call_id="call:service", load_receipt_id=str(loaded["receiptId"]),
        )
        self.assertEqual(legacy["invocationReceipt"], canonical["invocationReceipt"])
        self.assertFalse(legacy["result"]["executionPerformed"])
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": "commit:capability-service",
            "dispatchId": "dispatch:service",
            "action": "post",
            "contentHash": "sha256:deliver",
            "postProposal": {
                "schemaVersion": "wisdom-weasel.room-post.v2",
                "postId": "post:capability-service",
                "roomId": self.room_id,
                "rootId": "root:service",
                "generation": 0,
                "dispatchId": "dispatch:service",
                "authorActorRef": str(self.participant["id"]),
                "kind": "result",
                "visibility": "room",
                "content": "deliver",
                "idempotencyKey": "post:capability-service",
                "publicationSource": {"kind": "room_commit", "ref": "commit:capability-service"},
                "createdAtMs": 6,
            },
            "evidenceRefs": [],
            "requirementCoverage": [],
            "createdAtMs": 6,
        }
        settle = {
            "schemaVersion": ROOM_SETTLE_RECEIPT_SCHEMA_VERSION,
            "settleReceiptId": "settle:capability-service",
            "eventKind": "agent_settled",
            "status": "settled",
            "dispatchId": "dispatch:service",
            "sessionId": self.session_id,
            "generation": 0,
            "capabilityEpoch": 7,
            "createdAtMs": 6,
        }
        settle_payload = {
            "settleReceipt": settle,
            "commit": commit,
            "invocationReceiptId": canonical["invocationReceipt"]["receiptId"],
        }
        first_settle = self.service.settle_room_kernel_dispatch(
            self.room_id, settle_payload, caller_authorized=True,
        )
        replayed_settle = self.service.settle_room_kernel_dispatch(
            self.room_id, settle_payload, caller_authorized=True,
        )
        self.assertEqual(first_settle["receipt"], replayed_settle["receipt"])
        self.assertEqual(
            first_settle["executionReceipt"]["kernelReceiptId"],
            first_settle["receipt"]["receiptId"],
        )
        self.assertEqual(first_settle["executionReceipt"], replayed_settle["executionReceipt"])
        self.assertIsNone(self.service.execute_room_capability_tool(
            "ordinary-session", "room_send", {"content": "ordinary"}, tool_call_id="call:ordinary", load_receipt_id=""
        ))
        self.service.apply_room_kernel_command(
            self.room_id,
            self._cancel_command(),
            caller_authorized=True,
        )
        with self.assertRaises((RoomKernelFenceError, ToolAuthorizationError)):
            self.service.execute_room_capability_tool(
                self.session_id,
                "room_post",
                {"content": "late delivery"},
                tool_call_id="call:after-cancel",
                load_receipt_id=str(loaded["receiptId"]),
            )
        self.assertEqual(
            self.service.room_capabilities.runtime_binding(self.session_id, active_only=False)["state"],
            "revoked",
        )
        with self.assertRaises(ToolAuthorizationError):
            self.service.room_capabilities.authorize_runtime_invocation(
                session_id=self.session_id, receipt_id="invoke:revoked", invocation_key="call:revoked",
                load_receipt_id=str(loaded["receiptId"]), tool_name="room_post", arguments={"content": "no"}, created_at_ms=7,
            )

    def test_managed_dispatch_preparation_replays_after_crash_before_lease(self) -> None:
        dispatch = self._dispatch()
        self.service.room_kernel.enqueue_dispatch(dispatch, now_ms=3)

        first = self.service._prepare_managed_room_dispatch(dispatch, 3)
        prepared = self.service.room_capabilities.runtime_binding(
            self.session_id, active_only=False
        )
        self.assertEqual(prepared["state"], "prepared")
        with self.assertRaises(KeyError):
            self.service.room_kernel.lease("dispatch:service")
        self.assertEqual(self.factory.runtime.dispatched, [])

        replayed = self.service._prepare_managed_room_dispatch(dispatch, 99)
        self.assertEqual(first, replayed)
        self.service.room_kernel_worker.run_once()
        active = self.service.room_capabilities.runtime_binding(self.session_id)
        self.assertEqual(active["manifestHash"], first["manifestHash"])
        self.assertEqual(self.factory.runtime.dispatched, ["dispatch:service"])

        snapshot = self.service.room_kernel_snapshot(self.room_id)
        projected = next(item for item in snapshot["sessions"] if item["sessionId"] == self.session_id)
        self.assertEqual(projected["capabilityManifest"]["manifestHash"], first["manifestHash"])
        self.assertEqual(projected["capabilityManifest"]["status"], "active")

    def test_real_http_snapshot_command_and_sse_gap_routes(self) -> None:
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
        room_path = quote(self.room_id, safe="")
        base = f"http://127.0.0.1:{server.server_port}/api/agent/rooms/{room_path}/kernel"
        try:
            with urlopen(f"{base}/snapshot", timeout=5) as response:
                snapshot = json.load(response)
            self.assertEqual(snapshot["roots"][0]["rootId"], "root:service")

            request = Request(
                f"{base}/commands",
                data=json.dumps(self._cancel_command()).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                receipt = json.load(response)
            self.assertEqual(receipt["receiptKind"], "root_cancelled")

            gap_token = quote(f"{self.room_id}#999", safe="")
            with urlopen(f"{base}/events?afterEventId={gap_token}", timeout=5) as response:
                lines = []
                while True:
                    line = response.readline().decode("utf-8")
                    lines.append(line)
                    if line == "\n":
                        break
                event_stream = "".join(lines)
            self.assertIn("event: snapshot_required", event_stream)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
