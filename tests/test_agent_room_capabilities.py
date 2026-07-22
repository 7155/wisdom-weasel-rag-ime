from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_capabilities import (
    CapabilityManifestConflict,
    RoomCapabilityManifestStore,
    ToolAuthorizationError,
    validate_room_tool_command,
    room_runtime_registry,
)


class RoomCapabilityManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-capability-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RoomCapabilityManifestStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_manifest_separates_available_authorized_and_public_surface(self) -> None:
        manifest = self._compile(
            user=("room_state", "room_post"),
            state=("room_state", "room_post", "room_commit"),
        )
        tools = {tool["name"]: tool for tool in manifest["tools"]}
        self.assertEqual(tuple(tools), ("room_state", "room_post", "room_commit"))
        self.assertTrue(tools["room_state"]["available"])
        self.assertTrue(tools["room_post"]["authorized"])
        self.assertFalse(tools["room_commit"]["authorized"])
        self.assertIn("userAuthorization", tools["room_commit"]["deniedBy"])
        self.assertNotIn("room_assign", tools)
        self.assertNotIn("filesystem_write", tools)

        room, participant = self._bindings()
        readonly, _ = self.store.compile_manifest(
            manifest_id="manifest:readonly", room_binding={**room, "access": "read"},
            participant_binding=participant, dispatch_id="dispatch:1",
            runtime_registry=self._registry(),
            user_authorized=tuple(tools), template_allowed=tuple(tools),
            role_allowed=tuple(tools), profile_allowed=tuple(tools),
            state_allowed=tuple(tools), created_at_ms=2,
        )
        readonly_tools = {tool["name"]: tool for tool in readonly["tools"]}
        self.assertTrue(readonly_tools["room_state"]["authorized"])
        self.assertFalse(readonly_tools["room_post"]["authorized"])

    def test_progressive_search_discloses_catalog_then_loads_exactly_one_schema(self) -> None:
        manifest = self._compile()
        catalog_keys = {"name", "when", "notFor", "input", "output", "does"}
        searched, _ = self.store.tool_search(
            receipt_id="search:1", manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"], query="Room", created_at_ms=2,
        )
        self.assertGreaterEqual(len(searched["items"]), 1)
        self.assertTrue(all(set(item) == catalog_keys for item in searched["items"]))
        loaded, _ = self.store.tool_load(
            receipt_id="load:post", manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"], tool_name="room_post",
            runtime_registry=self._registry(), created_at_ms=3,
        )
        self.assertEqual(len(loaded["items"]), 1)
        self.assertEqual(loaded["toolName"], "room_post")
        self.assertEqual(set(loaded["items"][0]), catalog_keys | {"inputSchema"})
        self.assertIn("inputSchema", loaded["items"][0])
        self.assertNotIn("room_commit", str(loaded["items"][0]["inputSchema"]))

    def test_room_delivery_schema_accepts_managed_file_blocks(self) -> None:
        schema = room_runtime_registry()["room_post"]["inputSchema"]
        self.assertIn("file", str(schema))

    def test_disclosure_does_not_grant_authorization(self) -> None:
        manifest = self._compile(user=("room_state", "room_post"))
        loaded, _ = self.store.tool_load(
            receipt_id="load:commit", manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"], tool_name="room_commit",
            runtime_registry=self._registry(), created_at_ms=3,
        )
        tool = next(item for item in manifest["tools"] if item["name"] == "room_commit")
        self.assertFalse(tool["authorized"])
        self.assertNotIn("authorized", loaded["items"][0])
        with self.assertRaises(ToolAuthorizationError):
            self._invoke(manifest, tool="room_commit", load="load:commit")

    def test_retired_tool_names_are_rejected_before_authorization(self) -> None:
        manifest = self._compile()
        self.store.tool_load(
            receipt_id="load:post", manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"], tool_name="room_post",
            runtime_registry=self._registry(), created_at_ms=3,
        )
        with self.assertRaisesRegex(
            ValueError,
            "room_state/room_post/room_commit",
        ):
            self._invoke(
                manifest,
                tool="room_send",
                load="load:post",
                receipt="invoke:legacy",
                invocation_key="legacy-command",
            )
        canonical, created = self._invoke(
            manifest, tool="room_post", load="load:post", receipt="invoke:canonical",
            invocation_key="same-command",
        )
        self.assertTrue(created)
        self.assertEqual(canonical["canonicalCommand"]["tool"], "room_post")
        validated = validate_room_tool_command(
            "room_commit",
            {
                "decision": "deliver",
                "result": "done",
                "evidenceRefs": ["artifact:test"],
                "requirementCoverage": ["ac:1"],
            },
        )
        self.assertEqual(validated["canonicalTool"], "room_commit")
        self.assertFalse(validated["executionPerformed"])

    def test_revocation_invalidates_old_epoch_and_load_receipt(self) -> None:
        old = self._compile()
        self.store.tool_load(
            receipt_id="load:old", manifest_id=old["manifestId"],
            manifest_hash=old["manifestHash"], tool_name="room_post",
            runtime_registry=self._registry(), created_at_ms=3,
        )
        room, participant = self._bindings(capability_revision="cap-v2", capability_epoch=2)
        new = self._compile(
            manifest_id="manifest:2", room=room, participant=participant,
            user=("room_state",),
        )
        with self.assertRaisesRegex(CapabilityManifestConflict, "stale invocation context"):
            self._invoke(old, tool="room_post", load="load:old", room=room, participant=participant)
        with self.assertRaisesRegex(CapabilityManifestConflict, "stale or belongs"):
            self._invoke(new, tool="room_state", load="load:old", room=room, participant=participant)

    def test_surface_hash_mismatch_fails_before_invocation_receipt(self) -> None:
        manifest = self._compile()
        self.store.tool_load(
            receipt_id="load:state", manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"], tool_name="room_state",
            runtime_registry=self._registry(), created_at_ms=3,
        )
        with self.assertRaisesRegex(CapabilityManifestConflict, "hash mismatch"):
            self._invoke(
                manifest, tool="room_state", load="load:state",
                surface_hashes={
                    "prompt": manifest["manifestHash"], "runtime": "0" * 64,
                    "gateway": manifest["manifestHash"], "ui": manifest["manifestHash"],
                },
            )

    def test_no_room_binding_is_total_noop(self) -> None:
        path = Path(self.tmp.name) / "ordinary.sqlite"
        result = RoomCapabilityManifestStore(path).compile_manifest(
            manifest_id="none", room_binding=None, participant_binding=None,
            dispatch_id="dispatch:1", runtime_registry=self._registry(),
            user_authorized=(), template_allowed=(), role_allowed=(), profile_allowed=(),
            state_allowed=(), created_at_ms=1,
        )
        self.assertIsNone(result)
        self.assertFalse(path.exists())
        with self.assertRaisesRegex(CapabilityManifestConflict, "handshake is incomplete"):
            self.store.compile_manifest(
                manifest_id="bad", room_binding=self._bindings()[0], participant_binding=None,
                dispatch_id="dispatch:1", runtime_registry=self._registry(),
                user_authorized=(), template_allowed=(), role_allowed=(), profile_allowed=(),
                state_allowed=(), created_at_ms=1,
            )

    def test_runtime_binding_pins_prompt_profile_manifest_and_revocation(self) -> None:
        room, participant = self._bindings()
        manifest, _ = self.store.compile_manifest(
            manifest_id="manifest:runtime", room_binding=room, participant_binding=participant,
            dispatch_id="dispatch:1", runtime_registry=room_runtime_registry(),
            user_authorized=("room_state", "room_post", "room_commit"),
            template_allowed=("room_state", "room_post", "room_commit"),
            role_allowed=("room_state", "room_post", "room_commit"),
            profile_allowed=("room_state", "room_post", "room_commit"),
            state_allowed=("room_state", "room_post", "room_commit"), created_at_ms=1,
        )
        prompt_receipt = {
            "schemaVersion": "wisdom-weasel.prompt-compile-receipt.v1",
            "receiptId": "prompt:1",
            "plan": {
                "bindingId": participant["bindingId"],
                "roomId": room["roomId"],
                "rootId": room["rootId"],
                "sessionId": participant["sessionId"],
                "generation": room["generation"],
                "capabilityRevision": room["capabilityRevision"],
                "capabilityEpoch": participant["capabilityEpoch"],
                "planHash": "b" * 64,
            },
            "omittedLayers": [],
            "producerAudit": [],
            "createdAtMs": 2,
        }
        binding, created = self.store.bind_runtime(
            session_id="session:1",
            manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"],
            prompt_compile_receipt=prompt_receipt,
            compiled_runtime_profile_ref=participant["compiledRuntimeProfileRef"],
            room_binding=room,
            participant_binding=participant,
            surface_manifest_hashes={name: manifest["manifestHash"] for name in ("prompt", "runtime", "gateway", "ui")},
            created_at_ms=2,
        )
        self.assertTrue(created)
        self.assertEqual(binding["promptCompileReceiptId"], "prompt:1")
        loaded, _ = self.store.runtime_tool_load(
            session_id="session:1", receipt_id="load:runtime", tool_name="room_state", created_at_ms=3
        )
        invocation, _ = self.store.authorize_runtime_invocation(
            session_id="session:1", receipt_id="invoke:runtime", invocation_key="call:1",
            load_receipt_id=loaded["receiptId"], tool_name="room_state", arguments={}, created_at_ms=4,
        )
        self.assertEqual(invocation["canonicalCommand"]["capabilityEpoch"], 1)
        recovered = self.store.restore_runtime_tool_disclosures(
            session_id="session:1",
            recovery={
                "schemaVersion": "rag-ime.room-tool-recovery.v1",
                "items": [
                    {
                        "name": "room_state",
                        "receiptId": loaded["receiptId"],
                    }
                ],
            },
        )
        self.assertEqual(
            recovered["items"][0]["receiptId"],
            loaded["receiptId"],
        )
        self.assertEqual(recovered["capabilityEpoch"], 1)
        self.store.revoke_runtime("session:1", capability_epoch=2, now_ms=5)
        with self.assertRaises(ToolAuthorizationError):
            self.store.restore_runtime_tool_disclosures(
                session_id="session:1",
                recovery={
                    "items": [
                        {
                            "name": "room_state",
                            "receiptId": loaded["receiptId"],
                        }
                    ]
                },
            )
        with self.assertRaises(ToolAuthorizationError):
            self.store.authorize_runtime_invocation(
                session_id="session:1", receipt_id="invoke:stale", invocation_key="call:2",
                load_receipt_id=loaded["receiptId"], tool_name="room_state", arguments={}, created_at_ms=6,
            )

    def test_product_tool_load_invoke_execute_and_revoke_are_one_fenced_path(self) -> None:
        room, participant = self._bindings()
        registry = {
            **room_runtime_registry(),
            "workspace_read": {
                "catalogKind": "product-tool",
                "description": "Read one authorized workspace file",
                "when": ["需要核对工作区文件"],
                "notFor": ["当前上下文已经足够"],
                "input": "文件路径",
                "output": "有界文件内容",
                "does": "读取一个授权工作区文件。",
                "risk": "R0",
                "operation": "product.workspace_read",
                "inputSchema": {
                    "type": "object",
                    "required": ["op", "path"],
                    "properties": {
                        "op": {"const": "read"},
                        "path": {"type": "string", "minLength": 1},
                    },
                    "additionalProperties": False,
                },
            },
        }
        tools = (*room_runtime_registry(), "workspace_read")
        manifest, _ = self.store.compile_manifest(
            manifest_id="manifest:product",
            room_binding=room,
            participant_binding=participant,
            dispatch_id="dispatch:1",
            runtime_registry=registry,
            user_authorized=tools,
            template_allowed=tools,
            role_allowed=tools,
            profile_allowed=tools,
            state_allowed=tools,
            created_at_ms=1,
        )
        searched, _ = self.store.tool_search(
            receipt_id="search:workspace",
            manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"],
            query="workspace file",
            created_at_ms=2,
        )
        workspace_catalog = next(
            item for item in searched["items"] if item["name"] == "workspace_read"
        )
        self.assertEqual(
            set(workspace_catalog),
            {"name", "when", "notFor", "input", "output", "does"},
        )
        prompt_receipt = {
            "schemaVersion": "wisdom-weasel.prompt-compile-receipt.v1",
            "receiptId": "prompt:product",
            "plan": {
                "bindingId": participant["bindingId"],
                "roomId": room["roomId"],
                "rootId": room["rootId"],
                "sessionId": participant["sessionId"],
                "generation": room["generation"],
                "capabilityRevision": room["capabilityRevision"],
                "capabilityEpoch": participant["capabilityEpoch"],
                "planHash": "b" * 64,
            },
            "omittedLayers": [],
            "producerAudit": [],
            "createdAtMs": 2,
        }
        self.store.bind_runtime(
            session_id="session:1",
            manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"],
            prompt_compile_receipt=prompt_receipt,
            compiled_runtime_profile_ref=participant["compiledRuntimeProfileRef"],
            room_binding=room,
            participant_binding=participant,
            surface_manifest_hashes={
                name: manifest["manifestHash"]
                for name in ("prompt", "runtime", "gateway", "ui")
            },
            created_at_ms=2,
        )
        loaded, _ = self.store.runtime_tool_load(
            session_id="session:1",
            receipt_id="load:workspace",
            tool_name="workspace_read",
            created_at_ms=3,
        )
        self.assertEqual(
            loaded["items"][0]["inputSchema"],
            registry["workspace_read"]["inputSchema"],
        )
        invocation, _ = self.store.authorize_runtime_invocation(
            session_id="session:1",
            receipt_id="invoke:workspace",
            invocation_key="tool-call:workspace",
            load_receipt_id=loaded["receiptId"],
            tool_name="workspace_read",
            arguments={"op": "read", "path": "README.md"},
            created_at_ms=4,
        )
        execution, created = self.store.record_runtime_execution(
            session_id="session:1",
            invocation_receipt_id=invocation["receiptId"],
            status="applied",
            result_hash="a" * 64,
            created_at_ms=5,
        )
        self.assertTrue(created)
        self.assertEqual(execution["toolName"], "workspace_read")
        self.assertEqual(execution["resultHash"], "a" * 64)

        self.store.revoke_runtime("session:1", capability_epoch=2, now_ms=6)
        with self.assertRaisesRegex(ToolAuthorizationError, "revoked"):
            self.store.record_runtime_execution(
                session_id="session:1",
                invocation_receipt_id=invocation["receiptId"],
                status="applied",
                result_hash="a" * 64,
                created_at_ms=7,
            )

    def _compile(
        self,
        *,
        manifest_id="manifest:1",
        room=None,
        participant=None,
        user=("room_state", "room_post", "room_commit"),
        state=("room_state", "room_post", "room_commit"),
    ):
        default_room, default_participant = self._bindings()
        payload, _ = self.store.compile_manifest(
            manifest_id=manifest_id, room_binding=room or default_room,
            participant_binding=participant or default_participant,
            dispatch_id="dispatch:1", runtime_registry=self._registry(),
            user_authorized=user,
            template_allowed=("room_state", "room_post", "room_commit"),
            role_allowed=("room_state", "room_post", "room_commit"),
            profile_allowed=("room_state", "room_post", "room_commit"),
            state_allowed=state, created_at_ms=1,
        )
        return payload

    def _invoke(
        self,
        manifest,
        *,
        tool,
        load,
        receipt="invoke:1",
        invocation_key="invoke-key:1",
        room=None,
        participant=None,
        surface_hashes=None,
    ):
        default_room, default_participant = self._bindings()
        hashes = surface_hashes or {
            name: manifest["manifestHash"] for name in ("prompt", "runtime", "gateway", "ui")
        }
        return self.store.authorize_invocation(
            receipt_id=receipt, invocation_key=invocation_key,
            manifest_id=manifest["manifestId"], manifest_hash=manifest["manifestHash"],
            load_receipt_id=load, tool_name=tool, arguments={"content": "结论"},
            room_binding=room or default_room,
            participant_binding=participant or default_participant,
            dispatch_id="dispatch:1", surface_manifest_hashes=hashes, created_at_ms=4,
        )

    @staticmethod
    def _registry():
        return {
            "room_state": {"description": "Read current Room state", "risk": "read", "operation": "room.state", "inputSchema": {"type": "object", "properties": {}}},
            "room_post": {"description": "Publish an explicit Room Post", "risk": "write", "operation": "room.post", "inputSchema": {"type": "object", "required": ["content"], "properties": {"content": {"type": "string"}}}},
            "room_commit": {"description": "Propose a governed Room Commit", "risk": "write", "operation": "room.commit", "inputSchema": {"type": "object", "required": ["result"], "properties": {"result": {"type": "string"}}}},
            "room_assign": {"description": "legacy", "risk": "write", "operation": "legacy", "inputSchema": {"type": "object"}},
            "filesystem_write": {"description": "not public", "risk": "write", "operation": "fs.write", "inputSchema": {"type": "object"}},
        }

    @staticmethod
    def _bindings(*, capability_revision="cap-v1", capability_epoch=1):
        room = {
            "schemaVersion": "wisdom-weasel.room-binding.v2", "bindingId": "room-binding:1",
            "rootId": "root:1", "roomId": "room:1", "participantId": "participant:1",
            "taskId": "task:1", "generation": 3, "protocolRevision": "room-v2",
            "capabilityRevision": capability_revision, "access": "write",
        }
        digest = "a" * 64
        participant = {
            "schemaVersion": "wisdom-weasel.room-participant-binding.v2",
            "bindingId": "participant-binding:1", "sessionId": "session:1",
            "personaRef": f"rag-ime-definition://persona/p?version=1&contentHash=sha256:{digest}",
            "collaborationRoleRef": f"rag-ime-definition://collaboration-role/r?version=1&contentHash=sha256:{digest}",
            "agentTemplateRef": f"rag-ime-definition://agent-template/t?version=1&contentHash=sha256:{digest}",
            "collaborationProfileRef": None,
            "compiledRuntimeProfileRef": {"profileId": "compiled:1", "revision": "1", "contentHash": "sha256:abcdef"},
            "capabilityRevision": capability_revision, "capabilityEpoch": capability_epoch,
            "roomBindingRef": {"bindingId": "room-binding:1", "schemaVersion": "wisdom-weasel.room-binding.v2"},
        }
        return room, participant


if __name__ == "__main__":
    unittest.main()
