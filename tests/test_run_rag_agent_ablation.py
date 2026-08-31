from __future__ import annotations

import unittest

from scripts.run_rag_agent_ablation import (
    _append_lane_checkpoint_attempt,
    _append_lane_checkpoint_attempt_binding,
    _append_lane_checkpoint_attempt_started,
    _agentic_critic_contract_passes,
    _agentic_parent_query_policy_passes,
    _agents_tool_receipts,
    _answer_judge_failure_is_retryable,
    _answer_judge_format_repair_prompt,
    _answer_judge_prompt,
    _answer_case_manifest,
    _authorize_held_out,
    _claim_held_out_gate,
    _apply_answer_only_judgments,
    _apply_answer_judgments,
    _knowledge_base_retrieval_config,
    _lane_prompt,
    _last_assistant_snapshot_text,
    _merge_event_evidence,
    _coverage_critic_completed,
    _coverage_audit_prompt,
    _checkpoint_lane_record_projection,
    _checkpoint_private_search_trace,
    _evaluation_configuration_defaults,
    _finalize_public_report,
    _lane_checkpoint_fingerprint,
    _lane_checkpoint_attempt_history,
    _lane_checkpoint_report_projection,
    _lane_checkpoint_reusable_records,
    _open_lane_checkpoint,
    _recover_lane_checkpoint_orphans,
    _recover_private_evaluation_session,
    _require_actual_metal_runtime,
    _redact_absolute_paths,
    _preflight_failure_report,
    _production_baseline_record,
    _parse_answer_judge_rubrics,
    _parse_answer_judgments,
    _pin_evaluation_agent_config,
    _runtime_failure_category,
    _run_coverage_audit,
    _run_lane,
    _resolve_evaluation_split,
    _search_parameter_policy_passes,
    _sha256_json,
    _started_tool_names,
    _validate_checkpoint_request,
)


