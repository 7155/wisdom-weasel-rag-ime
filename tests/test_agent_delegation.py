from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import stat
import tempfile
import threading
import time
import unittest
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_artifacts import AgentArtifactStore
from rag_ime.agent_context_runtime import AgentContextRuntime
from rag_ime.agent_delegation import (
    AgentDelegationCoordinator,
    AgentDelegationStore,
    _subagent_prompt,
)
from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_templates import AgentTemplateBudget, agent_template as real_agent_template
from rag_ime.pi_runtime import PiRuntimeConfig

_TASK_CONTRACT = {
    "expectedOutput": "一份可供主持会话核验的有界结果",
    "acceptanceCriteria": ["区分已观察事实、推断与未决风险"],
}


class _CompletingRuntime:
    def __init__(self, *, sessions, events, session_context_provider=None, **_kwargs):
        self.sessions = sessions
        self.events = events
        self.context_provider = session_context_provider
        self.stopped = False

    def prompt(self, session_id, message):
        session = self.sessions.get(session_id)
        context = dict(self.context_provider(session)) if self.context_provider else {}
        template = str(context.get("agentTemplateId") or "delegate")
        turn_id = f"turn:{template}"
        self.events.publish(
            session_id,
            "message_completed",
            {
                "message": _assistant_message(session_id, turn_id, f"{template}: {message.splitlines()[1]}"),
                "usage": {"totalTokens": 321},
            },
            turn_id=turn_id,
        )
        self.events.publish(
            session_id,
            "turn_completed",
            {"status": "completed"},
            turn_id=turn_id,
        )
        return {"accepted": True, "turnId": turn_id}

    def abort(self, session_id):
        self.events.publish(session_id, "turn_failed", {"error": "aborted"})

    def stop(self):
        self.stopped = True


class _ClaimingWithoutEvidenceRuntime(_CompletingRuntime):
    """A normal model ending is not proof that the parent task succeeded."""

    def prompt(self, session_id, _message):
        turn_id = "turn:unsupported-claim"
        self.events.publish(
            session_id,
            "message_completed",
            {
                "message": _assistant_message(
                    session_id,
                    turn_id,
                    "已修复并通过验收。",
                ),
                "usage": {"totalTokens": 12},
            },
            turn_id=turn_id,
        )
        self.events.publish(
            session_id,
            "turn_completed",
            {"status": "completed"},
            turn_id=turn_id,
        )
        return {"accepted": True, "turnId": turn_id}


class _DuplicateTerminalRuntime(_CompletingRuntime):
    """Publishes contradictory late output after an accepted terminal event."""

    def prompt(self, session_id, _message):
        first_turn_id = "turn:first-terminal"
        self.events.publish(
            session_id,
            "message_completed",
            {
                "message": _assistant_message(
                    session_id,
                    first_turn_id,
                    "首个终态前的唯一结果",
                ),
                "usage": {"totalTokens": 17},
            },
            turn_id=first_turn_id,
        )
        self.events.publish(
            session_id,
            "turn_completed",
            {"status": "completed"},
            turn_id=first_turn_id,
        )
        late_turn_id = "turn:late-contradiction"
        self.events.publish(
            session_id,
            "message_completed",
            {
                "message": _assistant_message(
                    session_id,
                    late_turn_id,
                    "不应进入父会话的迟到结果",
                ),
                "usage": {"totalTokens": 999},
            },
            turn_id=late_turn_id,
        )
        self.events.publish(
            session_id,
            "turn_failed",
            {"error": "late contradictory terminal"},
            turn_id=late_turn_id,
        )
        return {"accepted": True, "turnId": first_turn_id}


class _LateCompletionAfterCancelRuntime(_CompletingRuntime):
    """Ignores cancellation and publishes a late success."""

    def prompt(self, session_id, _message):
        self.session_id = session_id
        self.events.publish(session_id, "text_delta", {"delta": "超" * 300})
        return {"accepted": True, "turnId": "turn:over-budget-late"}

    def abort(self, session_id):
        turn_id = "turn:late-after-cancel"
        self.events.publish(
            session_id,
            "message_completed",
            {
                "message": _assistant_message(
                    session_id,
                    turn_id,
                    "取消后的迟到成功不应被接收",
                ),
                "usage": {"totalTokens": 777},
            },
            turn_id=turn_id,
        )
        self.events.publish(
            session_id,
            "turn_completed",
            {"status": "completed"},
            turn_id=turn_id,
        )


class _HangingRuntime(_CompletingRuntime):
    def prompt(self, session_id, _message):
        self.session_id = session_id
        return {"accepted": True, "turnId": "turn:hanging"}


class _ForkInspectingRuntime(_CompletingRuntime):
    snapshots: list[dict[str, object]] = []

    def prompt(self, session_id, message):
        session = self.sessions.get(session_id)
        path = Path(str(session["sessionFile"]))
        self.__class__.snapshots.append(
            {
                "path": path,
                "mode": stat.S_IMODE(path.stat().st_mode),
                "text": path.read_text(encoding="utf-8"),
            }
        )
        return super().prompt(session_id, message)


class _SoftBudgetRuntime(_CompletingRuntime):
    def prompt(self, session_id, message):
        self.events.publish(session_id, "text_delta", {"delta": "软" * 205})
        return super().prompt(session_id, message)


class _IgnoringAbortRuntime(_CompletingRuntime):
    instances: list["_IgnoringAbortRuntime"] = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.abort_count = 0
        self.stop_count = 0
        self.__class__.instances.append(self)

    def prompt(self, session_id, _message):
        self.events.publish(session_id, "text_delta", {"delta": "硬" * 300})
        return {"accepted": True, "turnId": "turn:over-budget"}

    def abort(self, _session_id):
        self.abort_count += 1

    def stop(self):
        self.stop_count += 1
        self.stopped = True


class _ManyTurnsAndToolsRuntime(_CompletingRuntime):
    def prompt(self, session_id, _message):
        for index in range(20):
            self.events.publish(
                session_id,
                "tool_started",
                {"toolCallId": f"tool:{index}", "toolName": "knowledge"},
                turn_id=f"turn:{index}",
            )
        for index in range(12):
            turn_id = f"turn:{index}"
            self.events.publish(
                session_id,
                "message_completed",
                {
                    "message": _assistant_message(session_id, turn_id, f"阶段 {index + 1}"),
                    "usage": {"totalTokens": 1},
                },
                turn_id=turn_id,
            )
        self.events.publish(
            session_id,
            "turn_completed",
            {"status": "completed"},
            turn_id="turn:11",
        )
        return {"accepted": True, "turnId": "turn:11"}


class _InteractiveRuntime(_CompletingRuntime):
    instances: list["_InteractiveRuntime"] = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.deliveries: list[tuple[str, str]] = []
        self.ui_resolutions: list[tuple[str, dict[str, object]]] = []
        self.session_id = ""
        self.__class__.instances.append(self)

    def prompt(self, session_id, message, *, delivery="prompt", **_kwargs):
        self.deliveries.append((delivery, message))
        self.session_id = session_id
        if delivery == "prompt":
            self.events.publish(
                session_id,
                "tool_started",
                {"toolCallId": "tool:1", "toolName": "knowledge"},
                turn_id="turn:interactive",
            )
            self.events.publish(
                session_id,
                "user_input_required",
                {
                    "requestId": "request:choice",
                    "method": "confirm",
                    "title": "选择实现路径",
                    "message": "是否保留兼容层？",
                    "options": ["是", "否"],
                    "defaultValue": "否",
                },
                turn_id="turn:interactive",
            )
        return {"accepted": True, "turnId": "turn:interactive", "delivery": delivery}

    def resolve_ui_request(self, session_id, request_id, *, response):
        self.session_id = session_id
        self.ui_resolutions.append((request_id, dict(response)))
        return {"requestId": request_id, "resolved": True}

    def messages(self, session_id):
        return [
            {
                "schemaVersion": "rag-ime.agent-message.v1",
                "id": "message:task",
                "sessionId": session_id,
                "turnId": "turn:interactive",
                "role": "user",
                "status": "completed",
                "blocks": [
                    {
                        "id": "block:task",
                        "type": "text",
                        "status": "completed",
                        "presentationKind": "markdown",
                        "data": {"text": "核对实现路径"},
                    }
                ],
                "attachments": [],
                "citations": [],
                "createdAtMs": 1,
            }
        ]


