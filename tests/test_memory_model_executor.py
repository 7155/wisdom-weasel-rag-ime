from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.memory_model_executor import (
    MEMORY_CURATION_PROFILE,
    GovernedMemoryModelExecutor,
    MemoryModelTimeout,
    MemoryModelUnavailable,
    build_governed_memory_model_executor,
    memory_curation_model_status,
)


class FakeMemoryRuntime:
    def __init__(
        self,
        sessions: AgentSessionStore,
        events: AgentEventHub,
        *,
        settle: bool = True,
        settlement_receipt: bool = True,
        models: list[dict[str, object]] | None = None,
    ) -> None:
        self.sessions = sessions
        self.events = events
        self.settle = settle
        self.settlement_receipt = settlement_receipt
        self.models = models or [
            {
                "provider": "openai-codex",
                "id": "gpt-5.6-luna",
                "thinkingLevels": ["off", "high", "max"],
                "contextWindow": 372_000,
                "maxTokens": 128_000,
            }
        ]
        self.prompts: list[dict[str, object]] = []
        self.model_requests: list[dict[str, str]] = []
        self.thinking_requests: list[dict[str, str]] = []
        self.aborted: list[str] = []
        self.closed: list[str] = []
        self.close_error: Exception | None = None

    def available_models(self) -> list[dict[str, object]]:
        return [dict(model) for model in self.models]

    def set_model(
        self,
        session_id: str,
        *,
        provider: str,
        model_id: str,
    ) -> dict[str, object]:
        self.model_requests.append(
            {"sessionId": session_id, "provider": provider, "modelId": model_id}
        )
        self.sessions.set_model_profile(session_id, f"{provider}/{model_id}")
        return {
            "selected": {
                "provider": provider,
                "id": model_id,
                "thinkingLevels": ["off", "high", "max"],
                "contextWindow": 372_000,
                "maxTokens": 128_000,
            }
        }

    def set_thinking_level(
        self,
        session_id: str,
        *,
        level: str,
    ) -> dict[str, object]:
        self.thinking_requests.append({"sessionId": session_id, "level": level})
        self.sessions.set_thinking_level(session_id, level)
        return {"thinkingLevel": level}

    def prompt(
        self,
        session_id: str,
        message: str,
        *,
        images: list[dict[str, str]] | None = None,
        client_message_id: str = "",
        delivery: str = "prompt",
    ) -> dict[str, object]:
        turn_id = f"turn-{len(self.prompts) + 1}"
        self.prompts.append(
            {
                "sessionId": session_id,
                "message": message,
                "images": list(images or []),
                "clientMessageId": client_message_id,
                "delivery": delivery,
                "turnId": turn_id,
            }
        )
        if self.settle:
            self.events.publish(
                session_id,
                "message_completed",
                {
                    "message": {
                        "role": "assistant",
                        "blocks": [
                            {
                                "type": "text",
                                "data": {"text": '{"decisions":[]}'},
                            }
                        ],
                    },
                    "usage": {"input": len(message), "output": 4},
                },
                turn_id=turn_id,
            )
            self.events.publish(
                session_id,
                "turn_completed",
                {
                    "terminalEvent": "agent_settled",
                    **(
                        {
                            "runtimeSettlement": {
                                "schemaVersion": "pi.agent-settled.v2",
                                "receiptId": f"settled:{turn_id}",
                                "sessionId": session_id,
                                "runId": f"run:{turn_id}",
                                "scopeId": f"scope:{turn_id}",
                                "generation": 0,
                                "disposition": "completed",
                                "stopReason": "natural",
                                "operations": {
                                    "pending": 0,
                                    "pendingByKind": {},
                                    "registeredByKind": {},
                                },
                                "pendingOperations": 0,
                            }
                        }
                        if self.settlement_receipt
                        else {}
                    ),
                },
                turn_id=turn_id,
            )
        return {"accepted": True, "turnId": turn_id}

    def abort(self, session_id: str) -> dict[str, object]:
        self.aborted.append(session_id)
        return {"cancelled": True, "sessionId": session_id}

    def close_session(self, session_id: str) -> bool:
        if self.close_error is not None:
            raise self.close_error
        self.closed.append(session_id)
        self.sessions.set_status(session_id, "idle")
        return True


class GovernedMemoryModelExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-memory-model-executor-"
        )
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.events = AgentEventHub()

    def tearDown(self) -> None:
        self.events.close()
        self.temporary.cleanup()

    def _executor(
        self,
        runtime: FakeMemoryRuntime,
        *,
        timeout_seconds: float = 1.0,
    ) -> GovernedMemoryModelExecutor:
        return build_governed_memory_model_executor(
            runtime,
            "openai-codex/gpt-5.6-luna",
            "max",
            timeout_seconds=timeout_seconds,
            db_path=self.db_path,
        )

    def test_selected_model_profile_and_thinking_reach_session_prompt(self) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)
        executor = self._executor(runtime)
        frozen = hashlib.sha256(b"batch-1").hexdigest()
        run = executor.begin_run("memory_book_user_1", frozen_input_sha256=frozen)

        response = executor.complete(
            messages=[
                {"role": "system", "content": "classify exact refs"},
                {"role": "user", "content": '{"v":2,"e":[]}'},
            ],
            max_tokens=256,
        )

        session = self.sessions.get(str(run["sessionId"]))
        self.assertEqual(session["sessionKind"], "subagent_runtime")
        self.assertEqual(session["toolProfileVersion"], "memory-curation-v1")
        self.assertEqual(session["allowedTools"], [])
        self.assertFalse(session["projectContextEnabled"])
        self.assertFalse(session["piSkillsEnabled"])
        self.assertFalse(session["codexSkillsEnabled"])
        self.assertEqual(runtime.model_requests[0]["provider"], "openai-codex")
        self.assertEqual(runtime.model_requests[0]["modelId"], "gpt-5.6-luna")
        self.assertEqual(runtime.thinking_requests[0]["level"], "max")
        self.assertEqual(response["profile"], MEMORY_CURATION_PROFILE)
        self.assertEqual(response["thinkingLevel"], "max")
        self.assertEqual(
            response["receipt"]["transport"],
            "gateway_internal_session",
        )
        self.assertEqual(response["receipt"]["contextWindow"], 372_000)
        self.assertEqual(
            response["receipt"]["runtimeSettlement"]["disposition"],
            "completed",
        )
        self.assertNotIn('"messages"', str(runtime.prompts[0]["message"])[:300])

    def test_completed_event_without_exact_settlement_remains_resumable(
        self,
    ) -> None:
        runtime = FakeMemoryRuntime(
            self.sessions,
            self.events,
            settlement_receipt=False,
        )
        executor = self._executor(runtime)
        executor.begin_run("memory_book_missing_settlement")

        with self.assertRaisesRegex(
            MemoryModelUnavailable,
            "without an exact Pi settlement receipt",
        ):
            executor.complete(
                messages=[{"role": "user", "content": '{"v":2,"e":[]}'}]
            )

        status = executor.run_status("memory_book_missing_settlement")
        self.assertEqual(status["state"], "resumable")
        self.assertEqual(status["requests"][0]["state"], "resumable")

    def test_near_budget_packet_is_not_truncated_or_nested_as_json_messages(self) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)
        executor = self._executor(runtime)
        executor.begin_run("memory_book_near_budget")
        sentinels = "BEGIN-SENTINEL" + ("甲" * 700_000) + "END-SENTINEL"

        response = executor.complete(
            messages=[
                {"role": "system", "content": "return JSON"},
                {"role": "user", "content": sentinels},
            ]
        )

        transported = str(runtime.prompts[0]["message"])
        self.assertIn("BEGIN-SENTINEL", transported)
        self.assertIn("END-SENTINEL", transported)
        self.assertGreater(len(transported), 700_000)
        self.assertEqual(response["receipt"]["inputChars"], len(transported))
        status = executor.run_status("memory_book_near_budget")
        self.assertEqual(status["requests"][0]["state"], "completed")
        self.assertGreater(status["requests"][0]["inputChars"], 700_000)

    def test_isolated_request_uses_and_retires_a_fresh_internal_session(self) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)
        executor = self._executor(runtime)
        run = executor.begin_run("memory_book_independent_verifier")

        first = executor.complete(
            phase="evidence-adjudication",
            messages=[{"role": "user", "content": '{"v":2,"e":[["E1"]]}'}],
        )
        verifier = executor.complete(
            phase="independent-verifier",
            isolated=True,
            messages=[{"role": "user", "content": '{"v":2,"verify":1}'}],
        )

        self.assertEqual(first["receipt"]["sessionId"], run["sessionId"])
        self.assertNotEqual(
            verifier["receipt"]["sessionId"],
            run["sessionId"],
        )
        status = executor.run_status("memory_book_independent_verifier")
        self.assertEqual(
            [request["sessionId"] for request in status["requests"]],
            [first["receipt"]["sessionId"], verifier["receipt"]["sessionId"]],
        )

        executor.finish_run(state="completed")

        self.assertCountEqual(
            runtime.closed,
            [first["receipt"]["sessionId"], verifier["receipt"]["sessionId"]],
        )
        for session_id in runtime.closed:
            self.assertEqual(self.sessions.get(session_id)["status"], "archived")

    def test_public_status_reports_three_pass_receipts_without_contents(self) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)
        executor = self._executor(runtime)
        run = executor.begin_run("memory_book_public_status")
        for phase, isolated in (
            ("evidence-adjudication", False),
            ("atom-adjudication", False),
            ("independent-verifier", True),
        ):
            executor.complete(
                phase=phase,
                isolated=isolated,
                messages=[{"role": "user", "content": f"private-{phase}"}],
            )
        executor.finish_run(state="completed")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            status = memory_curation_model_status(conn)

        self.assertEqual(status["requiredModel"], "openai-codex/gpt-5.6-luna")
        self.assertEqual(status["requiredThinkingLevel"], "max")
        self.assertEqual(status["minimumContextTokens"], 272_000)
        latest = status["runs"][0]
        self.assertEqual(latest["runId"], "memory_book_public_status")
        self.assertEqual(latest["state"], "completed")
        requests = latest["requests"]
        self.assertEqual(
            [request["phase"] for request in requests],
            ["evidence-adjudication", "atom-adjudication", "independent-verifier"],
        )
        self.assertEqual(requests[0]["sessionId"], run["sessionId"])
        self.assertEqual(requests[1]["sessionId"], run["sessionId"])
        self.assertNotEqual(requests[2]["sessionId"], run["sessionId"])
        for request in requests:
            self.assertNotIn("messagesJson", request)
            self.assertNotIn("outputText", request)
            self.assertEqual(request["receipt"]["modelId"], "gpt-5.6-luna")
            self.assertEqual(request["receipt"]["thinkingLevel"], "max")
            self.assertEqual(request["receipt"]["contextWindow"], 372_000)
            self.assertNotIn("private-", str(request))

    def test_completed_request_is_reused_from_database_after_executor_restart(self) -> None:
        first_runtime = FakeMemoryRuntime(self.sessions, self.events)
        first = self._executor(first_runtime)
        frozen = hashlib.sha256(b"stable-batch").hexdigest()
        first.begin_run("memory_book_resume", frozen_input_sha256=frozen)
        messages = [{"role": "user", "content": '{"v":2,"e":[["e1"]]}'}]
        initial = first.complete(messages=messages)

        second_runtime = FakeMemoryRuntime(self.sessions, self.events)
        second = self._executor(second_runtime)
        second.begin_run("memory_book_resume", frozen_input_sha256=frozen)
        resumed = second.complete(messages=messages)

        self.assertEqual(resumed["requestId"], initial["requestId"])
        self.assertEqual(second_runtime.prompts, [])
        self.assertEqual(
            second.run_status("memory_book_resume")["requests"][0]["attemptCount"],
            1,
        )

    def test_timeout_aborts_turn_but_keeps_frozen_run_resumable(self) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events, settle=False)
        executor = self._executor(runtime, timeout_seconds=0.01)
        run = executor.begin_run("memory_book_timeout")

        with self.assertRaisesRegex(MemoryModelTimeout, "remains resumable"):
            executor.complete(
                messages=[{"role": "user", "content": '{"v":2,"e":[]}'}]
            )

        self.assertEqual(runtime.aborted, [run["sessionId"]])
        status = executor.run_status("memory_book_timeout")
        self.assertEqual(status["state"], "resumable")
        self.assertEqual(status["requests"][0]["state"], "resumable")
        self.assertEqual(self.sessions.get(str(run["sessionId"]))["status"], "idle")
        self.assertEqual(runtime.closed, [])

    def test_terminal_run_closes_only_its_session_and_retires_projection(self) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)
        executor = self._executor(runtime)
        run = executor.begin_run("memory_book_terminal")
        executor.complete(
            messages=[{"role": "user", "content": '{"v":2,"e":[]}'}]
        )

        terminal = executor.finish_run(state="completed")

        self.assertEqual(terminal["state"], "completed")
        self.assertEqual(runtime.closed, [run["sessionId"]])
        archived = self.sessions.get(str(run["sessionId"]))
        self.assertEqual(archived["status"], "archived")
        self.assertEqual(archived["sessionFile"], "")

    def test_retirement_failure_keeps_run_resumable_instead_of_completed(self) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)
        executor = self._executor(runtime)
        executor.begin_run("memory_book_retirement_failure")
        executor.complete(
            messages=[{"role": "user", "content": '{"v":2,"e":[]}'}]
        )
        runtime.close_error = RuntimeError("close failed")

        with self.assertRaisesRegex(MemoryModelUnavailable, "remains resumable"):
            executor.finish_run(state="completed")

        status = executor.run_status("memory_book_retirement_failure")
        self.assertEqual(status["state"], "resumable")
        self.assertIn("memory_session_retirement_failed", status["lastError"])

    def test_unavailable_or_short_context_model_fails_closed_without_session(self) -> None:
        runtime = FakeMemoryRuntime(
            self.sessions,
            self.events,
            models=[
                {
                    "provider": "openai-codex",
                    "id": "gpt-5.6-luna",
                    "thinkingLevels": ["max"],
                    "contextWindow": 128_000,
                    "maxTokens": 32_000,
                }
            ],
        )

        with self.assertRaisesRegex(MemoryModelUnavailable, "below 272000"):
            self._executor(runtime)

        self.assertEqual(
            self.sessions.list(include_internal=True, include_archived=True),
            [],
        )

    def test_legacy_gpt_alias_resolves_to_live_canonical_provider(self) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)

        executor = build_governed_memory_model_executor(
            runtime,
            "gpt/gpt-5.6-luna",
            "max",
            db_path=self.db_path,
        )

        self.assertEqual(executor.reference, "openai-codex/gpt-5.6-luna")


if __name__ == "__main__":
    unittest.main()