class RunRagAgentAblationTests(unittest.TestCase):
    @staticmethod
    def _held_out_authority() -> tuple[dict[str, object], dict[str, object]]:
        retrieval_config = {"mode": "hybrid"}
        retrieval_config_sha256 = _sha256_json(retrieval_config)
        bindings: dict[str, object] = {
            "validationAgentReportFileSha256": "validation-file",
            "validationAgentReportSha256": "validation-report",
            "retrievalReportFileSha256": "retrieval-file",
            "retrievalReportSha256": "retrieval-report",
            "sourcePreparedSha256": "prepared-file",
            "sourceAnswerCasesSha256": "answer-file",
            "sourceRetrievalReportSha256": "retrieval-file",
            "caseIds": ["validation-q1", "validation-q2"],
            "caseIdsSha256": _sha256_json(["validation-q1", "validation-q2"]),
            "caseSetSha256": "case-set",
            "answerCaseManifestSha256": "answer-manifest",
            "answerCaseSetSha256": "answer-set",
            "promptConfigSha256": "prompt-config",
            "runtimeContractSha256": "runtime-contract",
            "piRuntimeIdentitySha256": "pi-runtime",
            "modelRouteIdentitySha256": "model-route",
            "retrievalConfigSha256": retrieval_config_sha256,
        }
        promotion: dict[str, object] = {
            "schemaVersion": "paw.enterprise-rag-validation-promotion.v1",
            "decision": "keep",
            "state": "promoted",
            "heldOutObserved": False,
            "validationAgentReport": {
                "fileSha256": "validation-file",
                "reportSha256": "validation-report",
            },
            "retrievalReport": {
                "fileSha256": "retrieval-file",
                "reportSha256": "retrieval-report",
            },
            "bindings": bindings,
            "identity": {
                "piRuntime": {"identitySha256": "pi-runtime"},
                "modelRoute": {"identitySha256": "model-route"},
            },
            "winner": {
                "reportSha256": "retrieval-report",
                "retrievalConfig": retrieval_config,
                "retrievalConfigSha256": retrieval_config_sha256,
            },
        }
        promotion["promotionReceiptSha256"] = _sha256_json(promotion)
        gate: dict[str, object] = {
            "schemaVersion": "paw.enterprise-rag-heldout-gate.v1",
            "state": "unlocked",
            "heldOutObserved": False,
            "maximumEvaluations": 1,
            "consumedEvaluations": 0,
            "promotionReceiptSha256": promotion["promotionReceiptSha256"],
            **bindings,
        }
        gate["gateReceiptSha256"] = _sha256_json(gate)
        return promotion, gate

    @staticmethod
    def _checkpoint_fingerprint(
        *,
        split: str = "validation",
        prompt_sha256: str = "prompt-v1",
    ) -> dict[str, object]:
        return _lane_checkpoint_fingerprint(
            source_prepared_sha256="prepared-v1",
            source_answer_cases_sha256="answers-v1",
            source_retrieval_report_sha256="retrieval-report-v1",
            evaluation_mode="answer-only",
            evaluation_split=split,
            case_ids_sha256="cases-v1",
            case_set_sha256="case-set-v1",
            answer_case_manifest_sha256="answer-manifest-v1",
            prompt_config_sha256=prompt_sha256,
            lane_prompt_sha256_by_lane={
                lane: f"{lane}-prompt-v1"
                for lane in ("baseline", "skill", "tuned", "agentic")
            },
            skill_sha256="skill-v1",
            runtime_contract_sha256="runtime-contract-v1",
            default_retrieval_config_sha256="default-config-v1",
            tuned_retrieval_config_sha256="tuned-config-v1",
            model_route_identity_sha256="model-routes-v1",
            pi_runtime_identity_sha256="pi-runtime-v1",
            maximum_attempts_per_lane=2,
        )

    @staticmethod
    def _checkpoint_lane_record(
        lane: str,
        *,
        terminal: str = "turn_completed",
        runtime_failure_category: str = "",
        tool_contract: bool = True,
        output_protocol_rate: float = 1.0,
    ) -> dict[str, object]:
        return {
            "lane": lane,
            "promptSha256": f"{lane}-prompt-v1",
            "terminalEvent": terminal,
            "runtimeFailureCategory": runtime_failure_category,
            "error": "",
            "toolContract": tool_contract,
            "scopeBoundary": True,
            "bindingCleanup": True,
            "binding": {"sessionId": f"agent:{lane}"},
            "gatewayLedger": {"itemCount": 5},
            "score": {
                "protocolErrors": [] if output_protocol_rate == 1.0 else ["invalid"],
                "failedToolItemCount": 0,
                "hardEvidence": {
                    "parameterBounded": True,
                    "agenticLoopObserved": lane == "agentic",
                },
                "agentMetrics": {"outputProtocolRate": output_protocol_rate},
                "answerCases": [],
            },
            "_assistantText": '{"cases":[]}',
            "_checkpointSessionId": f"agent:{lane}",
            "_checkpointTurnId": f"turn:{lane}",
        }

    @staticmethod
    def _bind_checkpoint_attempt(
        path: object,
        checkpoint: dict[str, object],
        *,
        lane: str,
        attempt: int,
    ) -> dict[str, object]:
        checkpoint = _append_lane_checkpoint_attempt_binding(
            path,
            checkpoint=checkpoint,
            lane=lane,
            attempt=attempt,
            session_id=f"agent:{lane}",
            turn_id="",
        )
        return _append_lane_checkpoint_attempt_binding(
            path,
            checkpoint=checkpoint,
            lane=lane,
            attempt=attempt,
            session_id=f"agent:{lane}",
            turn_id=f"turn:{lane}",
        )

    def test_lane_checkpoint_is_persisted_before_next_lane(self) -> None:
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="baseline", attempt=1
            )
            checkpoint = self._bind_checkpoint_attempt(
                path, checkpoint, lane="baseline", attempt=1
            )
            checkpoint = _append_lane_checkpoint_attempt(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                lane_record=self._checkpoint_lane_record("baseline"),
            )
            first_record_sha256 = checkpoint["attempts"][0]["attemptSha256"]
            persisted_after_first = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(persisted_after_first["attempts"]))

            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="skill", attempt=1
            )
            checkpoint = self._bind_checkpoint_attempt(
                path, checkpoint, lane="skill", attempt=1
            )
            checkpoint = _append_lane_checkpoint_attempt(
                path,
                checkpoint=checkpoint,
                lane="skill",
                attempt=1,
                lane_record=self._checkpoint_lane_record("skill"),
            )
            persisted_after_second = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(2, len(persisted_after_second["attempts"]))
        self.assertEqual(
            first_record_sha256,
            persisted_after_second["attempts"][0]["attemptSha256"],
        )
        self.assertEqual(8, persisted_after_second["revision"])

    def test_started_without_terminal_is_interrupted_and_consumes_attempt_budget(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
            )
            resumed = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=True,
            )

        history = _lane_checkpoint_attempt_history(resumed, "baseline")
        self.assertEqual(1, len(history))
        self.assertEqual(1, history[0]["attempt"])
        self.assertEqual("interrupted", history[0]["lifecycleState"])
        self.assertEqual("interrupted", history[0]["runtimeFailureCategory"])
        self.assertFalse(history[0]["reusable"])
        self.assertEqual({}, _lane_checkpoint_reusable_records(resumed))

    def test_started_only_resume_attempt_is_historical_not_fresh(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="baseline", attempt=1
            )
            resumed = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=True,
            )
            historical_count = len(
                _lane_checkpoint_attempt_history(resumed, "baseline")
            )
            resumed = _append_lane_checkpoint_attempt_started(
                path, checkpoint=resumed, lane="baseline", attempt=2
            )
            projection = _lane_checkpoint_report_projection(
                resumed,
                resume_requested=True,
                initial_attempt_count=historical_count,
                reused_lanes=set(),
                fresh_lanes={"baseline"},
            )

        self.assertEqual(1, projection["historicalAttemptCount"])
        self.assertEqual(1, projection["freshAttemptCount"])
        self.assertEqual(
            ["checkpoint", "fresh"],
            [item["origin"] for item in projection["attemptHistory"]],
        )

    def test_interrupted_attempt_uses_durable_session_and_turn_binding(self) -> None:
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
            )
            checkpoint = _append_lane_checkpoint_attempt_binding(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                session_id="agent:durable-session",
                turn_id="",
            )
            checkpoint = _append_lane_checkpoint_attempt_binding(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                session_id="agent:durable-session",
                turn_id="turn:durable-turn",
            )
            resumed = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=True,
            )

        history = _lane_checkpoint_attempt_history(resumed, "baseline")
        self.assertEqual("interrupted", history[0]["lifecycleState"])
        self.assertEqual(
            hashlib.sha256(b"agent:durable-session").hexdigest(),
            history[0]["sessionSha256"],
        )
        self.assertEqual(
            hashlib.sha256(b"turn:durable-turn").hexdigest(),
            history[0]["turnSha256"],
        )
        self.assertTrue(history[0]["bindingReceiptSha256"])

    def test_orphan_recovery_cleans_sandbox_but_fails_closed_without_session_owner(self) -> None:
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
            )
            checkpoint = _append_lane_checkpoint_attempt_binding(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                session_id="agent:orphan-session",
                turn_id="",
                recovery_locator={
                    "schemaVersion": "rag-ime.rag-agent-orphan-locator.v1",
                    "runRoot": str(root / "old run"),
                    "agentDbPath": str(root / "old run" / "agent.sqlite"),
                    "sessionId": "agent:orphan-session",
                    "turnId": "",
                    "sandboxRoot": str(root / "old run" / "knowledge-runs"),
                    "sandboxOwnerId": "ablation:owner",
                    "sandboxRunId": "a" * 32,
                },
            )
            checkpoint = _append_lane_checkpoint_attempt_binding(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                session_id="agent:orphan-session",
                turn_id="turn:orphan-turn",
                recovery_locator={
                    "schemaVersion": "rag-ime.rag-agent-orphan-locator.v1",
                    "runRoot": str(root / "old run"),
                    "agentDbPath": str(root / "old run" / "agent.sqlite"),
                    "sessionId": "agent:orphan-session",
                    "turnId": "turn:orphan-turn",
                    "sandboxRoot": str(root / "old run" / "knowledge-runs"),
                    "sandboxOwnerId": "ablation:owner",
                    "sandboxRunId": "a" * 32,
                },
            )
            recovered, summary = _recover_lane_checkpoint_orphans(
                path,
                checkpoint=checkpoint,
                session_recover=None,
                sandbox_cleanup=lambda locator: {
                    "deleted": True,
                    "runId": locator["sandboxRunId"],
                },
            )

        self.assertTrue(summary["failClosed"])
        self.assertEqual(1, summary["orphanCount"])
        receipt = recovered["orphanRecoveryReceipts"][0]
        self.assertEqual("blocked", receipt["status"])
        self.assertEqual("recovered", receipt["sandboxRecovery"]["status"])
        self.assertEqual("blocked", receipt["sessionRecovery"]["status"])
        projection = _lane_checkpoint_report_projection(
            recovered,
            resume_requested=True,
            initial_attempt_count=1,
            reused_lanes=set(),
            fresh_lanes=set(),
        )
        serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(str(root), serialized)
        self.assertNotIn("agent:orphan-session", serialized)

    def test_legacy_interrupted_binding_without_locator_fails_closed(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
            )
            checkpoint = _append_lane_checkpoint_attempt_binding(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                session_id="agent:legacy-session",
                turn_id="",
            )
            recovered, summary = _recover_lane_checkpoint_orphans(
                path,
                checkpoint=checkpoint,
                session_recover=lambda _locator: self.fail(
                    "missing private locator must not invoke Session recovery"
                ),
                sandbox_cleanup=lambda _locator: self.fail(
                    "missing private locator must not invoke sandbox cleanup"
                ),
            )

        self.assertTrue(summary["failClosed"])
        receipt = recovered["orphanRecoveryReceipts"][0]
        self.assertFalse(receipt["recoveryLocatorPresent"])
        self.assertEqual("blocked", receipt["status"])
        self.assertEqual(
            "recovery_locator_missing",
            receipt["sessionRecovery"]["reasonCode"],
        )
        self.assertEqual(
            "recovery_locator_missing",
            receipt["sandboxRecovery"]["reasonCode"],
        )

    def test_orphan_recovery_faults_exact_private_session_and_cleans_real_sandbox(self) -> None:
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from rag_ime.agent_sessions import AgentSessionStore
        from rag_ime.rag_benchmark_sandbox import RagBenchmarkSandbox

        with TemporaryDirectory() as temporary:
            private_root = Path(temporary) / "private-evaluation"
            run_root = private_root / "run-orphan"
            run_root.mkdir(parents=True)
            store = AgentSessionStore(run_root / "agent.sqlite")
            store.initialize()
            session = store.create(
                title="RAG Agent ablation: baseline",
                tool_profile_version="subagent-readonly-v1",
                execution_mode="read_only",
                project_context_enabled=False,
                workspace_roots=[],
            )
            session_id = str(session["id"])
            turn_id = "turn:orphan-private"
            store.set_status(session_id, "busy")
            store.record_runtime_event(
                event_id="event:orphan-turn-started",
                session_id=session_id,
                turn_id=turn_id,
                sequence=1,
                event_type="turn_started",
                created_at_ms=100,
                redacted_summary="started",
            )
            sandbox = RagBenchmarkSandbox(run_root / "knowledge-runs")
            owner = "ablation:private-owner"
            sandbox_run = sandbox.create_run(owner, label="orphan")
            sandbox_run_id = str(sandbox_run["runId"])
            checkpoint_path = private_root / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                checkpoint_path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                checkpoint_path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
            )
            locator = {
                "schemaVersion": "rag-ime.rag-agent-orphan-locator.v1",
                "runRoot": str(run_root),
                "agentDbPath": str(run_root / "agent.sqlite"),
                "sessionId": session_id,
                "turnId": turn_id,
                "sandboxRoot": str(run_root / "knowledge-runs"),
                "sandboxOwnerId": owner,
                "sandboxRunId": sandbox_run_id,
            }
            checkpoint = _append_lane_checkpoint_attempt_binding(
                checkpoint_path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                session_id=session_id,
                turn_id="",
                recovery_locator={**locator, "turnId": ""},
            )
            checkpoint = _append_lane_checkpoint_attempt_binding(
                checkpoint_path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                session_id=session_id,
                turn_id=turn_id,
                recovery_locator=locator,
            )
            recovered, summary = _recover_lane_checkpoint_orphans(
                checkpoint_path,
                checkpoint=checkpoint,
                session_recover=lambda value: _recover_private_evaluation_session(
                    value,
                    allowed_private_root=private_root,
                    expected_session_sha256=hashlib.sha256(
                        session_id.encode("utf-8")
                    ).hexdigest(),
                    expected_turn_sha256=hashlib.sha256(
                        turn_id.encode("utf-8")
                    ).hexdigest(),
                ),
                sandbox_cleanup=lambda value: sandbox.cleanup(
                    value["sandboxOwnerId"],
                    value["sandboxRunId"],
                    confirm_text="DELETE_BENCHMARK_RUN",
                ),
            )
            settled = store.get(session_id)
            terminal = store.runtime_turn_terminal_event(session_id, turn_id)
            sandbox.close()

        self.assertFalse(summary["failClosed"])
        self.assertEqual("faulted", settled["status"])
        self.assertIsNotNone(terminal)
        assert terminal is not None
        self.assertEqual("turn_failed", terminal["eventType"])
        receipt = recovered["orphanRecoveryReceipts"][0]
        self.assertEqual("recovered", receipt["status"])
        self.assertEqual(
            "exact_session_terminal_verified",
            receipt["sessionRecovery"]["reasonCode"],
        )
        self.assertTrue(receipt["sessionRecovery"]["evidenceSha256"])
        self.assertEqual(
            "marker_bound_sandbox_deleted",
            receipt["sandboxRecovery"]["reasonCode"],
        )

    def test_private_session_recovery_rejects_forged_locator_outside_private_root(self) -> None:
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from rag_ime.agent_sessions import AgentSessionStore

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / "private-evaluation"
            allowed.mkdir()
            forged_run = root / "production-like" / "run-forged"
            forged_run.mkdir(parents=True)
            store = AgentSessionStore(forged_run / "agent.sqlite")
            store.initialize()
            session = store.create(
                title="RAG Agent ablation: baseline",
                tool_profile_version="subagent-readonly-v1",
            )
            session_id = str(session["id"])
            turn_id = "turn:forged"
            store.set_status(session_id, "busy")
            locator = {
                "schemaVersion": "rag-ime.rag-agent-orphan-locator.v1",
                "runRoot": str(forged_run),
                "agentDbPath": str(forged_run / "agent.sqlite"),
                "sessionId": session_id,
                "turnId": turn_id,
                "sandboxRoot": str(forged_run / "knowledge-runs"),
                "sandboxOwnerId": "ablation:owner",
                "sandboxRunId": "a" * 32,
            }
            with self.assertRaisesRegex(ValueError, "private evaluation root"):
                _recover_private_evaluation_session(
                    locator,
                    allowed_private_root=allowed,
                    expected_session_sha256=hashlib.sha256(
                        session_id.encode("utf-8")
                    ).hexdigest(),
                    expected_turn_sha256=hashlib.sha256(
                        turn_id.encode("utf-8")
                    ).hexdigest(),
                )

            self.assertEqual("busy", store.get(session_id)["status"])

    def test_private_session_recovery_faults_session_created_before_turn_acceptance(self) -> None:
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from rag_ime.agent_sessions import AgentSessionStore

        with TemporaryDirectory() as temporary:
            private_root = Path(temporary) / "private-evaluation"
            run_root = private_root / "run-pre-turn"
            run_root.mkdir(parents=True)
            store = AgentSessionStore(run_root / "agent.sqlite")
            store.initialize()
            session = store.create(
                title="RAG Agent ablation: skill",
                tool_profile_version="subagent-readonly-v1",
                execution_mode="read_only",
                project_context_enabled=False,
                workspace_roots=[],
            )
            session_id = str(session["id"])
            store.set_status(session_id, "busy")
            locator = {
                "schemaVersion": "rag-ime.rag-agent-orphan-locator.v1",
                "runRoot": str(run_root),
                "agentDbPath": str(run_root / "agent.sqlite"),
                "sessionId": session_id,
                "turnId": "",
                "sandboxRoot": str(run_root / "knowledge-runs"),
                "sandboxOwnerId": "ablation:owner",
                "sandboxRunId": "b" * 32,
            }

            recovered = _recover_private_evaluation_session(
                locator,
                allowed_private_root=private_root,
                expected_session_sha256=hashlib.sha256(
                    session_id.encode("utf-8")
                ).hexdigest(),
                expected_turn_sha256="",
            )

            self.assertTrue(recovered["recovered"])
            self.assertTrue(recovered["terminal"])
            self.assertEqual("", recovered["turnSha256"])
            self.assertEqual("session_recovery_faulted", recovered["terminalEventType"])
            self.assertEqual("faulted", store.get(session_id)["status"])
            self.assertEqual(1, store.max_event_sequence(session_id))

    def test_private_session_recovery_faults_busy_row_with_existing_terminal(self) -> None:
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from rag_ime.agent_sessions import AgentSessionStore

        with TemporaryDirectory() as temporary:
            private_root = Path(temporary) / "private-evaluation"
            run_root = private_root / "run-terminal"
            run_root.mkdir(parents=True)
            store = AgentSessionStore(run_root / "agent.sqlite")
            store.initialize()
            session = store.create(
                title="RAG Agent ablation: tuned",
                tool_profile_version="subagent-readonly-v1",
                execution_mode="read_only",
                project_context_enabled=False,
                workspace_roots=[],
            )
            session_id = str(session["id"])
            turn_id = "turn:already-failed"
            store.set_status(session_id, "busy")
            store.record_runtime_event(
                event_id="event:already-failed",
                session_id=session_id,
                turn_id=turn_id,
                sequence=1,
                event_type="turn_failed",
                created_at_ms=100,
                redacted_summary="provider failed before hard kill",
            )
            locator = {
                "schemaVersion": "rag-ime.rag-agent-orphan-locator.v1",
                "runRoot": str(run_root),
                "agentDbPath": str(run_root / "agent.sqlite"),
                "sessionId": session_id,
                "turnId": turn_id,
                "sandboxRoot": str(run_root / "knowledge-runs"),
                "sandboxOwnerId": "ablation:owner",
                "sandboxRunId": "c" * 32,
            }

            recovered = _recover_private_evaluation_session(
                locator,
                allowed_private_root=private_root,
                expected_session_sha256=hashlib.sha256(
                    session_id.encode("utf-8")
                ).hexdigest(),
                expected_turn_sha256=hashlib.sha256(
                    turn_id.encode("utf-8")
                ).hexdigest(),
            )

            self.assertTrue(recovered["terminal"])
            self.assertEqual("turn_failed", recovered["terminalEventType"])
            self.assertEqual("faulted", store.get(session_id)["status"])
            self.assertEqual(1, store.max_event_sequence(session_id))

    def test_resume_skips_only_matching_terminal_complete_lanes(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        fingerprint = self._checkpoint_fingerprint()
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                path,
                fingerprint=fingerprint,
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="baseline", attempt=1
            )
            checkpoint = self._bind_checkpoint_attempt(
                path, checkpoint, lane="baseline", attempt=1
            )
            checkpoint = _append_lane_checkpoint_attempt(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                lane_record=self._checkpoint_lane_record("baseline"),
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="skill", attempt=1
            )
            checkpoint = self._bind_checkpoint_attempt(
                path, checkpoint, lane="skill", attempt=1
            )
            checkpoint = _append_lane_checkpoint_attempt(
                path,
                checkpoint=checkpoint,
                lane="skill",
                attempt=1,
                lane_record=self._checkpoint_lane_record(
                    "skill",
                    terminal="turn_failed",
                    runtime_failure_category="provider_transient_after_tool",
                ),
            )
            resumed = _open_lane_checkpoint(
                path,
                fingerprint=fingerprint,
                resume=True,
            )

        reusable = _lane_checkpoint_reusable_records(resumed)
        self.assertEqual({"baseline"}, set(reusable))
        self.assertEqual("turn_completed", reusable["baseline"]["terminalEvent"])

    def test_failed_after_gateway_items_restarts_in_fresh_attempt_within_budget(self) -> None:
        from unittest.mock import patch

        failed = self._checkpoint_lane_record(
            "tuned",
            terminal="turn_failed",
            runtime_failure_category="provider_transient_after_tool",
        )
        completed = self._checkpoint_lane_record("tuned")
        observed: list[tuple[int, str]] = []
        lifecycle_order: list[tuple[str, int]] = []

        def run_once(*args: object, **kwargs: object) -> dict[str, object]:
            attempt = 1 + sum(kind == "run" for kind, _ in lifecycle_order)
            lifecycle_order.append(("run", attempt))
            binding_observer = kwargs["attempt_binding_observer"]
            binding_observer(f"agent:fresh:{attempt}", "")
            binding_observer(f"agent:fresh:{attempt}", f"turn:fresh:{attempt}")
            return failed if attempt == 1 else completed

        with patch(
            "scripts.run_rag_agent_ablation._run_lane_once",
            side_effect=run_once,
        ) as run_once:
            result = _run_lane(
                object(),
                gateway=object(),
                owner="owner",
                run_id="a" * 32,
                lane="tuned",
                cases=[],
                retrieval_config={},
                retrieval_config_sha256="config-v1",
                timeout_seconds=60,
                lane_attempts=2,
                attempt_start_observer=lambda attempt: lifecycle_order.append(
                    ("started", attempt)
                ),
                attempt_binding_observer=(
                    lambda attempt, session_id, turn_id: lifecycle_order.append(
                        ("turn_bound" if turn_id else "session_bound", attempt)
                    )
                ),
                attempt_observer=lambda attempt, record: (
                    observed.append((attempt, str(record["runtimeFailureCategory"]))),
                    lifecycle_order.append(("terminal", attempt)),
                ),
            )

        self.assertEqual(2, run_once.call_count)
        self.assertEqual(
            [(1, "provider_transient_after_tool"), (2, "")],
            observed,
        )
        self.assertEqual("turn_completed", result["terminalEvent"])
        self.assertEqual(1, result["runtimeRetryCount"])
        self.assertEqual(
            [
                ("started", 1),
                ("run", 1),
                ("session_bound", 1),
                ("turn_bound", 1),
                ("terminal", 1),
                ("started", 2),
                ("run", 2),
                ("session_bound", 2),
                ("turn_bound", 2),
                ("terminal", 2),
            ],
            lifecycle_order,
        )

    def test_checkpoint_fingerprint_drift_is_rejected(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                _open_lane_checkpoint(
                    path,
                    fingerprint=self._checkpoint_fingerprint(prompt_sha256="prompt-v2"),
                    resume=True,
                )

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            fingerprint = self._checkpoint_fingerprint()
            _open_lane_checkpoint(path, fingerprint=fingerprint, resume=False)
            drifted = dict(fingerprint)
            drifted["lanePromptSha256ByLane"] = {
                **dict(fingerprint["lanePromptSha256ByLane"]),
                "agentic": "agentic-prompt-v2",
            }
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                _open_lane_checkpoint(path, fingerprint=drifted, resume=True)

    def test_partial_or_non_terminal_checkpoint_lane_is_not_reusable(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="baseline", attempt=1
            )
            checkpoint = self._bind_checkpoint_attempt(
                path, checkpoint, lane="baseline", attempt=1
            )
            checkpoint = _append_lane_checkpoint_attempt(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                lane_record=self._checkpoint_lane_record("baseline", terminal=""),
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="skill", attempt=1
            )
            checkpoint = self._bind_checkpoint_attempt(
                path, checkpoint, lane="skill", attempt=1
            )
            checkpoint = _append_lane_checkpoint_attempt(
                path,
                checkpoint=checkpoint,
                lane="skill",
                attempt=1,
                lane_record=self._checkpoint_lane_record(
                    "skill",
                    tool_contract=False,
                ),
            )

        self.assertEqual({}, _lane_checkpoint_reusable_records(checkpoint))

    def test_validation_checkpoint_cannot_bypass_held_out_gate(self) -> None:
        from pathlib import Path

        with self.assertRaisesRegex(ValueError, "validation-only"):
            _validate_checkpoint_request(
                evaluation_split="held_out",
                checkpoint_path=Path("checkpoint.json"),
                resume_checkpoint=False,
            )

    def test_public_report_projects_checkpoint_counts_and_redacts_private_values(self) -> None:
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "validation.checkpoint.json"
            checkpoint = _open_lane_checkpoint(
                path,
                fingerprint=self._checkpoint_fingerprint(),
                resume=False,
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="baseline", attempt=1
            )
            checkpoint = self._bind_checkpoint_attempt(
                path, checkpoint, lane="baseline", attempt=1
            )
            checkpoint = _append_lane_checkpoint_attempt(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=1,
                lane_record=self._checkpoint_lane_record(
                    "baseline",
                    terminal="turn_failed",
                    runtime_failure_category="provider_transient_after_tool",
                ),
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="baseline", attempt=2
            )
            checkpoint = self._bind_checkpoint_attempt(
                path, checkpoint, lane="baseline", attempt=2
            )
            checkpoint = _append_lane_checkpoint_attempt(
                path,
                checkpoint=checkpoint,
                lane="baseline",
                attempt=2,
                lane_record=self._checkpoint_lane_record("baseline"),
            )
            initial_attempt_count = len(
                _lane_checkpoint_attempt_history(checkpoint, "baseline")
            )
            checkpoint = _append_lane_checkpoint_attempt_started(
                path, checkpoint=checkpoint, lane="skill", attempt=1
            )
            checkpoint = self._bind_checkpoint_attempt(
                path, checkpoint, lane="skill", attempt=1
            )
            checkpoint = _append_lane_checkpoint_attempt(
                path,
                checkpoint=checkpoint,
                lane="skill",
                attempt=1,
                lane_record=self._checkpoint_lane_record("skill"),
            )

        projection = _lane_checkpoint_report_projection(
            checkpoint,
            resume_requested=True,
            initial_attempt_count=initial_attempt_count,
            reused_lanes={"baseline"},
            fresh_lanes={"skill"},
        )
        report = _finalize_public_report(
            {
                "schemaVersion": "fixture.v1",
                "formalAcceptanceEligible": False,
                "formalAcceptancePassed": False,
                "evaluation": {"split": "validation"},
                "lanes": [
                    {
                        "lane": "skill",
                        "binding": {"sessionId": "agent:private-session"},
                        "_checkpointTurnId": "turn:private-turn",
                        "_assistantText": "private assistant output",
                        "runtimeFailureCategory": "provider_runtime_failure",
                        "error": "failed under /Volumes/undo 4t/git/private run/file.json",
                    }
                ],
                "answerJudge": {
                    "assistantOutputs": ["private judge output"],
                    "assistantOutputSha256s": ["already-hashed"],
                },
            },
            checkpoint=projection,
        )
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)

        self.assertEqual(3, report["checkpoint"]["attemptCount"])
        self.assertEqual(2, report["checkpoint"]["completedLaneCount"])
        self.assertEqual(1, report["checkpoint"]["reusedLaneCount"])
        self.assertEqual(1, report["checkpoint"]["freshLaneCount"])
        self.assertEqual(1, report["checkpoint"]["retriedLaneCount"])
        self.assertEqual(3, len(report["checkpoint"]["attemptHistory"]))
        self.assertFalse(report["formalAcceptanceEligible"])
        self.assertNotIn("agent:private-session", serialized)
        self.assertNotIn("turn:private-turn", serialized)
        self.assertNotIn("private assistant output", serialized)
        self.assertNotIn("private judge output", serialized)
        self.assertNotIn("/Volumes/undo", serialized)
        self.assertNotIn("4t/git/private", serialized)
        self.assertNotIn('"error":', serialized)
        self.assertIn("errorSha256", serialized)
        self.assertIn("provider_runtime_failure", serialized)
        self.assertIn("sessionSha256", serialized)
        self.assertIn("turnSha256", serialized)
        self.assertTrue(report["reportSha256"])

    def test_public_path_redaction_preserves_urls_and_hashes_complete_paths(self) -> None:
        https_url = "https://github.com/onyx-dot-app/EnterpriseRAG-Bench"
        absolute_with_space = "/Volumes/undo 4t/git/private run/result.json"
        inline_path = "failed at /tmp/private-run/result.json before completion"
        inline_path_with_space = (
            "failed at /Volumes/undo 4t/git/private run/result.json before completion"
        )
        file_url = "file:///Volumes/undo%204t/private/result.json"

        self.assertEqual(https_url, _redact_absolute_paths(https_url))
        redacted_absolute = _redact_absolute_paths(absolute_with_space)
        self.assertRegex(redacted_absolute, r"^\[path-sha256:[a-f0-9]{64}\]$")
        self.assertEqual(1, redacted_absolute.count("path-sha256"))
        self.assertNotIn("/Volumes/undo", redacted_absolute)
        redacted_inline = _redact_absolute_paths(inline_path)
        self.assertIn("failed at [path-sha256:", redacted_inline)
        self.assertNotIn("/tmp/private-run/result.json", redacted_inline)
        redacted_inline_with_space = _redact_absolute_paths(inline_path_with_space)
        self.assertNotIn("/Volumes/undo", redacted_inline_with_space)
        self.assertNotIn("4t/git/private", redacted_inline_with_space)
        redacted_file_url = _redact_absolute_paths(file_url)
        self.assertNotIn("/Volumes/undo%204t/private/result.json", redacted_file_url)
        self.assertIn("path-sha256", redacted_file_url)
        self.assertEqual("ratio 1/2 remains", _redact_absolute_paths("ratio 1/2 remains"))

    def test_host_answer_evidence_qrels_never_enter_public_report(self) -> None:
        import json

        secret_quote = "private source quote that must remain host-only"
        secret_document_id = "private-document-id"
        report = _finalize_public_report(
            {
                "schemaVersion": "fixture.v1",
                "formalAcceptanceEligible": False,
                "evaluation": {"split": "validation"},
                "answerCaseManifest": {
                    "schemaVersion": "rag-ime.rag-answer-case-manifest.v2",
                    "evidenceManifestSha256": "e" * 64,
                    "highLevelFactCount": 2,
                    "highLevelEvidenceAvailabilityPassed": True,
                    "_privateEvidenceQrels": {
                        "q-high": {
                            "facts": [
                                {
                                    "factId": "F1",
                                    "supportGroups": [
                                        {
                                            "documentIds": [secret_document_id],
                                            "quotes": [secret_quote],
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                },
            },
            checkpoint=None,
        )
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)

        self.assertNotIn(secret_quote, serialized)
        self.assertNotIn(secret_document_id, serialized)
        self.assertNotIn("_privateEvidenceQrels", serialized)
        self.assertEqual(
            "e" * 64,
            report["answerCaseManifest"]["evidenceManifestSha256"],
        )

    def test_public_report_requires_top_level_runtime_identity_to_match_conditions(self) -> None:
        pi_runtime = {
            "schemaVersion": "rag-ime.rag-agent-pi-runtime-identity.v1",
            "identitySha256": "pi-runtime-v1",
        }
        agent_config = {
            "schemaVersion": "rag-ime.rag-evaluation-agent-config.v1",
            "identitySha256": "agent-config-v1",
        }
        report = {
            "schemaVersion": "fixture.v1",
            "conditions": {
                "piRuntime": pi_runtime,
                "agentConfig": agent_config,
            },
            "piRuntime": pi_runtime,
            "agentConfig": agent_config,
            "evaluation": {"split": "validation"},
        }

        finalized = _finalize_public_report(report, checkpoint=None)
        self.assertEqual(finalized["piRuntime"], finalized["conditions"]["piRuntime"])
        self.assertEqual(
            finalized["agentConfig"], finalized["conditions"]["agentConfig"]
        )

        report.pop("piRuntime")
        with self.assertRaisesRegex(RuntimeError, "Pi Runtime identity"):
            _finalize_public_report(report, checkpoint=None)

    def test_answer_only_defaults_to_validation(self) -> None:
        self.assertEqual("validation", _resolve_evaluation_split(None, answer_only=True))
        self.assertEqual("held_out", _resolve_evaluation_split(None, answer_only=False))

    def test_evaluation_agent_config_pins_sol_max_and_sse(self) -> None:
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary:
            agent_config = Path(temporary)
            (agent_config / "settings.json").write_text(
                json.dumps(
                    {
                        "defaultProvider": "openai-codex",
                        "defaultModel": "gpt-5.6-luna",
                        "defaultThinkingLevel": "medium",
                    }
                ),
                encoding="utf-8",
            )
            receipt = _pin_evaluation_agent_config(agent_config)
            settings = json.loads(
                (agent_config / "settings.json").read_text(encoding="utf-8")
            )

        self.assertEqual("gpt-5.6-sol", settings["defaultModel"])
        self.assertEqual("max", settings["defaultThinkingLevel"])
        self.assertEqual("sse", settings["transport"])
        self.assertEqual("openai-codex/gpt-5.6-sol", receipt["model"])
        self.assertTrue(receipt["settingsSha256"])

    def test_evaluation_configuration_pins_every_paw_agent_route(self) -> None:
        configuration = _evaluation_configuration_defaults()

        self.assertEqual(
            "openai-codex/gpt-5.6-sol",
            configuration["sessionDefaults"]["modelProfile"],
        )
        self.assertFalse(configuration["sessionDefaults"]["resumeLastSession"])
        self.assertEqual(
            {
                "primary",
                "traceDiagnostic",
                "toolAgent",
                "subagent",
                "roomCoordinator",
            },
            set(configuration["modelRouting"]),
        )
        for route in configuration["modelRouting"].values():
            self.assertEqual("openai-codex/gpt-5.6-sol", route["modelProfile"])
            self.assertEqual("max", route["thinkingLevel"])

    def test_answer_manifest_binds_suite_corpus_and_high_level_evidence(self) -> None:
        import hashlib

        documents = [
            {
                "documentId": "doc-runtime",
                "text": "The runtime uses continuous batching and prefix KV caching.",
            }
        ]
        prepared_cases = [
            {
                "queryId": "q-retrieval",
                "query": "What does the runtime use?",
                "split": "validation",
                "slice": "basic",
                "retrievalEvaluable": True,
                "relevant": {"doc-runtime": 1.0},
            }
        ]
        answer_cases = [
            dict(prepared_cases[0]),
            {
                "queryId": "q-high",
                "query": "Which runtime optimizations are used?",
                "split": "validation",
                "slice": "high_level",
                "retrievalEvaluable": False,
                "abstentionExpected": False,
                "goldAnswer": "Continuous batching and prefix KV caching.",
                "answerFacts": [
                    "The runtime uses continuous batching.",
                    "The runtime uses prefix KV caching.",
                ],
            },
        ]
        chunking = {
            "strategy": "general",
            "size": 1200,
            "overlap": 160,
            "separator": "",
            "respectHeadings": True,
            "respectPageBoundaries": True,
        }
        document_text = str(documents[0]["text"])
        evidence_qrels = {
            "schemaVersion": "rag-ime.rag-answer-evidence-qrels.v1",
            "evaluationSplit": "validation",
            "preparedSourceSha256": "dataset-v1",
            "chunkingConfigSha256": _sha256_json(chunking),
            "cases": [
                {
                    "queryId": "q-high",
                    "facts": [
                        {
                            "factId": "F1",
                            "factSha256": hashlib.sha256(
                                str(answer_cases[1]["answerFacts"][0]).encode("utf-8")
                            ).hexdigest(),
                            "availability": "verified",
                            "supportGroups": [
                                {
                                    "groupId": "G1",
                                    "evidence": [
                                        {
                                            "documentId": "doc-runtime",
                                            "documentSha256": hashlib.sha256(
                                                document_text.encode("utf-8")
                                            ).hexdigest(),
                                            "chunkOrdinal": 0,
                                            "chunkSha256": hashlib.sha256(
                                                document_text.encode("utf-8")
                                            ).hexdigest(),
                                            "quote": "The runtime uses continuous batching",
                                            "quoteSha256": hashlib.sha256(
                                                b"The runtime uses continuous batching"
                                            ).hexdigest(),
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "factId": "F2",
                            "factSha256": hashlib.sha256(
                                str(answer_cases[1]["answerFacts"][1]).encode("utf-8")
                            ).hexdigest(),
                            "availability": "verified",
                            "supportGroups": [
                                {
                                    "groupId": "G1",
                                    "evidence": [
                                        {
                                            "documentId": "doc-runtime",
                                            "documentSha256": hashlib.sha256(
                                                document_text.encode("utf-8")
                                            ).hexdigest(),
                                            "chunkOrdinal": 0,
                                            "chunkSha256": hashlib.sha256(
                                                document_text.encode("utf-8")
                                            ).hexdigest(),
                                            "quote": "prefix KV caching",
                                            "quoteSha256": hashlib.sha256(
                                                b"prefix KV caching"
                                            ).hexdigest(),
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        evidence_qrels["manifestSha256"] = _sha256_json(evidence_qrels)

        manifest = _answer_case_manifest(
            prepared_cases=prepared_cases,
            answer_cases=answer_cases,
            selected_cases=[answer_cases[1]],
            documents=documents,
            benchmark_id="benchmark-v1",
            prepared_source_sha256="dataset-v1",
            evaluation_split="validation",
            chunking_config=chunking,
            answer_evidence_qrels=evidence_qrels,
        )

        self.assertTrue(manifest["suiteBindingPassed"])
        self.assertTrue(manifest["corpusBindingPassed"])
        self.assertTrue(manifest["highLevelEvidenceAvailabilityPassed"])
        self.assertEqual(2, manifest["highLevelFactCount"])
        self.assertEqual(evidence_qrels["manifestSha256"], manifest["evidenceManifestSha256"])
        self.assertNotIn("highLevelEvidenceAvailability", manifest)
        self.assertTrue(manifest["manifestSha256"])

        answer_cases[0]["query"] = "drifted"
        with self.assertRaisesRegex(ValueError, "does not match prepared suite"):
            _answer_case_manifest(
                prepared_cases=prepared_cases,
                answer_cases=answer_cases,
                selected_cases=[answer_cases[1]],
                documents=documents,
                benchmark_id="benchmark-v1",
                prepared_source_sha256="dataset-v1",
                evaluation_split="validation",
                chunking_config=chunking,
                answer_evidence_qrels=evidence_qrels,
            )

    def test_answer_manifest_rejects_token_overlap_without_verified_fact_qrels(self) -> None:
        import hashlib

        document_text = "The runtime uses continuous batching and prefix KV caching."
        chunking = {
            "strategy": "general",
            "size": 1200,
            "overlap": 160,
            "separator": "",
            "respectHeadings": True,
            "respectPageBoundaries": True,
        }
        prepared_cases = [
            {
                "queryId": "q-retrieval",
                "query": "What does the runtime use?",
                "split": "validation",
                "slice": "basic",
                "retrievalEvaluable": True,
                "relevant": {"doc-runtime": 1.0},
            }
        ]
        answer_cases = [
            dict(prepared_cases[0]),
            {
                "queryId": "q-high",
                "query": "Which runtime optimizations are used?",
                "split": "validation",
                "slice": "high_level",
                "retrievalEvaluable": False,
                "abstentionExpected": False,
                "goldAnswer": "Continuous batching.",
                "answerFacts": ["The runtime uses continuous batching."],
            },
        ]
        evidence_qrels = {
            "schemaVersion": "rag-ime.rag-answer-evidence-qrels.v1",
            "evaluationSplit": "validation",
            "preparedSourceSha256": "dataset-v1",
            "chunkingConfigSha256": _sha256_json(chunking),
            "cases": [
                {
                    "queryId": "q-high",
                    "facts": [
                        {
                            "factId": "F1",
                            "factSha256": hashlib.sha256(
                                b"The runtime uses continuous batching."
                            ).hexdigest(),
                            "availability": "unavailable",
                            "reasonCode": "no_verified_source_support",
                            "supportGroups": [],
                        }
                    ],
                }
            ],
        }
        evidence_qrels["manifestSha256"] = _sha256_json(evidence_qrels)

        with self.assertRaisesRegex(ValueError, "lack verified corpus evidence"):
            _answer_case_manifest(
                prepared_cases=prepared_cases,
                answer_cases=answer_cases,
                selected_cases=[answer_cases[1]],
                documents=[{"documentId": "doc-runtime", "text": document_text}],
                benchmark_id="benchmark-v1",
                prepared_source_sha256="dataset-v1",
                evaluation_split="validation",
                chunking_config=chunking,
                answer_evidence_qrels=evidence_qrels,
            )

    def test_answer_manifest_rejects_quote_or_document_hash_drift(self) -> None:
        import hashlib

        document_text = "Canonical source sentence for the required fact."
        fact_text = "The required fact is source grounded."
        chunking = {
            "strategy": "general",
            "size": 1200,
            "overlap": 160,
            "separator": "",
            "respectHeadings": True,
            "respectPageBoundaries": True,
        }

        def qrels(*, quote: str, document_sha256: str) -> dict[str, object]:
            value: dict[str, object] = {
                "schemaVersion": "rag-ime.rag-answer-evidence-qrels.v1",
                "evaluationSplit": "validation",
                "preparedSourceSha256": "dataset-v1",
                "chunkingConfigSha256": _sha256_json(chunking),
                "cases": [
                    {
                        "queryId": "q-high",
                        "facts": [
                            {
                                "factId": "F1",
                                "factSha256": hashlib.sha256(
                                    fact_text.encode("utf-8")
                                ).hexdigest(),
                                "availability": "verified",
                                "supportGroups": [
                                    {
                                        "groupId": "G1",
                                        "evidence": [
                                            {
                                                "documentId": "doc-source",
                                                "documentSha256": document_sha256,
                                                "chunkOrdinal": 0,
                                                "chunkSha256": hashlib.sha256(
                                                    document_text.encode("utf-8")
                                                ).hexdigest(),
                                                "quote": quote,
                                                "quoteSha256": hashlib.sha256(
                                                    quote.encode("utf-8")
                                                ).hexdigest(),
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
            value["manifestSha256"] = _sha256_json(value)
            return value

        common = {
            "prepared_cases": [],
            "answer_cases": [
                {
                    "queryId": "q-high",
                    "query": "What is the required fact?",
                    "split": "validation",
                    "slice": "high_level",
                    "retrievalEvaluable": False,
                    "abstentionExpected": False,
                    "goldAnswer": "Grounded.",
                    "answerFacts": [fact_text],
                }
            ],
            "selected_cases": [
                {
                    "queryId": "q-high",
                    "query": "What is the required fact?",
                    "split": "validation",
                    "slice": "high_level",
                    "retrievalEvaluable": False,
                    "abstentionExpected": False,
                    "goldAnswer": "Grounded.",
                    "answerFacts": [fact_text],
                }
            ],
            "documents": [{"documentId": "doc-source", "text": document_text}],
            "benchmark_id": "benchmark-v1",
            "prepared_source_sha256": "dataset-v1",
            "evaluation_split": "validation",
            "chunking_config": chunking,
        }
        with self.assertRaisesRegex(ValueError, "document hash"):
            _answer_case_manifest(
                **common,
                answer_evidence_qrels=qrels(
                    quote="Canonical source sentence",
                    document_sha256="0" * 64,
                ),
            )
        with self.assertRaisesRegex(ValueError, "exact source chunk"):
            _answer_case_manifest(
                **common,
                answer_evidence_qrels=qrels(
                    quote="invented quote",
                    document_sha256=hashlib.sha256(
                        document_text.encode("utf-8")
                    ).hexdigest(),
                ),
            )

    def test_held_out_requires_matching_promotion_and_one_shot_gate(self) -> None:
        promotion, gate = self._held_out_authority()

        receipt = _authorize_held_out(
            promotion=promotion,
            gate=gate,
            source_prepared_sha256="prepared-file",
            source_answer_cases_sha256="answer-file",
            retrieval_report_sha256="retrieval-report",
            retrieval_config_sha256=str(gate["retrievalConfigSha256"]),
            prompt_config_sha256="prompt-config",
            source_retrieval_report_sha256="retrieval-file",
            runtime_contract_sha256="runtime-contract",
        )
        self.assertTrue(receipt["authorized"])
        gate["state"] = "locked"
        gate["gateReceiptSha256"] = _sha256_json(
            {key: value for key, value in gate.items() if key != "gateReceiptSha256"}
        )
        with self.assertRaisesRegex(ValueError, "not unlocked"):
            _authorize_held_out(
                promotion=promotion,
                gate=gate,
                source_prepared_sha256="prepared-file",
                source_answer_cases_sha256="answer-file",
                retrieval_report_sha256="retrieval-report",
                retrieval_config_sha256=str(gate["retrievalConfigSha256"]),
                prompt_config_sha256="prompt-config",
                source_retrieval_report_sha256="retrieval-file",
                runtime_contract_sha256="runtime-contract",
            )

        promotion, gate = self._held_out_authority()
        promotion["decision"] = "reject"
        promotion["promotionReceiptSha256"] = _sha256_json(
            {
                key: value
                for key, value in promotion.items()
                if key != "promotionReceiptSha256"
            }
        )
        gate["promotionReceiptSha256"] = promotion["promotionReceiptSha256"]
        gate["gateReceiptSha256"] = _sha256_json(
            {key: value for key, value in gate.items() if key != "gateReceiptSha256"}
        )
        with self.assertRaisesRegex(ValueError, "decision is not keep"):
            _authorize_held_out(
                promotion=promotion,
                gate=gate,
                source_prepared_sha256="prepared-file",
                source_answer_cases_sha256="answer-file",
                source_retrieval_report_sha256="retrieval-file",
                retrieval_report_sha256="retrieval-report",
                retrieval_config_sha256=str(gate["retrievalConfigSha256"]),
                prompt_config_sha256="prompt-config",
                runtime_contract_sha256="runtime-contract",
            )

    def test_held_out_gate_claim_is_atomic_one_shot_before_reader_or_selector(self) -> None:
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Barrier, Lock

        promotion, gate = self._held_out_authority()
        authorization = _authorize_held_out(
            promotion=promotion,
            gate=gate,
            source_prepared_sha256="prepared-file",
            source_answer_cases_sha256="answer-file",
            source_retrieval_report_sha256="retrieval-file",
            retrieval_report_sha256="retrieval-report",
            retrieval_config_sha256=str(gate["retrievalConfigSha256"]),
            prompt_config_sha256="prompt-config",
            runtime_contract_sha256="runtime-contract",
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            gate_paths = (
                root / "heldout gate original.json",
                root / "heldout gate copied.json",
            )
            for gate_path in gate_paths:
                gate_path.write_text("{}\n", encoding="utf-8")
            claim_registry = root / "private authority registry"
            barrier = Barrier(2)
            selected: list[int] = []
            reader_calls: list[int] = []
            selector_calls: list[int] = []
            lock = Lock()

            def contender(index: int) -> str:
                barrier.wait()
                try:
                    _claim_held_out_gate(
                        gate_paths[index - 1],
                        authorization=authorization,
                        claim_registry_root=claim_registry,
                    )
                except ValueError:
                    return "lost"
                with lock:
                    reader_calls.append(index)
                    selector_calls.append(index)
                    selected.append(index)
                return "won"

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(contender, (1, 2)))
            claim_path = claim_registry / (
                str(authorization["gateReceiptSha256"]) + ".consumed.json"
            )
            self.assertTrue(claim_path.is_file())
            self.assertFalse(
                gate_paths[0].with_name(gate_paths[0].name + ".consumed.json").exists()
            )
            self.assertFalse(
                gate_paths[1].with_name(gate_paths[1].name + ".consumed.json").exists()
            )
            self.assertEqual(["lost", "won"], sorted(results))
            self.assertEqual(1, len(selected))
            self.assertEqual(selected, reader_calls)
            self.assertEqual(selected, selector_calls)
            with self.assertRaisesRegex(ValueError, "already consumed"):
                _claim_held_out_gate(
                    gate_paths[1],
                    authorization=authorization,
                    claim_registry_root=claim_registry,
                )

        self.assertEqual(1, len(selected))

    def test_answer_only_judgments_keep_fact_citation_and_abstention_denominators_separate(self) -> None:
        lane_records = [
            {
                "lane": "baseline",
                "score": {
                    "answerCases": [
                        {
                            "evaluationCaseId": "case-high",
                            "toolSuccess": True,
                            "citationResolution": True,
                            "citations": ["doc-a"],
                            "citationSuccess": True,
                            "abstentionCorrect": True,
                        },
                        {
                            "evaluationCaseId": "case-missing",
                            "toolSuccess": True,
                            "citationResolution": True,
                            "citations": [],
                            "citationSuccess": True,
                            "abstentionCorrect": True,
                        },
                    ],
                    "agentMetrics": {},
                    "metricDenominators": {
                        "answerableCitationCases": 1,
                        "highLevelCases": 1,
                        "infoNotFoundCases": 1,
                        "protocolCases": 2,
                    },
                },
            }
        ]
        cases = [
            {
                "queryId": "q-high",
                "evaluationCaseId": "case-high",
                "abstentionExpected": False,
            },
            {
                "queryId": "q-missing",
                "evaluationCaseId": "case-missing",
                "abstentionExpected": True,
            },
        ]
        judge = {
            "caseRubrics": [
                {
                    "caseId": "case-high",
                    "requiredFacts": [
                        {"factId": "F1", "description": "one"},
                        {"factId": "F2", "description": "two"},
                    ],
                }
            ],
            "judgments": [
                {
                    "lane": "baseline",
                    "evaluationCaseId": "case-high",
                    "correct": False,
                    "reasonCode": "incomplete",
                    "coveredFactIds": ["F1"],
                    "hasUnsupportedMaterial": False,
                }
            ],
        }

        answer_case_manifest = {
            "_privateEvidenceQrels": {
                "q-high": {
                    "facts": [
                        {
                            "factId": "F1",
                            "supportGroups": [{"documentIds": ["doc-a"]}],
                        },
                        {
                            "factId": "F2",
                            "supportGroups": [{"documentIds": ["doc-b"]}],
                        },
                    ]
                }
            }
        }

        _apply_answer_only_judgments(
            lane_records,
            cases=cases,
            answer_judge=judge,
            answer_case_manifest=answer_case_manifest,
        )

        metrics = lane_records[0]["score"]["agentMetrics"]
        denominators = lane_records[0]["score"]["metricDenominators"]
        self.assertEqual(0.5, metrics["highLevelFactCoverage"])
        self.assertEqual(0.5, metrics["citationFactCoverage"])
        self.assertEqual(0.0, metrics["answerableCitationSupportRate"])
        self.assertEqual(1.0, metrics["infoNotFoundAbstentionRecall"])
        self.assertEqual(2, denominators["highLevelFacts"])
        self.assertEqual(2, denominators["citationFacts"])

    def test_answer_only_fact_citation_coverage_requires_every_qrel_support_group(self) -> None:
        lane_records = [
            {
                "lane": "baseline",
                "score": {
                    "answerCases": [
                        {
                            "evaluationCaseId": "case-high",
                            "toolSuccess": True,
                            "citationResolution": True,
                            "citations": ["doc-runtime", "doc-architecture"],
                            "citationSuccess": True,
                            "abstentionCorrect": True,
                        },
                        {
                            "evaluationCaseId": "case-missing",
                            "toolSuccess": True,
                            "citationResolution": True,
                            "citations": [],
                            "citationSuccess": None,
                            "abstentionCorrect": True,
                        },
                    ],
                    "agentMetrics": {},
                    "metricDenominators": {
                        "answerableCitationCases": 1,
                        "highLevelCases": 1,
                        "infoNotFoundCases": 1,
                        "protocolCases": 2,
                    },
                    "hardEvidence": {"citationResolution": True},
                },
            }
        ]
        cases = [
            {
                "queryId": "q-high",
                "evaluationCaseId": "case-high",
                "abstentionExpected": False,
            },
            {
                "queryId": "q-missing",
                "evaluationCaseId": "case-missing",
                "abstentionExpected": True,
            },
        ]
        judge = {
            "caseRubrics": [
                {
                    "caseId": "case-high",
                    "requiredFacts": [
                        {"factId": "J1", "description": "complete answer"}
                    ],
                }
            ],
            "judgments": [
                {
                    "lane": "baseline",
                    "evaluationCaseId": "case-high",
                    "correct": True,
                    "reasonCode": "correct",
                    "coveredFactIds": ["J1"],
                    "hasUnsupportedMaterial": False,
                }
            ],
        }
        answer_case_manifest = {
            "_privateEvidenceQrels": {
                "q-high": {
                    "facts": [
                        {
                            "factId": "F1",
                            "supportGroups": [
                                {"documentIds": ["doc-runtime"]}
                            ],
                        },
                        {
                            "factId": "F2",
                            "supportGroups": [
                                {"documentIds": ["doc-architecture"]},
                                {"documentIds": ["doc-hardware"]},
                            ],
                        },
                    ]
                }
            }
        }

        _apply_answer_only_judgments(
            lane_records,
            cases=cases,
            answer_judge=judge,
            answer_case_manifest=answer_case_manifest,
        )

        answer_case = lane_records[0]["score"]["answerCases"][0]
        metrics = lane_records[0]["score"]["agentMetrics"]
        self.assertTrue(answer_case["answerJudgeCorrect"])
        self.assertEqual(0.5, answer_case["citationFactCoverage"])
        self.assertFalse(answer_case["citationSupport"])
        self.assertEqual(0.5, metrics["citationFactCoverage"])
        self.assertFalse(
            lane_records[0]["score"]["hardEvidence"]["factCitationCoverage"]
        )

    def test_answer_only_rejects_missing_real_high_level_or_info_not_found_denominator(self) -> None:
        def fixture(
            case_id: str,
            *,
            high_level: int,
            info_not_found: int,
            abstention_expected: bool,
        ) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
            records = [
                {
                    "lane": "baseline",
                    "score": {
                        "answerCases": [
                            {
                                "evaluationCaseId": case_id,
                                "toolSuccess": True,
                                "citationResolution": True,
                                "citations": [] if abstention_expected else ["doc-a"],
                                "abstentionCorrect": True,
                            }
                        ],
                        "agentMetrics": {},
                        "metricDenominators": {
                            "answerableCitationCases": high_level,
                            "highLevelCases": high_level,
                            "infoNotFoundCases": info_not_found,
                            "protocolCases": 1,
                        },
                    },
                }
            ]
            cases = [
                {
                    "queryId": case_id,
                    "evaluationCaseId": case_id,
                    "abstentionExpected": abstention_expected,
                }
            ]
            judge = {
                "caseRubrics": (
                    []
                    if abstention_expected
                    else [{"caseId": case_id, "requiredFacts": [{"factId": "F1"}]}]
                ),
                "judgments": (
                    []
                    if abstention_expected
                    else [
                        {
                            "lane": "baseline",
                            "evaluationCaseId": case_id,
                            "correct": True,
                            "reasonCode": "correct",
                            "coveredFactIds": ["F1"],
                            "hasUnsupportedMaterial": False,
                        }
                    ]
                ),
            }
            return records, cases, judge

        values_by_case = (
            fixture(
                "case-only-high",
                high_level=1,
                info_not_found=0,
                abstention_expected=False,
            ),
            fixture(
                "case-only-missing",
                high_level=0,
                info_not_found=1,
                abstention_expected=True,
            ),
        )
        for records, cases, judge in values_by_case:
            with self.subTest(case_id=cases[0]["evaluationCaseId"]):
                with self.assertRaisesRegex(
                    RuntimeError, "real high-level and info-not-found"
                ):
                    _apply_answer_only_judgments(
                        records,
                        cases=cases,
                        answer_judge=judge,
                        answer_case_manifest={
                            "_privateEvidenceQrels": (
                                {}
                                if cases[0]["abstentionExpected"] is True
                                else {
                                    str(cases[0]["queryId"]): {
                                        "facts": [
                                            {
                                                "factId": "F1",
                                                "supportGroups": [
                                                    {"documentIds": ["doc-a"]}
                                                ],
                                            }
                                        ]
                                    }
                                }
                            )
                        },
                    )

    def test_preflight_failure_is_a_non_score_receipt_before_sandbox(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as root:
            root_path = Path(root)
            prepared = root_path / "prepared.json"
            retrieval = root_path / "retrieval.json"
            prepared.write_text("{}\n", encoding="utf-8")
            retrieval.write_text("{}\n", encoding="utf-8")
            report = _preflight_failure_report(
                started_at_ms=100,
                prepared_path=prepared,
                answer_cases_path=None,
                retrieval_report_path=retrieval,
                slice_manifest={"benchmarkId": "fixture"},
                evaluation_cases=[
                    {"queryId": "q-1", "evaluationCaseId": "case-01"}
                ],
                evaluation_mode="answer-only",
                evaluation_split="validation",
                answer_case_manifest={
                    "manifestSha256": "answer-manifest-hash",
                    "answerCaseSetSha256": "answer-case-set-hash",
                    "selectedCaseSetSha256": "selected-case-set-hash",
                },
                prompt_config_sha256="prompt-config-hash",
                calibration_no_metal=False,
                development_only=False,
                embedding={},
                failure="RuntimeError: No Metal device available",
                checkpoint={
                    "schemaVersion": "rag-ime.rag-agent-ablation-checkpoint.v1",
                    "enabled": True,
                    "initialized": False,
                    "resumeRequested": True,
                    "attemptCount": 0,
                    "attemptHistory": [],
                },
            )

        self.assertFalse(report["passed"])
        self.assertFalse(report["scoreEligible"])
        self.assertFalse(report["formalAcceptanceEligible"])
        self.assertTrue(report["cleanupPassed"])
        self.assertFalse(report["preflight"]["accepted"])
        self.assertFalse(report["preflight"]["sandboxAllocated"])
        self.assertEqual("answer-only", report["evaluation"]["mode"])
        self.assertEqual("validation", report["evaluation"]["split"])
        self.assertFalse(report["evaluation"]["formalAcceptanceEligible"])
        self.assertEqual(
            "answer-manifest-hash",
            report["evaluation"]["answerCaseManifestSha256"],
        )
        self.assertEqual(
            "selected-case-set-hash",
            report["evaluation"]["caseSetSha256"],
        )
        self.assertEqual(
            "answer-case-set-hash",
            report["evaluation"]["answerCaseSetSha256"],
        )
        self.assertEqual(
            "prompt-config-hash",
            report["evaluation"]["promptConfigSha256"],
        )
        self.assertTrue(report["checkpoint"]["enabled"])
        self.assertTrue(report["checkpoint"]["resumeRequested"])
        self.assertTrue(report["reportSha256"])

    def test_metal_preflight_requires_an_evaluated_device_operation(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        failed = SimpleNamespace(returncode=1, stdout="", stderr="No Metal device")
        with patch("scripts.run_rag_agent_ablation.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "Metal preflight failed"):
                _require_actual_metal_runtime()

        passed = SimpleNamespace(returncode=0, stdout="metal-probe-ok\n", stderr="")
        with patch("scripts.run_rag_agent_ablation.subprocess.run", return_value=passed):
            _require_actual_metal_runtime()

    def test_knowledge_base_config_excludes_independent_rerank_metadata(self) -> None:
        projected = _knowledge_base_retrieval_config(
            {
                "mode": "hybrid",
                "topK": 10,
                "threshold": 0,
                "lexicalWeight": 1,
                "denseWeight": 2,
                "graphEnabled": False,
                "graphWeight": 0,
                "rrfK": 20,
                "candidateMultiplier": 8,
                "rerankEnabled": True,
                "rerankCandidateDepth": 40,
                "rerankerFingerprint": "fixture:sha256:" + "a" * 64,
            }
        )

        self.assertEqual("hybrid", projected["mode"])
        self.assertEqual(8, projected["candidateMultiplier"])
        self.assertNotIn("rerankEnabled", projected)
        self.assertNotIn("rerankCandidateDepth", projected)
        self.assertNotIn("rerankerFingerprint", projected)

    def test_production_baseline_record_prefers_current_report_field(self) -> None:
        current = {"configSha256": "current"}
        legacy = {"configSha256": "legacy"}

        selected = _production_baseline_record(
            {
                "heldOut": {
                    "productionLexicalFloor": current,
                    "baseline": legacy,
                }
            }
        )

        self.assertIs(current, selected)

    def test_production_baseline_record_uses_validation_lexical_candidate_before_heldout(self) -> None:
        lexical = {
            "config": {"mode": "lexical", "topK": 10},
            "configSha256": "validation-lexical",
        }

        selected = _production_baseline_record(
            {
                "heldOut": None,
                "validationSelection": {
                    "candidates": [
                        {"config": {"mode": "hybrid"}, "configSha256": "other"},
                        lexical,
                    ]
                },
            }
        )

        self.assertIs(lexical, selected)

    def test_snapshot_recovers_tool_evidence_without_double_counting(self) -> None:
        primary = [
            {
                "eventId": "session:1",
                "eventType": "tool_started",
                "payload": {"toolCallId": "call-skill", "toolName": "skill_load"},
            }
        ]
        snapshot_events = [
            primary[0],
            {
                "eventId": "session:2",
                "eventType": "tool_started",
                "payload": {"toolCallId": "call-tool", "toolName": "tool_load"},
            },
        ]
        messages = [
            {
                "role": "assistant",
                "blocks": [
                    {
                        "id": "block-skill",
                        "type": "tool_call",
                        "data": {"toolCallId": "call-skill", "toolName": "skill_load"},
                    },
                    {
                        "id": "block-rag",
                        "type": "tool_call",
                        "data": {"toolCallId": "call-rag", "toolName": "rag_benchmark"},
                    },
                ],
            }
        ]

        merged = _merge_event_evidence(primary, snapshot_events)

        self.assertEqual(2, len(merged))
        self.assertEqual(
            ["skill_load", "tool_load", "rag_benchmark"],
            _started_tool_names(merged, messages),
        )

    def test_provider_transient_retry_distinguishes_gateway_progress(self) -> None:
        events = [
            {
                "eventType": "turn_failed",
                "payload": {"error": "fetch failed"},
            }
        ]

        self.assertEqual(
            "provider_transient_before_tool",
            _runtime_failure_category(
                terminal="turn_failed",
                error="",
                events=events,
                ledger={"itemCount": 0},
            ),
        )
        self.assertEqual(
            "provider_transient_after_tool",
            _runtime_failure_category(
                terminal="turn_failed",
                error="",
                events=events,
                ledger={"itemCount": 1},
            ),
        )

    def test_answer_judge_retry_is_terminal_only_and_not_score_based(self) -> None:
        self.assertTrue(
            _answer_judge_failure_is_retryable(
                "RuntimeError: answer judge ended with turn_failed"
            )
        )
        self.assertFalse(
            _answer_judge_failure_is_retryable(
                "RuntimeError: answer judge output is schema-invalid"
            )
        )
        self.assertFalse(
            _answer_judge_failure_is_retryable("correctnessByLane.agentic=0.5")
        )

    def test_bound_run_prompt_does_not_disclose_random_run_id(self) -> None:
        prompt = _lane_prompt(
            lane="baseline",
            run_id="a" * 32,
            cases=[{"queryId": "q-1", "query": "问题"}],
            retrieval_config={"mode": "lexical"},
            evaluation_mode="answer-only",
            evaluation_split="validation",
        )

        self.assertNotIn("a" * 32, prompt)
        self.assertIn("不要传 runId", prompt)
        self.assertNotIn("held-out", prompt.lower())

    def test_lane_prompt_hash_changes_with_explicit_mode_and_split(self) -> None:
        import hashlib

        common = {
            "lane": "baseline",
            "run_id": "run",
            "cases": [{"queryId": "q-1", "query": "问题"}],
            "retrieval_config": {"mode": "lexical"},
        }
        validation = _lane_prompt(
            **common,
            evaluation_mode="answer-only",
            evaluation_split="validation",
        )
        held_out = _lane_prompt(
            **common,
            evaluation_mode="answer-only",
            evaluation_split="held_out",
        )

        self.assertNotEqual(
            hashlib.sha256(validation.encode("utf-8")).hexdigest(),
            hashlib.sha256(held_out.encode("utf-8")).hexdigest(),
        )

    def test_coverage_audit_is_label_blind_bounded_and_no_tool(self) -> None:
        cases = [
            {
                "queryId": "opaque-source-id",
                "evaluationCaseId": "case-generic",
                "query": "Which services, measures, and effects are described?",
                "answer": "PRIVATE GOLD MUST NOT APPEAR",
                "answerFacts": ["PRIVATE FACT MUST NOT APPEAR"],
            }
        ]

        prompt = _coverage_audit_prompt(cases)
        skill_prompt = _lane_prompt(
            lane="skill",
            run_id="run",
            cases=cases,
            retrieval_config={"mode": "lexical"},
            evaluation_mode="answer-only",
            evaluation_split="validation",
        )

        self.assertIn("case-generic", prompt)
        self.assertIn("Which services, measures, and effects are described?", prompt)
        self.assertIn("不得调用任何 Tool", prompt)
        self.assertIn("枚举槽位", prompt)
        self.assertIn("并列项目", prompt)
        self.assertIn("跨文档", prompt)
        self.assertIn("完整 JSON", prompt)
        self.assertNotIn("PRIVATE GOLD", prompt)
        self.assertNotIn("PRIVATE FACT", prompt)
        self.assertNotIn("opaque-source-id", prompt)
        self.assertIn("主体和所有被问枚举槽位", skill_prompt)
        self.assertIn("每个 case 严格调用一次 search", skill_prompt)

    def test_run_coverage_audit_uses_one_same_session_turn(self) -> None:
        from unittest.mock import patch

        class FakeService:
            def __init__(self) -> None:
                self.prompts: list[tuple[str, dict[str, object]]] = []

            def prompt(
                self,
                session_id: str,
                payload: dict[str, object],
            ) -> dict[str, object]:
                self.prompts.append((session_id, payload))
                return {"turnId": "audit-turn"}

        service = FakeService()
        with patch(
            "scripts.run_rag_agent_ablation._wait_for_terminal",
            return_value=([{"eventType": "turn_completed"}], "turn_completed"),
        ) as wait:
            receipt, events, terminal = _run_coverage_audit(
                service,
                session_id="private-session",
                cases=[
                    {
                        "evaluationCaseId": "case-generic",
                        "query": "What goals and measures are listed?",
                        "answer": "PRIVATE GOLD",
                    }
                ],
                timeout_seconds=30,
            )

        self.assertEqual("audit-turn", receipt["turnId"])
        self.assertEqual("turn_completed", terminal)
        self.assertEqual([{"eventType": "turn_completed"}], events)
        self.assertEqual(1, len(service.prompts))
        self.assertNotIn("PRIVATE GOLD", str(service.prompts[0][1]))
        wait.assert_called_once_with(
            service,
            session_id="private-session",
            turn_id="audit-turn",
            timeout_seconds=30,
        )

    def test_agentic_no_tool_critic_contract_uses_completed_child_evidence(self) -> None:
        child_runs = [
            {
                "childSessionId": "child-a",
                "state": "completed",
                "usage": {"toolCount": 0, "turnCount": 1},
            }
        ]
        wrapper_error_receipt = [
            {
                "operation": "delegate",
                "finished": True,
                "isError": True,
            }
        ]

        self.assertTrue(
            _agentic_critic_contract_passes(
                child_runs=child_runs,
                child_searches=[],
                agents_tool_receipts=wrapper_error_receipt,
            )
        )
        self.assertFalse(
            _agentic_critic_contract_passes(
                child_runs=child_runs,
                child_searches=[{"operation": "search", "ok": True}],
                agents_tool_receipts=wrapper_error_receipt,
            )
        )
        child_runs[0]["usage"] = {"toolCount": 1, "turnCount": 1}
        self.assertFalse(
            _agentic_critic_contract_passes(
                child_runs=child_runs,
                child_searches=[],
                agents_tool_receipts=wrapper_error_receipt,
            )
        )

    def test_checkpoint_keeps_hash_bound_search_trace_private(self) -> None:
        import json

        lane_record = self._checkpoint_lane_record("baseline")
        lane_record["gatewayLedger"] = {
            "ledgerSha256": "l" * 64,
            "itemCount": 1,
            "items": [
                {
                    "sequence": 1,
                    "sessionId": "agent:private-session",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-generic",
                        "querySha256": "q" * 64,
                        "queryChars": 42,
                        "baseAlias": "benchmark",
                        "mode": "hybrid",
                        "topK": 10,
                    },
                    "resultSha256": "r" * 64,
                    "resultSummary": {
                        "hits": [
                            {
                                "externalDocumentId": "private-document-id",
                                "chunkId": "private-chunk-id",
                                "citationRef": "K1",
                            }
                        ]
                    },
                    "receiptSha256": "p" * 64,
                }
            ],
        }

        trace = _checkpoint_private_search_trace(lane_record["gatewayLedger"])
        projected, _session_id, _turn_id = _checkpoint_lane_record_projection(
            lane_record
        )
        public = _finalize_public_report(
            {"schemaVersion": "test", "lanes": [projected]},
            checkpoint=None,
        )

        self.assertEqual(1, trace["searchCount"])
        self.assertEqual("q" * 64, trace["searches"][0]["querySha256"])
        self.assertTrue(trace["searches"][0]["documentSha256s"])
        self.assertTrue(trace["traceSha256"])
        private_serialized = json.dumps(projected, sort_keys=True)
        self.assertIn("privateSearchTrace", projected)
        self.assertNotIn("agent:private-session", private_serialized)
        self.assertNotIn("private-document-id", private_serialized)
        self.assertNotIn("private-chunk-id", private_serialized)
        public_serialized = json.dumps(public, sort_keys=True)
        self.assertNotIn("privateSearchTrace", public_serialized)
        self.assertEqual(
            "rag-ime.rag-agent-checkpoint-ledger-summary.v1",
            projected["gatewayLedger"]["schemaVersion"],
        )

    def test_agentic_prompt_requires_parent_two_pass_and_one_coverage_critic(self) -> None:
        prompt = _lane_prompt(
            lane="agentic",
            run_id="b" * 32,
            cases=[{"queryId": "q-1", "query": "谁批准了预算？"}],
            retrieval_config={
                "mode": "dense",
                "rerankEnabled": True,
                "rerankCandidateDepth": 40,
            },
            evaluation_mode="answer-only",
            evaluation_split="validation",
        )

        self.assertIn("agents.delegate", prompt)
        self.assertIn('"op":"delegate"', prompt)
        self.assertIn('"tasks":[', prompt)
        self.assertEqual(1, prompt.count('"agent":"reviewer"'))
        self.assertIn('"wait":true', prompt)
        self.assertIn("不得调用 agents.catalog", prompt)
        self.assertIn("第一阶段由父 Agent", prompt)
        self.assertIn("DYNAMIC_FIRST_PASS_EVIDENCE_PACKET", prompt)
        self.assertIn("必须把 task 中的 DYNAMIC_FIRST_PASS_EVIDENCE_PACKET 替换", prompt)
        self.assertIn("reviewer 不得调用任何 Tool", prompt)
        self.assertIn("父 Agent 必须对每个真实 case 再做且只做一次 search", prompt)
        self.assertIn("不得依赖默认值或省略 rerank 参数", prompt)
        self.assertIn("rerank=true", prompt)
        self.assertIn("rerankCandidateDepth=40", prompt)
        self.assertIn("topK=10", prompt)
        self.assertEqual(1, prompt.count('"caseId":"q-1"'))
        self.assertIn("query 必须逐字复制", prompt)
        self.assertIn("每个真实 case 严格两次父级 search", prompt)
        self.assertIn("safety 严格一次", prompt)
        self.assertIn("最终合成以两轮父级 search 正文为唯一事实依据", prompt)
        self.assertIn("所有直接佐证来源", prompt)
        self.assertNotIn("b" * 32, prompt)

    def test_agentic_prompt_uses_one_batch_coverage_critic(self) -> None:
        prompt = _lane_prompt(
            lane="agentic",
            run_id="partition-run",
            cases=[
                {"queryId": f"q-{index}", "query": f"问题 {index}"}
                for index in range(1, 5)
            ],
            retrieval_config={
                "mode": "dense",
                "rerankEnabled": True,
                "rerankCandidateDepth": 40,
            },
            evaluation_mode="answer-only",
            evaluation_split="validation",
        )

        self.assertIn("CriticCallShape=", prompt)
        self.assertEqual(1, prompt.count('"op":"delegate"'))
        self.assertEqual(1, prompt.count('"agent":"reviewer"'))
        for index in range(1, 5):
            self.assertEqual(1, prompt.count(f'"caseId":"q-{index}"'))

    def test_coverage_critic_requires_one_completed_child_without_searches(self) -> None:
        runs = [{"childSessionId": "child-a", "state": "completed"}]

        self.assertTrue(
            _coverage_critic_completed(child_runs=runs, child_searches=[])
        )
        self.assertFalse(
            _coverage_critic_completed(
                child_runs=runs,
                child_searches=[{"operation": "search", "ok": True}],
            )
        )
        self.assertFalse(
            _coverage_critic_completed(
                child_runs=[{"childSessionId": "child-a", "state": "failed"}],
                child_searches=[],
            )
        )

    def test_lane_prompt_requires_atomic_answer_and_evidence_ledger(self) -> None:
        prompt = _lane_prompt(
            lane="agentic",
            run_id="c" * 32,
            cases=[
                {
                    "queryId": "q-1",
                    "query": "哪些国家下降，具体覆盖率和排名变化是什么？",
                }
            ],
            retrieval_config={
                "mode": "dense",
                "rerankEnabled": True,
                "rerankCandidateDepth": 40,
            },
            evaluation_mode="answer-only",
            evaluation_split="validation",
        )

        self.assertIn("逐 case 的证据账本", prompt)
        self.assertIn("名称、数字、日期、比较方向和行动", prompt)
        self.assertIn("每个问题子项", prompt)
        self.assertIn("citations 取这些直接证据来源 citationRef 的去重并集", prompt)
        self.assertIn("只写问题明确要求的槽位", prompt)
        self.assertIn("不复制未被提问的背景", prompt)
        self.assertIn("短 citationRef", prompt)
        self.assertIn("不得手工抄写 externalDocumentId", prompt)
        self.assertIn("不得因此整题拒答", prompt)
        self.assertIn("枚举容器", prompt)

    def test_agentic_parent_query_policy_requires_exact_then_distinct_query(self) -> None:
        cases = [
            {
                "evaluationCaseId": "case-01",
                "query": "原始问题一",
            },
            {
                "evaluationCaseId": "case-02",
                "query": "原始问题二",
            },
        ]
        ledger = {
            "items": [
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-01",
                        "query": "原始问题一",
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-02",
                        "query": "原始问题二",
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "safety-not-found",
                        "query": "虚构项目‘紫微零号’在2099年的预算批准人是谁？",
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-01",
                        "query": "主体一 被问槽位 直接证据",
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-02",
                        "query": "主体二 被问槽位 直接证据",
                    },
                },
                {
                    "sessionId": "child",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "evaluationCaseId": "case-01",
                        "query": "child rewrite",
                    },
                },
            ]
        }

        self.assertTrue(
            _agentic_parent_query_policy_passes(
                ledger,
                parent_session_id="parent",
                cases=cases,
            )
        )
        ledger["items"][0]["args"]["query"] = "缩短问题"
        self.assertFalse(
            _agentic_parent_query_policy_passes(
                ledger,
                parent_session_id="parent",
                cases=cases,
            )
        )
        ledger["items"][0]["args"]["query"] = "原始问题一"
        ledger["items"][3]["args"]["query"] = "原始问题一"
        self.assertFalse(
            _agentic_parent_query_policy_passes(
                ledger,
                parent_session_id="parent",
                cases=cases,
            )
        )

    def test_answer_judge_accepts_concise_answers_and_rejects_incomplete_lists(self) -> None:
        prompt = _answer_judge_prompt(
            [
                {
                    "caseId": "case-01",
                    "question": "哪两军参与？",
                    "referenceAnswer": "演习安排攻击军与防卫军参与。",
                    "evidenceDocuments": [
                        {
                            "evidenceId": "E1",
                            "text": "演习由攻击军与防卫军共同参与。",
                        }
                    ],
                    "candidates": [
                        {
                            "candidateId": "C1",
                            "answer": "攻击军与防卫军",
                            "abstained": False,
                            "evidenceIds": ["E1"],
                        }
                    ],
                }
            ]
        )

        self.assertIn("A concise span is correct", prompt)
        self.assertIn("multi-part", prompt)
        self.assertIn("future expansion plan", prompt)
        self.assertIn("candidate's own evidenceIds", prompt)
        self.assertIn("演习由攻击军与防卫军共同参与", prompt)
        self.assertNotIn("baseline", prompt)
        output = (
            '{"caseRubrics":[{"caseId":"case-01","requiredFacts":['
            '{"factId":"F1","description":"the two named armies"}]}],'
            '"judgments":['
            '{"caseId":"case-01","candidateId":"C1",'
            '"coveredFactIds":["F1"],"hasContradiction":false,'
            '"hasUnsupportedMaterial":false,'
            '"correct":true,"reasonCode":"correct"}]}'
        )
        rubrics = _parse_answer_judge_rubrics(
            output,
            expected_case_ids={"case-01"},
        )
        self.assertEqual("the two named armies", rubrics[0]["requiredFacts"][0]["description"])
        parsed = _parse_answer_judgments(
            output,
            expected_pairs={("case-01", "C1")},
        )
        self.assertTrue(parsed[0]["correct"])
        with self.assertRaisesRegex(RuntimeError, "omitted"):
            _parse_answer_judgments(
                '{"caseRubrics":[{"caseId":"case-01","requiredFacts":['
                '{"factId":"F1","description":"the two named armies"}]}],'
                '"judgments":[]}',
                expected_pairs={("case-01", "C1")},
            )

        repair = _answer_judge_format_repair_prompt(
            expected_pairs={("case-01", "C1")},
        )
        self.assertIn("failed only the machine-readable schema", repair)
        self.assertIn("do not use any score", repair)
        self.assertIn('"caseId":"case-01"', repair)
        self.assertIn('"candidateId":"C1"', repair)

    def test_answer_judgment_keeps_raw_f1_and_controls_task_success(self) -> None:
        lane_records = [
            {
                "lane": "baseline",
                "score": {
                    "answerCases": [
                        {
                            "evaluationCaseId": "case-01",
                            "answerCharF1": 1 / 3,
                            "answerSuccess": False,
                            "toolSuccess": True,
                            "citationSuccess": True,
                            "agentSuccess": False,
                        }
                    ],
                    "agentMetrics": {
                        "answerCharF1": 1 / 3,
                        "answerSuccessRate": 0.0,
                        "agentSuccessRate": 0.0,
                    },
                },
            }
        ]
        judgments = [
            {
                "lane": "baseline",
                "evaluationCaseId": "case-01",
                "correct": True,
                "reasonCode": "correct",
            }
        ]

        _apply_answer_judgments(lane_records, judgments)

        answer = lane_records[0]["score"]["answerCases"][0]
        metrics = lane_records[0]["score"]["agentMetrics"]
        self.assertAlmostEqual(1 / 3, answer["answerCharF1"])
        self.assertFalse(answer["answerCharF1Success"])
        self.assertTrue(answer["answerJudgeCorrect"])
        self.assertTrue(answer["agentSuccess"])
        self.assertEqual(0.0, metrics["answerCharF1SuccessRate"])
        self.assertEqual(1.0, metrics["answerJudgeCorrectnessRate"])
        self.assertEqual(1.0, metrics["agentSuccessRate"])

    def test_search_parameter_policy_requires_frozen_reranker_contract(self) -> None:
        ledger = {
            "items": [
                {
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "baseAlias": "benchmark",
                        "evaluationCaseId": "case-01",
                        "mode": "dense",
                        "topK": 10,
                        "threshold": 0,
                        "rerank": True,
                        "rerankCandidateDepth": 40,
                    },
                }
            ]
        }
        config = {
            "mode": "dense",
            "rerankEnabled": True,
            "rerankCandidateDepth": 40,
        }

        self.assertTrue(
            _search_parameter_policy_passes(
                ledger,
                lane="tuned",
                retrieval_config=config,
            )
        )
        ledger["items"][0]["args"]["rerankCandidateDepth"] = 20
        self.assertFalse(
            _search_parameter_policy_passes(
                ledger,
                lane="tuned",
                retrieval_config=config,
            )
        )

    def test_agentic_parameter_policy_requires_parent_top_ten_for_both_passes(self) -> None:
        config = {
            "mode": "dense",
            "rerankEnabled": True,
            "rerankCandidateDepth": 40,
        }
        ledger = {
            "items": [
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "baseAlias": "benchmark",
                        "evaluationCaseId": "case-01",
                        "mode": "dense",
                        "topK": 10,
                        "threshold": 0,
                        "rerank": True,
                        "rerankCandidateDepth": 40,
                    },
                },
                {
                    "sessionId": "parent",
                    "operation": "search",
                    "ok": True,
                    "args": {
                        "baseAlias": "benchmark",
                        "evaluationCaseId": "case-01",
                        "mode": "dense",
                        "topK": 10,
                        "threshold": 0,
                        "rerank": True,
                        "rerankCandidateDepth": 40,
                    },
                },
            ]
        }

        self.assertTrue(
            _search_parameter_policy_passes(
                ledger,
                lane="agentic",
                retrieval_config=config,
            )
        )
        ledger["items"][1]["args"]["topK"] = 5
        self.assertFalse(
            _search_parameter_policy_passes(
                ledger,
                lane="agentic",
                retrieval_config=config,
            )
        )

    def test_agents_tool_receipts_keep_operation_and_bounded_error_only(self) -> None:
        receipts = _agents_tool_receipts(
            [
                {
                    "eventType": "tool_started",
                    "payload": {
                        "toolCallId": "call-secret",
                        "toolName": "agents",
                        "args": {"op": "delegate", "task": "do not retain"},
                    },
                },
                {
                    "eventType": "tool_finished",
                    "payload": {
                        "toolCallId": "call-secret",
                        "toolName": "agents",
                        "isError": True,
                        "result": {
                            "errorType": "ValueError",
                            "message": "invalid acceptance criteria",
                        },
                    },
                },
            ]
        )

        self.assertEqual("delegate", receipts[0]["operation"])
        self.assertTrue(receipts[0]["finished"])
        self.assertTrue(receipts[0]["isError"])
        self.assertEqual("ValueError", receipts[0]["errorType"])
        self.assertEqual("invalid acceptance criteria", receipts[0]["errorMessage"])
        self.assertNotIn("do not retain", str(receipts))
        self.assertNotIn("call-secret", str(receipts))

    def test_snapshot_text_reads_last_assistant_text_block(self) -> None:
        self.assertEqual(
            '{"cases":[]}',
            _last_assistant_snapshot_text(
                [
                    {"role": "user", "blocks": []},
                    {
                        "role": "assistant",
                        "blocks": [
                            {"type": "text", "data": {"text": '{"cases":[]}'}}
                        ],
                    },
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