class _RejectingUiRuntime(_InteractiveRuntime):
    def resolve_ui_request(self, session_id, request_id, *, response):
        del session_id, request_id, response
        raise RuntimeError("UI resolution ACK failed")


class _ResumeRuntime(_CompletingRuntime):
    prompts: list[str] = []

    def prompt(self, session_id, message, **_kwargs):
        self.__class__.prompts.append(message)
        if len(self.__class__.prompts) == 1:
            self.events.publish(
                session_id,
                "turn_failed",
                {"error": "temporary failure"},
                turn_id="turn:first",
            )
            return {"accepted": True, "turnId": "turn:first"}
        turn_id = "turn:resumed"
        self.events.publish(
            session_id,
            "message_completed",
            {
                "message": _assistant_message(session_id, turn_id, "恢复后完成"),
                "usage": {"totalTokens": 123},
            },
            turn_id=turn_id,
        )
        self.events.publish(
            session_id,
            "turn_completed",
            {"status": "completed"},
            turn_id=turn_id,
        )
        return {"accepted": True, "turnId": turn_id}

    def messages(self, _session_id):
        return []


class AgentDelegationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-delegation-")
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.events = AgentEventHub(sequence_loader=self.sessions.max_event_sequence)
        self.context_runtime = AgentContextRuntime(self.db_path)
        self.context_runtime.initialize()
        self.config = PiRuntimeConfig(
            enabled=True,
            executable=self.root / "pi",
            agent_dir=self.root / "config",
            session_dir=self.root / "sessions",
            logs_dir=self.root / "logs",
            tools=("memory", "knowledge", "agents"),
        )
        self.parent = self.sessions.create(
            title="主持会话",
            role_id="companion-firstlight-v1",
            role_version="1",
            model_profile="gpt/test-model",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def coordinator(
        self,
        runtime_factory=_CompletingRuntime,
        *,
        cancellation_grace_ms: int = 50,
        subagent_session_retention_ms: int | None = None,
        subagent_session_gc_interval_ms: int | None = None,
        room_context_provider=None,
    ) -> AgentDelegationCoordinator:
        return AgentDelegationCoordinator(
            db_path=self.db_path,
            runtime_config=self.config,
            sessions=self.sessions,
            events=self.events,
            context_runtime=self.context_runtime,
            runtime_factory=runtime_factory,
            cancellation_grace_ms=cancellation_grace_ms,
            subagent_session_retention_ms=subagent_session_retention_ms,
            subagent_session_gc_interval_ms=subagent_session_gc_interval_ms,
            room_context_provider=room_context_provider,
        )

    def test_fixed_catalog_parallel_results_and_internal_sessions(self) -> None:
        coordinator = self.coordinator()
        catalog = coordinator.catalog()
        self.assertEqual(
            [item["templateId"] for item in catalog["items"]],
            ["researcher", "planner", "worker", "reviewer", "delegate"],
        )
        self.assertTrue(all(item["budget"]["maxTurns"] == 0 for item in catalog["items"]))
        self.assertTrue(all(item["budget"]["maxToolCalls"] == 0 for item in catalog["items"]))

        response = coordinator.delegate(
            str(self.parent["id"]),
            {
                "contextMode": "fresh",
                "tasks": [
                    {
                        "agent": "researcher",
                        "task": "核对已有证据",
                        **_TASK_CONTRACT,
                        "outputSchema": {
                            "type": "object",
                            "required": ["claims"],
                            "properties": {"claims": {"type": "array"}},
                        },
                    },
                    {"agent": "reviewer", "task": "检查结论是否充分", **_TASK_CONTRACT},
                ],
            },
        )
        batch = response["batch"]
        self.assertEqual(response["acceptanceScope"], "delegation_request")
        self.assertEqual(batch["state"], "completed")
        self.assertEqual(batch["depth"], 1)
        self.assertEqual(batch["resultDeliveryMode"], "inline")
        self.assertEqual(len(batch["runs"]), 2)
        self.assertEqual({run["usage"]["totalTokens"] for run in batch["runs"]}, {321})
        self.assertTrue(
            all(run["expectedOutput"] == _TASK_CONTRACT["expectedOutput"] for run in batch["runs"])
        )
        self.assertTrue(
            all(
                run["acceptanceCriteria"] == _TASK_CONTRACT["acceptanceCriteria"]
                for run in batch["runs"]
            )
        )
        self.assertTrue(all(run["result"]["summary"] for run in batch["runs"]))
        self.assertTrue(
            all(run["result"]["deliveryStatus"] == "returned" for run in batch["runs"])
        )
        self.assertTrue(
            all(
                run["result"]["verificationStatus"] == "unverified"
                for run in batch["runs"]
            )
        )
        self.assertTrue(
            all(run["result"]["authority"] == "evidence_only" for run in batch["runs"])
        )
        self.assertTrue(all(run["artifact"]["recordCount"] >= 4 for run in batch["runs"]))
        self.assertNotIn(str(self.root), json.dumps(batch["runs"][0]["artifact"]))
        self.assertEqual([item["id"] for item in self.sessions.list()], [self.parent["id"]])
        self.assertEqual(
            [item["id"] for item in self.sessions.list(include_archived=True)],
            [self.parent["id"]],
        )
        internal = self.sessions.list(include_archived=True, include_internal=True)
        self.assertEqual(len(internal), 3)
        children = [item for item in internal if item["id"] != self.parent["id"]]
        self.assertTrue(all(item["sessionKind"] == "subagent_runtime" for item in children))
        self.assertTrue(all(item["status"] != "archived" for item in children))
        run_id = str(batch["runs"][0]["id"])
        _wait_until(
            lambda: "runtime_retained"
            in {
                str(item["eventType"])
                for item in coordinator.artifacts.lifecycle_records(
                    owner_kind="subagent_run", owner_id=run_id
                )
            }
        )
        records = coordinator.artifacts.lifecycle_records(
            owner_kind="subagent_run",
            owner_id=run_id,
        )
        self.assertIn("runtime_retained", {str(item["eventType"]) for item in records})
        projection = coordinator.artifacts.snapshot(
            owner_kind="subagent_run",
            owner_id=run_id,
        )["projection"]
        self.assertEqual(projection["expectedOutput"], _TASK_CONTRACT["expectedOutput"])
        self.assertEqual(
            projection["acceptanceCriteria"],
            _TASK_CONTRACT["acceptanceCriteria"],
        )
        self.assertEqual(projection["outputSchema"]["required"], ["claims"])
        self.assertNotIn("runtime_retired", {str(item["eventType"]) for item in records})
        with self.assertRaisesRegex(ValueError, "unsupported agent template"):
            coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "market-shell-agent", "task": "执行任意命令", **_TASK_CONTRACT},
            )
        coordinator.close()

    def test_read_only_execution_mode_fences_stale_parent_profile(self) -> None:
        coordinator = self.coordinator()
        parent_id = str(self.parent["id"])
        original_get = self.sessions.get

        def stale_parent_get(session_id: str, *args, **kwargs):
            session = original_get(session_id, *args, **kwargs)
            if str(session_id) == parent_id:
                return {
                    **session,
                    "toolProfileVersion": "control-center-v1",
                    "executionMode": "read_only",
                }
            return session

        try:
            with patch.object(self.sessions, "get", side_effect=stale_parent_get):
                batch = coordinator.delegate(
                    parent_id,
                    {"agent": "worker", "task": "只读子任务", **_TASK_CONTRACT},
                )["batch"]
            child = self.sessions.get(str(batch["runs"][0]["childSessionId"]))
            self.assertEqual(child["toolProfileVersion"], "subagent-readonly-v1")
            self.assertEqual(child["executionMode"], "read_only")
        finally:
            coordinator.close()

    def test_room_bound_delegation_records_task_lineage(self) -> None:
        coordinator = self.coordinator(
            room_context_provider=lambda _session_id: {
                "roomBound": True,
                "roomId": "room:delegation",
                "rootId": "root:delegation",
                "taskId": "task:delegation",
                "dispatchId": "dispatch:delegation",
                "generation": 7,
            }
        )

        response = coordinator.delegate(
            str(self.parent["id"]),
            {
                "agent": "researcher",
                "task": "读取任务证据",
                **_TASK_CONTRACT,
            },
        )

        self.assertEqual(
            response["batch"]["causalMetadata"],
            {
                "todoId": f"todo:{self.parent['id']}",
                "todoRevision": 0,
                "goalId": "",
                "goalRevision": 0,
                "roomBound": True,
                "roomId": "room:delegation",
                "rootId": "root:delegation",
                "taskId": "task:delegation",
                "dispatchId": "dispatch:delegation",
                "generation": 7,
            },
        )
        coordinator.close()

    def test_room_bound_child_prompt_routes_handoff_without_private_room_ownership(
        self,
    ) -> None:
        run = {
            "task": "核对 Room 委派上下文",
            "expectedOutput": "有界结果",
            "acceptanceCriteria": ["列出真实依据"],
        }
        fork_batch = {
            "contextMode": "fork",
            "depth": 2,
            "maxDepth": 2,
            "causalMetadata": {"roomBound": True},
        }
        fork_prompt = _subagent_prompt(run, fork_batch)
        self.assertIn("私有、有界助手", fork_prompt)
        self.assertIn("不得 settle Room、room_post 或直接打开原生 Ask", fork_prompt)
        self.assertIn("exact managed Pi transcript prefix", fork_prompt)
        self.assertIn("不承诺 provider cache hit", fork_prompt)
        self.assertIn("只用 status/symbols/hover/definition/references/diagnostics", fork_prompt)
        self.assertIn("hash-bound approval", fork_prompt)
        self.assertIn("导出符号变更先用 references", fork_prompt)

        fresh_prompt = _subagent_prompt(
            run,
            {
                **fork_batch,
                "contextMode": "fresh",
            },
        )
        self.assertIn("fresh 表示独立上下文", fresh_prompt)
        self.assertIn("不引入父会话私有 transcript", fresh_prompt)

        ordinary_prompt = _subagent_prompt(
            run,
            {
                **fork_batch,
                "causalMetadata": {"roomBound": False},
            },
        )
        self.assertNotIn("Room nested handoff", ordinary_prompt)


    def test_delegation_contract_rejects_legacy_unstructured_tasks(self) -> None:
        coordinator = self.coordinator()
        with self.assertRaisesRegex(ValueError, "expectedOutput"):
            coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "researcher", "task": "旧式无结构委派"},
            )
        with self.assertRaisesRegex(ValueError, "one to eight"):
            coordinator.delegate(
                str(self.parent["id"]),
                {
                    "agent": "researcher",
                    "task": "缺少验收条件",
                    "expectedOutput": "一份报告",
                    "acceptanceCriteria": [],
                },
            )
        coordinator.close()

    def test_store_serializes_concurrent_terminal_writers(self) -> None:
        artifacts = AgentArtifactStore(self.db_path)
        store = AgentDelegationStore(self.db_path, artifacts=artifacts)
        store.initialize()
        child = self.sessions.create(title="concurrent terminal child")
        batch = store.create_batch(
            parent_session_id=str(self.parent["id"]),
            parent_run_id="",
            context_mode="fresh",
            depth=1,
            max_depth=2,
            runs=[_run_spec(str(child["id"]), task="并发终态只接收一次")],
        )
        run_id = str(batch["runs"][0]["id"])
        store.start_run(run_id)

        def finish(summary: str) -> dict[str, object]:
            return store.finish_run(
                run_id,
                state="completed",
                result={
                    "summary": summary,
                    "deliveryStatus": "returned",
                    "verificationStatus": "unverified",
                    "authority": "evidence_only",
                },
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            returned = list(pool.map(finish, ("first", "second")))

        self.assertEqual(returned[0]["result"], returned[1]["result"])
        self.assertIn(returned[0]["result"]["summary"], {"first", "second"})
        terminal_events = [
            event["eventType"]
            for event in store.list_events(run_id)
            if event["eventType"] in {"completed", "failed", "aborted", "timed_out"}
        ]
        self.assertEqual(terminal_events, ["completed"])

    def test_async_terminal_result_is_scheduled_once_without_parent_acceptance(self) -> None:
        coordinator = self.coordinator()
        response = coordinator.delegate(
            str(self.parent["id"]),
            {
                "agent": "reviewer",
                "task": "异步核对证据",
                "expectedOutput": "结构化复核结论",
                "acceptanceCriteria": ["结论带有证据边界"],
                "outputSchema": {
                    "type": "object",
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                },
                "wait": False,
            },
        )
        self.assertFalse(response["waited"])
        self.assertEqual(response["batch"]["resultDeliveryMode"], "next_turn")
        run_id = str(response["batch"]["runs"][0]["id"])
        _wait_until(
            lambda: coordinator.store.get_run(run_id)["resultContextScheduledAtMs"]
            is not None
        )
        terminal = coordinator.store.get_run(run_id)
        self.assertEqual(terminal["state"], "completed")
        self.assertEqual(terminal["result"]["deliveryStatus"], "returned")
        self.assertEqual(terminal["result"]["verificationStatus"], "unverified")
        self.assertEqual(terminal["result"]["authority"], "evidence_only")
        context_items = [
            item
            for item in self.context_runtime.list_items(str(self.parent["id"]))
            if item["sourceKind"] == "subagent_result"
        ]
        self.assertEqual(len(context_items), 1)
        item_id = context_items[0]["itemId"]
        coordinator.close()

        restarted = self.coordinator()
        repeated = [
            item
            for item in self.context_runtime.list_items(str(self.parent["id"]))
            if item["sourceKind"] == "subagent_result"
        ]
        self.assertEqual([item["itemId"] for item in repeated], [item_id])
        materialized = self.context_runtime.materialize(str(self.parent["id"]))
        self.assertEqual(materialized["itemIds"], [item_id])
        payload = materialized["items"][0]["payload"]
        self.assertEqual(payload["deliveryStatus"], "returned")
        self.assertEqual(payload["verificationStatus"], "unverified")
        self.assertEqual(payload["authority"], "evidence_only")
        self.assertEqual(payload["acceptanceCriteria"], ["结论带有证据边界"])
        self.assertEqual(
            self.sessions.agent_todo(str(self.parent["id"]))["phases"],
            [],
        )
        restarted.close()

    def test_first_terminal_result_is_ingested_once_and_late_terminal_is_ignored(self) -> None:
        coordinator = self.coordinator(_DuplicateTerminalRuntime)
        try:
            response = coordinator.delegate(
                str(self.parent["id"]),
                {
                    "agent": "reviewer",
                    "task": "验证首个终态结果",
                    **_TASK_CONTRACT,
                    "wait": False,
                },
            )
            run_id = str(response["batch"]["runs"][0]["id"])

            def terminal_parent_progress() -> list[Mapping[str, object]]:
                events, gap = self.events.replay(str(self.parent["id"]))
                self.assertFalse(gap)
                return [
                    event.payload
                    for event in events
                    if event.event_type == "tool_progress"
                    and event.payload.get("runId") == run_id
                    and event.payload.get("state") == "completed"
                ]

            _wait_until(
                lambda: coordinator.store.get_run(run_id)["resultContextScheduledAtMs"]
                is not None
            )
            _wait_until(lambda: len(terminal_parent_progress()) == 1)
            run = coordinator.store.get_run(run_id)
            self.assertEqual(run["state"], "completed")
            self.assertIn("首个终态前的唯一结果", run["result"]["summary"])
            self.assertNotIn("迟到结果", run["result"]["summary"])
            self.assertEqual(run["usage"]["turnCount"], 1)
            self.assertEqual(run["usage"]["totalTokens"], 17)
            terminal_events = [
                event["eventType"]
                for event in coordinator.store.list_events(run_id)
                if event["eventType"] in {"completed", "failed", "aborted", "timed_out"}
            ]
            self.assertEqual(terminal_events, ["completed"])
            context_items = [
                item
                for item in self.context_runtime.list_items(str(self.parent["id"]))
                if item["sourceKind"] == "subagent_result"
                and item["sourceId"] == run_id
            ]
            self.assertEqual(len(context_items), 1)
            materialized = self.context_runtime.materialize(str(self.parent["id"]))
            payload = next(
                item["payload"]
                for item in materialized["items"]
                if item["itemId"] == context_items[0]["itemId"]
            )
            self.assertEqual(payload["verificationStatus"], "unverified")
            snapshot = coordinator.artifacts.snapshot(
                owner_kind="subagent_run",
                owner_id=run_id,
            )
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(
                snapshot["runtimeCheckpoint"]["terminalState"],
                "completed",
            )
            self.assertNotIn("迟到结果", json.dumps(snapshot, ensure_ascii=False))
        finally:
            coordinator.close()

    def test_cancelled_run_rejects_late_success_and_projects_one_failed_result(self) -> None:
        with patch(
            "rag_ime.agent_delegation.agent_template",
            side_effect=_small_budget_template,
        ):
            coordinator = self.coordinator(_LateCompletionAfterCancelRuntime)
            try:
                response = coordinator.delegate(
                    str(self.parent["id"]),
                    {
                        "agent": "worker",
                        "task": "触发取消后迟到成功",
                        **_TASK_CONTRACT,
                        "wait": False,
                    },
                )
                run_id = str(response["batch"]["runs"][0]["id"])

                def failed_parent_progress() -> list[Mapping[str, object]]:
                    events, gap = self.events.replay(str(self.parent["id"]))
                    self.assertFalse(gap)
                    return [
                        event.payload
                        for event in events
                        if event.event_type == "tool_progress"
                        and event.payload.get("runId") == run_id
                        and event.payload.get("state") == "failed"
                    ]

                _wait_until(
                    lambda: coordinator.store.get_run(run_id)["resultContextScheduledAtMs"]
                    is not None
                )
                _wait_until(lambda: len(failed_parent_progress()) == 1)
                run = coordinator.store.get_run(run_id)
                self.assertEqual(run["state"], "failed")
                self.assertEqual(run["error"], "output budget exceeded")
                self.assertEqual(run["result"], {})
                self.assertEqual(run["usage"]["turnCount"], 0)
                self.assertEqual(run["usage"]["totalTokens"], 0)
                terminal_events = [
                    event["eventType"]
                    for event in coordinator.store.list_events(run_id)
                    if event["eventType"] in {"completed", "failed", "aborted", "timed_out"}
                ]
                self.assertEqual(terminal_events, ["failed"])
                context_items = [
                    item
                    for item in self.context_runtime.list_items(str(self.parent["id"]))
                    if item["sourceKind"] == "subagent_result"
                    and item["sourceId"] == run_id
                ]
                self.assertEqual(len(context_items), 1)
                materialized = self.context_runtime.materialize(str(self.parent["id"]))
                payload = next(
                    item["payload"]
                    for item in materialized["items"]
                    if item["itemId"] == context_items[0]["itemId"]
                )
                self.assertEqual(payload["state"], "failed")
                self.assertEqual(payload["verificationStatus"], "unverified")
                snapshot = coordinator.artifacts.snapshot(
                    owner_kind="subagent_run",
                    owner_id=run_id,
                )
                self.assertIsNotNone(snapshot)
                assert snapshot is not None
                self.assertEqual(
                    snapshot["runtimeCheckpoint"]["terminalState"],
                    "failed",
                )
                self.assertNotIn(
                    "取消后的迟到成功",
                    json.dumps(snapshot, ensure_ascii=False),
                )
            finally:
                coordinator.close()

    def test_todo_backed_delegation_requires_and_preserves_explicit_task_link(self) -> None:
        session_id = str(self.parent["id"])
        todo_task = "核对子 Agent 证据"
        self.sessions.mutate_agent_todo(
            session_id,
            {
                "op": "init",
                "list": [{"phase": "验证", "items": [todo_task]}],
            },
        )
        self.sessions.mutate_agent_todo(
            session_id,
            {"op": "start", "task": todo_task},
        )
        coordinator = self.coordinator()
        try:
            with self.assertRaisesRegex(ValueError, "todoTask is required"):
                coordinator.delegate(
                    session_id,
                    {"agent": "researcher", "task": "缺少明确 Todo 关联", **_TASK_CONTRACT},
                )
            with self.assertRaisesRegex(ValueError, "does not belong"):
                coordinator.delegate(
                    session_id,
                    {
                        "agent": "researcher",
                        "task": "错误 Todo 关联",
                        **_TASK_CONTRACT,
                        "todoTask": "其他不存在的任务",
                    },
                )

            batch = coordinator.delegate(
                session_id,
                {
                    "agent": "researcher",
                    "task": "返回证据供主持会话核验",
                    **_TASK_CONTRACT,
                    "todoTask": todo_task,
                },
            )["batch"]
            run = batch["runs"][0]
            self.assertEqual(run["todoTask"], todo_task)
            self.assertEqual(run["todoPhase"], "验证")
            self.assertEqual(run["state"], "completed")
            self.assertEqual(
                self.sessions.agent_todo(session_id)["phases"][0]["tasks"][0]["status"],
                "in_progress",
            )

            def linked_terminal_progress() -> list[Mapping[str, object]]:
                parent_events, gap = self.events.replay(session_id)
                self.assertFalse(gap)
                return [
                    event.payload
                    for event in parent_events
                    if event.event_type == "tool_progress"
                    and event.payload.get("runId") == run["id"]
                    and event.payload.get("state") == "completed"
                ]

            _wait_until(lambda: bool(linked_terminal_progress()))
            terminal_progress = linked_terminal_progress()
            self.assertEqual(terminal_progress[-1]["todoTask"], todo_task)
            self.assertEqual(terminal_progress[-1]["todoPhase"], "验证")
            self.assertTrue(terminal_progress[-1]["requiresParentTodoUpdate"])
        finally:
            coordinator.close()

    def test_model_claim_without_receipts_is_returned_but_never_accepted(self) -> None:
        coordinator = self.coordinator(_ClaimingWithoutEvidenceRuntime)
        try:
            response = coordinator.delegate(
                str(self.parent["id"]),
                {
                    "agent": "worker",
                    "task": "声称完成但不提供任何工具证据",
                    **_TASK_CONTRACT,
                },
            )

            self.assertEqual(response["acceptanceScope"], "delegation_request")
            run = response["batch"]["runs"][0]
            self.assertEqual(run["state"], "completed")
            self.assertEqual(run["result"]["deliveryStatus"], "returned")
            self.assertEqual(run["result"]["verificationStatus"], "unverified")
            self.assertEqual(run["result"]["authority"], "evidence_only")
            self.assertIn("已修复并通过验收", run["result"]["summary"])
            self.assertNotIn("evidenceRefs", run["result"])
            self.assertNotIn("artifactRefs", run["result"])

            def progress_summaries() -> list[str]:
                parent_events, gap = self.events.replay(str(self.parent["id"]))
                self.assertFalse(gap)
                return [
                    str(event.payload.get("summary") or "")
                    for event in parent_events
                    if event.event_type == "tool_progress"
                ]

            _wait_until(
                lambda: "子 Agent 已返回结果，待主持会话核验"
                in progress_summaries()
            )
            summaries = progress_summaries()
            self.assertIn("子 Agent 已返回结果，待主持会话核验", summaries)
            self.assertNotIn("子 Agent 已完成", summaries)
        finally:
            coordinator.close()

    def test_paused_or_exhausted_parent_goal_blocks_new_delegation(self) -> None:
        goal = self.sessions.mutate_agent_goal(
            str(self.parent["id"]),
            {
                "action": "confirm_setup",
                "confirmed": True,
                "expectedRevision": 0,
                "objective": "在预算内完成委派",
                "tokenBudget": 5,
            },
        )["workflow"]["goal"]
        paused = self.sessions.mutate_agent_goal(
            str(self.parent["id"]),
            {"action": "pause", "expectedRevision": goal["revision"]},
        )["workflow"]["goal"]
        coordinator = self.coordinator()
        with self.assertRaisesRegex(ValueError, "goal_paused"):
            coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "worker", "task": "不应启动", "contextMode": "fresh", **_TASK_CONTRACT},
            )
        resumed = self.sessions.mutate_agent_goal(
            str(self.parent["id"]),
            {"action": "resume", "expectedRevision": paused["revision"]},
        )["workflow"]["goal"]
        self.sessions.record_agent_goal_usage(
            str(self.parent["id"]),
            idempotency_key="delegate-gate:usage",
            turn_id="turn:delegate-gate",
            event_id="event:delegate-gate",
            token_delta=5,
            elapsed_delta_ms=0,
        )
        with self.assertRaisesRegex(ValueError, "goal_budget_exhausted"):
            coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "worker", "task": "仍不应启动", "contextMode": "fresh", **_TASK_CONTRACT},
            )
        self.assertGreaterEqual(resumed["revision"], goal["revision"])
        coordinator.close()

    def test_default_templates_do_not_stop_on_fixed_turn_or_tool_counts(self) -> None:
        coordinator = self.coordinator(_ManyTurnsAndToolsRuntime)
        batch = coordinator.delegate(
            str(self.parent["id"]),
            {"agent": "researcher", "task": "完成需要多轮检索的任务", **_TASK_CONTRACT},
        )["batch"]

        run = batch["runs"][0]
        self.assertEqual(run["state"], "completed")
        self.assertEqual(run["budget"]["maxTurns"], 0)
        self.assertEqual(run["budget"]["maxToolCalls"], 0)
        self.assertEqual(run["usage"]["turnCount"], 12)
        self.assertEqual(run["usage"]["toolCount"], 20)
        self.assertEqual(run["supervision"]["phase"], "none")
        coordinator.close()

    def test_artifact_inspection_requires_the_owning_parent_session(self) -> None:
        coordinator = self.coordinator()
        batch = coordinator.delegate(
            str(self.parent["id"]),
            {"agent": "reviewer", "task": "检查受控 Artifact", **_TASK_CONTRACT},
        )["batch"]
        artifact_id = str(batch["runs"][0]["artifact"]["artifactId"])
        other = self.sessions.create(title="其他主持会话")

        inspected = coordinator.inspect_artifact(
            str(self.parent["id"]),
            artifact_id,
            limit=3,
        )

        self.assertEqual(inspected["artifact"]["artifactId"], artifact_id)
        self.assertLessEqual(inspected["returnedRecords"], 3)
        with self.assertRaisesRegex(ValueError, "does not belong"):
            coordinator.inspect_artifact(str(other["id"]), artifact_id)
        coordinator.close()

    def test_subagent_permissions_are_intersected_with_explicit_parent_allowlist(self) -> None:
        self.parent = self.sessions.set_runtime_policy(
            str(self.parent["id"]),
            mode="assistant",
            tool_profile_version="control-center-v1",
            allowed_tools=["overview", "memory"],
        )
        coordinator = self.coordinator()
        batch = coordinator.delegate(
            str(self.parent["id"]),
            {"agent": "worker", "task": "只能使用父会话允许的工具", **_TASK_CONTRACT},
        )["batch"]
        child = self.sessions.get(str(batch["runs"][0]["childSessionId"]))

        self.assertEqual(child["toolProfileVersion"], "subagent-worker-v1")
        self.assertEqual(child["toolAllowlistMode"], "explicit")
        self.assertEqual(child["allowedTools"], ["overview", "memory"])
        coordinator.close()

    def test_retention_defaults_to_72_hours_and_gc_runs_on_startup(self) -> None:
        self.config.session_dir.mkdir(parents=True)
        child_file = self.config.session_dir / "expired-on-startup.jsonl"
        _write_jsonl(
            child_file,
            _session_records(session_id="expired-child", cwd=self.config.agent_dir),
            mode=0o600,
        )
        child = self.sessions.create(
            title="过期子任务",
            session_kind="subagent_runtime",
        )
        self.sessions.bind_runtime_session(
            str(child["id"]),
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id="expired-child",
            transcript_ref=str(child_file),
            binding_state="prepared",
        )
        store = AgentDelegationStore(self.db_path)
        store.initialize()
        batch = store.create_batch(
            parent_session_id=str(self.parent["id"]),
            parent_run_id="",
            context_mode="fresh",
            depth=1,
            max_depth=2,
            runs=[_run_spec(str(child["id"]), task="启动时回收")],
            created_at_ms=1_000,
        )
        run_id = str(batch["runs"][0]["id"])
        store.start_run(run_id, started_at_ms=1_100)
        store.finish_run(
            run_id,
            state="completed",
            result={"summary": "持久结果"},
            completed_at_ms=1_200,
        )

        coordinator = self.coordinator(
            subagent_session_retention_ms=1_000,
            subagent_session_gc_interval_ms=60_000,
        )

        default_db = self.root / "default-retention.sqlite"
        default_sessions = AgentSessionStore(default_db)
        default_sessions.initialize()
        default_context_runtime = AgentContextRuntime(default_db)
        default_context_runtime.initialize()
        with patch.dict(
            "os.environ",
            {"RAG_IME_SUBAGENT_SESSION_RETENTION_HOURS": "72"},
        ):
            default_coordinator = AgentDelegationCoordinator(
                db_path=default_db,
                runtime_config=self.config,
                sessions=default_sessions,
                events=AgentEventHub(),
                context_runtime=default_context_runtime,
                runtime_factory=_CompletingRuntime,
            )
        self.assertEqual(
            72 * 60 * 60 * 1_000,
            default_coordinator._subagent_session_retention_ms,
        )
        default_coordinator.close()
        with self.assertRaises(KeyError):
            self.sessions.get(str(child["id"]))
        self.assertFalse(child_file.exists())
        self.assertEqual(coordinator.store.get_run(run_id)["result"]["summary"], "持久结果")
        coordinator.close()

    def test_nested_delegation_stops_at_depth_two(self) -> None:
        coordinator = self.coordinator()
        first = coordinator.delegate(
            str(self.parent["id"]),
            {"agent": "delegate", "task": "第一层", **_TASK_CONTRACT},
        )["batch"]
        first_child = first["runs"][0]["childSessionId"]
        second = coordinator.delegate(
            str(first_child),
            {"agent": "reviewer", "task": "第二层", **_TASK_CONTRACT},
        )["batch"]
        self.assertEqual(second["depth"], 2)
        second_child = second["runs"][0]["childSessionId"]
        with self.assertRaisesRegex(ValueError, "maximum depth is 2"):
            coordinator.delegate(
                str(second_child),
                {"agent": "reviewer", "task": "第三层", **_TASK_CONTRACT},
            )
        coordinator.close()

    def test_fork_accepts_only_native_0600_session_and_preserves_safe_thinking(self) -> None:
        self.config.session_dir.mkdir(parents=True)
        parent_file = self.config.session_dir / "parent.jsonl"
        parent_records = _session_records(
            session_id="parent-pi",
            cwd=self.config.agent_dir,
            assistant_content=[
                {"type": "thinking", "thinking": "普通思考可以保留"},
                {"type": "text", "text": "公开结论"},
            ],
        )
        _write_jsonl(parent_file, parent_records)
        self.parent = self.sessions.prepare_session_file(
            str(self.parent["id"]),
            pi_session_id="parent-pi",
            session_file=str(parent_file),
        )
        child_file = self.config.session_dir / "native-child.jsonl"
        child_records = [dict(item) for item in parent_records]
        child_records[0] = {
            **child_records[0],
            "id": "child-pi",
            "parentSession": str(parent_file),
        }
        child_records[2] = {
            **child_records[2],
            "message": {
                "role": "assistant",
                "provider": "anthropic",
                "content": [
                    {"type": "thinking", "thinking": "普通思考可以保留"},
                    {"type": "text", "text": "公开结论"},
                ],
            },
        }
        _write_jsonl(child_file, child_records, mode=0o600)
        _ForkInspectingRuntime.snapshots.clear()
        coordinator = self.coordinator(_ForkInspectingRuntime)
        batch = coordinator.delegate(
            str(self.parent["id"]),
            {
                "agent": "planner",
                "task": "继承讨论并规划",
                **_TASK_CONTRACT,
                "contextMode": "fork",
                "_runtimeContext": _fork_context(
                    parent_file=parent_file,
                    child_file=child_file,
                    child_session_id="child-pi",
                ),
            },
        )["batch"]
        child = self.sessions.get(str(batch["runs"][0]["childSessionId"]))
        self.assertEqual(child["sessionKind"], "subagent_runtime")
        self.assertNotEqual(child["status"], "archived")
        self.assertEqual(Path(str(child["sessionFile"])).resolve(), child_file.resolve())
        self.assertNotEqual(child_file, parent_file)
        self.assertTrue(child_file.exists())
        self.assertEqual(len(_ForkInspectingRuntime.snapshots), 1)
        snapshot = _ForkInspectingRuntime.snapshots[0]
        self.assertEqual(Path(str(snapshot["path"])).resolve(), child_file.resolve())
        self.assertEqual(snapshot["mode"], 0o600)
        child_text = str(snapshot["text"])
        self.assertIn("已有上下文", child_text)
        self.assertIn("公开结论", child_text)
        self.assertIn("普通思考可以保留", child_text)
        self.assertEqual(json.loads(child_text.splitlines()[0])["id"], "child-pi")
        coordinator.close()

    def test_expired_runtime_session_is_retired_but_result_and_artifact_remain(self) -> None:
        self.config.session_dir.mkdir(parents=True)
        parent_file = self.config.session_dir / "retained-parent.jsonl"
        child_file = self.config.session_dir / "retained-child.jsonl"
        parent_records = _session_records(session_id="retained-parent", cwd=self.config.agent_dir)
        child_records = [dict(item) for item in parent_records]
        child_records[0] = {
            **child_records[0],
            "id": "retained-child",
            "parentSession": str(parent_file),
        }
        _write_jsonl(parent_file, parent_records)
        _write_jsonl(child_file, child_records, mode=0o600)
        self.parent = self.sessions.prepare_session_file(
            str(self.parent["id"]),
            pi_session_id="retained-parent",
            session_file=str(parent_file),
        )
        coordinator = self.coordinator(
            _ForkInspectingRuntime,
            subagent_session_retention_ms=1_000,
            subagent_session_gc_interval_ms=0,
        )
        batch = coordinator.delegate(
            str(self.parent["id"]),
            {
                "agent": "reviewer",
                "task": "保留后清理",
                **_TASK_CONTRACT,
                "contextMode": "fork",
                "_runtimeContext": _fork_context(
                    parent_file=parent_file,
                    child_file=child_file,
                    child_session_id="retained-child",
                ),
            },
        )["batch"]
        run = batch["runs"][0]
        child_session_id = str(run["childSessionId"])
        artifact_id = str(run["artifact"]["artifactId"])
        completed_at_ms = int(run["completedAtMs"])

        retained = self.sessions.get(child_session_id)
        self.assertNotEqual(retained["status"], "archived")
        self.assertTrue(child_file.exists())
        self.assertEqual(coordinator.collect_expired_sessions(now_ms=completed_at_ms + 999), 0)

        self.assertEqual(coordinator.collect_expired_sessions(now_ms=completed_at_ms + 1_000), 1)
        with self.assertRaises(KeyError):
            self.sessions.get(child_session_id)
        self.assertNotIn(
            child_session_id,
            {
                str(item["id"])
                for item in self.sessions.list(
                    include_archived=True, include_internal=True
                )
            },
        )
        self.assertFalse(child_file.exists())
        durable_run = coordinator.store.get_run(str(run["id"]))
        self.assertEqual(durable_run["result"]["summary"], run["result"]["summary"])
        inspected = coordinator.inspect_artifact(
            str(self.parent["id"]), artifact_id, limit=100
        )
        self.assertIn(
            "runtime_retired",
            {str(item["eventType"]) for item in inspected["records"]},
        )
        coordinator.close()

    def test_fork_rejects_missing_or_untrusted_runtime_context(self) -> None:
        self.config.session_dir.mkdir(parents=True)
        parent_file = self.config.session_dir / "parent.jsonl"
        parent_records = _session_records(session_id="parent-pi", cwd=self.config.agent_dir)
        _write_jsonl(parent_file, parent_records)
        self.parent = self.sessions.prepare_session_file(
            str(self.parent["id"]),
            pi_session_id="parent-pi",
            session_file=str(parent_file),
        )
        coordinator = self.coordinator()
        with self.assertRaisesRegex(ValueError, "active Pi runtime"):
            coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "planner", "task": "不能手工分叉", "contextMode": "fork", **_TASK_CONTRACT},
            )

        child_file = self.config.session_dir / "forged-child.jsonl"
        child_records = _session_records(
            session_id="child-pi",
            cwd=self.config.agent_dir,
            parent_session=self.config.session_dir / "someone-else.jsonl",
        )
        _write_jsonl(child_file, child_records, mode=0o600)
        with self.assertRaisesRegex(ValueError, "does not reference the active parent"):
            coordinator.delegate(
                str(self.parent["id"]),
                {
                    "agent": "planner",
                    "task": "拒绝伪造分叉",
                    **_TASK_CONTRACT,
                    "contextMode": "fork",
                    "_runtimeContext": _fork_context(
                        parent_file=parent_file,
                        child_file=child_file,
                        child_session_id="child-pi",
                    ),
                },
            )

        unsafe_file = self.config.session_dir / "unsafe-child.jsonl"
        unsafe_records = _session_records(
            session_id="unsafe-pi",
            cwd=self.config.agent_dir,
            parent_session=parent_file,
            assistant_content=[
                {
                    "type": "thinking",
                    "thinking": "不能跨会话复用",
                    "signature": "provider-bound-signature",
                }
            ],
        )
        unsafe_records[2]["message"]["provider"] = "anthropic"
        _write_jsonl(unsafe_file, unsafe_records, mode=0o600)
        with self.assertRaisesRegex(ValueError, "provider-bound thinking"):
            coordinator.delegate(
                str(self.parent["id"]),
                {
                    "agent": "planner",
                    "task": "拒绝不安全思考块",
                    **_TASK_CONTRACT,
                    "contextMode": "fork",
                    "_runtimeContext": _fork_context(
                        parent_file=parent_file,
                        child_file=unsafe_file,
                        child_session_id="unsafe-pi",
                    ),
                },
            )
        coordinator.close()

    def test_global_parallel_limit_and_abort_stop_both_runs(self) -> None:
        coordinator = self.coordinator(_HangingRuntime)
        response = coordinator.delegate(
            str(self.parent["id"]),
            {
                "wait": False,
                "tasks": [
                    {"agent": "researcher", "task": "长任务一", **_TASK_CONTRACT},
                    {"agent": "reviewer", "task": "长任务二", **_TASK_CONTRACT},
                ],
            },
        )
        batch = response["batch"]
        _wait_until(lambda: coordinator.store.active_run_count() == 2)
        self.assertEqual(
            [item["id"] for item in self.sessions.list(include_archived=True)],
            [self.parent["id"]],
        )
        live_internal = self.sessions.list(include_archived=True, include_internal=True)
        self.assertEqual(len(live_internal), 3)
        self.assertTrue(
            all(
                item["sessionKind"] == "subagent_runtime"
                for item in live_internal
                if item["id"] != self.parent["id"]
            )
        )
        with self.assertRaisesRegex(ValueError, "at most two"):
            coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "planner", "task": "第三个并行任务", "wait": False, **_TASK_CONTRACT},
            )
        receipt = coordinator.abort(
            str(self.parent["id"]),
            {"batchId": batch["id"]},
        )
        self.assertEqual(receipt["cancellation"]["state"], "terminated")
        self.assertEqual(receipt["cancellation"]["pendingRunIds"], [])
        final = receipt["batch"]
        self.assertTrue(final["abortRequested"])
        self.assertEqual({run["state"] for run in final["runs"]}, {"aborted"})
        _wait_until(lambda: coordinator.store.active_run_count() == 0)
        retained = self.sessions.list(include_archived=True, include_internal=True)
        self.assertTrue(
            all(
                item["status"] != "archived"
                for item in retained
                if item["id"] != self.parent["id"]
            )
        )
        coordinator.close()

    def test_soft_budget_is_recorded_without_stopping_a_successful_run(self) -> None:
        with patch(
            "rag_ime.agent_delegation.agent_template",
            side_effect=_small_budget_template,
        ):
            coordinator = self.coordinator(_SoftBudgetRuntime)
            batch = coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "reviewer", "task": "接近输出预算但仍完成", **_TASK_CONTRACT},
            )["batch"]

        run = batch["runs"][0]
        self.assertEqual(run["state"], "completed")
        self.assertEqual(run["supervision"]["phase"], "soft")
        records = coordinator.artifacts.lifecycle_records(
            owner_kind="subagent_run",
            owner_id=str(run["id"]),
        )
        self.assertIn("supervision_soft", {str(item["eventType"]) for item in records})
        coordinator.close()

    def test_hard_budget_uses_abort_then_forced_stop_after_grace(self) -> None:
        _IgnoringAbortRuntime.instances.clear()
        with patch(
            "rag_ime.agent_delegation.agent_template",
            side_effect=_small_budget_template,
        ):
            coordinator = self.coordinator(
                _IgnoringAbortRuntime,
                cancellation_grace_ms=20,
            )
            batch = coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "worker", "task": "触发硬输出预算", **_TASK_CONTRACT},
            )["batch"]

        run = batch["runs"][0]
        runtime = _IgnoringAbortRuntime.instances[-1]
        self.assertEqual(run["state"], "failed")
        self.assertEqual(run["error"], "output budget exceeded")
        self.assertEqual(run["supervision"]["phase"], "forced")
        self.assertGreaterEqual(runtime.abort_count, 1)
        self.assertGreaterEqual(runtime.stop_count, 1)
        records = coordinator.artifacts.lifecycle_records(
            owner_kind="subagent_run",
            owner_id=str(run["id"]),
        )
        self.assertIn("supervision_forced", {str(item["eventType"]) for item in records})
        coordinator.close()

    def test_restart_reconciles_terminal_artifact_checkpoint_without_reprompting(self) -> None:
        artifacts = AgentArtifactStore(self.db_path)
        store = AgentDelegationStore(self.db_path, artifacts=artifacts)
        store.initialize()
        child = self.sessions.create(
            title="待恢复子任务",
            role_id="companion-firstlight-v1",
            role_version="1",
            model_profile="gpt/test-model",
            session_kind="subagent_runtime",
        )
        batch = store.create_batch(
            parent_session_id=str(self.parent["id"]),
            parent_run_id="",
            context_mode="fresh",
            depth=1,
            max_depth=2,
            runs=[_run_spec(str(child["id"]), task="恢复完成态")],
        )
        run_id = str(batch["runs"][0]["id"])
        store.start_run(run_id)
        message = _assistant_message(str(child["id"]), "turn:recovered", "恢复后的结果")
        event = self.events.publish(
            str(child["id"]),
            "turn_completed",
            {"status": "completed"},
            turn_id="turn:recovered",
        )
        store.checkpoint_runtime_event(
            run_id,
            event,
            {
                "terminalState": "completed",
                "terminalAtMs": event.created_at_ms,
                "lastMessage": message,
                "usage": {"turnCount": 1, "toolCount": 0, "totalTokens": 42},
            },
        )

        coordinator = self.coordinator(_CompletingRuntime)
        recovered = coordinator.store.get_batch(str(batch["id"]))
        run = recovered["runs"][0]
        self.assertEqual(recovered["state"], "completed")
        self.assertTrue(run["result"]["recovered"])
        self.assertEqual(run["result"]["deliveryStatus"], "returned")
        self.assertEqual(run["result"]["verificationStatus"], "unverified")
        self.assertEqual(run["result"]["authority"], "evidence_only")
        self.assertEqual(run["usage"]["totalTokens"], 42)
        self.assertNotIn(run_id, coordinator._threads)
        retained = self.sessions.get(str(child["id"]))
        self.assertEqual(retained["sessionKind"], "subagent_runtime")
        self.assertNotEqual(retained["status"], "archived")
        coordinator.close()

    def test_restart_relaunches_queued_work_but_fails_uncheckpointed_running_work(self) -> None:
        artifacts = AgentArtifactStore(self.db_path)
        store = AgentDelegationStore(self.db_path, artifacts=artifacts)
        store.initialize()
        queued_child = self.sessions.create(title="安全重放 queued")
        queued = store.create_batch(
            parent_session_id=str(self.parent["id"]),
            parent_run_id="",
            context_mode="fresh",
            depth=1,
            max_depth=2,
            runs=[_run_spec(str(queued_child["id"]), task="重放 queued")],
        )
        running_child = self.sessions.create(title="拒绝猜测 running")
        running = store.create_batch(
            parent_session_id=str(self.parent["id"]),
            parent_run_id="",
            context_mode="fresh",
            depth=1,
            max_depth=2,
            runs=[_run_spec(str(running_child["id"]), task="中断 running")],
        )
        store.start_run(str(running["runs"][0]["id"]))

        coordinator = self.coordinator(_CompletingRuntime)
        _wait_until(
            lambda: coordinator.store.get_batch(str(queued["id"]))["state"] == "completed"
        )
        failed = coordinator.store.get_batch(str(running["id"]))
        self.assertEqual(failed["state"], "failed")
        self.assertIn("durable terminal checkpoint", failed["runs"][0]["error"])
        coordinator.close()

    def test_console_uses_live_runtime_and_controls_are_idempotent(self) -> None:
        _InteractiveRuntime.instances.clear()
        coordinator = self.coordinator(_InteractiveRuntime)
        response = coordinator.delegate(
            str(self.parent["id"]),
            {
                "agent": "worker",
                "task": "核对实现路径",
                **_TASK_CONTRACT,
                "contextMode": "fresh",
                "wait": False,
            },
        )
        run_id = str(response["batch"]["runs"][0]["id"])
        _wait_until(lambda: coordinator.store.get_run(run_id)["state"] == "running")
        _wait_until(lambda: len(coordinator.store.list_inbox(run_id)) == 1)

        console = coordinator.console(str(self.parent["id"]), run_id)
        self.assertEqual(console["conversation"]["source"], "active_runtime")
        self.assertTrue(console["capabilities"]["steer"]["available"])
        self.assertEqual(console["inbox"][0]["kind"], "need_decision")
        self.assertEqual(console["inbox"][0]["request"]["options"], ["是", "否"])
        self.assertEqual(console["inbox"][0]["request"]["defaultValue"], "否")
        self.assertEqual(console["run"]["usage"]["toolCount"], 1)

        first = coordinator.control(
            str(self.parent["id"]),
            run_id,
            {
                "action": "steer",
                "clientActionId": "action:one",
                "message": "保留兼容层",
            },
        )
        replay = coordinator.control(
            str(self.parent["id"]),
            run_id,
            {
                "action": "steer",
                "clientActionId": "action:one",
                "message": "保留兼容层",
            },
        )
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            _InteractiveRuntime.instances[0].deliveries.count(("steer", "保留兼容层")),
            1,
        )
        with self.assertRaisesRegex(ValueError, "different action"):
            coordinator.control(
                str(self.parent["id"]),
                run_id,
                {
                    "action": "steer",
                    "clientActionId": "action:one",
                    "message": "删除兼容层",
                },
            )

        inbox_id = str(console["inbox"][0]["id"])
        coordinator.control(
            str(self.parent["id"]),
            run_id,
            {
                "action": "reply",
                "clientActionId": "action:reply",
                "inboxId": inbox_id,
                "message": "是，保留兼容层。",
            },
        )
        self.assertEqual(coordinator.store.list_inbox(run_id)[0]["status"], "replied")
        self.assertEqual(
            _InteractiveRuntime.instances[0].ui_resolutions,
            [("request:choice", {"value": "是，保留兼容层。"})],
        )
        self.assertNotIn(
            ("steer", "是，保留兼容层。"),
            _InteractiveRuntime.instances[0].deliveries,
        )
        coordinator.control(
            str(self.parent["id"]),
            run_id,
            {"action": "abort", "clientActionId": "action:abort"},
        )
        _wait_until(lambda: coordinator.store.get_run(run_id)["state"] == "aborted")
        coordinator.close()

    def test_reply_stays_pending_when_runtime_does_not_ack_ui_resolution(self) -> None:
        coordinator = self.coordinator(_RejectingUiRuntime)
        response = coordinator.delegate(
            str(self.parent["id"]),
            {
                "agent": "worker",
                "task": "核对 ACK 顺序",
                **_TASK_CONTRACT,
                "contextMode": "fresh",
                "wait": False,
            },
        )
        run_id = str(response["batch"]["runs"][0]["id"])
        _wait_until(lambda: len(coordinator.store.list_inbox(run_id)) == 1)
        inbox_id = str(coordinator.store.list_inbox(run_id)[0]["id"])

        with self.assertRaisesRegex(RuntimeError, "ACK failed"):
            coordinator.control(
                str(self.parent["id"]),
                run_id,
                {
                    "action": "reply",
                    "clientActionId": "reply:no-ack",
                    "inboxId": inbox_id,
                    "message": "是",
                },
            )
        self.assertEqual(coordinator.store.list_inbox(run_id)[0]["status"], "pending")
        coordinator.close()

    def test_resume_continues_the_retained_child_session(self) -> None:
        _ResumeRuntime.prompts.clear()
        coordinator = self.coordinator(_ResumeRuntime)
        response = coordinator.delegate(
            str(self.parent["id"]),
            {
                "agent": "reviewer",
                "task": "完成中断恢复验证",
                **_TASK_CONTRACT,
                "contextMode": "fresh",
                "wait": False,
            },
        )
        run_id = str(response["batch"]["runs"][0]["id"])
        child_session_id = str(response["batch"]["runs"][0]["childSessionId"])
        _wait_until(lambda: coordinator.store.get_run(run_id)["state"] == "failed")
        coordinator.control(
            str(self.parent["id"]),
            run_id,
            {
                "action": "resume",
                "clientActionId": "action:resume",
                "message": "从失败位置继续，不要重复已完成步骤。",
            },
        )
        _wait_until(lambda: coordinator.store.get_run(run_id)["state"] == "completed")
        resumed = coordinator.store.get_run(run_id)
        self.assertEqual(resumed["childSessionId"], child_session_id)
        self.assertEqual(_ResumeRuntime.prompts[-1], "从失败位置继续，不要重复已完成步骤。")
        coordinator.close()


