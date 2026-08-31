from __future__ import annotations

import hashlib
import json
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
    reconcile_stale_memory_runtime_sessions,
)


class FakeMemoryRuntime:
    def __init__(
        self,
        sessions: AgentSessionStore,
        events: AgentEventHub,
        *,
        settle: bool = True,
        emit_terminal_events: bool = True,
        models: list[dict[str, object]] | None = None,
    ) -> None:
        self.sessions = sessions
        self.events = events
        self.settle = settle
        self.emit_terminal_events = emit_terminal_events
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
        self.model_requests: list[dict[str, object]] = []
        self.thinking_requests: list[dict[str, str]] = []
        self.aborted: list[str] = []
        self.closed: list[str] = []
        self.close_error: Exception | None = None
        self.settlement_calls: list[dict[str, object]] = []
        self.settlements: dict[str, dict[str, object]] = {}

    def available_models(self) -> list[dict[str, object]]:
        return [dict(model) for model in self.models]

    def set_model(
        self,
        session_id: str,
        *,
        provider: str,
        model_id: str,
        max_tokens: int | None = None,
    ) -> dict[str, object]:
        self.model_requests.append(
            {
                "sessionId": session_id,
                "provider": provider,
                "modelId": model_id,
                "maxTokens": max_tokens,
            }
        )
        self.sessions.set_model_profile(session_id, f"{provider}/{model_id}")
        return {
            "selected": {
                "provider": provider,
                "id": model_id,
                "thinkingLevels": ["off", "high", "max"],
                "contextWindow": 372_000,
                "maxTokens": max_tokens or 128_000,
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
            self.settlements[turn_id] = {
                "schemaVersion": "rag-ime.pi-turn-settlement.v1",
                "sessionId": session_id,
                "runtimeSessionId": f"pi-{session_id}",
                "turnId": turn_id,
                "clientMessageId": client_message_id,
                "receipt": {
                    "schemaVersion": "pi.agent-settled.v2",
                    "receiptId": f"pi-settled:{turn_id}",
                    "sessionId": f"pi-{session_id}",
                    "runId": turn_id,
                    "scopeId": f"pi-{session_id}:{turn_id}",
                    "generation": 1,
                    "disposition": "completed",
                    "stopReason": "stop",
                    "settledAtMs": 100,
                    "aborted": False,
                    "pendingOperations": 0,
                    "operations": {
                        "pending": 0,
                        "pendingByKind": {},
                        "registeredByKind": {},
                    },
                    "operationCounts": {},
                    "finalMessage": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "private chain"},
                            {"type": "text", "text": '{"decisions":[]}'},
                        ],
                        "usage": {"input": len(message), "output": 4},
                    },
                },
            }
        if self.settle and self.emit_terminal_events:
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
                {"terminalEvent": "agent_settled"},
                turn_id=turn_id,
            )
        return {"accepted": True, "turnId": turn_id}

    def await_turn_settled(
        self,
        session_id: str,
        turn_id: str,
        *,
        client_message_id: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.settlement_calls.append(
            {
                "sessionId": session_id,
                "turnId": turn_id,
                "clientMessageId": client_message_id,
                "timeoutSeconds": timeout_seconds,
            }
        )
        settlement = self.settlements.get(turn_id)
        if settlement is None:
            raise TimeoutError("Memory Session turn timed out")
        return dict(settlement)

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

    def test_default_timeout_covers_the_verified_luna_production_lease(self) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)

        executor = build_governed_memory_model_executor(
            runtime,
            "openai-codex/gpt-5.6-luna",
            "max",
            db_path=self.db_path,
        )

        self.assertEqual(executor.timeout_seconds, 1_200.0)

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
        self.assertEqual(runtime.model_requests[0]["maxTokens"], 16_384)
        self.assertEqual(runtime.thinking_requests[0]["level"], "max")
        self.assertEqual(response["profile"], MEMORY_CURATION_PROFILE)
        self.assertEqual(response["thinkingLevel"], "max")
        self.assertEqual(
            response["receipt"]["transport"],
            "gateway_internal_session",
        )
        self.assertEqual(response["receipt"]["contextWindow"], 372_000)
        self.assertEqual(response["receipt"]["maxTokens"], 16_384)
        self.assertEqual(response["receipt"]["catalogMaxTokens"], 128_000)
        self.assertNotIn('"messages"', str(runtime.prompts[0]["message"])[:300])

    def test_provider_output_budget_is_capped_by_catalog_and_runtime_protocol(self) -> None:
        runtime = FakeMemoryRuntime(
            self.sessions,
            self.events,
            models=[
                {
                    "provider": "openai-codex",
                    "id": "gpt-5.6-luna",
                    "thinkingLevels": ["max"],
                    "contextWindow": 372_000,
                    "maxTokens": 500_000,
                }
            ],
        )
        executor = self._executor(runtime)
        executor.begin_run("memory_book_protocol_budget")

        response = executor.complete(
            messages=[{"role": "user", "content": '{"v":2,"e":[]}'}],
            max_tokens=500_000,
        )

        self.assertEqual(runtime.model_requests[0]["maxTokens"], 262_144)
        self.assertEqual(response["receipt"]["maxTokens"], 262_144)
        self.assertEqual(response["receipt"]["catalogMaxTokens"], 500_000)

    def test_authoritative_settlement_completes_when_product_terminal_events_are_lost(
        self,
    ) -> None:
        runtime = FakeMemoryRuntime(
            self.sessions,
            self.events,
            emit_terminal_events=False,
        )
        executor = self._executor(runtime)
        run = executor.begin_run("memory_book_settlement_reconciliation")

        response = executor.complete(
            messages=[{"role": "user", "content": '{"v":2,"e":[]}'}]
        )

        self.assertEqual(response["choices"][0]["message"]["content"], '{"decisions":[]}')
        self.assertEqual(
            runtime.settlement_calls,
            [
                {
                    "sessionId": run["sessionId"],
                    "turnId": "turn-1",
                    "clientMessageId": runtime.prompts[0]["clientMessageId"],
                    "timeoutSeconds": 1.0,
                }
            ],
        )

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

    def test_failed_run_keeps_receipt_and_retries_in_stable_successor_attempt(self) -> None:
        frozen = hashlib.sha256(b"failed-batch").hexdigest()
        messages = [{"role": "user", "content": '{"v":2,"e":[["e1"]]}'}]
        first_runtime = FakeMemoryRuntime(self.sessions, self.events)
        first = self._executor(first_runtime)
        original = first.begin_run(
            "memory_book_failed_retry",
            frozen_input_sha256=frozen,
        )
        first.complete(messages=messages)
        first.fail_run(RuntimeError("invalid delivery contract"))

        second_runtime = FakeMemoryRuntime(self.sessions, self.events)
        second = self._executor(second_runtime)
        successor = second.begin_run(
            "memory_book_failed_retry",
            frozen_input_sha256=frozen,
        )

        self.assertEqual(successor["runId"], "memory_book_failed_retry:attempt:2")
        self.assertEqual(successor["state"], "prepared")
        self.assertNotEqual(successor["sessionId"], original["sessionId"])
        self.assertEqual(
            second.run_status("memory_book_failed_retry")["state"],
            "failed",
        )
        second.complete(messages=messages)
        second.finish_run(state="completed")
        self.assertEqual(len(second_runtime.prompts), 1)

        third_runtime = FakeMemoryRuntime(self.sessions, self.events)
        third = self._executor(third_runtime)
        resumed = third.begin_run(
            "memory_book_failed_retry",
            frozen_input_sha256=frozen,
        )
        third.complete(messages=messages)

        self.assertEqual(resumed["runId"], successor["runId"])
        self.assertEqual(resumed["state"], "completed")
        self.assertEqual(third_runtime.prompts, [])

    def test_interrupted_running_run_is_recovered_as_resumable(self) -> None:
        frozen = hashlib.sha256(b"interrupted-batch").hexdigest()
        first_runtime = FakeMemoryRuntime(self.sessions, self.events)
        first = self._executor(first_runtime)
        original = first.begin_run(
            "memory_book_interrupted",
            frozen_input_sha256=frozen,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_runs
                SET state = 'running', updated_at_ms = updated_at_ms - 60000
                WHERE run_id = ?
                """,
                (original["runId"],),
            )

        second_runtime = FakeMemoryRuntime(self.sessions, self.events)
        second = self._executor(second_runtime)
        recovered = second.begin_run(
            "memory_book_interrupted",
            frozen_input_sha256=frozen,
        )

        self.assertEqual(recovered["runId"], original["runId"])
        self.assertEqual(recovered["state"], "resumable")
        self.assertEqual(second_runtime.aborted, [original["sessionId"]])
        second.complete(
            messages=[{"role": "user", "content": '{"v":2,"e":[]}'}]
        )
        self.assertEqual(len(second_runtime.prompts), 1)

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

    def test_resumable_isolated_request_retries_in_a_fresh_internal_session(self) -> None:
        messages = [{"role": "user", "content": '{"v":2,"activity":[]}'}]
        first_runtime = FakeMemoryRuntime(self.sessions, self.events)
        first = self._executor(first_runtime)
        first.begin_run("memory_book_isolated_active_turn")
        original_prompt = first_runtime.prompt

        def reject_active_turn(*args: object, **kwargs: object) -> dict[str, object]:
            raise RuntimeError("Session already has an active turn")

        first_runtime.prompt = reject_active_turn  # type: ignore[method-assign]
        with self.assertRaisesRegex(MemoryModelUnavailable, "active turn"):
            first.complete(
                phase="activity-organizer",
                isolated=True,
                messages=messages,
            )
        failed_request = first.run_status(
            "memory_book_isolated_active_turn"
        )["requests"][0]
        failed_session_id = str(failed_request["sessionId"])
        self.assertEqual(failed_request["state"], "resumable")
        first_runtime.prompt = original_prompt  # type: ignore[method-assign]

        second_runtime = FakeMemoryRuntime(self.sessions, self.events)
        second = self._executor(second_runtime)
        second.begin_run("memory_book_isolated_active_turn")
        completed = second.complete(
            phase="activity-organizer",
            isolated=True,
            messages=messages,
        )

        self.assertNotEqual(completed["receipt"]["sessionId"], failed_session_id)
        self.assertEqual(first_runtime.aborted, [failed_session_id])
        self.assertEqual(second_runtime.closed, [failed_session_id])
        self.assertEqual(self.sessions.get(failed_session_id)["status"], "archived")
        self.assertEqual(len(second_runtime.prompts), 1)
        retried = second.run_status(
            "memory_book_isolated_active_turn"
        )["requests"][0]
        self.assertEqual(retried["state"], "completed")
        self.assertEqual(retried["attemptCount"], 2)

    def test_resumable_primary_request_retries_in_a_fresh_internal_session(self) -> None:
        """A cancelled Pi turn may remain active after the Gateway lease ends.

        Retrying the frozen owner-curation request in that same Session would
        fail forever with ``Session already has an active turn``.  Recovery
        must preserve the frozen request identity while moving transport to a
        fresh internal Session.
        """

        messages = [{"role": "user", "content": '{"v":2,"e":[]}'}]
        first_runtime = FakeMemoryRuntime(self.sessions, self.events)
        first = self._executor(first_runtime)
        run = first.begin_run("memory_book_primary_active_turn")
        original_session_id = str(run["sessionId"])

        def reject_active_turn(*args: object, **kwargs: object) -> dict[str, object]:
            raise RuntimeError("Session already has an active turn")

        first_runtime.prompt = reject_active_turn  # type: ignore[method-assign]
        with self.assertRaisesRegex(MemoryModelUnavailable, "active turn"):
            first.complete(phase="evidence-adjudication", messages=messages)
        failed = first.run_status("memory_book_primary_active_turn")["requests"][0]
        self.assertEqual(failed["state"], "resumable")
        self.assertEqual(failed["sessionId"], original_session_id)

        second_runtime = FakeMemoryRuntime(self.sessions, self.events)
        second = self._executor(second_runtime)
        second.begin_run("memory_book_primary_active_turn")
        completed = second.complete(
            phase="evidence-adjudication",
            messages=messages,
        )

        self.assertNotEqual(completed["receipt"]["sessionId"], original_session_id)
        self.assertEqual(first_runtime.aborted, [original_session_id])
        self.assertEqual(second_runtime.closed, [original_session_id])
        self.assertEqual(self.sessions.get(original_session_id)["status"], "archived")
        self.assertEqual(len(second_runtime.prompts), 1)
        retried = second.run_status("memory_book_primary_active_turn")["requests"][0]
        self.assertEqual(retried["state"], "completed")
        self.assertEqual(retried["attemptCount"], 2)

    def test_gateway_restart_retires_only_memory_sessions_and_is_idempotent(
        self,
    ) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)
        executor = self._executor(runtime)
        run = executor.begin_run("memory_book_gateway_restart")
        memory_session_id = str(run["sessionId"])
        ordinary = self.sessions.create(
            title="ordinary conversation",
            session_kind="conversation",
        )
        ordinary_session_id = str(ordinary["id"])
        orphaned_messages = [
            {"role": "user", "content": '{"v":2,"activity":[]}'},
        ]
        orphaned_messages_json = json.dumps(
            orphaned_messages,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        orphaned_input_sha256 = hashlib.sha256(
            orphaned_messages_json.encode("utf-8")
        ).hexdigest()
        self.sessions.set_status(memory_session_id, "busy")
        self.sessions.bind_runtime_session(
            memory_session_id,
            driver_id="pi-runtime-v2",
            runtime_kind="pi",
            external_session_id="pi-memory-stale",
        )
        self.sessions.bind_runtime_session(
            ordinary_session_id,
            driver_id="pi-runtime-v2",
            runtime_kind="pi",
            external_session_id="pi-ordinary-live",
        )
        self.sessions.set_status(ordinary_session_id, "busy")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_runs
                SET state = 'running'
                WHERE run_id = ?
                """,
                (run["runId"],),
            )
            conn.execute(
                """
                INSERT INTO memory_curation_model_requests(
                    request_id, run_id, phase, ordinal, input_sha256,
                    messages_json, input_chars, session_id, state,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, 'activity-organizer', 1, ?, '[]', 2, ?,
                          'running', 1, 1)
                """,
                (
                    "memory-request:gateway-restart",
                    run["runId"],
                    "0" * 64,
                    memory_session_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_curation_model_runs(
                    run_id, session_id, profile, provider, model_id,
                    thinking_level, frozen_input_sha256, state,
                    created_at_ms, updated_at_ms
                ) VALUES ('memory_book_orphaned_run', NULL, 'MEMORY_CURATION',
                          'openai-codex', 'gpt-5.6-luna', 'max', '', 'running',
                          1, 1)
                """
            )
            conn.execute(
                """
                INSERT INTO memory_curation_model_requests(
                    request_id, run_id, phase, ordinal, input_sha256,
                    messages_json, input_chars, session_id, state,
                    created_at_ms, updated_at_ms
                ) VALUES ('memory-request:orphaned', 'memory_book_orphaned_run',
                          'activity-organizer', 1, ?, '[]', 2,
                          'agent:missing-memory-session', 'running', 1, 1)
                """,
                (orphaned_input_sha256,),
            )
            conn.execute(
                """
                UPDATE memory_curation_model_requests
                SET messages_json = ?, input_chars = ?
                WHERE request_id = 'memory-request:orphaned'
                """,
                (orphaned_messages_json, len(orphaned_messages_json)),
            )

        receipt = reconcile_stale_memory_runtime_sessions(
            self.sessions,
            db_path=self.db_path,
        )

        self.assertEqual(receipt["recoveredSessionCount"], 1)
        self.assertEqual(receipt["resumableRequestCount"], 2)
        self.assertEqual(receipt["resumableRunCount"], 2)
        status = executor.run_status(str(run["runId"]))
        self.assertEqual(status["state"], "resumable")
        self.assertEqual(status["lastError"], "memory_gateway_restart")
        self.assertEqual(status["requests"][0]["state"], "resumable")
        self.assertEqual(
            status["requests"][0]["lastError"],
            "memory_gateway_restart",
        )
        self.assertEqual(
            self.sessions.get(memory_session_id)["status"],
            "archived",
        )
        self.assertIsNone(self.sessions.runtime_binding(memory_session_id))
        self.assertEqual(self.sessions.get(ordinary_session_id)["status"], "busy")
        self.assertEqual(
            self.sessions.runtime_binding(ordinary_session_id)["externalSessionId"],
            "pi-ordinary-live",
        )
        orphaned = executor.run_status("memory_book_orphaned_run")
        self.assertEqual(orphaned["state"], "resumable")
        self.assertEqual(orphaned["lastError"], "memory_gateway_restart")
        self.assertEqual(orphaned["requests"][0]["state"], "resumable")

        repeated = reconcile_stale_memory_runtime_sessions(
            self.sessions,
            db_path=self.db_path,
        )
        self.assertEqual(repeated["recoveredSessionCount"], 0)
        self.assertEqual(repeated["resumableRequestCount"], 0)
        self.assertEqual(repeated["resumableRunCount"], 0)

        recovery_runtime = FakeMemoryRuntime(self.sessions, self.events)
        recovery = self._executor(recovery_runtime)
        recovered_run = recovery.begin_run("memory_book_orphaned_run")
        recovered_response = recovery.complete(
            phase="activity-organizer",
            messages=orphaned_messages,
        )
        self.assertTrue(str(recovered_run["sessionId"]).startswith("agent:"))
        self.assertNotEqual(
            recovered_response["receipt"]["sessionId"],
            "agent:missing-memory-session",
        )
        self.assertEqual(
            recovery.run_status("memory_book_orphaned_run")["requests"][0]["state"],
            "completed",
        )

    def test_gateway_restart_reopens_terminal_run_with_unfinished_request(
        self,
    ) -> None:
        runtime = FakeMemoryRuntime(self.sessions, self.events)
        executor = self._executor(runtime)
        run = executor.begin_run("memory_book_split_terminal")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_runs
                SET state = 'completed', completed_at_ms = 2
                WHERE run_id = ?
                """,
                (run["runId"],),
            )
            conn.execute(
                """
                INSERT INTO memory_curation_model_requests(
                    request_id, run_id, phase, ordinal, input_sha256,
                    messages_json, input_chars, session_id, state,
                    created_at_ms, updated_at_ms
                ) VALUES ('memory-request:split-terminal', ?, 'model-call', 1,
                          ?, '[]', 2, ?, 'running', 1, 1)
                """,
                (run["runId"], "2" * 64, run["sessionId"]),
            )

        receipt = reconcile_stale_memory_runtime_sessions(
            self.sessions,
            db_path=self.db_path,
        )

        self.assertEqual(receipt["resumableRunCount"], 1)
        self.assertEqual(receipt["resumableRequestCount"], 1)
        status = executor.run_status(str(run["runId"]))
        self.assertEqual(status["state"], "resumable")
        self.assertEqual(status["completedAtMs"], 0)
        self.assertEqual(status["requests"][0]["state"], "resumable")

    def test_gateway_restart_replaces_archived_run_session_before_new_phase(
        self,
    ) -> None:
        first_runtime = FakeMemoryRuntime(self.sessions, self.events)
        first = self._executor(first_runtime)
        run = first.begin_run("memory_book_gateway_restart_before_request")
        stale_session_id = str(run["sessionId"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_runs
                SET state = 'running'
                WHERE run_id = ?
                """,
                (run["runId"],),
            )
        reconcile_stale_memory_runtime_sessions(
            self.sessions,
            db_path=self.db_path,
        )

        second_runtime = FakeMemoryRuntime(self.sessions, self.events)
        second = self._executor(second_runtime)
        resumed = second.begin_run(str(run["runId"]))
        response = second.complete(
            phase="activity-organizer",
            messages=[{"role": "user", "content": '{"v":2,"activity":[]}'}],
        )

        self.assertEqual(resumed["state"], "resumable")
        self.assertNotEqual(response["receipt"]["sessionId"], stale_session_id)
        self.assertEqual(
            second_runtime.prompts[0]["sessionId"],
            response["receipt"]["sessionId"],
        )
        self.assertEqual(self.sessions.get(stale_session_id)["status"], "archived")

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

    def test_model_with_too_small_output_budget_fails_closed_without_session(self) -> None:
        runtime = FakeMemoryRuntime(
            self.sessions,
            self.events,
            models=[
                {
                    "provider": "openai-codex",
                    "id": "gpt-5.6-luna",
                    "thinkingLevels": ["max"],
                    "contextWindow": 372_000,
                    "maxTokens": 8_192,
                }
            ],
        )

        with self.assertRaisesRegex(MemoryModelUnavailable, "below 16384"):
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
