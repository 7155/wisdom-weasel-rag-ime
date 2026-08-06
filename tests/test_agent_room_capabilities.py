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
from rag_ime.contracts.json_schema import (
    ContractValidationError,
    validate_contract,
)


ROOM_TOOLS = (
    "room_state",
    "room_post",
    "room_commit",
    "room_collaborate",
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
            user=("room_state", "room_collaborate", "room_post"),
            state=ROOM_TOOLS,
        )
        tools = {tool["name"]: tool for tool in manifest["tools"]}
        self.assertEqual(tuple(tools), ROOM_TOOLS)
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

    def test_runtime_projection_metadata_is_pinned_but_not_added_to_route_cards(self) -> None:
        room, participant = self._bindings()
        memory = self._product_tool(
            "Govern long-term memory",
            does="查询和治理长期记忆。",
        )
        memory["inputSchema"] = {
            "type": "object",
            "required": ["op"],
            "properties": {"op": {"const": "capture"}},
            "additionalProperties": False,
        }
        memory["runtimeProjections"] = [
            {"name": "memory_capture", "operation": "capture"},
        ]
        memory["modelVisible"] = False
        registry = {**self._registry(), "memory": memory}
        names = (*ROOM_TOOLS, "memory")

        manifest, _ = self.store.compile_manifest(
            manifest_id="manifest:memory-projection",
            room_binding=room,
            participant_binding=participant,
            dispatch_id="dispatch:1",
            runtime_registry=registry,
            user_authorized=names,
            template_allowed=names,
            role_allowed=names,
            profile_allowed=names,
            state_allowed=names,
            created_at_ms=1,
        )
        tool = next(
            item for item in manifest["tools"] if item["name"] == "memory"
        )
        self.assertEqual(
            tool["runtimeProjections"],
            [{"name": "memory_capture", "operation": "capture"}],
        )
        self.assertIs(tool["modelVisible"], False)
        searched, _ = self.store.tool_search(
            receipt_id="search:memory-projection",
            manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"],
            query="memory",
            created_at_ms=2,
        )
        route = next(
            item for item in searched["items"] if item["name"] == "memory"
        )
        self.assertNotIn("runtimeProjections", route)

    def test_governed_search_matches_exact_name_tokens_and_verbose_intent(self) -> None:
        room, participant = self._bindings()
        registry = {
            **self._registry(),
            "workspace_list": self._product_tool(
                "List authorized workspace files",
                does="列出授权工作区中的文件。",
            ),
            "workspace_read": self._product_tool(
                "Read one authorized workspace file",
                does="读取授权工作区中的一个文件。",
            ),
        }
        names = (*ROOM_TOOLS, "workspace_list", "workspace_read")
        manifest, _ = self.store.compile_manifest(
            manifest_id="manifest:search-routing",
            room_binding=room,
            participant_binding=participant,
            dispatch_id="dispatch:1",
            runtime_registry=registry,
            user_authorized=names,
            template_allowed=names,
            role_allowed=names,
            profile_allowed=names,
            state_allowed=names,
            created_at_ms=1,
        )

        queries = (
            ("search:exact-token", "name workspace_list", "workspace_list"),
            (
                "search:verbose",
                "workspace_read read files authorized workspace input path",
                "workspace_read",
            ),
            ("search:family", "workspace", "workspace_list"),
        )
        for index, (receipt_id, query, expected_name) in enumerate(
            queries,
            start=2,
        ):
            receipt, _ = self.store.tool_search(
                receipt_id=receipt_id,
                manifest_id=manifest["manifestId"],
                manifest_hash=manifest["manifestHash"],
                query=query,
                created_at_ms=index,
            )
            names_found = [item["name"] for item in receipt["items"]]
            self.assertIn(expected_name, names_found)
            self.assertTrue(
                all("inputSchema" not in item for item in receipt["items"])
            )

    def test_tool_load_batch_records_all_receipts_atomically_in_input_order(self) -> None:
        manifest = self._compile()
        receipts, created = self.store.tool_load_batch(
            manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"],
            loads=(
                {"receiptId": "load:post", "toolName": "room_post"},
                {"receiptId": "load:state", "toolName": "room_state"},
            ),
            runtime_registry=self._registry(),
            created_at_ms=3,
        )

        self.assertTrue(created)
        self.assertEqual(
            [receipt["toolName"] for receipt in receipts],
            ["room_post", "room_state"],
        )
        replayed, replay_created = self.store.tool_load_batch(
            manifest_id=manifest["manifestId"],
            manifest_hash=manifest["manifestHash"],
            loads=(
                {"receiptId": "load:post", "toolName": "room_post"},
                {"receiptId": "load:state", "toolName": "room_state"},
            ),
            runtime_registry=self._registry(),
            created_at_ms=99,
        )
        self.assertFalse(replay_created)
        self.assertEqual(replayed, receipts)

        with self.assertRaisesRegex(KeyError, "workspace_missing"):
            self.store.tool_load_batch(
                manifest_id=manifest["manifestId"],
                manifest_hash=manifest["manifestHash"],
                loads=(
                    {"receiptId": "load:collaborate", "toolName": "room_collaborate"},
                    {"receiptId": "load:missing", "toolName": "workspace_missing"},
                ),
                runtime_registry=self._registry(),
                created_at_ms=4,
            )
        with self.assertRaises(KeyError):
            self.store._disclosure("load:collaborate")

        with self.assertRaisesRegex(
            CapabilityManifestConflict,
            "receipt identity changed",
        ):
            self.store.tool_load_batch(
                manifest_id=manifest["manifestId"],
                manifest_hash=manifest["manifestHash"],
                loads=(
                    {"receiptId": "load:new", "toolName": "room_collaborate"},
                    {"receiptId": "load:state", "toolName": "room_post"},
                ),
                runtime_registry=self._registry(),
                created_at_ms=3,
            )
        with self.assertRaises(KeyError):
            self.store._disclosure("load:new")

    def test_room_delivery_schema_accepts_managed_file_blocks(self) -> None:
        schema = room_runtime_registry()["room_post"]["inputSchema"]
        self.assertIn("file", str(schema))

    def test_room_collaboration_requires_at_least_one_parent_acceptance_alias(
        self,
    ) -> None:
        tool = room_runtime_registry()["room_collaborate"]
        schema = tool["inputSchema"]
        self.assertTrue(any("平级伙伴" in value for value in tool["when"]))
        self.assertTrue(
            any("review handoff" in value for value in tool["notFor"])
        )
        self.assertIn("acceptance", schema["required"])
        self.assertIn("workspacePolicy", schema["required"])
        self.assertIn(
            "不得填写自己",
            schema["properties"]["targetParticipantRef"]["description"],
        )
        self.assertIn(
            "当前工作卡片",
            schema["properties"]["acceptance"]["description"],
        )
        self.assertEqual(
            schema["properties"]["acceptance"]["minItems"],
            1,
        )
        self.assertEqual(
            set(schema["properties"]["workspacePolicy"]["enum"]),
            {"read_only", "isolated_writable"},
        )
        base = {
            "targetParticipantRef": "P-2",
            "objective": "实现明确且互不重叠的子任务",
            "expectedOutput": "带证据的实现结果",
            "intent": "execute",
            "workspacePolicy": "read_only",
        }
        validate_contract({**base, "acceptance": ["AC-1"]}, schema)
        with self.assertRaises(ContractValidationError):
            validate_contract(
                {
                    **base,
                    "workspacePolicy": "shared_single_writer",
                    "acceptance": ["AC-1"],
                },
                schema,
            )
        with self.assertRaises(ContractValidationError):
            validate_contract({**base, "acceptance": []}, schema)
        with self.assertRaises(ContractValidationError):
            validate_contract(
                {**base, "intent": "review", "acceptance": ["AC-1"]},
                schema,
            )

    def test_room_commit_schema_leaves_quality_verdict_to_kernel(self) -> None:
        tool = room_runtime_registry()["room_commit"]
        schema = tool["inputSchema"]
        self.assertTrue(
            any("最终验收" in value for value in tool["when"])
        )
        self.assertEqual(
            set(schema["required"]),
            {
                "decision",
                "summary",
                "publicSummary",
                "evidence",
                "residualRisks",
            },
        )
        self.assertFalse(
            {"qualityGate", "verdict", "originalRequestChecked"}
            & set(schema["properties"])
        )
        evidence_item = schema["properties"]["evidence"]["items"]
        self.assertEqual(
            set(evidence_item["required"]),
            {"acceptance", "refs"},
        )
        self.assertFalse(evidence_item["additionalProperties"])
        self.assertEqual(len(schema["oneOf"]), 4)
        self.assertEqual(
            schema["properties"]["acceptanceAliases"]["minItems"],
            1,
        )
        self.assertNotIn("Kernel", tool["description"])
        self.assertIn("服务端会核对", tool["description"])
        self.assertIn("acceptanceAliases 只用于 handoff", tool["description"])
        acceptance_aliases = schema["properties"]["acceptanceAliases"]["description"]
        self.assertIn("仅 handoff", acceptance_aliases)
        self.assertIn("deliver", acceptance_aliases)
        self.assertIn("禁止填写", acceptance_aliases)
        intent = schema["properties"]["intent"]["description"]
        self.assertIn("最终验收", intent)
        self.assertIn("必须用 close", intent)
        self.assertIn("review", intent)
        self.assertIn("不负责最终回复", intent)
        self.assertIn(
            "不要再用 room_post 重复发布",
            schema["properties"]["publicSummary"]["description"],
        )
        self.assertIn(
            "不输出私下推理",
            schema["properties"]["publicSummary"]["description"],
        )
        self.assertIn(
            "不会直接展示给用户",
            schema["properties"]["summary"]["description"],
        )
        self.assertIn(
            "马上要调用 room_commit",
            " ".join(room_runtime_registry()["room_post"]["notFor"]),
        )
        self.assertIn(
            "每个 active Dispatch 最多发布一条",
            room_runtime_registry()["room_post"]["description"],
        )
        self.assertIn(
            "稳定的 Tool 活动面",
            room_runtime_registry()["room_post"]["description"],
        )

    def test_room_post_cannot_publish_a_nonterminal_user_question(self) -> None:
        tool = room_runtime_registry()["room_post"]
        schema = tool["inputSchema"]
        self.assertNotIn("question", schema["properties"]["kind"]["enum"])
        self.assertIn(
            "必须用 room_commit(wait) 发布并暂停",
            " ".join(tool["notFor"]),
        )
        with self.assertRaises(ContractValidationError):
            validate_contract(
                {
                    "kind": "question",
                    "content": "请选择一个方案后再继续。",
                },
                schema,
            )

    def test_room_define_does_not_require_a_fake_implementation_peer(
        self,
    ) -> None:
        schema = room_runtime_registry()["room_define"]["inputSchema"]
        self.assertIn("executionPlan", schema["properties"])
        plan_schema = schema["properties"]["executionPlan"]
        self.assertEqual(plan_schema["properties"]["featureTasks"]["maxItems"], 4)
        self.assertIn("continuityPlan", plan_schema["properties"])
        self.assertIn(
            "用户的语言",
            plan_schema["description"],
        )
        self.assertIn(
            "受管工作文档",
            plan_schema["properties"]["continuityPlan"]["description"],
        )
        self.assertNotIn(
            "implementationParticipantRef",
            schema["required"],
        )
        self.assertIn("independentReviewRequired", schema["required"])
        with self.assertRaises(ContractValidationError):
            validate_contract(
                {
                    "objective": "完成小型单写任务",
                    "expectedOutput": "可验证结果",
                    "entrySurface": "协作任务页的单写任务入口",
                    "primaryInteraction": "主持伙伴执行一次有界检查",
                    "observableCompletion": "任务页显示检查结果和证据",
                    "requirements": ["不虚构并行工作"],
                    "acceptanceCriteria": ["结果通过验证"],
                },
                schema,
            )
        validate_contract(
            {
                "objective": "完成小型单写任务",
                "expectedOutput": "可验证结果",
                "entrySurface": "协作任务页的单写任务入口",
                "primaryInteraction": "主持伙伴执行一次有界检查",
                "observableCompletion": "任务页显示检查结果和证据",
                "requirements": ["不虚构并行工作"],
                "acceptanceCriteria": ["结果通过验证"],
                "executionPlan": {
                    "sharedContracts": [],
                    "featureTasks": [{
                        "title": "小型单写任务",
                        "participantRef": "P1",
                        "userOutcome": "从入口完成检查并看到证据",
                        "dependencies": [],
                    }],
                    "integrationPlan": "负责人完成后统一核对",
                    "acceptancePlan": ["任务页显示结果和证据"],
                },
                "independentReviewRequired": False,
            },
            schema,
        )

    def test_room_commit_schema_keeps_decision_fields_mutually_exclusive(
        self,
    ) -> None:
        schema = room_runtime_registry()["room_commit"]["inputSchema"]
        base = {
            "summary": "当前责任说明",
            "evidence": [],
            "residualRisks": [],
            "publicSummary": "给用户的自然语言终态报告",
        }
        valid = (
            {**base, "decision": "deliver"},
            {
                **base,
                "decision": "handoff",
                "targetParticipantRef": "P-2",
                "intent": "review",
                "nextTask": "独立复核实现",
                "expectedOutput": "复核证据",
                "acceptanceAliases": ["AC-1"],
            },
            {
                **base,
                "decision": "wait",
                "waitingFor": "user",
                "resumeCondition": "用户确认禁区",
            },
            {
                **base,
                "decision": "wait",
                "waitingFor": "participant",
                "waitingForParticipantRef": "P-2",
                "resumeCondition": "成员公开复核结果",
            },
            {
                **base,
                "decision": "blocked",
                "blocker": "缺少授权输入",
                "attemptedAlternatives": ["检查当前配置"],
                "unlockCondition": "获得授权输入",
            },
        )
        for payload in valid:
            validate_contract(payload, schema)

        invalid = (
            {**valid[0], "waitingFor": "user"},
            {**valid[0], "acceptanceAliases": ["AC-1"]},
            {**valid[1], "blocker": "不属于 handoff"},
            {**valid[1], "acceptanceAliases": []},
            {**valid[2], "targetParticipantRef": "P-2"},
            {
                **base,
                "decision": "wait",
                "waitingFor": "participant",
                "resumeCondition": "成员公开复核结果",
            },
            {
                **valid[2],
                "waitingForParticipantRef": "P-2",
            },
            {**valid[4], "question": "不属于 blocked"},
        )
        for payload in invalid:
            with self.assertRaises(ContractValidationError):
                validate_contract(payload, schema)

    def test_room_commit_schema_owns_structured_questions_for_user_waits(
        self,
    ) -> None:
        schema = room_runtime_registry()["room_commit"]["inputSchema"]
        base = {
            "summary": "需要用户澄清",
            "evidence": [],
            "residualRisks": [],
            "publicSummary": "需要用户选择后才能继续",
            "decision": "wait",
            "waitingFor": "user",
            "resumeCondition": "用户选择一个方案",
            "question": "采用哪个方案？",
            "questionKind": "bounded",
        }
        options = [
            {
                "value": "safe",
                "label": "稳妥方案",
                "description": "保留现有边界",
                "recommended": True,
            },
            {
                "value": "fast",
                "label": "快速方案",
                "description": "缩小首轮范围以更快得到可运行结果",
            },
        ]
        validate_contract({**base, "questionOptions": options}, schema)
        validate_contract(
            {
                **base,
                "questionKind": "unbounded",
            },
            schema,
        )

        invalid = (
            {
                key: value
                for key, value in base.items()
                if key != "questionKind"
            },
            {**base, "questionKind": "unbounded", "questionOptions": options},
            {
                key: value
                for key, value in base.items()
                if key != "questionOptions"
            },
            {
                **base,
                "decision": "deliver",
                "questionOptions": options,
            },
            {
                **base,
                "waitingFor": "external",
                "questionOptions": options,
            },
            {
                key: value
                for key, value in {
                    **base,
                    "questionOptions": options,
                }.items()
                if key != "question"
            },
            {**base, "questionOptions": options[:1]},
            {**base, "questionOptions": [*options, *options, *options]},
            {
                **base,
                "questionOptions": [
                    {**options[0], "value": "v" * 81},
                    options[1],
                ],
            },
            {
                **base,
                "questionOptions": [
                    {**options[0], "label": "l" * 121},
                    options[1],
                ],
            },
            {
                **base,
                "questionOptions": [
                    {**options[0], "description": "d" * 501},
                    options[1],
                ],
            },
            {
                **base,
                "questionOptions": [
                    {
                        key: value
                        for key, value in options[0].items()
                        if key != "description"
                    },
                    options[1],
                ],
            },
        )
        for payload in invalid:
            with self.assertRaises(ContractValidationError):
                validate_contract(payload, schema)

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
            "Room public tool surface only supports",
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
                "summary": "done",
                "publicSummary": "用户可见的完成报告",
                "evidence": [
                    {
                        "acceptance": "AC-1",
                        "refs": ["artifact:test"],
                    }
                ],
                "residualRisks": [],
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
            user_authorized=ROOM_TOOLS,
            template_allowed=ROOM_TOOLS,
            role_allowed=ROOM_TOOLS,
            profile_allowed=ROOM_TOOLS,
            state_allowed=ROOM_TOOLS, created_at_ms=1,
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
        user=ROOM_TOOLS,
        state=ROOM_TOOLS,
    ):
        default_room, default_participant = self._bindings()
        payload, _ = self.store.compile_manifest(
            manifest_id=manifest_id, room_binding=room or default_room,
            participant_binding=participant or default_participant,
            dispatch_id="dispatch:1", runtime_registry=self._registry(),
            user_authorized=user,
            template_allowed=ROOM_TOOLS,
            role_allowed=ROOM_TOOLS,
            profile_allowed=ROOM_TOOLS,
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
            "room_collaborate": {"description": "Enqueue a bounded Room collaboration", "risk": "write", "operation": "room.collaborate", "inputSchema": {"type": "object", "required": ["targetParticipantId", "objective", "expectedOutput"], "properties": {"targetParticipantId": {"type": "string"}, "objective": {"type": "string"}, "expectedOutput": {"type": "string"}}}},
            "room_post": {"description": "Publish an explicit Room Post", "risk": "write", "operation": "room.post", "inputSchema": {"type": "object", "required": ["content"], "properties": {"content": {"type": "string"}}}},
            "room_commit": {"description": "Propose a governed Room Commit", "risk": "write", "operation": "room.commit", "inputSchema": {"type": "object", "required": ["result"], "properties": {"result": {"type": "string"}}}},
            "room_assign": {"description": "legacy", "risk": "write", "operation": "legacy", "inputSchema": {"type": "object"}},
            "filesystem_write": {"description": "not public", "risk": "write", "operation": "fs.write", "inputSchema": {"type": "object"}},
        }

    @staticmethod
    def _product_tool(
        description: str,
        *,
        does: str,
    ) -> dict[str, object]:
        return {
            "catalogKind": "product-tool",
            "description": description,
            "when": ["需要查看授权工作区文件"],
            "notFor": ["不需要工作区证据"],
            "input": "工作区路径",
            "output": "有界文件结果",
            "does": does,
            "risk": "R0",
            "operation": "product.workspace",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "additionalProperties": False,
            },
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
