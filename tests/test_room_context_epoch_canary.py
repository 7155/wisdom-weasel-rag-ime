from __future__ import annotations

import importlib.util
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "room_context_epoch_canary.py"
SPEC = importlib.util.spec_from_file_location("room_context_epoch_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)
sys.modules.setdefault("room_context_epoch_canary", CANARY)
REPORT_SCRIPT = ROOT / "scripts" / "report_room_context_epoch_canary.py"
REPORT_SPEC = importlib.util.spec_from_file_location(
    "report_room_context_epoch_canary", REPORT_SCRIPT
)
assert REPORT_SPEC is not None and REPORT_SPEC.loader is not None
REPORT = importlib.util.module_from_spec(REPORT_SPEC)
REPORT_SPEC.loader.exec_module(REPORT)


def _model_call(
    *,
    index: int,
    system_prompt: str,
    messages: list[dict[str, object]],
    tools: list[dict[str, object]],
    previous_messages: list[dict[str, object]] | None,
) -> dict[str, object]:
    previous = previous_messages or []
    common_messages = 0
    while (
        common_messages < len(previous)
        and common_messages < len(messages)
        and CANARY._json_bytes(previous[common_messages])
        == CANARY._json_bytes(messages[common_messages])
    ):
        common_messages += 1
    previous_bytes = CANARY._json_bytes(previous)
    current_bytes = CANARY._json_bytes(messages)
    prefix_bytes = 0
    while (
        prefix_bytes < len(previous_bytes)
        and prefix_bytes < len(current_bytes)
        and previous_bytes[prefix_bytes] == current_bytes[prefix_bytes]
    ):
        prefix_bytes += 1
    return {
        "index": index,
        "contextMessages": messages,
        "providerContext": {
            "systemPrompt": system_prompt,
            "messages": messages,
            "tools": tools,
        },
        "contextDelta": {
            "baseCallIndex": index - 1 if index > 1 else None,
            "commonPrefixMessages": common_messages,
            "removedMessageCount": len(previous) - common_messages,
            "addedMessageCount": len(messages) - common_messages,
            "prefixBytes": prefix_bytes,
            "prefixSha256": hashlib.sha256(
                current_bytes[:prefix_bytes]
            ).hexdigest(),
            "currentBytes": len(current_bytes),
            "deltaBytes": len(current_bytes) - prefix_bytes,
            "duplicateBytes": prefix_bytes,
        },
    }


class RoomContextEpochCanaryTest(unittest.TestCase):
    def test_cancel_root_skips_a_terminal_root(self) -> None:
        requests: list[tuple[str, str, object | None]] = []

        def requester(
            _base_url: str,
            method: str,
            path: str,
            payload: object | None = None,
            *,
            timeout: float,
        ) -> dict[str, object]:
            requests.append((method, path, payload))
            return {
                "roots": [{
                    "rootId": "room-root:terminal",
                    "state": "completed",
                    "generation": 4,
                }]
            }

        result = CANARY.cancel_root(
            "http://in-process.invalid",
            "room-1",
            "room-root:terminal",
            requester=requester,
        )

        self.assertEqual(result["status"], "already_terminal")
        self.assertEqual(result["generation"], 4)
        self.assertEqual([method for method, _path, _payload in requests], ["GET"])

    def test_cancel_root_uses_the_current_generation(self) -> None:
        requests: list[tuple[str, str, object | None]] = []

        def requester(
            _base_url: str,
            method: str,
            path: str,
            payload: object | None = None,
            *,
            timeout: float,
        ) -> dict[str, object]:
            requests.append((method, path, payload))
            if method == "GET":
                return {
                    "roots": [{
                        "rootId": "room-root:running",
                        "state": "running",
                        "generation": 3,
                    }]
                }
            return {"receipt": {"status": "applied"}}

        result = CANARY.cancel_root(
            "http://in-process.invalid",
            "room-1",
            "room-root:running",
            requester=requester,
        )

        self.assertEqual(result["status"], "cancel_requested")
        command = requests[1][2]
        self.assertIsInstance(command, dict)
        assert isinstance(command, dict)
        self.assertEqual(command["generation"], 3)

    def test_cleanup_failure_is_added_to_the_primary_failure(self) -> None:
        primary = RuntimeError("provider stream failed first")

        def requester(
            _base_url: str,
            _method: str,
            _path: str,
            _payload: object | None = None,
            *,
            timeout: float,
        ) -> dict[str, object]:
            raise TimeoutError("cleanup request timed out")

        result = CANARY.cancel_root_after_failure(
            "http://in-process.invalid",
            "room-1",
            "room-root:failed",
            primary,
            requester=requester,
        )

        self.assertEqual(result["status"], "cleanup_failed")
        self.assertEqual(str(primary), "provider stream failed first")
        self.assertEqual(len(primary.__notes__), 1)
        self.assertIn("cleanup request timed out", primary.__notes__[0])

    def test_debug_evidence_uses_the_audit_timeout_for_both_snapshots(
        self,
    ) -> None:
        requests: list[tuple[str, float]] = []

        def requester(
            _base_url: str,
            _method: str,
            path: str,
            _payload: object | None = None,
            *,
            timeout: float,
        ) -> dict[str, object]:
            requests.append((path, timeout))
            if path.endswith("/debug-context"):
                return {"context": {}, "transcript": {}}
            return {"messageQueue": {}}

        CANARY.debug_evidence(
            "http://in-process.invalid",
            "session-audit",
            requester=requester,
            timeout=240,
        )

        self.assertEqual(
            requests,
            [
                (
                    "/api/agent/sessions/session-audit/debug-context",
                    240,
                ),
                (
                    "/api/agent/sessions/session-audit/messages",
                    240,
                ),
            ],
        )

    def test_debug_evidence_can_select_one_recovery_turn(self) -> None:
        requests: list[str] = []

        def requester(
            _base_url: str,
            _method: str,
            path: str,
            _payload: object | None = None,
            *,
            timeout: float,
        ) -> dict[str, object]:
            del timeout
            requests.append(path)
            if "/debug-context" in path:
                return {"context": {}, "transcript": {}}
            return {"messageQueue": {}}

        CANARY.debug_evidence(
            "http://in-process.invalid",
            "session-audit",
            requester=requester,
            turn_id="turn:recovery",
        )

        self.assertEqual(
            requests[0],
            (
                "/api/agent/sessions/session-audit/debug-context"
                "?turnId=turn%3Arecovery"
            ),
        )

    def test_provider_prefix_evidence_proves_content_free_append_only_context(
        self,
    ) -> None:
        first_messages = [{"role": "user", "content": "private requirement"}]
        second_messages = [
            *first_messages,
            {"role": "assistant", "content": "working"},
            {"role": "toolResult", "content": "private result"},
        ]
        first_tools = [{"name": "tool_search", "parameters": {"type": "object"}}]
        second_tools = [
            *first_tools,
            {"name": "workspace_read", "parameters": {"type": "object"}},
        ]
        context = {
            "modelCalls": [
                _model_call(
                    index=1,
                    system_prompt="stable private prompt",
                    messages=first_messages,
                    tools=first_tools,
                    previous_messages=None,
                ),
                _model_call(
                    index=2,
                    system_prompt="stable private prompt",
                    messages=second_messages,
                    tools=second_tools,
                    previous_messages=first_messages,
                ),
            ]
        }

        evidence = CANARY.provider_prefix_evidence(context)

        self.assertTrue(evidence["passed"])
        self.assertTrue(evidence["checks"]["messageBytePrefixPreserved"])
        self.assertEqual(evidence["calls"][0]["messageCount"], 1)
        serialized = json.dumps(evidence, ensure_ascii=False)
        self.assertNotIn("private requirement", serialized)
        self.assertNotIn("private result", serialized)
        self.assertNotIn("stable private prompt", serialized)

    def test_provider_prefix_evidence_accepts_an_identical_provider_replay(
        self,
    ) -> None:
        messages = [{"role": "user", "content": "same request"}]
        tools = [{"name": "tool_search", "parameters": {"type": "object"}}]
        context = {
            "modelCalls": [
                _model_call(
                    index=1,
                    system_prompt="stable prompt",
                    messages=messages,
                    tools=tools,
                    previous_messages=None,
                ),
                _model_call(
                    index=2,
                    system_prompt="stable prompt",
                    messages=messages,
                    tools=tools,
                    previous_messages=messages,
                ),
            ]
        }

        evidence = CANARY.provider_prefix_evidence(context)

        self.assertTrue(evidence["passed"])
        transition = evidence["transitions"][0]
        self.assertTrue(transition["runtimeMessageBytePrefixPreserved"])
        self.assertEqual(
            evidence["calls"][1]["contextDelta"]["prefixBytes"],
            evidence["calls"][0]["contextDelta"]["currentBytes"],
        )

    def test_provider_room_post_visibility_ignores_dispatch_instructions(
        self,
    ) -> None:
        dispatch_only = (
            '<room-fact kind="dispatch_state">要求输出 POST-A</room-fact>'
        )
        post_visible = (
            '<room-fact kind="room_post">POST-A 已完成，下一步输出 POST-B</room-fact>'
        )
        context = {
            "modelCalls": [
                _model_call(
                    index=3,
                    system_prompt=dispatch_only,
                    messages=[{"role": "user", "content": "task"}],
                    tools=[],
                    previous_messages=None,
                ),
                _model_call(
                    index=4,
                    system_prompt=post_visible,
                    messages=[{"role": "user", "content": "task"}],
                    tools=[],
                    previous_messages=[{"role": "user", "content": "task"}],
                ),
            ]
        }

        evidence = CANARY.provider_room_post_visibility(
            context,
            {"A": "POST-A", "B": "POST-B"},
        )

        self.assertEqual(evidence["A"], {"seen": True, "callIndexes": [4]})
        self.assertEqual(evidence["B"], {"seen": False, "callIndexes": []})

    def test_provider_prefix_evidence_rejects_reorder_and_prompt_change(self) -> None:
        first_messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ]
        second_messages = [
            first_messages[1],
            first_messages[0],
            {"role": "toolResult", "content": "three"},
        ]
        first_tools = [{"name": "alpha"}, {"name": "beta"}]
        second_tools = [first_tools[1], first_tools[0]]
        context = {
            "modelCalls": [
                _model_call(
                    index=1,
                    system_prompt="prompt one",
                    messages=first_messages,
                    tools=first_tools,
                    previous_messages=None,
                ),
                _model_call(
                    index=2,
                    system_prompt="prompt two",
                    messages=second_messages,
                    tools=second_tools,
                    previous_messages=first_messages,
                ),
            ]
        }

        evidence = CANARY.provider_prefix_evidence(context)

        self.assertFalse(evidence["passed"])
        self.assertFalse(evidence["checks"]["stableSystemPrompt"])
        self.assertFalse(evidence["checks"]["messageHistoryAppendOnly"])
        self.assertFalse(evidence["checks"]["toolSchemasAppendOnly"])
        self.assertFalse(evidence["checks"]["messageBytePrefixPreserved"])

    def test_prompt_governance_requires_room_authority_without_duplicate_recovery(self) -> None:
        routing_card = json.dumps(
            {
                "name": "workspace_read",
                "when": ["读取文件"],
                "notFor": ["写入文件"],
                "input": "路径与范围",
                "output": "有界文本",
                "does": "读取授权文件。",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        clean_prompt = (
            "base\n### Act Gate\n"
            "当前受管 Room Dispatch 已授权执行；写操作仍受原生审批。"
            "\n<available_skills format=\"routing-card-jsonl\">\n"
            f"{routing_card}\n</available_skills>"
            "\n<available_product_tools format=\"route-jsonl\">\n"
            f"{routing_card}\n</available_product_tools>"
        )
        context = {
            "modelCalls": [
                _model_call(
                    index=1,
                    system_prompt=clean_prompt,
                    messages=[{"role": "user", "content": "work"}],
                    tools=[{"name": "tool_load"}],
                    previous_messages=None,
                )
            ]
        }

        clean = CANARY.provider_prompt_governance_evidence(context)
        self.assertTrue(clean["managedRoomAuthorityEveryCall"])
        self.assertEqual(clean["conflictingWorkflowMarkers"], [])
        self.assertEqual(clean["lifecycleHookBlockCount"], 0)
        self.assertEqual(clean["volatileCurrentTimeCount"], 0)
        self.assertEqual(clean["projectContextBlockCount"], 0)
        self.assertTrue(clean["catalogBlocksExactlyOnceEveryCall"])
        self.assertTrue(clean["routingCardFieldContractEveryCall"])
        self.assertTrue(clean["routingCardContentCompleteEveryCall"])
        self.assertTrue(clean["initialProductSchemasDeferred"])
        self.assertTrue(clean["initialProductSchemasHaveLoadReceipts"])
        self.assertTrue(clean["progressiveProductSchemasValid"])
        self.assertEqual(clean["invalidRoutingCardCount"], 0)
        self.assertEqual(clean["truncatedRoutingCardValueCount"], 0)

        context["modelCalls"][0]["providerContext"]["systemPrompt"] = (
            clean_prompt
            + "\n计划尚未批准，不得执行写操作。"
            + '\n<rag-ime-context type="lifecycle_hook" current_time="volatile">'
            + "duplicate</rag-ime-context>"
        )
        conflicted = CANARY.provider_prompt_governance_evidence(context)
        self.assertEqual(
            conflicted["conflictingWorkflowMarkers"],
            ["不得执行写操作", "计划尚未批准"],
        )
        self.assertEqual(conflicted["lifecycleHookBlockCount"], 1)
        self.assertEqual(conflicted["volatileCurrentTimeCount"], 1)

    def test_prompt_governance_rejects_agentmd_and_eager_product_schema(self) -> None:
        card = json.dumps(
            {
                "name": "workspace_read",
                "when": ["读取"],
                "notFor": ["写入"],
                "input": "路径",
                "output": "文本",
                "does": "读取文件。",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        prompt = (
            "当前受管 Room Dispatch 已授权执行"
            "\n<project_context>AGENTS.md</project_context>"
            f"\n<available_skills>{card}</available_skills>"
            f"\n<available_product_tools>{card}</available_product_tools>"
        )
        context = {
            "modelCalls": [
                _model_call(
                    index=1,
                    system_prompt=prompt,
                    messages=[{"role": "user", "content": "work"}],
                    tools=[{"name": "tool_load"}, {"name": "workspace_read"}],
                    previous_messages=None,
                )
            ]
        }

        evidence = CANARY.provider_prompt_governance_evidence(context)

        self.assertEqual(evidence["projectContextBlockCount"], 1)
        self.assertFalse(evidence["initialProductSchemasDeferred"])
        self.assertEqual(evidence["initialProductSchemaCount"], 1)
        self.assertFalse(evidence["initialProductSchemasHaveLoadReceipts"])
        self.assertFalse(evidence["progressiveProductSchemasValid"])

    def test_prompt_governance_rejects_truncated_routing_card_values(self) -> None:
        card = json.dumps(
            {
                "name": "workspace_read",
                "when": ["读取"],
                "notFor": ["写入"],
                "input": "被硬截断的输入...",
                "output": "文本",
                "does": "读取文件。",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        prompt = (
            "当前受管 Room Dispatch 已授权执行"
            f"\n<available_skills>{card}</available_skills>"
            f"\n<available_product_tools>{card}</available_product_tools>"
        )
        context = {
            "modelCalls": [
                _model_call(
                    index=1,
                    system_prompt=prompt,
                    messages=[{"role": "user", "content": "work"}],
                    tools=[{"name": "tool_load"}],
                    previous_messages=None,
                )
            ]
        }

        evidence = CANARY.provider_prompt_governance_evidence(context)

        self.assertFalse(evidence["routingCardContentCompleteEveryCall"])
        self.assertEqual(evidence["truncatedRoutingCardValueCount"], 2)

    def test_prompt_governance_accepts_schema_loaded_before_resumed_capture(
        self,
    ) -> None:
        card = json.dumps(
            {
                "name": "workspace_read",
                "when": ["读取"],
                "notFor": ["写入"],
                "input": "路径",
                "output": "文本",
                "does": "读取文件。",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        prompt = (
            "当前受管 Room Dispatch 已授权执行"
            f"\n<available_skills>{card}</available_skills>"
            f"\n<available_product_tools>{card}</available_product_tools>"
        )
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "name": "tool_load",
                        "arguments": {"name": "workspace_read"},
                    }
                ],
            },
            {
                "role": "toolResult",
                "toolName": "tool_load",
                "details": {
                    "disclosed": True,
                    "tool": {"name": "workspace_read"},
                },
            },
            {"role": "user", "content": "resume after approval"},
        ]
        context = {
            "modelCalls": [
                _model_call(
                    index=10,
                    system_prompt=prompt,
                    messages=messages,
                    tools=[{"name": "tool_load"}, {"name": "workspace_read"}],
                    previous_messages=None,
                )
            ]
        }

        evidence = CANARY.provider_prompt_governance_evidence(context)

        self.assertFalse(evidence["initialProductSchemasDeferred"])
        self.assertEqual(evidence["initialProductSchemaCount"], 1)
        self.assertEqual(
            evidence["loadedProductSchemasBeforeFirstCapture"],
            ["workspace_read"],
        )
        self.assertTrue(evidence["initialProductSchemasHaveLoadReceipts"])
        self.assertTrue(evidence["progressiveProductSchemasValid"])

    def test_prompt_governance_detects_duplicate_original_requirement_projection(self) -> None:
        original = "原始需求只应进入 Provider 上下文一次"
        clean_dispatch = "\n".join(
            (
                "## Room 任务",
                "原始需求（不可改写）：",
                f"- {original}",
                "当前任务：",
                "- 目标：验证唯一投影",
            )
        )
        clean_prompt = (
            '<room-projection state="pending">\n'
            f'<room-fact kind="dispatch_state">{clean_dispatch}</room-fact>\n'
            "</room-projection>"
        )
        context = {
            "modelCalls": [
                _model_call(
                    index=1,
                    system_prompt=clean_prompt,
                    messages=[{"role": "user", "content": "work"}],
                    tools=[],
                    previous_messages=None,
                )
            ]
        }

        clean = CANARY.provider_prompt_governance_evidence(context)
        self.assertTrue(
            clean["originalRequirementProjectionDeduplicatedEveryCall"]
        )
        self.assertEqual(clean["catalogOriginalReferenceCount"], 1)
        self.assertEqual(clean["duplicateOriginalRoomPostCount"], 0)
        self.assertEqual(clean["duplicateOriginalCatalogStatementCount"], 0)

        duplicate_dispatch = clean_dispatch + "\n" + "\n".join(
            ("补充要求：", f"- {original}")
        )
        context["modelCalls"][0]["providerContext"]["systemPrompt"] = (
            '<room-projection state="pending">\n'
            f'<room-fact kind="room_post">{original}</room-fact>\n'
            f'<room-fact kind="dispatch_state">{duplicate_dispatch}</room-fact>\n'
            "</room-projection>"
        )
        duplicated = CANARY.provider_prompt_governance_evidence(context)
        self.assertFalse(
            duplicated["originalRequirementProjectionDeduplicatedEveryCall"]
        )
        self.assertEqual(duplicated["duplicateOriginalRoomPostCount"], 1)
        self.assertEqual(
            duplicated["duplicateOriginalCatalogStatementCount"],
            1,
        )

    def test_progressive_discovery_allows_loaded_schemas_in_later_epochs(self) -> None:
        first = {
            "catalogBlocksExactlyOnceEveryCall": True,
            "routingCardFieldContractEveryCall": True,
            "routingCardContentCompleteEveryCall": True,
            "initialProductSchemasDeferred": True,
            "progressiveProductSchemasValid": True,
            "initialProductSchemaNames": [],
            "loadedProductSchemasBeforeFirstCapture": [],
            "invalidRoutingCardCount": 0,
            "truncatedRoutingCardValueCount": 0,
        }
        later = {
            **first,
            "initialProductSchemasDeferred": False,
            "initialProductSchemaCount": 3,
            "initialProductSchemaNames": [
                "room_commit",
                "room_post",
                "workspace_read",
            ],
        }

        self.assertTrue(
            CANARY.progressive_discovery_check(
                [first, later],
                [set(), {"room_commit", "room_post", "workspace_read"}],
            )
        )
        self.assertFalse(
            CANARY.progressive_discovery_check(
                [later],
                [{"room_commit", "room_post"}],
            )
        )

    def test_offline_report_recovers_provider_prefix_from_exact_turn_receipt(
        self,
    ) -> None:
        first_messages = [{"role": "user", "content": "one"}]
        second_messages = [
            *first_messages,
            {"role": "assistant", "content": "two"},
        ]
        raw = {
            "sessionId": "agent:1",
            "turnId": "turn:1",
            "capturedAtMs": 1,
            "updatedAtMs": 2,
            "modelCalls": [
                _model_call(
                    index=1,
                    system_prompt="prompt",
                    messages=first_messages,
                    tools=[{"name": "tool_search"}],
                    previous_messages=None,
                ),
                _model_call(
                    index=2,
                    system_prompt="prompt",
                    messages=second_messages,
                    tools=[{"name": "tool_search"}],
                    previous_messages=first_messages,
                ),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "context-inspection"
            receipt_dir = root / "agent_1"
            receipt_dir.mkdir(parents=True)
            (receipt_dir / "receipt.json").write_text(
                json.dumps(raw, ensure_ascii=False),
                encoding="utf-8",
            )

            evidence = REPORT._context_inspection_provider_prefix_evidence(
                root,
                session_id="agent:1",
                turn_id="turn:1",
            )

        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["source"], "context_inspection_receipt")
        self.assertEqual(evidence["sourceReceipt"]["candidateCount"], 1)

    def test_workload_files_are_two_real_files_inside_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "rag_ime"
            source.mkdir()
            first = source / "agent_service.py"
            second = source / "agent_room_kernel.py"
            first.write_text("service\n", encoding="utf-8")
            second.write_text("kernel\n", encoding="utf-8")

            resolved = CANARY.resolve_workload_files(workspace)

        self.assertEqual(resolved, (first.resolve(), second.resolve()))

    def test_tool_receipt_evidence_requires_two_applied_fenced_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipts.sqlite"
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE room_v2_capability_manifests(
                        manifest_id TEXT, manifest_hash TEXT, dispatch_id TEXT
                    );
                    CREATE TABLE room_v2_capability_runtime_bindings(
                        manifest_id TEXT, session_id TEXT
                    );
                    CREATE TABLE room_v2_tool_disclosure_receipts(
                        receipt_id TEXT, receipt_kind TEXT,
                        tool_name TEXT, schema_hash TEXT
                    );
                    CREATE TABLE room_v2_tool_invocation_receipts(
                        receipt_id TEXT, manifest_id TEXT, manifest_hash TEXT,
                        load_receipt_id TEXT, canonical_tool_name TEXT,
                        created_at_ms INTEGER
                    );
                    CREATE TABLE room_v2_tool_execution_receipts(
                        execution_receipt_id TEXT, invocation_receipt_id TEXT,
                        status TEXT, result_hash TEXT
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO room_v2_capability_manifests VALUES (?, ?, ?)",
                    ("manifest:1", "m" * 64, "dispatch:1"),
                )
                connection.execute(
                    "INSERT INTO room_v2_capability_runtime_bindings VALUES (?, ?)",
                    ("manifest:1", "session:1"),
                )
                connection.execute(
                    "INSERT INTO room_v2_tool_disclosure_receipts VALUES (?, ?, ?, ?)",
                    ("load:read", "load", "workspace_read", "s" * 64),
                )
                for index in (1, 2):
                    connection.execute(
                        "INSERT INTO room_v2_tool_invocation_receipts VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            f"invoke:{index}",
                            "manifest:1",
                            "m" * 64,
                            "load:read",
                            "workspace_read",
                            index,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO room_v2_tool_execution_receipts VALUES (?, ?, ?, ?)",
                        (f"execute:{index}", f"invoke:{index}", "applied", "r" * 64),
                    )

            evidence = CANARY.tool_receipt_evidence(
                path,
                session_id="session:1",
                dispatch_ids=["dispatch:1"],
                tool_name="workspace_read",
            )

        self.assertEqual(evidence["loadReceiptIds"], ["load:read"])
        self.assertEqual(evidence["invocationCount"], 2)
        self.assertEqual(evidence["appliedExecutionCount"], 2)

    def test_transition_report_resolves_exact_skill_and_tool_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transition.sqlite"
            evidence = {
                "originalRequirementCount": 1,
                "currentTaskPresent": True,
                "acceptanceCount": 3,
                "blockerCount": 0,
                "handoffPresent": True,
                "skillReceiptId": "skill:1",
                "toolReceiptIds": ["load:workspace", "load:commit"],
                "roomProviderEntryHash": "a" * 64,
                "sessionProviderEntryHash": "",
            }
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE room_v2_session_context_epoch_transitions(
                        session_id TEXT, source_ref TEXT, from_epoch INTEGER,
                        to_epoch INTEGER, epoch_reason TEXT, evidence_json TEXT
                    );
                    CREATE TABLE room_v2_tool_disclosure_receipts(
                        receipt_id TEXT, tool_name TEXT,
                        schema_hash TEXT, receipt_kind TEXT
                    );
                    CREATE TABLE room_v2_skill_load_receipts(
                        receipt_id TEXT, skill_id TEXT,
                        skill_hash TEXT, load_reason TEXT
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO room_v2_session_context_epoch_transitions VALUES (?, ?, ?, ?, ?, ?)",
                    ("session:1", "compact:1", 1, 2, "compaction", json.dumps(evidence)),
                )
                connection.executemany(
                    "INSERT INTO room_v2_tool_disclosure_receipts VALUES (?, ?, ?, ?)",
                    [
                        ("load:workspace", "workspace_read", "c" * 64, "load"),
                        ("load:commit", "room_commit", "d" * 64, "load"),
                    ],
                )
                connection.execute(
                    "INSERT INTO room_v2_skill_load_receipts VALUES (?, ?, ?, ?)",
                    ("skill:1", "room-implementation", "e" * 64, "compaction_restore"),
                )

            transition = REPORT._transition_evidence(
                path,
                session_id="session:1",
                source_ref="compact:1",
            )

        self.assertEqual(transition["skillReceipt"]["receiptId"], "skill:1")
        self.assertEqual(
            {item["toolName"] for item in transition["toolReceipts"]},
            {"workspace_read", "room_commit"},
        )
        self.assertEqual(transition["providerHashes"], ["a" * 64])

    def test_message_acceptance_requires_the_v2_root_contract(self) -> None:
        self.assertEqual(
            CANARY.accepted_root_id(
                {
                    "schemaVersion": "wisdom-weasel.room-ingress-accepted.v1",
                    "rootId": "room-root:1",
                }
            ),
            "room-root:1",
        )
        with self.assertRaisesRegex(RuntimeError, "Room V2 is not active"):
            CANARY.accepted_root_id(
                {
                    "schemaVersion": "rag-ime.agent-room-message.v1",
                    "roomTurnId": "room-turn:legacy",
                }
            )

    def test_memory_check_is_scoped_to_the_session_memory_envelope(self) -> None:
        requests = [
            {
                "payload": {
                    "input": [
                        {
                            "role": "developer",
                            "content": (
                                "Core 规则：不输出相关度、分数或内部 ID。\n"
                                '<rag-ime-context type="session_memory">\n'
                                "## Session 记忆\n"
                                "- **项目偏好**: 每个 epoch 只补一份恢复包。\n"
                                "</rag-ime-context>"
                            ),
                        }
                    ]
                }
            }
        ]

        blocks = CANARY._provider_session_memory_blocks(requests)

        self.assertEqual(len(blocks), 1)
        self.assertIn("每个 epoch 只补一份恢复包", blocks[0])
        self.assertNotIn("相关度", blocks[0])

    def test_memory_check_finds_internal_retrieval_metadata(self) -> None:
        requests = [
            {
                "payload": {
                    "input": (
                        '<rag-ime-context type="session_memory">'
                        "## Session 记忆\nsourceId=atom:private\n相关度：0.92"
                        "</rag-ime-context>"
                    )
                }
            }
        ]

        block = CANARY._provider_session_memory_blocks(requests)[0]
        leaked = {
            token for token in CANARY._FORBIDDEN_MEMORY_METADATA if token in block
        }

        self.assertEqual(leaked, {"sourceId", "相关度："})

    def test_memory_check_reads_deterministic_provider_context(self) -> None:
        blocks = CANARY._session_memory_blocks(
            [
                {
                    "systemPrompt": "stable prompt",
                    "messages": [
                        {
                            "role": "developer",
                            "content": (
                                '<rag-ime-context type="session_memory">'
                                "## Session 记忆\n- 只恢复一份有界上下文。"
                                "</rag-ime-context>"
                            ),
                        }
                    ],
                }
            ]
        )

        self.assertEqual(blocks, ["## Session 记忆\n- 只恢复一份有界上下文。"])

    def test_transcript_evidence_rejects_room_projection_as_user_message(self) -> None:
        entries = [
            {"type": "session", "version": 3},
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": "执行当前受管 Room 任务；任务事实以 Provider Context 为准。",
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": (
                        "收工检查未通过：请使用精确验收 ID。"
                        '<room-projection state="pending">不应进入 Session</room-projection>'
                    ),
                },
            },
        ]
        payload = "".join(
            json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_bytes(payload)

            evidence = CANARY.transcript_evidence(Path(directory), digest)

        self.assertEqual(evidence["privateTriggerCount"], 1)
        self.assertEqual(evidence["repairContinuationCount"], 1)
        self.assertEqual(evidence["roomEnvelopeCount"], 1)

    def test_transcript_evidence_requires_a_fact_free_room_compaction_pointer(self) -> None:
        entries = [
            {"type": "session", "version": 3},
            {
                "type": "compaction",
                "summary": (
                    "Managed Room history was compacted. The only authoritative "
                    'task recovery is <rag-ime-context type="room_context">.'
                ),
                "fromHook": True,
            },
        ]
        payload = "".join(
            json.dumps(entry, ensure_ascii=False) + "\n"
            for entry in entries
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_bytes(payload)
            evidence = CANARY.transcript_evidence(
                Path(directory),
                digest,
            )

        self.assertEqual(evidence["compactionCount"], 1)
        self.assertEqual(evidence["extensionCompactionCount"], 1)
        self.assertEqual(evidence["roomRecoveryPointerCount"], 1)
        self.assertEqual(evidence["compactionTaskFactLeakCount"], 0)

    def test_offline_report_reuses_recorded_session_memory_receipt(self) -> None:
        receipt = REPORT._recorded_memory_evidence(
            {
                "blockCount": 2,
                "nonEmptyBlockCount": 2,
                "forbiddenMetadata": [],
            },
            turn_id="turn:1",
            source="canary_report",
        )

        self.assertEqual(
            receipt,
            {
                "turnId": "turn:1",
                "blockCount": 2,
                "nonEmptyBlockCount": 2,
                "forbiddenMetadata": [],
                "assistantConversationBlockCount": 0,
                "source": "canary_report",
            },
        )

    def test_offline_report_reuses_sealed_transcript_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(
                json.dumps(
                    {
                        "epochs": [],
                        "observations": {"transcript": {"sha256": "a" * 64}},
                    }
                ),
                encoding="utf-8",
            )

            digest = REPORT._prior_transcript_sha(path)

        self.assertEqual(digest, "a" * 64)

    def test_transcript_boundary_does_not_require_a_repair_per_epoch(self) -> None:
        checks = REPORT._transcript_boundary_checks(
            {
                "privateTriggerCount": 3,
                "repairContinuationCount": 1,
                "roomEnvelopeCount": 0,
                "publicCanaryPostCount": 0,
                "compactionCount": 3,
                "extensionCompactionCount": 3,
                "roomRecoveryPointerCount": 3,
                "compactionTaskFactLeakCount": 0,
            },
            epoch_count=3,
        )

        self.assertEqual(
            checks,
            {
                "repairContinuationsAreBounded": True,
                "roomContextAbsentFromSessionTranscript": True,
                "piCompactionStoresOnlyRoomRecoveryPointer": True,
            },
        )

    def test_transcript_boundary_rejects_an_unbounded_repair_loop(self) -> None:
        checks = REPORT._transcript_boundary_checks(
            {
                "privateTriggerCount": 3,
                "repairContinuationCount": 4,
                "roomEnvelopeCount": 0,
                "publicCanaryPostCount": 0,
            },
            epoch_count=3,
        )

        self.assertFalse(checks["repairContinuationsAreBounded"])


if __name__ == "__main__":
    unittest.main()