def _assistant_message(session_id: str, turn_id: str, text: str) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-message.v1",
        "id": f"message:{turn_id}",
        "sessionId": session_id,
        "turnId": turn_id,
        "role": "assistant",
        "status": "completed",
        "blocks": [
            {
                "id": f"text:{turn_id}",
                "type": "text",
                "status": "completed",
                "presentationKind": "markdown",
                "data": {"text": text},
            }
        ],
        "attachments": [],
        "citations": [],
        "createdAtMs": 10,
        "completedAtMs": 11,
    }


def _small_budget_template(template_id: object, version: object = "1"):
    template = real_agent_template(template_id, version)
    return replace(
        template,
        budget=AgentTemplateBudget(
            max_depth=2,
            max_turns=8,
            max_tool_calls=12,
            max_total_tokens=10_000,
            max_duration_ms=5_000,
            max_output_chars=256,
        ),
    )


def _run_spec(child_session_id: str, *, task: str) -> dict[str, object]:
    return {
        "childSessionId": child_session_id,
        "templateId": "reviewer",
        "templateVersion": "1",
        "task": task,
        **_TASK_CONTRACT,
        "maxTurns": 8,
        "maxToolCalls": 12,
        "maxTotalTokens": 10_000,
        "maxDurationMs": 5_000,
        "maxOutputChars": 1_000,
    }


