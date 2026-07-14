from __future__ import annotations

import json
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from rag_ime.agent_delegation import AgentDelegationCoordinator
from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
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

    def coordinator(self, runtime_factory=_CompletingRuntime) -> AgentDelegationCoordinator:
        return AgentDelegationCoordinator(
            db_path=self.db_path,
            runtime_config=self.config,
            sessions=self.sessions,
            events=self.events,
            runtime_factory=runtime_factory,
        )

    def test_fixed_catalog_parallel_results_and_internal_sessions(self) -> None:
        coordinator = self.coordinator()
        catalog = coordinator.catalog()
        self.assertEqual(
            [item["templateId"] for item in catalog["items"]],
            ["researcher", "planner", "worker", "reviewer", "delegate"],
        )

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
        self.assertEqual([item["id"] for item in self.sessions.list()], [self.parent["id"]])
        self.assertEqual(len(self.sessions.list(include_internal=True)), 3)
        with self.assertRaisesRegex(ValueError, "unsupported agent template"):
            coordinator.delegate(
                str(self.parent["id"]),
                {"agent": "market-shell-agent", "task": "执行任意命令"},
            )
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
        coordinator = self.coordinator()
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
        self.assertEqual(Path(str(child["sessionFile"])).resolve(), child_file.resolve())
        self.assertNotEqual(child_file, parent_file)
        self.assertEqual(stat.S_IMODE(child_file.stat().st_mode), 0o600)
        child_text = child_file.read_text(encoding="utf-8")
        self.assertIn("已有上下文", child_text)
        self.assertIn("公开结论", child_text)
        self.assertIn("普通思考可以保留", child_text)
        self.assertEqual(json.loads(child_text.splitlines()[0])["id"], "child-pi")
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
