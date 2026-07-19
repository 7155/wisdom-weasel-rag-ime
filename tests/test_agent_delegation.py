from __future__ import annotations

import json
import stat
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_artifacts import AgentArtifactStore
from rag_ime.agent_delegation import AgentDelegationCoordinator, AgentDelegationStore
from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_templates import AgentTemplateBudget, agent_template as real_agent_template
from rag_ime.pi_runtime import PiRuntimeConfig


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
                {"toolCallId": f"tool:{index}", "toolName": "ime_knowledge"},
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
        self.session_id = ""
        self.__class__.instances.append(self)

    def prompt(self, session_id, message, *, delivery="prompt", **_kwargs):
        self.deliveries.append((delivery, message))
        self.session_id = session_id
        if delivery == "prompt":
            self.events.publish(
                session_id,
                "tool_started",
                {"toolCallId": "tool:1", "toolName": "ime_knowledge"},
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
                },
                turn_id="turn:interactive",
            )
        return {"accepted": True, "turnId": "turn:interactive", "delivery": delivery}

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
        self.config = PiRuntimeConfig(
            enabled=True,
            executable=self.root / "pi",
            agent_dir=self.root / "config",
            session_dir=self.root / "sessions",
            logs_dir=self.root / "logs",
            tools=("ime_memory", "ime_knowledge", "ime_agents"),
        )
        self.parent = self.sessions.create(
            title="主持会话",
            role_id="hermes-v1",
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
    ) -> AgentDelegationCoordinator:
        return AgentDelegationCoordinator(
            db_path=self.db_path,
            runtime_config=self.config,
            sessions=self.sessions,
            events=self.events,
            runtime_factory=runtime_factory,
            cancellation_grace_ms=cancellation_grace_ms,
            subagent_session_retention_ms=subagent_session_retention_ms,
            subagent_session_gc_interval_ms=subagent_session_gc_interval_ms,
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
                    {"agent": "researcher", "task": "核对已有证据"},
                    {"agent": "reviewer", "task": "检查结论是否充分"},
                ],
            },
        )
        batch = response["batch"]
        self.assertEqual(batch["state"], "completed")
        self.assertEqual(batch["depth"], 1)
        self.assertEqual(len(batch["runs"]), 2)
        self.assertEqual({run["usage"]["totalTokens"] for run in batch["runs"]}, {321})
        self.assertTrue(all(run["result"]["summary"] for run in batch["runs"]))
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
        self.assertNotIn("runtime_retired", {str(item["eventType"]) for item in records})
        with self.assertRaisesRegex(ValueError, "unsupported agent template"):
            coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "market-shell-agent", "task": "执行任意命令"},
            )
        coordinator.close()

    def test_default_templates_do_not_stop_on_fixed_turn_or_tool_counts(self) -> None:
        coordinator = self.coordinator(_ManyTurnsAndToolsRuntime)
        batch = coordinator.delegate(
            str(self.parent["id"]),
            {"agent": "researcher", "task": "完成需要多轮检索的任务"},
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
            {"agent": "reviewer", "task": "检查受控 Artifact"},
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
            allowed_tools=["ime_overview", "ime_memory"],
        )
        coordinator = self.coordinator()
        batch = coordinator.delegate(
            str(self.parent["id"]),
            {"agent": "worker", "task": "只能使用父会话允许的工具"},
        )["batch"]
        child = self.sessions.get(str(batch["runs"][0]["childSessionId"]))

        self.assertEqual(child["toolProfileVersion"], "subagent-worker-v1")
        self.assertEqual(child["toolAllowlistMode"], "explicit")
        self.assertEqual(child["allowedTools"], ["ime_overview", "ime_memory"])
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
        with patch.dict(
            "os.environ",
            {"RAG_IME_SUBAGENT_SESSION_RETENTION_HOURS": "72"},
        ):
            default_coordinator = AgentDelegationCoordinator(
                db_path=default_db,
                runtime_config=self.config,
                sessions=default_sessions,
                events=AgentEventHub(),
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
            {"agent": "delegate", "task": "第一层"},
        )["batch"]
        first_child = first["runs"][0]["childSessionId"]
        second = coordinator.delegate(
            str(first_child),
            {"agent": "reviewer", "task": "第二层"},
        )["batch"]
        self.assertEqual(second["depth"], 2)
        second_child = second["runs"][0]["childSessionId"]
        with self.assertRaisesRegex(ValueError, "maximum depth is 2"):
            coordinator.delegate(
                str(second_child),
                {"agent": "reviewer", "task": "第三层"},
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
                {"agent": "planner", "task": "不能手工分叉", "contextMode": "fork"},
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
                    {"agent": "researcher", "task": "长任务一"},
                    {"agent": "reviewer", "task": "长任务二"},
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
                {"agent": "planner", "task": "第三个并行任务", "wait": False},
            )
        coordinator.abort(str(self.parent["id"]), {"batchId": batch["id"]})
        _wait_until(
            lambda: coordinator.store.get_batch(str(batch["id"]))["state"] == "aborted"
        )
        final = coordinator.store.get_batch(str(batch["id"]))
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
                {"agent": "reviewer", "task": "接近输出预算但仍完成"},
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
                {"agent": "worker", "task": "触发硬输出预算"},
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
            role_id="hermes-v1",
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
        coordinator.control(
            str(self.parent["id"]),
            run_id,
            {"action": "abort", "clientActionId": "action:abort"},
        )
        _wait_until(lambda: coordinator.store.get_run(run_id)["state"] == "aborted")
        coordinator.close()

    def test_resume_continues_the_retained_child_session(self) -> None:
        _ResumeRuntime.prompts.clear()
        coordinator = self.coordinator(_ResumeRuntime)
        response = coordinator.delegate(
            str(self.parent["id"]),
            {
                "agent": "reviewer",
                "task": "完成中断恢复验证",
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
