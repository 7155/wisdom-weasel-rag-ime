from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from rag_ime.agent_service import AgentService
from rag_ime.pi.config import PiRuntimeConfig
from rag_ime.trace_runtime import EvidenceRef, build_eval_run, build_trace_envelope, make_span
from rag_ime.vertical_agent_harness import load_builtin_manifests
from rag_ime.vertical_agent_suite import evaluate_vertical_agent_case_trace


def _external_sgg_trace() -> dict[str, object]:
    """Build the smallest canonical external sgg trace for schedule wiring."""

    return build_trace_envelope(
        trace_id="trace:vertical:scheduled-external-case",
        source_kind="vertical_agent",
        input_text="public fixture query",
        spans=(
            make_span(
                span_id="span:input",
                name="agent.input",
                started_at_ms=100,
                ended_at_ms=101,
            ),
            make_span(
                span_id="span:retrieve",
                name="rag.retrieve",
                parent_span_id="span:input",
                started_at_ms=101,
                ended_at_ms=102,
            ),
            make_span(
                span_id="span:memory",
                name="memory.recall",
                parent_span_id="span:input",
                started_at_ms=102,
                ended_at_ms=103,
            ),
            make_span(
                span_id="span:tool",
                name="tool.execute",
                parent_span_id="span:input",
                started_at_ms=103,
                ended_at_ms=104,
                attributes={"toolName": "vertical.lookup"},
            ),
            make_span(
                span_id="span:answer",
                name="agent.answer",
                parent_span_id="span:input",
                started_at_ms=104,
                ended_at_ms=105,
            ),
        ),
        evidence=(
            EvidenceRef(
                "knowledge:sales-ledger",
                "knowledge",
                "K-08fe67dcbc",
                source_lane="sandbox_knowledge",
                evidence_stage="retrieval_output",
            ),
            EvidenceRef(
                "memory:fixture:sgg:pricing-policy",
                "memory",
                "fixture://memory/sgg/pricing-policy",
                source_lane="fixture_memory",
                evidence_stage="memory_recall",
            ),
        ),
        now_ms=100,
    ).to_dict()