def _session_records(
    *,
    session_id: str,
    cwd: Path,
    parent_session: Path | None = None,
    assistant_content: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    header: dict[str, object] = {
        "type": "session",
        "version": 3,
        "id": session_id,
        "timestamp": "2026-07-14T00:00:00.000Z",
        "cwd": str(cwd),
    }
    if parent_session is not None:
        header["parentSession"] = str(parent_session)
    return [
        header,
        {
            "type": "message",
            "id": "m1",
            "parentId": None,
            "message": {"role": "user", "content": [{"type": "text", "text": "已有上下文"}]},
        },
        {
            "type": "message",
            "id": "m2",
            "parentId": "m1",
            "message": {
                "role": "assistant",
                "content": assistant_content or [{"type": "text", "text": "公开结论"}],
            },
        },
    ]


def _write_jsonl(path: Path, records: list[dict[str, object]], *, mode: int | None = None) -> None:
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
        encoding="utf-8",
    )
    if mode is not None:
        path.chmod(mode)


def _fork_context(
    *,
    parent_file: Path,
    child_file: Path,
    child_session_id: str,
) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-runtime-context.v1",
        "forkSessions": [
            {
                "sessionId": child_session_id,
                "sessionFile": str(child_file),
                "parentSessionFile": str(parent_file),
                "parentLeafId": "m2",
                "thinkingOverride": "off",
            }
        ],
    }


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


if __name__ == "__main__":
    unittest.main()