class EvalScheduleRuntimeTests(unittest.TestCase):
    @staticmethod
    def _wait_for_run(
        service: AgentService,
        schedule_id: str,
        state: str,
        *,
        timeout_seconds: float = 20.0,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            schedule = service.eval_schedules.get(schedule_id)
            latest = schedule.get("latestRun")
            if isinstance(latest, dict) and latest.get("state") == state:
                return schedule
            time.sleep(0.02)
        raise AssertionError(f"scheduled Eval did not reach {state}: {schedule_id}")

    @staticmethod
    def _wait_for_attempt(
        service: AgentService,
        schedule_id: str,
        attempt: int,
        state: str,
        *,
        timeout_seconds: float = 20.0,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            schedule = service.eval_schedules.get(schedule_id)
            latest = schedule.get("latestRun")
            if (
                isinstance(latest, dict)
                and latest.get("attempt") == attempt
                and latest.get("state") == state
            ):
                return schedule
            time.sleep(0.02)
        raise AssertionError(
            f"scheduled Eval attempt {attempt} did not reach {state}: {schedule_id}"
        )

    def test_agent_service_runs_eval_from_existing_wake_tick_and_requires_persisted_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-eval-runtime-") as tmp:
            root = Path(tmp)
            service = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=PiRuntimeConfig(
                    enabled=False,
                    executable=None,
                    agent_dir=root / "agent-config",
                    session_dir=root / "sessions",
                    logs_dir=root / "logs",
                ),
                wake_scheduler_enabled=False,
            )
            try:
                now_ms = 1_800_000_000_000
                schedule = service.eval_schedules.create(
                    {
                        "scheduleId": "eval-schedule:runtime",
                        "suiteId": "sgg",
                        "suiteRevision": "fixture-v2",
                        "recurrenceKind": "daily",
                        "nextDueAtMs": now_ms + 1_000,
                        "maxRuns": 2,
                    },
                    now_ms=now_ms,
                )
                eval_run = build_eval_run(
                    eval_run_id="eval:sgg:runtime-1",
                    trace_ids=["trace:sgg:runtime-1"],
                    mode="ground_truth",
                    truth_kind="frozen",
                    dataset_id="vertical:sgg",
                    label_revision="fixture-v2",
                    metrics={"f1": 1.0},
                    suite_binding={"suiteId": "sgg", "suiteRevision": "fixture-v2"},
                    now_ms=now_ms + 2_000,
                )
                service.eval_runs.persist(eval_run)
                seen: list[dict[str, object]] = []

                def execute(claim: dict[str, object]) -> dict[str, object]:
                    seen.append(dict(claim))
                    return {"evalRunId": "eval:sgg:runtime-1", "private": "ignored"}

                service.bind_eval_schedule_executor(execute)

                # This is the same wake scheduler tick used by the resident
                # Runtime.  No second Eval thread is started.
                self.assertEqual(
                    service.wake_scheduler.run_due_once(now_ms=now_ms + 1_000),
                    0,
                )
                self._wait_for_run(service, str(schedule["id"]), "succeeded")
                self.assertEqual(len(seen), 1)
                self.assertEqual(
                    set(seen[0]),
                    {
                        "scheduleId",
                        "suiteId",
                        "suiteRevision",
                        "recurrenceKind",
                        "attempt",
                        "runId",
                        "leaseToken",
                        "dueAtMs",
                    },
                )
                completed = service.eval_schedules.get(str(schedule["id"]))
                self.assertEqual(completed["status"], "scheduled")
                self.assertEqual(completed["latestRun"]["state"], "succeeded")
                self.assertEqual(
                    completed["latestRun"]["evalRunId"],
                    "eval:sgg:runtime-1",
                )

                # The executor must not be able to settle a fabricated ID as
                # success; only an EvalRun already owned by EvalRunStore does.
                second_schedule = service.eval_schedules.create(
                    {
                        "scheduleId": "eval-schedule:runtime-missing",
                        "suiteId": "sgg",
                        "suiteRevision": "fixture-v2",
                        "recurrenceKind": "daily",
                        "nextDueAtMs": now_ms + 1_000,
                    },
                    now_ms=now_ms,
                )
                service.bind_eval_schedule_executor(
                    lambda _claim: {"evalRunId": "eval:not-persisted"}
                )
                service.wake_scheduler.run_due_once(now_ms=now_ms + 1_000)
                failed = self._wait_for_run(
                    service,
                    str(second_schedule["id"]),
                    "failed",
                )
                self.assertEqual(failed["latestRun"]["state"], "failed")
                self.assertEqual(
                    failed["latestRun"]["errorCode"],
                    "eval_run_not_found",
                )
            finally:
                service.close()

    def test_custom_executor_evaluates_external_vertical_trace_through_due_schedule(self) -> None:
        manifest = load_builtin_manifests()["sgg"]
        trace = _external_sgg_trace()
        expected_suite_binding = {"suiteId": "sgg", "suiteRevision": "fixture-v2"}

        with tempfile.TemporaryDirectory(prefix="rag-ime-eval-runtime-custom-") as tmp:
            root = Path(tmp)
            service = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=PiRuntimeConfig(
                    enabled=False,
                    executable=None,
                    agent_dir=root / "agent-config",
                    session_dir=root / "sessions",
                    logs_dir=root / "logs",
                ),
                wake_scheduler_enabled=False,
            )
            try:
                now_ms = 1_800_000_000_000
                schedule = service.eval_schedules.create(
                    {
                        "scheduleId": "eval-schedule:custom-vertical",
                        "suiteId": "sgg",
                        "suiteRevision": "fixture-v2",
                        "recurrenceKind": "daily",
                        "nextDueAtMs": now_ms + 1_000,
                        "maxRuns": 1,
                    },
                    now_ms=now_ms,
                )
                claims: list[dict[str, object]] = []

                def execute(claim: dict[str, object]) -> dict[str, object]:
                    claims.append(dict(claim))
                    evaluated = evaluate_vertical_agent_case_trace(
                        manifest,
                        trace,
                        eval_store=service.eval_runs,
                        trace_store=service.trace_store,
                        fixture_id="sales-ledger-answer",
                        now_ms=now_ms + 2_000,
                    )
                    return {"evalRunId": evaluated["evalRunId"]}

                service.bind_eval_schedule_executor(execute)
                self.assertEqual(
                    service.wake_scheduler.run_due_once(now_ms=now_ms + 1_000),
                    0,
                )
                completed = self._wait_for_run(
                    service,
                    str(schedule["id"]),
                    "succeeded",
                )

                self.assertEqual(len(claims), 1)
                eval_run_id = str(completed["latestRun"]["evalRunId"])
                eval_run = service.eval_runs.get(eval_run_id)
                self.assertIsNotNone(eval_run)
                assert eval_run is not None
                trace_id = str(trace["traceId"])
                self.assertEqual(eval_run["traceIds"], [trace_id])
                self.assertEqual(eval_run["suiteBinding"], expected_suite_binding)

                self.assertEqual(service.trace_store.get(trace_id), trace)
                detail = service.observation_trace({"traceId": trace_id})
                self.assertEqual(detail["projectionSource"], "trace_store")
                self.assertEqual(detail["trace"], trace)
                evaluations = service.observation_evals({"traceId": trace_id})
                self.assertEqual(evaluations["total"], 1)
                self.assertEqual(
                    evaluations["items"][0]["evalRunId"],
                    eval_run_id,
                )
                self.assertEqual(
                    evaluations["items"][0]["suiteBinding"],
                    expected_suite_binding,
                )
            finally:
                service.close()

    def test_agent_service_default_executor_runs_allowlisted_fixture_suite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-eval-runtime-default-") as tmp:
            root = Path(tmp)
            service = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=PiRuntimeConfig(
                    enabled=False,
                    executable=None,
                    agent_dir=root / "agent-config",
                    session_dir=root / "sessions",
                    logs_dir=root / "logs",
                ),
                wake_scheduler_enabled=False,
            )
            try:
                now_ms = 1_800_000_000_000
                for suite_id in ("sgg", "zhanggui-wenshu"):
                    with self.subTest(suite_id=suite_id):
                        schedule = service.eval_schedules.create(
                            {
                                "scheduleId": f"eval-schedule:default-{suite_id}",
                                "suiteId": suite_id,
                                "suiteRevision": "fixture-v2",
                                "recurrenceKind": "daily",
                                "nextDueAtMs": now_ms + 1_000,
                            },
                            now_ms=now_ms,
                        )

                        self.assertEqual(
                            service.wake_scheduler.run_due_once(now_ms=now_ms + 1_000),
                            0,
                        )
                        completed = self._wait_for_run(
                            service,
                            str(schedule["id"]),
                            "succeeded",
                        )
                        self.assertEqual(completed["status"], "scheduled")
                        eval_run_id = str(completed["latestRun"]["evalRunId"])
                        persisted = service.eval_runs.get(eval_run_id)
                        self.assertIsNotNone(persisted)
                        self.assertEqual(persisted["mode"], "ground_truth")
                        self.assertEqual(persisted["metricAuthority"], "ground_truth")
                        self.assertEqual(
                            persisted["suiteBinding"],
                            {"suiteId": suite_id, "suiteRevision": "fixture-v2"},
                        )
                        trace_ids = persisted["traceIds"]
                        self.assertIsInstance(trace_ids, list)
                        for trace_id in trace_ids:
                            canonical_trace = service.trace_store.get(str(trace_id))
                            self.assertIsNotNone(canonical_trace)
                            self.assertEqual(canonical_trace["traceId"], trace_id)
            finally:
                service.close()

    def test_default_builtin_schedule_keeps_canonical_trace_after_workspace_and_service_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-eval-runtime-restart-") as tmp:
            root = Path(tmp)
            config = PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=root / "agent-config",
                session_dir=root / "sessions",
                logs_dir=root / "logs",
            )
            service = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=config,
                wake_scheduler_enabled=False,
            )
            try:
                result = service._run_builtin_eval_schedule({
                    "suiteId": "sgg",
                    "suiteRevision": "fixture-v2",
                })
                eval_run = service.eval_runs.get(str(result["evalRunId"]))
                self.assertIsNotNone(eval_run)
                assert eval_run is not None
                trace_id = str(eval_run["traceIds"][0])
                canonical = service.trace_store.get(trace_id)
                self.assertIsNotNone(canonical)
            finally:
                service.close()

            # The evaluator's TemporaryDirectory has already been removed;
            # only the shared SQLite authorities remain.
            restarted = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=config,
                wake_scheduler_enabled=False,
            )
            try:
                self.assertEqual(restarted.trace_store.get(trace_id), canonical)
                detail = restarted.observation_trace({"traceId": trace_id})
                self.assertEqual(detail["projectionSource"], "trace_store")
                self.assertEqual(detail["trace"], canonical)
            finally:
                restarted.close()

    def test_default_schedule_claims_have_independent_trace_and_eval_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-eval-runtime-history-") as tmp:
            root = Path(tmp)
            service = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=PiRuntimeConfig(
                    enabled=False,
                    executable=None,
                    agent_dir=root / "agent-config",
                    session_dir=root / "sessions",
                    logs_dir=root / "logs",
                ),
                wake_scheduler_enabled=False,
            )
            try:
                first_due = 1_800_000_000_000
                schedule = service.eval_schedules.create(
                    {
                        "scheduleId": "eval-schedule:history",
                        "suiteId": "sgg",
                        "suiteRevision": "fixture-v2",
                        "recurrenceKind": "daily",
                        "nextDueAtMs": first_due,
                        "maxRuns": 2,
                    },
                    now_ms=first_due - 1_000,
                )

                service.wake_scheduler.run_due_once(now_ms=first_due)
                first_schedule = self._wait_for_attempt(
                    service,
                    str(schedule["id"]),
                    1,
                    "succeeded",
                )
                first_eval_id = str(first_schedule["latestRun"]["evalRunId"])
                first_eval = service.eval_runs.get(first_eval_id)
                self.assertIsNotNone(first_eval)
                assert first_eval is not None
                first_trace_id = str(first_eval["traceIds"][0])
                first_trace = service.trace_store.get(first_trace_id)
                self.assertIsNotNone(first_trace)
                assert first_trace is not None
                self.assertIn(
                    str(first_schedule["latestRun"]["id"]),
                    str(first_trace["binding"]["sourceLoopId"]),
                )
                self.assertEqual(first_trace["spans"][0]["startedAtMs"], first_due)

                second_due = int(first_schedule["nextDueAtMs"])
                service.wake_scheduler.run_due_once(now_ms=second_due)
                second_schedule = self._wait_for_attempt(
                    service,
                    str(schedule["id"]),
                    2,
                    "succeeded",
                )
                second_eval_id = str(second_schedule["latestRun"]["evalRunId"])
                second_eval = service.eval_runs.get(second_eval_id)
                self.assertIsNotNone(second_eval)
                assert second_eval is not None
                second_trace_id = str(second_eval["traceIds"][0])
                second_trace = service.trace_store.get(second_trace_id)
                self.assertIsNotNone(second_trace)
                assert second_trace is not None

                self.assertNotEqual(first_eval_id, second_eval_id)
                self.assertNotEqual(first_trace_id, second_trace_id)
                self.assertEqual(
                    {first_trace_id, second_trace_id},
                    {trace["traceId"] for trace in service.trace_store.list()},
                )
                self.assertEqual(second_trace["spans"][0]["startedAtMs"], second_due)
            finally:
                service.close()

            restarted = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=PiRuntimeConfig(
                    enabled=False,
                    executable=None,
                    agent_dir=root / "agent-config",
                    session_dir=root / "sessions",
                    logs_dir=root / "logs",
                ),
                wake_scheduler_enabled=False,
            )
            try:
                self.assertIsNotNone(restarted.trace_store.get(first_trace_id))
                self.assertIsNotNone(restarted.trace_store.get(second_trace_id))
                self.assertEqual(
                    restarted.eval_runs.get(first_eval_id)["traceIds"],
                    [first_trace_id],
                )
                self.assertEqual(
                    restarted.eval_runs.get(second_eval_id)["traceIds"],
                    [second_trace_id],
                )
            finally:
                restarted.close()

    def test_replaying_one_schedule_claim_is_idempotent_across_temp_workspaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-eval-runtime-retry-") as tmp:
            root = Path(tmp)
            config = PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=root / "agent-config",
                session_dir=root / "sessions",
                logs_dir=root / "logs",
            )
            service = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=config,
                wake_scheduler_enabled=False,
            )
            claim = {
                "suiteId": "sgg",
                "suiteRevision": "fixture-v2",
                "runId": "eval-run:retry-1",
                "dueAtMs": 1_800_000_000_000,
            }
            try:
                first = service._run_builtin_eval_schedule(claim)
                second = service._run_builtin_eval_schedule(dict(claim))
                self.assertEqual(first, second)
                eval_run = service.eval_runs.get(str(first["evalRunId"]))
                self.assertIsNotNone(eval_run)
                assert eval_run is not None
                trace_id = str(eval_run["traceIds"][0])
                self.assertEqual(len(service.trace_store.list()), 1)
                self.assertEqual(
                    service.trace_store.get(trace_id)["binding"]["sourceLoopId"],
                    "vertical-self-test:sgg:sales-ledger-answer:eval-run:retry-1",
                )
            finally:
                service.close()

            # Both temporary evaluator workspaces have been removed; the
            # canonical Trace and Eval authorities survive the process restart.
            restarted = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=config,
                wake_scheduler_enabled=False,
            )
            try:
                self.assertIsNotNone(restarted.trace_store.get(trace_id))
                self.assertIsNotNone(restarted.eval_runs.get(str(first["evalRunId"])))
            finally:
                restarted.close()

    def test_agent_service_rejects_unknown_suite_and_revision_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-eval-runtime-unknown-") as tmp:
            root = Path(tmp)
            service = AgentService(
                db_path=root / "rag-ime.sqlite",
                runtime_config=PiRuntimeConfig(
                    enabled=False,
                    executable=None,
                    agent_dir=root / "agent-config",
                    session_dir=root / "sessions",
                    logs_dir=root / "logs",
                ),
                wake_scheduler_enabled=False,
            )
            try:
                now_ms = 1_800_000_000_000
                for suffix, suite_id, suite_revision, expected in (
                    ("suite", "not-allowlisted", "fixture-v2", "allowlisted"),
                    ("revision", "sgg", "fixture-v1", "revision"),
                ):
                    with self.subTest(suite_id=suite_id, suite_revision=suite_revision):
                        with self.assertRaisesRegex(ValueError, expected):
                            service.eval_schedules.create(
                                {
                                    "scheduleId": f"eval-schedule:unknown-{suffix}",
                                    "suiteId": suite_id,
                                    "suiteRevision": suite_revision,
                                    "recurrenceKind": "daily",
                                    "nextDueAtMs": now_ms + 1_000,
                                },
                                now_ms=now_ms,
                            )
                        self.assertEqual(service.eval_schedules.list(), [])
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
